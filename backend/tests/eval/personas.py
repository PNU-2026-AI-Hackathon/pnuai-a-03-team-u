"""PersonaSpec → SQLite 인메모리 DB 시드.

주의: `_ROADMAP_TEST_TABLES` (backend/tests/test_roadmap_chat.py)의 테이블 세트를
그대로 재사용한다. tracks 케이스는 이 위에 그대로 special_rules를 얹으면 되고 (별도
테이블 없음), 시간표 케이스는 CourseOffering/CourseTime을 추가로 만든다.

`_build_student_context_block`이 major/department 조회를 하므로 hierarchy는 반드시
DB에 있어야 한다 — 그래서 PersonaSpec에서 departments/majors를 필수 시드로 받는다.
"""

from __future__ import annotations

import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import Base
from app.domains.academics.models import (
    College, Department, GraduationRequirement, Major, ProgramCourse, School,
    StudentCourseRecord, UserAcademicProgram,
)
from app.domains.courses.models import Course, CourseOffering, CourseTime
from app.domains.planning.models import (
    CourseRoadmap, CourseRoadmapChatMessage, CourseRoadmapChatSession,
    CourseRoadmapItem, PendingRoadmapChange, TimetableChatMessage, TimetableChatSession,
)
from app.domains.users.models import User

from .case_spec import PersonaSpec


_TABLES = [
    School.__table__, College.__table__, Department.__table__, Major.__table__,
    User.__table__, Course.__table__,
    CourseOffering.__table__, CourseTime.__table__,
    CourseRoadmap.__table__, CourseRoadmapItem.__table__, PendingRoadmapChange.__table__,
    CourseRoadmapChatSession.__table__, CourseRoadmapChatMessage.__table__,
    # 시간표 챗도 PR #120 이후 세션 영속형이라 run_timetable_chat이 이 두 테이블을
    # 반드시 읽고 쓴다. 빠져 있으면 --live에서 케이스 17~21이 LLM에 닿지도 못하고
    # `no such table: timetable_chat_sessions`로 죽는다 — 실제로 그 상태였다.
    # dry-run은 _TimeTableToolContext를 직접 부르고 run_timetable_chat을 안 거쳐서
    # 초록불이라 이 공백이 오래 안 보였다.
    TimetableChatSession.__table__, TimetableChatMessage.__table__,
    UserAcademicProgram.__table__, GraduationRequirement.__table__,
    StudentCourseRecord.__table__, ProgramCourse.__table__,
]


def build_persona_db(spec: PersonaSpec) -> tuple[Session, User, CourseRoadmap]:
    """spec을 SQLite 인메모리 DB에 시드하고 (Session, User, CourseRoadmap)을 돌려준다.

    departments/majors → college/school은 자동으로 하나씩 만들어 붙인다 (실제 이름과
    무관, 계층 조회만 통과하면 됨).
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=_TABLES)
    session_factory = sessionmaker(bind=engine)
    db: Session = session_factory()

    # School/College는 케이스마다 유의미하지 않아 하드코딩. Department는 spec의 id 그대로.
    db.add(School(id=1, name="부산대학교"))
    db.flush()
    # Department별 college를 다르게 두는 케이스가 없어 하나로 몰아 붙인다.
    college_ids: dict[str, int] = {}
    next_college_id = 1
    for dept in spec.departments:
        cid = college_ids.get(dept.college_name)
        if cid is None:
            cid = next_college_id
            db.add(College(id=cid, school_id=1, name=dept.college_name))
            db.flush()
            college_ids[dept.college_name] = cid
            next_college_id += 1
        db.add(Department(id=dept.id, college_id=cid, name=dept.name))
    db.flush()

    for m in spec.majors:
        db.add(Major(id=m.id, department_id=m.department_id, name=m.name))
    db.flush()

    user = User(
        id=spec.user_id,
        email=f"{spec.id}@test",
        password_hash="x",
        name=spec.user_name,
        department_id=spec.department_id,
        major_id=spec.major_id,
        career_goal=spec.career_goal,
        admission_type=spec.admission_type,
    )
    db.add(user)
    db.flush()

    for p in spec.programs:
        db.add(UserAcademicProgram(
            user_id=user.id,
            department_id=p.department_id,
            major_id=p.major_id,
            program_type=p.program_type,
            curriculum_year=p.curriculum_year,
            status=p.status,
        ))
    for r in spec.requirements:
        db.add(GraduationRequirement(
            department_id=r.department_id,
            major_id=r.major_id,
            program_type=r.program_type,
            curriculum_year=r.curriculum_year,
            required_total_credits=r.required_total_credits,
            required_major_foundation=r.required_major_foundation,
            required_major_required=r.required_major_required,
            required_major_elective=r.required_major_elective,
            required_general_required=r.required_general_required,
            required_general_elective=r.required_general_elective,
            required_free_elective=r.required_free_elective,
            special_rules=r.special_rules,
        ))
    for c in spec.courses:
        db.add(Course(
            id=c.id,
            course_name=c.course_name,
            department_id=c.department_id,
            major_id=c.major_id,
            category=c.category,
            credits=c.credits,
            year=c.year,
            semester=c.semester,
            description=c.description,
        ))
    db.flush()

    for rec in spec.records:
        db.add(StudentCourseRecord(
            user_id=user.id,
            course_id=rec.course_id,
            raw_course_name=rec.raw_course_name,
            category=rec.category,
            credits=rec.credits,
            year=rec.year,
            semester=rec.semester,
            grade=rec.grade,
            grade_point=rec.grade_point,
        ))

    roadmap = CourseRoadmap(id=1, user_id=user.id)
    db.add(roadmap)
    db.flush()

    for it in spec.roadmap_items:
        db.add(CourseRoadmapItem(
            roadmap_id=roadmap.id,
            course_id=it.course_id,
            course_name=it.course_name,
            planned_grade=it.planned_grade,
            planned_year=it.planned_year,
            planned_semester=it.planned_semester,
            credits=it.credits,
            category=it.category,
            status=it.status,
        ))

    for off in spec.offerings:
        db.add(CourseOffering(
            id=off.id,
            course_id=off.course_id,
            year=off.year,
            semester=off.semester,
            section=off.section,
        ))
        for (day, start, end) in off.times:
            hh, mm = start.split(":")
            eh, em = end.split(":")
            db.add(CourseTime(
                offering_id=off.id,
                day_of_week=day,
                start_time=datetime.time(int(hh), int(mm)),
                end_time=datetime.time(int(eh), int(em)),
            ))

    db.commit()
    return db, user, roadmap
