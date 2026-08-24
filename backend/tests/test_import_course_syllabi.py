"""`scripts/import_course_syllabi.upsert_syllabus_row` 테스트.

크롤러(브라우저 자동화)와 실 DB(`SessionLocal`)에 묶인 `import_course_syllabi`
전체는 여기서 단위 테스트하지 않는다 — offering 매칭 + upsert 로직만 떼어낸
`upsert_syllabus_row`를 SQLite 인메모리로 검증한다. 크롤러/파서 자체는
`tests/test_onestop_syllabus_parser.py`와 실제 크롤 재현(local.md 참고)으로
따로 검증했다.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.domains.courses.models import Course, CourseOffering, CourseSyllabus
from app.ingestion.crawlers.onestop_syllabus import SyllabusCrawlResult, SyllabusOffering
from app.ingestion.parsers.onestop_syllabus import ParsedSyllabus
from scripts.import_course_syllabi import upsert_syllabus_row


def _offering(subj_no="CB1501019", class_no="059") -> SyllabusOffering:
    return SyllabusOffering(
        subj_no=subj_no, class_no=class_no, subj_nm="자료구조",
        prof_no="110601", prof_nm="이기준", dept_nm="컴퓨터공학전공", has_kor=True,
    )


class UpsertSyllabusRowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            cls.engine,
            tables=[Course.__table__, CourseOffering.__table__, CourseSyllabus.__table__],
        )

    def setUp(self):
        self.db = Session(self.engine)
        for model in (CourseSyllabus, CourseOffering, Course):
            self.db.query(model).delete()
        self.db.commit()
        self.db.add(Course(id=1, course_code="CB1501019", course_name="자료구조", credits=3))
        self.db.add(CourseOffering(id=1, course_id=1, year="2026", semester="2학기", section="059"))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _parsed(self, **overrides) -> ParsedSyllabus:
        defaults = dict(
            phone="2299", email="lik@pusan.ac.kr", evaluation_method="Exams 90%",
            prerequisites_text="C++ 언어/Python", course_objectives="1. ...",
            course_overview="배열/스택/큐...", raw_text="(raw)",
        )
        defaults.update(overrides)
        return ParsedSyllabus(**defaults)

    def test_creates_row_for_matching_offering(self):
        result = SyllabusCrawlResult(offering=_offering(), pdf_path=Path("/tmp/x.pdf"))
        with patch("scripts.import_course_syllabi.parse_syllabus_pdf", return_value=self._parsed()):
            status = upsert_syllabus_row(self.db, result, year=2026)
        self.db.commit()
        self.assertEqual("created", status)
        row = self.db.query(CourseSyllabus).filter_by(offering_id=1).one()
        self.assertEqual("lik@pusan.ac.kr", row.email)
        self.assertEqual("C++ 언어/Python", row.prerequisites_text)

    def test_updates_existing_row_instead_of_duplicating(self):
        result = SyllabusCrawlResult(offering=_offering(), pdf_path=Path("/tmp/x.pdf"))
        with patch("scripts.import_course_syllabi.parse_syllabus_pdf", return_value=self._parsed()):
            upsert_syllabus_row(self.db, result, year=2026)
        self.db.commit()
        with patch(
            "scripts.import_course_syllabi.parse_syllabus_pdf",
            return_value=self._parsed(email="changed@pusan.ac.kr"),
        ):
            status = upsert_syllabus_row(self.db, result, year=2026)
        self.db.commit()
        self.assertEqual("updated", status)
        rows = self.db.query(CourseSyllabus).filter_by(offering_id=1).all()
        self.assertEqual(1, len(rows), "같은 offering을 두 번 넣으면 중복이 아니라 갱신이어야 한다")
        self.assertEqual("changed@pusan.ac.kr", rows[0].email)

    def test_no_matching_offering_reports_status_without_writing(self):
        result = SyllabusCrawlResult(offering=_offering(subj_no="ZZ9999999"), pdf_path=Path("/tmp/x.pdf"))
        status = upsert_syllabus_row(self.db, result, year=2026)
        self.assertEqual("no_offering", status)
        self.assertEqual(0, self.db.query(CourseSyllabus).count())

    def test_wrong_year_does_not_match(self):
        """같은 subj_no/section이라도 연도가 다르면(재개설) 다른 offering이다."""
        result = SyllabusCrawlResult(offering=_offering(), pdf_path=Path("/tmp/x.pdf"))
        status = upsert_syllabus_row(self.db, result, year=2025)
        self.assertEqual("no_offering", status)

    def test_no_pdf_without_error_is_no_pdf_status(self):
        """PRT_KOR이 애초에 없던 분반(정상 스킵) — 실패가 아니다."""
        result = SyllabusCrawlResult(offering=_offering(), pdf_path=None)
        status = upsert_syllabus_row(self.db, result, year=2026)
        self.assertEqual("no_pdf", status)

    def test_download_error_is_failed_status(self):
        result = SyllabusCrawlResult(offering=_offering(), pdf_path=None, error="타임아웃")
        status = upsert_syllabus_row(self.db, result, year=2026)
        self.assertEqual("failed", status)


if __name__ == "__main__":
    unittest.main()
