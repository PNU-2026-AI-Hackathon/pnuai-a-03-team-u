"""portal-sync의 균형교양 세부영역 override 회귀 테스트.

이 경로에는 테스트가 하나도 없었는데, 졸업요건 판정에 직접 영향을 준다:
One-Stop 판정을 근거로 `student_course_records.category`를 '교양선택' → 세부영역명으로
덮어쓰고, 판정 엔진이 그걸 `_CATEGORY_ROLLUP`으로 다시 '교양선택'에 합산한다.

**쓰는 쪽과 되돌리는 쪽이 어긋나면 학점이 통째로 사라진다** — 실제로 그 버그가 있었고
(2026-08-13), 여기서 두 방향을 함께 고정한다.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.portal_sync import _match_known_liberal_area, _refine_liberal_area_categories
from app.core.db import Base
from app.domains.academics.graduation_progress import (
    BALANCED_LIBERAL_AREAS,
    compute_graduation_progress,
)
from app.domains.academics.models import (
    College,
    Department,
    GraduationRequirement,
    Major,
    ProgramCourse,
    School,
    StudentCourseRecord,
    StudentCourseSubstitution,
    StudentGraduationCategory,
    UserAcademicProgram,
)
from app.domains.courses.models import Course  # noqa: F401 — SCR.course_id FK 해석용
from app.domains.users.models import User

_TABLES = [
    School.__table__, College.__table__, Department.__table__, Major.__table__,
    User.__table__, Course.__table__, UserAcademicProgram.__table__,
    GraduationRequirement.__table__, StudentCourseRecord.__table__,
    ProgramCourse.__table__, StudentCourseSubstitution.__table__,
    StudentGraduationCategory.__table__,
]


def _area_row(course_name: str, area_label: str, completed: str = "이수") -> dict:
    """One-Stop 졸업예정정보의 균형교양 행 한 줄 (normalize된 형태)."""
    return {
        "requirement_area": "general_education_area_completion",
        "required_category": area_label,
        "raw_record": {
            "학생이수정보_교과목명": course_name,
            "학생이수정보_이수여부": completed,
        },
    }


class LiberalAreaNameMatchingTest(unittest.TestCase):
    def test_exact_and_spaced_names_are_accepted(self):
        self.assertEqual("사상과역사", _match_known_liberal_area("사상과역사"))
        self.assertEqual("사상과역사", _match_known_liberal_area("사상과 역사"))

    def test_unknown_area_returns_none(self):
        """모르는 이름을 조용히 추측하면 안 된다 — 새 영역이거나 표기 체계가 바뀐 것이다."""
        self.assertIsNone(_match_known_liberal_area("영역구분없음"))
        self.assertIsNone(_match_known_liberal_area("제2외국어"))

    def test_every_known_area_matches_itself(self):
        for area in BALANCED_LIBERAL_AREAS:
            self.assertEqual(area, _match_known_liberal_area(area))


class RefineLiberalAreaCategoriesTest(unittest.TestCase):
    def make_db(self, records):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_TABLES)
        db = sessionmaker(bind=engine)()
        db.add_all([
            School(id=1, name="부산대학교"),
            College(id=1, school_id=1, name="정보의생명공학대학"),
            Department(id=10, college_id=1, name="정보컴퓨터공학부"),
        ])
        db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=10))
        db.add(UserAcademicProgram(user_id=1, department_id=10, program_type="primary",
                                   curriculum_year="2024"))
        db.add(GraduationRequirement(
            department_id=10, program_type="primary", curriculum_year="2024",
            required_total_credits=130, required_general_elective=9,
        ))
        for name, category in records:
            db.add(StudentCourseRecord(user_id=1, raw_course_name=name,
                                        category=category, credits=3))
        db.commit()
        return db

    def _general_elective(self, db):
        progress = compute_graduation_progress(db, 1)[0]
        return next(c for c in progress.categories if c.category_name == "교양선택")

    def test_known_area_is_written_and_still_counts(self):
        db = self.make_db([("역사의이해", "교양선택")])
        n = _refine_liberal_area_categories(db, 1, [_area_row("역사의이해", "1영역 : 사상과역사")])
        db.commit()

        self.assertEqual(1, n)
        rec = db.query(StudentCourseRecord).one()
        self.assertEqual("교양선택", rec.category)     # 상위 이수구분은 유지되고
        self.assertEqual("사상과역사", rec.liberal_area)  # 세부영역은 전용 컬럼에 저장된다
        self.assertEqual(3, int(self._general_elective(db).earned_credits))  # 집계는 그대로

    def test_spaced_area_name_is_normalized_not_written_raw(self):
        """원문 공백 차이를 그대로 쓰면 롤업이 못 알아보고 학점이 사라진다."""
        db = self.make_db([("역사의이해", "교양선택")])
        _refine_liberal_area_categories(db, 1, [_area_row("역사의이해", "1영역 : 사상과 역사")])
        db.commit()

        rec = db.query(StudentCourseRecord).one()
        self.assertEqual("교양선택", rec.category)
        self.assertEqual("사상과역사", rec.liberal_area)
        self.assertEqual(3, int(self._general_elective(db).earned_credits))

    def test_unknown_area_keeps_original_category(self):
        """모르는 영역명이면 덮어쓰지 않는다 — 집계 정확성이 세부영역 조언보다 우선."""
        db = self.make_db([("이상한과목", "교양선택")])
        n = _refine_liberal_area_categories(db, 1, [_area_row("이상한과목", "9영역 : 영역구분없음")])
        db.commit()

        self.assertEqual(0, n)
        self.assertEqual("교양선택", db.query(StudentCourseRecord).one().category)
        self.assertIsNone(db.query(StudentCourseRecord).one().liberal_area)
        self.assertEqual(3, int(self._general_elective(db).earned_credits))

    def test_not_completed_rows_are_ignored(self):
        db = self.make_db([("역사의이해", "교양선택")])
        n = _refine_liberal_area_categories(
            db, 1, [_area_row("역사의이해", "1영역 : 사상과역사", completed="미이수")]
        )
        self.assertEqual(0, n)
        self.assertEqual("교양선택", db.query(StudentCourseRecord).one().category)
        self.assertIsNone(db.query(StudentCourseRecord).one().liberal_area)

    def test_multiple_areas_all_roll_up_to_general_elective(self):
        db = self.make_db([("역사의이해", "교양선택"), ("사회학입문", "교양선택"),
                            ("현대문학", "교양선택")])
        _refine_liberal_area_categories(db, 1, [
            _area_row("역사의이해", "1영역 : 사상과역사"),
            _area_row("사회학입문", "2영역 : 사회와문화"),
            _area_row("현대문학", "3영역 : 문학과예술"),
        ])
        db.commit()

        ge = self._general_elective(db)
        self.assertEqual(9, int(ge.earned_credits))
        self.assertEqual(0, int(ge.remaining_credits))
        self.assertTrue(ge.satisfied)


if __name__ == "__main__":
    unittest.main()
