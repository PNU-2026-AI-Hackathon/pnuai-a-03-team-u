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
