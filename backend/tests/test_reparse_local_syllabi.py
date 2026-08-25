"""`scripts/reparse_local_syllabi` 테스트.

`upsert_syllabus_row` 자체(오프셋 매칭·upsert 로직)는 `tests/test_import_course_syllabi.py`
가 이미 검증한다 — 여기서는 이 스크립트 고유 로직(파일명 → subj_no/class_no 역파싱,
course_offerings.professor 조회, upsert_syllabus_row 호출 인자 구성)만 SQLite
인메모리로 검증한다. 실제 PDF 파싱은 `upsert_syllabus_row`를 패치해서 우회한다.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.domains.courses.models import Course, CourseOffering
from scripts.reparse_local_syllabi import _FILENAME_RE, reparse_local_syllabi


class FilenamePatternTest(unittest.TestCase):
    def test_matches_expected_crawler_filename_format(self):
        m = _FILENAME_RE.match("AB2002371_140_KOR.pdf")
        self.assertIsNotNone(m)
        self.assertEqual("AB2002371", m.group("subj_no"))
        self.assertEqual("140", m.group("class_no"))
        self.assertEqual("KOR", m.group("lang"))

    def test_rejects_unrelated_filenames(self):
        self.assertIsNone(_FILENAME_RE.match("readme.pdf"))
        self.assertIsNone(_FILENAME_RE.match("AB2002371.pdf"))


class ReparseLocalSyllabiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine, tables=[Course.__table__, CourseOffering.__table__])
        self.db = Session(self.engine, autoflush=False)
        self.db.add(Course(id=1, course_code="AB2002371", course_name="유기화학", credits=3))
        self.db.add(CourseOffering(
            id=1, course_id=1, year="2026", semester="2학기", section="140", professor="정상화",
        ))
        # 같은 연도·과목코드·분반번호가 다른 학기에도 있을 수 있다(분반 번호가 학기마다
        # 재시작) — professor 조회가 학기까지 안 걸면 엉뚱한 학기 교수 이름이 섞여
        # 들어갈 수 있다(독립 리뷰 2026-08-25 지적, test_import_course_syllabi.py의
        # test_wrong_semester_does_not_match_even_with_same_section_number와 같은 원칙).
        self.db.add(CourseOffering(
            id=2, course_id=1, year="2026", semester="1학기", section="140", professor="다른교수",
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_reparse_looks_up_professor_and_calls_upsert_with_right_args(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "AB2002371_140_KOR.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 dummy")

            captured = {}

            def _fake_upsert(db, result, year, semester):
                captured["subj_no"] = result.offering.subj_no
                captured["class_no"] = result.offering.class_no
                captured["prof_nm"] = result.offering.prof_nm
                captured["pdf_path"] = result.pdf_path
                captured["year"] = year
                captured["semester"] = semester
                return "updated"

            with patch("scripts.reparse_local_syllabi.SessionLocal", return_value=self.db), \
                 patch("scripts.reparse_local_syllabi.upsert_syllabus_row", side_effect=_fake_upsert):
                reparse_local_syllabi(tmp_dir, year=2026, semester_code="0020", dry_run=True)

            self.assertEqual("AB2002371", captured["subj_no"])
            self.assertEqual("140", captured["class_no"])
            self.assertEqual("정상화", captured["prof_nm"])
            self.assertEqual(pdf_path, captured["pdf_path"])
            self.assertEqual(2026, captured["year"])
            self.assertEqual("2학기", captured["semester"])

    def test_professor_lookup_does_not_leak_across_semesters(self):
        """같은 과목코드·분반이 1학기에도 있는 상태(setUp의 id=2)에서, 1학기용
        재파싱과 2학기용 재파싱은 반드시 서로 다른 교수 이름을 찾아야 한다.

        고정값(예: "2학기 요청 시 항상 정상화가 나와야 한다")만 검증하면
        약하다 — 학기 필터를 통째로 없애도 SQLite가 우연히 같은 행을 먼저
        돌려주면 그 고정값 assert가 그대로 통과해버린다(실측: 리뷰에서
        학기 필터를 지우고 이 값을 검사했더니 통과했었다). 같은 조회를
        학기만 바꿔 두 번 실행해서 **결과가 실제로 달라지는지** 비교하면,
        학기 필터가 아예 없어졌을 때 두 결과가 우연히도 똑같이 나와서
        회귀를 확실히 잡아낸다."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "AB2002371_140_KOR.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 dummy")

            captured = {}

            def _make_fake_upsert(key):
                def _fake_upsert(db, result, year, semester):
                    captured[key] = result.offering.prof_nm
                    return "updated"
                return _fake_upsert

            with patch("scripts.reparse_local_syllabi.SessionLocal", return_value=self.db), \
                 patch("scripts.reparse_local_syllabi.upsert_syllabus_row", side_effect=_make_fake_upsert("2학기")):
                reparse_local_syllabi(tmp_dir, year=2026, semester_code="0020", dry_run=True)
            with patch("scripts.reparse_local_syllabi.SessionLocal", return_value=self.db), \
                 patch("scripts.reparse_local_syllabi.upsert_syllabus_row", side_effect=_make_fake_upsert("1학기")):
                reparse_local_syllabi(tmp_dir, year=2026, semester_code="0010", dry_run=True)

            self.assertEqual("정상화", captured["2학기"])
            self.assertEqual("다른교수", captured["1학기"])

    def test_dry_run_does_not_crash_on_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("scripts.reparse_local_syllabi.SessionLocal", return_value=self.db), \
                 patch("scripts.reparse_local_syllabi.upsert_syllabus_row", return_value="no_pdf"):
                reparse_local_syllabi(tmp_dir, year=2026, semester_code="0020", dry_run=True)

    def test_unrecognized_filenames_are_skipped_not_crashed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            (Path(tmp_dir) / "readme.pdf").write_bytes(b"%PDF-1.4 dummy")
            with patch("scripts.reparse_local_syllabi.SessionLocal", return_value=self.db), \
                 patch("scripts.reparse_local_syllabi.upsert_syllabus_row") as mock_upsert:
                reparse_local_syllabi(tmp_dir, year=2026, semester_code="0020", dry_run=True)
            mock_upsert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
