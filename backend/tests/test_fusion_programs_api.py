"""GET /me/fusion-programs/available 유닛테스트.

- 참여 학과에 학생 학과가 포함된 융합/연계/트랙만 노출
- 참여 학과 아님 / program_courses 0건 / 본인 주전공 프로그램 / 학과 미지정 → 제외
- curriculum_year 중복 시 최신 행 채택
- special_rules.certification_type='AI융합트랙' → kind='track'
- program_type='primary' + 이름에 융합전공 → 제외
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.fusion_programs import list_available_fusion_programs
from app.core.db import Base
from app.domains.academics.models import (
    College,
    Department,
    GraduationRequirement,
    Major,
    ProgramCourse,
    School,
    UserAcademicProgram,
)
from app.domains.courses.models import Course
from app.domains.users.models import User

_TABLES = [
    School.__table__,
    College.__table__,
    Department.__table__,
    Major.__table__,
    User.__table__,
    UserAcademicProgram.__table__,
    Course.__table__,
    GraduationRequirement.__table__,
    ProgramCourse.__table__,
]

_YEAR = "2026"


def _seed(db: Session):
    db.add(School(id=1, name="테스트"))
    db.flush()
    db.add(College(id=1, school_id=1, name="테스트대학"))
    db.flush()
    # 학생 소속 학과
    db.add(Department(id=18, college_id=1, name="심리학과"))
    # 연계전공 host + 공통 기여 학과 + dept-level 융합전공 host
    db.add(Department(id=20, college_id=1, name="경영학과"))
    db.add(Department(id=30, college_id=1, name="정보컴퓨터공학부"))
    db.add(Department(id=40, college_id=1, name="반도체융합전공"))
    db.flush()
    db.add(Major(id=66, department_id=20, name="빅데이터(SW연계전공)"))
    db.flush()

    # linked, major-level: 2026/48이 최신, 2023/42는 무시돼야 함
    db.add(GraduationRequirement(
        department_id=20, major_id=66, program_type="interdisciplinary",
        required_total_credits=48, curriculum_year="2026",
    ))
    db.add(GraduationRequirement(
        department_id=20, major_id=66, program_type="interdisciplinary",
        required_total_credits=42, curriculum_year="2023",
    ))
    # convergence, dept-level: 참여학과 = {30}만 → 심리학과 학생에겐 안 보임
    db.add(GraduationRequirement(
        department_id=40, major_id=None, program_type="minor",
        required_total_credits=21, curriculum_year="2026",
    ))
    db.flush()

    # courses
    db.add(Course(id=1, course_code="PS100", course_name="심리통계", department_id=18, credits=3.0))
    db.add(Course(id=2, course_code="CS200", course_name="자료구조", department_id=30, credits=3.0))
    db.add(Course(id=3, course_code="SV300", course_name="반도체개론", department_id=30, credits=3.0))
    db.flush()

    # program_courses: (20,66) → 심리학과·정보컴퓨터공학부 과목 인정 → 참여 {18,30}
    db.add(ProgramCourse(department_id=20, major_id=66, course_id=1, curriculum_year=_YEAR))
    db.add(ProgramCourse(department_id=20, major_id=66, course_id=2, curriculum_year=_YEAR))
    # (40,None) → 정보컴퓨터공학부 과목만 → 참여 {30}
    db.add(ProgramCourse(department_id=40, major_id=None, course_id=3, curriculum_year=_YEAR))
    db.flush()


def _make_user(db: Session, dept_id: int | None = 18, major_id: int | None = None) -> User:
    u = User(id=100, email="t@x.com", password_hash="x", name="테스트",
             department_id=dept_id, major_id=major_id)
    db.add(u)
    db.flush()
    db.add(UserAcademicProgram(user_id=u.id, department_id=dept_id, major_id=major_id,
                                program_type="primary", status="active"))
    db.flush()
    return u


def _make_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=_TABLES)
    return Session(engine)


class FusionProgramsAvailableTest(unittest.TestCase):
    def test_eligible_linked_program_shown(self):
        db = _make_db(); _seed(db); user = _make_user(db, dept_id=18); db.commit()
        result = list_available_fusion_programs(current_user=user, db=db)
        self.assertEqual(1, len(result))
        option = result[0]
        self.assertEqual("linked", option.kind)
        self.assertEqual("SW연계전공", option.kind_label)  # 접미사 우선
        self.assertEqual(48, option.total_credits)
        self.assertEqual("2026", option.curriculum_year)  # 중복행 중 최신 채택
        self.assertEqual("경영학과", option.department_name)
        self.assertEqual(66, option.major_id)
        self.assertEqual("빅데이터(SW연계전공)", option.program_name)
        self.assertIsNone(option.program_type_label)
        self.assertEqual(
            ["심리학과", "정보컴퓨터공학부"],
            [d.name for d in option.participating_departments],
        )

    def test_non_participating_program_excluded(self):
        """반도체융합전공(참여학과 {30}) — 심리학과 학생에겐 안 보임."""
        db = _make_db(); _seed(db); user = _make_user(db, dept_id=18); db.commit()
        result = list_available_fusion_programs(current_user=user, db=db)
        self.assertNotIn(40, [o.department_id for o in result])

    def test_no_program_courses_excluded(self):
        db = _make_db(); _seed(db)
        db.add(Major(id=77, department_id=20, name="에너지IoT(SW연계전공)"))
        db.flush()
        db.add(GraduationRequirement(
            department_id=20, major_id=77, program_type="interdisciplinary",
            required_total_credits=48, curriculum_year="2026",
        ))
        user = _make_user(db, dept_id=18); db.commit()
        result = list_available_fusion_programs(current_user=user, db=db)
        self.assertNotIn(77, [o.major_id for o in result])

    def test_excludes_own_primary_program(self):
        """학생이 (20,66) 자체를 주전공으로 갖고 있으면 그 프로그램은 빠진다."""
        db = _make_db(); _seed(db)
        user = _make_user(db, dept_id=20, major_id=66); db.commit()
        result = list_available_fusion_programs(current_user=user, db=db)
        self.assertEqual([], result)

    def test_no_department_returns_empty(self):
        db = _make_db(); _seed(db); user = _make_user(db, dept_id=None); db.commit()
        self.assertEqual([], list_available_fusion_programs(current_user=user, db=db))

    def test_ai_track_classified_as_track(self):
        db = _make_db(); _seed(db)
        db.add(Major(id=88, department_id=18, name="심리데이터사이언스(SW융합트랙)"))
        db.flush()
        db.add(GraduationRequirement(
            department_id=18, major_id=88, program_type="interdisciplinary",
            required_total_credits=21, curriculum_year="2026",
            special_rules={"certification_type": "AI융합트랙", "not_graduation_requirement": True},
        ))
        db.flush()
        # 트랙 인정 과목 = 심리학과 + 정보컴퓨터공학부(AI공통 대용) → 참여 {18,30}
        db.add(ProgramCourse(department_id=18, major_id=88, course_id=1, curriculum_year=_YEAR))
        db.add(ProgramCourse(department_id=18, major_id=88, course_id=2, curriculum_year=_YEAR))
        user = _make_user(db, dept_id=18); db.commit()
        result = list_available_fusion_programs(current_user=user, db=db)
        track = next(o for o in result if o.major_id == 88)
        self.assertEqual("track", track.kind)
        self.assertEqual("AI융합트랙", track.kind_label)  # is_ai_track 우선

    def test_interdisciplinary_dropped_when_minor_or_dual_exists(self):
        """핀테크융합전공처럼 interdisciplinary(42) + dual(42)이면 interdisciplinary는 버린다."""
        db = _make_db(); _seed(db)
        db.add(Department(id=60, college_id=1, name="핀테크융합전공"))
        db.flush()
        for ptype, credits in (("interdisciplinary", 42), ("dual", 42), ("minor", 21)):
            db.add(GraduationRequirement(
                department_id=60, major_id=None, program_type=ptype,
                required_total_credits=credits, curriculum_year="2026",
            ))
        db.flush()
        db.add(ProgramCourse(department_id=60, major_id=None, course_id=1, curriculum_year=_YEAR))
        user = _make_user(db, dept_id=18); db.commit()
        result = list_available_fusion_programs(current_user=user, db=db)
        fintech = [o for o in result if o.department_id == 60]
        self.assertEqual(
            {"dual", "minor"}, {o.program_type for o in fintech}
        )
        self.assertEqual({"복수전공", "부전공"}, {o.program_type_label for o in fintech})

    def test_primary_program_type_excluded(self):
        """이름에 '융합전공'이 들어가도 program_type='primary'면 제외."""
        db = _make_db(); _seed(db)
        db.add(Department(id=50, college_id=1, name="지능형헬스사이언스융합전공"))
        db.flush()
        db.add(GraduationRequirement(
            department_id=50, major_id=None, program_type="primary",
            required_total_credits=126, curriculum_year="2026",
        ))
        db.flush()
        # primary 행에도 program_courses가 있어 참여학과 게이트는 통과한다고 가정 (참여 {18})
        db.add(ProgramCourse(department_id=50, major_id=None, course_id=1, curriculum_year=_YEAR))
        user = _make_user(db, dept_id=18); db.commit()
        result = list_available_fusion_programs(current_user=user, db=db)
        self.assertNotIn("primary", [o.program_type for o in result])
        self.assertNotIn(50, [o.department_id for o in result])


if __name__ == "__main__":
    unittest.main()
