"""졸업요건 판정 엔진(compute_graduation_progress)의 실사용 결함 회귀 테스트.

2026-08-13 백엔드 전수 점검에서 나온 두 건. 둘 다 학생에게 잘못된 판정이 보이거나
아예 에러가 나던 문제라 P0로 다뤘다.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

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
    School,
    StudentCourseRecord,
    UserAcademicProgram,
)
from app.domains.courses.models import Course  # noqa: F401 — SCR.course_id FK 해석용
from app.domains.users.models import User

_TABLES = [
    School.__table__, College.__table__, Department.__table__, Major.__table__,
    User.__table__, Course.__table__, UserAcademicProgram.__table__,
    GraduationRequirement.__table__, StudentCourseRecord.__table__,
]


class _Base(unittest.TestCase):
    def make_db(self):
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
        db.flush()
        return db


class BalancedLiberalAreaRollupTest(_Base):
    """균형교양 세부영역 이수학점이 '교양선택' 요건에 합산되는지.

    portal_sync._refine_liberal_area_categories가 One-Stop 판정을 근거로
    student_course_records.category를 '교양선택' → 세부영역명('사상과역사' 등)으로
    덮어쓴다. 판정 엔진이 그걸 롤업하지 않으면 **이수학점이 통째로 사라진다** —
    균형교양 18학점을 이수한 학생이 포털 동기화 후 "교양선택 0학점 이수, 18학점 남음"
    으로 보이던 실제 버그.
    """

    def _progress_with(self, categories):
        db = self.make_db()
        db.add(GraduationRequirement(
            department_id=10, program_type="primary", curriculum_year="2024",
            required_total_credits=130, required_general_elective=18,
        ))
        for i, cat in enumerate(categories):
            db.add(StudentCourseRecord(user_id=1, raw_course_name=f"과목{i}",
                                       category=cat, credits=3))
        db.commit()
        progress = compute_graduation_progress(db, 1)[0]
        return next(c for c in progress.categories if c.category_name == "교양선택")

    def test_detail_areas_count_toward_general_elective(self):
        ge = self._progress_with(list(BALANCED_LIBERAL_AREAS[:6]))
        self.assertEqual(18, int(ge.earned_credits))
        self.assertEqual(0, int(ge.remaining_credits))
        self.assertTrue(ge.satisfied)

    def test_plain_general_elective_still_counts(self):
        ge = self._progress_with(["교양선택"] * 6)
        self.assertEqual(18, int(ge.earned_credits))

    def test_mixed_detail_and_plain_are_summed_together(self):
        """포털 동기화가 일부만 세부영역으로 바꾼 중간 상태에서도 합산돼야 한다."""
        ge = self._progress_with(["사상과역사", "사회와문화", "교양선택"])
        self.assertEqual(9, int(ge.earned_credits))

    def test_other_categories_are_untouched(self):
        db = self.make_db()
        db.add(GraduationRequirement(
            department_id=10, program_type="primary", curriculum_year="2024",
            required_total_credits=130, required_major_required=30,
        ))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="자료구조",
                                   category="전공필수", credits=3))
        db.commit()
        progress = compute_graduation_progress(db, 1)[0]
        mr = next(c for c in progress.categories if c.category_name == "전공필수")
        self.assertEqual(3, int(mr.earned_credits))


class DuplicateRequirementRowTest(_Base):
    """같은 조건의 기준학점 행이 여럿일 때 죽지 않고 판정하는지.

    graduation_requirements에 (program_type, department_id, major_id, curriculum_year)
    유니크 제약이 없어서 중복 행이 실재한다(간호학과 dual 2026이 2행). 옛 구현은
    `.one_or_none()`이라 그 학생의 졸업요건 조회가 MultipleResultsFound로 500이 났다.
    """

    def _db_with_duplicate_requirements(self):
        db = self.make_db()
        for rid in (1, 2):
            db.add(GraduationRequirement(
                id=rid, department_id=10, program_type="primary", curriculum_year="2024",
                required_total_credits=130, required_general_elective=18,
            ))
        db.commit()
        return db

    def test_does_not_raise_and_picks_deterministically(self):
        db = self._db_with_duplicate_requirements()
        progress = compute_graduation_progress(db, 1)[0]  # 예전엔 여기서 예외
        self.assertTrue(progress.requirement_found)
        self.assertEqual(130, progress.required_total_credits)

    def test_warns_so_the_ambiguity_is_visible(self):
        """조용히 하나를 고르면 판정이 달라진 이유를 아무도 모른다."""
        db = self._db_with_duplicate_requirements()
        progress = compute_graduation_progress(db, 1)[0]
        self.assertTrue(any("기준학점 행이 2개" in w for w in progress.warnings), progress.warnings)

    def test_single_requirement_has_no_duplicate_warning(self):
        db = self.make_db()
        db.add(GraduationRequirement(
            department_id=10, program_type="primary", curriculum_year="2024",
            required_total_credits=130,
        ))
        db.commit()
        progress = compute_graduation_progress(db, 1)[0]
        self.assertFalse(any("기준학점 행이" in w for w in progress.warnings), progress.warnings)


if __name__ == "__main__":
    unittest.main()
