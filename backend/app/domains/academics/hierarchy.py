"""학교/단과대/학과·학부/전공 계층 get-or-create 헬퍼.

크롤러나 회원가입 입력에서 이름이 들어올 때마다 없으면 만들고 있으면
재사용한다. auth.py(회원가입)와 ingestion/normalizers/pnu_normalizer.py
(크롤링 매핑)에서 공용으로 쓴다.

단, AIS 2026 편제를 시드한 정식 계층(seeds/school_hierarchy_mapping.csv,
scripts/seed_school_hierarchy.py)이 이미 있으므로 **같은 이름의 학과가 정식
계층에 있으면 반드시 그것을 재사용한다**. 단과대 정보 없이 학과명만 들어왔다고
"미지정" 단과대 아래에 새 학과를 만들면, 과목·졸업요건이 하나도 연결되지 않은
껍데기가 생겨 그 사용자는 과목 검색·졸업요건 조회·로드맵 추천이 전부 빈 결과가
된다(실제로 발생했던 사고 — "미지정 > 통계학과"가 자연과학대학의 정식 통계학과와
별개로 생성됨).
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


# 단과대 정보 없이 학과명만 들어왔는데 정식 계층에서도 못 찾은 경우에만 쓰는 임시 단과대.
UNASSIGNED_COLLEGE = "미지정"


def find_department_by_name(db: Session, school_id: int, name: str) -> Department | None:
    """학교 전체에서 이름이 같은 학과를 단과대 무관하게 찾는다.

    이미 "미지정" 아래 중복이 만들어져 있는 데이터가 남아 있을 수 있으므로,
    정식 단과대 소속을 우선해서 돌려준다.
    """
    departments = (
        db.query(Department)
        .join(College, College.id == Department.college_id)
        .filter(College.school_id == school_id, Department.name == name)
        .all()
    )
    if not departments:
        return None
    for department in departments:
        college = db.get(College, department.college_id)
        if college is not None and college.name != UNASSIGNED_COLLEGE:
            return department
    return departments[0]


def resolve_hierarchy(
    db: Session,
    school_name: str | None,
    college_name: str | None,
    department_name: str | None,
    major_name: str | None,
) -> tuple[int | None, int | None]:
    """(학교, 단과대, 학과, 전공) 이름을 받아 (department_id, major_id)를 반환한다.

    department_name이 없으면 (None, None).

    학과를 찾는 순서:
      1. college_name이 주어졌으면 그 단과대 아래에서 먼저 찾는다.
      2. 못 찾으면 학교 전체에서 같은 이름의 학과를 찾아 재사용한다 — 단과대
         표기가 없는 성적표/회원가입 입력이라도 정식 계층에 이름이 있으면
         그쪽에 붙어야 과목·졸업요건이 연결된다.
      3. 그래도 없으면 그때만 새로 만든다(단과대 미상이면 "미지정" 아래).

    2번이 없으면 "미지정 > 통계학과"처럼 과목 0개·졸업요건 0행짜리 껍데기가
    정식 "자연과학대학 > 통계학과"와 별개로 생겨, 그 사용자는 과목 검색·졸업요건
    조회·로드맵 추천이 전부 빈 결과가 된다.
    """
    if not department_name:
        return None, None

    school = get_or_create_school(db, school_name or "부산대학교")

    college: College | None = None
    department: Department | None = None
    if college_name:
        college = get_or_create_college(db, school.id, college_name)
        department = (
            db.query(Department).filter_by(college_id=college.id, name=department_name).one_or_none()
        )

    if department is None:
        department = find_department_by_name(db, school.id, department_name)

    if department is None:
        if college is None:
            college = get_or_create_college(db, school.id, UNASSIGNED_COLLEGE)
        department = get_or_create_department(db, college.id, department_name)

    major_id = None
    if major_name:
        major_id = get_or_create_major(db, department.id, major_name).id

    return department.id, major_id
