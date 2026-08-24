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
    LIBERAL_AREAS_2021,
    LIBERAL_AREAS_2026,
    compute_graduation_progress,
    liberal_areas_for_generation,
    resolve_liberal_area_generation,
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


class LiberalAreaGenerationTest(_Base):
    """교양 세부영역 구/신체계(2021 vs 2026) 세대 분기.

    2026-08-24 실측: courses.general_education_area에 2026체계 영역명이 이미
    "세계와 소통"/"융합과 창의"/"인성과 사회봉사"(공백 포함)로 들어와 있는데, 판정
    엔진의 BALANCED_LIBERAL_AREAS는 2021체계 8개만 알고 있었다 — 신입생이 이
    이름으로 One-Stop 동기화를 하면 세부영역 인식이 조용히 실패했을 것이다(아직
    실사용자가 없어 드러나지 않았을 뿐). 세대별 목록과 판별 함수를 고정한다.
    """

    def test_resolve_generation_by_year(self):
        self.assertEqual("2021", resolve_liberal_area_generation("2023"))
        self.assertEqual("2021", resolve_liberal_area_generation("2025"))
        self.assertEqual("2026", resolve_liberal_area_generation("2026"))
        self.assertEqual("2026", resolve_liberal_area_generation("2027"))
        self.assertEqual("2026", resolve_liberal_area_generation(2026))

    def test_resolve_generation_defaults_to_2021_when_unknown(self):
        """실사용자 curriculum_year가 결측이면 전부 구체계라(2026-08-24 기준) 기본값도 구체계."""
        self.assertEqual("2021", resolve_liberal_area_generation(None))
        self.assertEqual("2021", resolve_liberal_area_generation("모름"))

    def test_liberal_areas_for_generation_returns_correct_subset(self):
        self.assertEqual(LIBERAL_AREAS_2021, liberal_areas_for_generation("2024"))
        self.assertEqual(LIBERAL_AREAS_2026, liberal_areas_for_generation("2026"))

    def test_generation_specific_names_dont_leak_into_each_other(self):
        """2021학번에게 신체계 이름을, 2026학번에게 구체계 이름을 보여주면 안 된다."""
        areas_2021 = liberal_areas_for_generation("2024")
        areas_2026 = liberal_areas_for_generation("2026")
        self.assertIn("외국어", areas_2021)
        self.assertNotIn("세계와 소통", areas_2021)
        self.assertIn("세계와 소통", areas_2026)
        self.assertNotIn("외국어", areas_2026)
        self.assertIn("인성과 사회봉사", areas_2026)
        self.assertNotIn("인성과 사회봉사", areas_2021)

    def test_balanced_liberal_areas_union_covers_both_generations(self):
        for area in LIBERAL_AREAS_2021 + LIBERAL_AREAS_2026:
            self.assertIn(area, BALANCED_LIBERAL_AREAS)

    def test_2026_area_names_still_roll_up_to_general_elective(self):
        """세대와 무관하게 이 flat 엔진에서 롤업 대상은 항상 '교양선택' 하나뿐이다."""
        db = self.make_db()
        db.add(GraduationRequirement(
            department_id=10, program_type="primary", curriculum_year="2024",
            required_total_credits=130, required_general_elective=9,
        ))
        db.add_all([
            StudentCourseRecord(user_id=1, raw_course_name="글로벌커뮤니케이션",
                                 category="세계와 소통", credits=3),
            StudentCourseRecord(user_id=1, raw_course_name="창의적문제해결",
                                 category="융합과 창의", credits=3),
            StudentCourseRecord(user_id=1, raw_course_name="사회봉사와나눔",
                                 category="인성과 사회봉사", credits=3),
        ])
        db.commit()
        progress = compute_graduation_progress(db, 1)[0]
        ge = next(c for c in progress.categories if c.category_name == "교양선택")
        self.assertEqual(9, int(ge.earned_credits))
        self.assertTrue(ge.satisfied)


class DepartmentLevelFallbackTest(_Base):
    """전공 단위 요건이 없으면 학과 단위(major_id IS NULL)로 폴백하는지.

    `graduation_requirements.major_id = NULL`은 "모름"이 아니라 "이 학과 전체에 공통 적용"
    이라는 확정적 의미다(운영 DB 실측: 전공이 있는 학과인데 요건은 학과 단위로만 등록된
    행이 64개, 예를 들어 기계공학부 primary 2026은 전공 5개 각각의 요건 행이 없다).

    폴백이 없던 옛 구현은 그런 학생을 `requirement_found=False`로 떨어뜨려 졸업요건 판정을
    아예 못 받게 했다. `timetable._term_credit_cap`은 이미 같은 폴백을 하고 있어서 두 코드
    경로가 서로 다르게 동작하던 문제이기도 하다.
    """

    def _make_student_with_major(self, db, major_id=20):
        db.add(Major(id=major_id, department_id=10, name="컴퓨터공학전공"))
        user = db.get(User, 1)
        user.major_id = major_id
        prog = db.query(UserAcademicProgram).filter_by(user_id=1).one()
        prog.major_id = major_id
        db.flush()

    def test_falls_back_to_department_level_requirement(self):
        db = self.make_db()
        self._make_student_with_major(db)
        db.add(GraduationRequirement(
            department_id=10, major_id=None, program_type="primary",
            curriculum_year="2024", required_total_credits=133,
        ))
        db.commit()
        progress = compute_graduation_progress(db, 1)[0]
        self.assertTrue(progress.requirement_found)
        self.assertEqual(133, progress.required_total_credits)

    def test_fallback_is_flagged_in_warnings(self):
        """전공별 세부 기준이 아니라는 걸 사용자·LLM이 알아야 한다."""
        db = self.make_db()
        self._make_student_with_major(db)
        db.add(GraduationRequirement(
            department_id=10, major_id=None, program_type="primary",
            curriculum_year="2024", required_total_credits=133,
        ))
        db.commit()
        progress = compute_graduation_progress(db, 1)[0]
        self.assertTrue(any("학과 단위 기준으로 판정" in w for w in progress.warnings),
                        progress.warnings)

    def test_major_level_still_wins_when_present(self):
        """폴백을 넣었다고 전공 우선순위가 무너지면 안 된다 (골든 TC05와 같은 취지)."""
        db = self.make_db()
        self._make_student_with_major(db)
        db.add(GraduationRequirement(
            department_id=10, major_id=None, program_type="primary",
            curriculum_year="2024", required_total_credits=133,
        ))
        db.add(GraduationRequirement(
            department_id=10, major_id=20, program_type="primary",
            curriculum_year="2024", required_total_credits=120,
        ))
        db.commit()
        progress = compute_graduation_progress(db, 1)[0]
        self.assertEqual(120, progress.required_total_credits)
        self.assertFalse(any("학과 단위 기준으로 판정" in w for w in progress.warnings))

    def test_no_requirement_at_any_level_is_still_not_found(self):
        """어느 수준에도 요건이 없으면 없는 대로 보고해야 한다 — 억지로 만들지 않는다.

        실제 사례: 디자인학과 primary 요건은 두 행 다 전공이 지정돼 있고(시각디자인·
        애니메이션) 학과 단위 행이 없다. 디자인앤테크놀로지전공 학생은 폴백해도 못 찾는다.
        """
        db = self.make_db()
        self._make_student_with_major(db, major_id=20)
        db.add(GraduationRequirement(
            department_id=10, major_id=99, program_type="primary",
            curriculum_year="2024", required_total_credits=133,
        ))
        db.commit()
        progress = compute_graduation_progress(db, 1)[0]
        self.assertFalse(progress.requirement_found)


class LeaveOfAbsenceIsJudgedTest(_Base):
    """휴학생도 졸업요건 판정을 받는지 (2026-08-14 정책 결정).

    옛 구현은 `status == "active"`로만 걸러서, 포털이 '휴학'으로 내려준 학생은 로드맵·
    시간표·졸업 진단 전부에서 판정이 통째로 비었다. 휴학은 학업을 그만둔 게 아니라 잠시
    쉬는 것이라 오히려 "복학하면 뭐가 남았나"를 알아야 한다.
    """

    def _progress_with_status(self, status):
        db = self.make_db()
        prog = db.query(UserAcademicProgram).filter_by(user_id=1).one()
        prog.status = status
        db.add(GraduationRequirement(
            department_id=10, program_type="primary", curriculum_year="2024",
            required_total_credits=130,
        ))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="자료구조",
                                   category="전공필수", credits=3))
        db.commit()
        return compute_graduation_progress(db, 1)

    def test_on_leave_student_is_judged(self):
        results = self._progress_with_status("휴학")
        self.assertEqual(1, len(results))
        self.assertTrue(results[0].requirement_found)
        self.assertEqual(130, results[0].required_total_credits)

    def test_enrolled_and_default_statuses_are_judged(self):
        for status in ("재학", "active"):
            self.assertEqual(1, len(self._progress_with_status(status)), status)

    def test_withdrawn_student_is_excluded(self):
        """자퇴·제적·졸업은 판정 대상이 아니다."""
        for status in ("자퇴", "제적", "졸업"):
            self.assertEqual([], self._progress_with_status(status), status)


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
