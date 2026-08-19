"""One-Stop 졸업예정정보의 **학교 공식 판정** 저장 테스트.

이 데이터는 원래 크롤링은 되는데 `portal_sync`가 표 0(학적신청)과 균형교양 세부영역만
쓰고 **나머지를 통째로 버려서**, "졸업요건이랑 토익 등 자격증을 못 가져온다"는 문제로
보였다(2026-08-16 실측으로 확인).

여기서는 정규화 결과 → DB upsert 경로만 본다(네트워크 없음).
"""

import datetime
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.domains.academics.models import (
    StudentGraduationCategory,
    StudentGraduationRequirement,
)
from app.domains.users.models import User
from app.ingestion.normalizers.graduation_status_normalizer import (
    upsert_official_graduation_status,
)


_TABLES = [
    User.__table__,
    StudentGraduationCategory.__table__,
    StudentGraduationRequirement.__table__,
]


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=_TABLES)
    db = sessionmaker(bind=engine)()
    db.add(User(id=1, email="t@e.com", password_hash="x", name="테스트"))
    db.flush()
    return db


def _category(program="주전공", category="전공필수", required=33.0, earned=26.0,
              status="N", reason="전공필수학점미달"):
    return {
        "program_type": program, "category": category,
        "required_credits": required, "earned_credits": earned,
        "registered_credits": 0.0, "expected_credits": 0.0,
        "completed_status": status, "failure_reason": reason,
    }


def _requirement(name="표준외국어능력시험", status="N", program="주전공", detail=""):
    """실제 크롤 결과와 같은 모양. program_type은 raw_record에서만 온다."""
    return {
        "requirement_area": "graduation_requirement_completion",
        "source_table_name": "graduation_requirement_completion",
        "required_category": name,
        "required_course_name": detail,
        "completed_status": status,
        "note": "",
        "raw_record": {
            "졸업기준_학적신청구분": program,
            "졸업기준_합격구분": "",
            "졸업기준_취득일자": "",
        },
    }


class UpsertOfficialStatusTest(unittest.TestCase):
    def test_categories_and_requirements_are_stored(self):
        db = _make_db()
        stats = upsert_official_graduation_status(db, 1, {
            "category_statuses": [_category(), _category(category="교양선택", required=12.0,
                                                         earned=15.0, status="Y", reason="")],
            "requirement_items": [_requirement(), _requirement(name="TOPCIT")],
        })
        self.assertEqual(2, stats["categories_created"])
        self.assertEqual(2, stats["requirements_created"])

        rows = db.query(StudentGraduationCategory).all()
        by_category = {r.category: r for r in rows}
        self.assertFalse(by_category["전공필수"].satisfied)
        self.assertEqual("전공필수학점미달", by_category["전공필수"].failure_reason)
        self.assertTrue(by_category["교양선택"].satisfied)
        # 사유가 빈 문자열이면 None으로 (빈 문자열과 "없음"을 구분할 이유가 없다)
        self.assertIsNone(by_category["교양선택"].failure_reason)

        names = {r.requirement_name for r in db.query(StudentGraduationRequirement).all()}
        self.assertEqual({"표준외국어능력시험", "TOPCIT"}, names)

    def test_upsert_is_idempotent(self):
        db = _make_db()
        payload = {"category_statuses": [_category()], "requirement_items": [_requirement()]}
        upsert_official_graduation_status(db, 1, payload)
        stats = upsert_official_graduation_status(db, 1, payload)

        self.assertEqual(0, stats["categories_created"])
        self.assertEqual(1, stats["categories_updated"])
        self.assertEqual(1, db.query(StudentGraduationCategory).count())
        self.assertEqual(1, db.query(StudentGraduationRequirement).count())

    def test_stale_rows_are_removed(self):
        """스냅샷이므로 이번 크롤에 없는 행은 지운다.

        복수전공을 포기하면 그 프로그램 행이 남아 "충족 못 한 요건"으로 계속 보인다.
        """
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [_category(), _category(program="복수전공")],
            "requirement_items": [_requirement(), _requirement(name="TOPCIT")],
        })
        stats = upsert_official_graduation_status(db, 1, {
            "category_statuses": [_category()],
            "requirement_items": [_requirement()],
        })

        self.assertEqual(1, stats["categories_deleted"])
        self.assertEqual(1, stats["requirements_deleted"])
        self.assertEqual(1, db.query(StudentGraduationCategory).count())
        self.assertEqual(1, db.query(StudentGraduationRequirement).count())

    def test_empty_crawl_does_not_wipe_snapshot(self):
        """페이지 구조 변경이나 일시적 실패로 빈 결과가 왔을 때 멀쩡한 스냅샷을
        통째로 날리는 게 제일 나쁘다."""
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [_category()], "requirement_items": [_requirement()],
        })
        stats = upsert_official_graduation_status(db, 1, {
            "category_statuses": [], "requirement_items": [],
        })

        self.assertEqual(0, stats["categories_deleted"])
        self.assertEqual(1, db.query(StudentGraduationCategory).count())
        self.assertEqual(1, db.query(StudentGraduationRequirement).count())

    def test_unknown_completed_status_is_none_not_false(self):
        """Y/N이 아닌 값을 False로 떨어뜨리면 "학교가 미충족이라 했다"와
        "우리가 못 읽었다"가 구분되지 않는다."""
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [_category(status="")],
            "requirement_items": [_requirement(status="???")],
        })
        self.assertIsNone(db.query(StudentGraduationCategory).one().satisfied)
        self.assertIsNone(db.query(StudentGraduationRequirement).one().satisfied)

    def test_no_records_rows_are_skipped(self):
        """"조회내역이 없습니다." 행은 요건이 아니다."""
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [],
            "requirement_items": [{
                "requirement_area": "graduation_requirement_completion",
                "source_table_name": "graduation_requirement_completion",
                "completed_status": "no_records",
                "raw_record": {"no_records": "Y"},
            }],
        })
        self.assertEqual(0, db.query(StudentGraduationRequirement).count())

    def test_other_tables_rows_are_ignored(self):
        """같은 requirement_items에 다른 표(필수과목·교양영역) 행이 섞여 온다."""
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [],
            "requirement_items": [
                {"source_table_name": "required_course_completion",
                 "required_category": "교양필수", "required_course_name": "고전읽기와토론",
                 "completed_status": "N", "raw_record": {}},
                _requirement(),
            ],
        })
        rows = db.query(StudentGraduationRequirement).all()
        self.assertEqual(["표준외국어능력시험"], [r.requirement_name for r in rows])

    def test_synced_at_is_recorded(self):
        db = _make_db()
        stamp = datetime.datetime(2026, 8, 19, 12, 0, tzinfo=datetime.UTC)
        upsert_official_graduation_status(
            db, 1, {"category_statuses": [_category()], "requirement_items": []},
            synced_at=stamp,
        )
        self.assertIsNotNone(db.query(StudentGraduationCategory).one().synced_at)


if __name__ == "__main__":
    unittest.main()
