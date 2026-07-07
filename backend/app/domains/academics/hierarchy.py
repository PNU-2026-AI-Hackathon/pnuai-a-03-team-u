"""학교/단과대/학과·학부/전공 계층 get-or-create 헬퍼.

미리 시드하지 않고, 크롤러나 회원가입 입력에서 이름이 들어올 때마다
없으면 만들고 있으면 재사용한다. auth.py(회원가입)와
ingestion/normalizers/pnu_normalizer.py(크롤링 매핑)에서 공용으로 쓴다.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.academics.models import College, Department, Major, School


def get_or_create_school(db: Session, name: str) -> School:
    school = db.query(School).filter_by(name=name).one_or_none()
    if school is None:
        school = School(name=name)
        db.add(school)
        db.flush()
    return school


def get_or_create_college(db: Session, school_id: int, name: str) -> College:
    college = db.query(College).filter_by(school_id=school_id, name=name).one_or_none()
    if college is None:
        college = College(school_id=school_id, name=name)
        db.add(college)
        db.flush()
    return college


def get_or_create_department(db: Session, college_id: int, name: str) -> Department:
    department = db.query(Department).filter_by(college_id=college_id, name=name).one_or_none()
    if department is None:
        department = Department(college_id=college_id, name=name)
        db.add(department)
        db.flush()
    return department


def get_or_create_major(db: Session, department_id: int, name: str) -> Major:
    major = db.query(Major).filter_by(department_id=department_id, name=name).one_or_none()
    if major is None:
        major = Major(department_id=department_id, name=name)
        db.add(major)
        db.flush()
    return major


def resolve_hierarchy(
    db: Session,
    school_name: str | None,
    college_name: str | None,
    department_name: str | None,
    major_name: str | None,
) -> tuple[int | None, int | None]:
    """(학교, 단과대, 학과, 전공) 이름을 받아 (department_id, major_id)를 반환한다.

    department_name이 없으면 (None, None). college_name/school_name이 없으면
    "미지정" 단과대/학교 아래에 학과를 붙인다(단과대 표기가 없는 성적표/입력이 있어서).
    """
    if not department_name:
        return None, None

    school = get_or_create_school(db, school_name or "부산대학교")
    college = get_or_create_college(db, school.id, college_name or "미지정")
    department = get_or_create_department(db, college.id, department_name)

    major_id = None
    if major_name:
        major_id = get_or_create_major(db, department.id, major_name).id

    return department.id, major_id
