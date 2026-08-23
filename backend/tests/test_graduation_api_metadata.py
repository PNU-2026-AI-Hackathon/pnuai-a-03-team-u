"""졸업 진행 API가 추가 이수과정 카드에 필요한 메타데이터를 제공하는지 검증."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.graduation import _build_graduation_response
from app.core.db import Base
from app.domains.academics.models import (
    College,
    Department,
    GraduationRequirement,
    Major,
    School,
    StudentCourseRecord,
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
    Course.__table__,
    UserAcademicProgram.__table__,
    GraduationRequirement.__table__,
    StudentCourseRecord.__table__,
]


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=_TABLES)
    db = sessionmaker(bind=engine)()
    db.add_all([
        School(id=1, name="부산대학교"),
        College(id=1, school_id=1, name="단과대"),
        Department(id=10, college_id=1, name="주전공학과"),
        Department(id=20, college_id=1, name="복수전공학과"),
        Department(id=30, college_id=1, name="트랙학과"),
        Major(id=21, department_id=20, name="복수전공명"),
        Major(id=31, department_id=30, name="AI융합트랙명"),
        User(id=1, email="student@example.com", password_hash="x", name="학생",
             department_id=10),
    ])
    db.flush()
    db.add_all([
        UserAcademicProgram(user_id=1, department_id=10, program_type="primary",
                            curriculum_year="2026"),
        UserAcademicProgram(user_id=1, department_id=20, major_id=21,
                            program_type="dual", curriculum_year="2026"),
        UserAcademicProgram(user_id=1, department_id=30, major_id=31,
                            program_type="interdisciplinary", curriculum_year="2026"),
        GraduationRequirement(department_id=10, program_type="primary",
                              curriculum_year="2026", required_total_credits=130),
        GraduationRequirement(department_id=20, major_id=21, program_type="dual",
                              curriculum_year="2026", required_total_credits=36),
        GraduationRequirement(
            department_id=30,
            major_id=31,
            program_type="interdisciplinary",
            curriculum_year="2026",
            required_total_credits=21,
            special_rules={"certification_type": "AI융합트랙"},
        ),
    ])
    db.commit()
    return db


def test_default_response_keeps_primary_only():
    db = _make_db()
    response = _build_graduation_response(db, db.get(User, 1))
    assert [program.program_type for program in response.programs] == ["primary"]


def test_non_primary_response_includes_names_and_track_marker():
    db = _make_db()
    response = _build_graduation_response(db, db.get(User, 1), include_non_primary=True)
    programs = {program.program_type: program for program in response.programs}

    assert programs["dual"].department_name == "복수전공학과"
    assert programs["dual"].major_name == "복수전공명"
    assert programs["dual"].is_ai_track is False
    assert programs["interdisciplinary"].major_name == "AI융합트랙명"
    assert programs["interdisciplinary"].is_ai_track is True
