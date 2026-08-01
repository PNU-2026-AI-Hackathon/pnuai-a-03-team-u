"""SW융합교육과정(융합트랙·연계전공·융합전공)을 계층과 졸업요건에 적재한다.

출처: 「PNU SW융합교육과정 안내」 p.2~4 (부산대학교 교육과정 편성 및 운영규정
제23조의4·제24조의4, 24.04.01. 개정 기준)

모델링 결정
-----------
- 프로그램 하나 = 개설학과 밑의 `majors` 행. 같은 프로그램명이라도 개설학과가
  다르면 다른 행이다. `graduation_requirements`/`user_academic_programs`가 이미
  (department_id, major_id, program_type)로 키를 잡고 있어, 학과별로 다른 이수학점을
  추가 스키마 없이 표현할 수 있다.
- `program_type`은 전부 `interdisciplinary` 하나로 통합한다. 프로그램 식별은
  major_id가 이미 하므로 유형별로 값을 나눌 실익이 없고, 유형 구분은 majors.name의
  접미사("(SW융합트랙)" 등)로 남긴다.
- 개설 주체가 세부전공인 경우(디자인앤테크놀로지전공, 전자공학전공, 전기공학전공)는
  majors가 department를 부모로만 가질 수 있어 **상위 학과 밑에 붙인다.** 어느 세부전공이
  운영하는지는 HOST_MAJOR_NOTE에 기록만 해둔다.

범위에서 제외한 것
------------------
- **SW융합마이크로디그리**: 자료상 "25학년도 2학기 이후 신설 예정"이라 확정 편제가 아님.
- **부전공/복수전공**: SW학과 과목을 이수하는 형태라 별도 프로그램 행이 필요 없다.

인정 과목(TRACK_COURSES)
------------------------
자료의 트랙별 교육과정표를 `program_courses`에 넣는다. 교과목번호(course_code)로
매칭하고, 매칭 실패는 조용히 넘기지 않고 건너뜀 목록에 남긴다 — 이름으로 매칭하면
같은 이름의 다른 과목에 잘못 붙을 수 있어서다(실제로 자료의 '도서관데이터분석실습'은
LI2001637이 아니라 LI2001639이고, LI2001637은 현행 '디지털자료관리'다).

**아직 반영하지 못한 것**: "해당 과목 중 최소 4과목 이상", "공통교과목 중 최소 2과목"
같은 과목 수 조건. flat `graduation_requirements`는 이수구분별 학점 합계만 담는
구조라 표현할 수 없다. 아래 min_courses에 데이터로만 적어두고, 나머지 트랙 자료를
모두 받은 뒤 그룹 요건 스키마를 한 번에 설계한다.

이수학점 근거
-------------
- SW융합트랙: 학과전공과목(12~15) + SW융합 공통교과목(6~9) = **총 21학점**
- SW연계전공: 최소전공인정학점인 전공필수 및 전공선택 **48학점**
- SW융합전공: "복수전공 이수 시 해당 전공의 최소전공 학점" — 전공별로 달라 자료에
  확정 숫자가 없다. required_total_credits를 NULL로 두고 요건 계산에서 경고가 뜨게 한다.

flat `graduation_requirements`는 이수구분별 컬럼(전공필수/전공선택/교양…)만 있는데
위 기준은 "학과전공 + SW공통"처럼 다른 축으로 쪼개져 있어 매핑되지 않는다. 그래서
총학점만 채우고 이수구분 컬럼은 비운다.

실행:
    python -m scripts.seed_sw_convergence_programs             # dry-run
    python -m scripts.seed_sw_convergence_programs --apply     # 실제 반영
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domains.academics.models import (
    College,
    Department,
    GraduationRequirement,
    Major,
    ProgramCourse,
    School,
)
from app.domains.courses.models import Course

CURRICULUM_YEAR = "2026"
PROGRAM_TYPE = "interdisciplinary"

TRACK_SUFFIX = "(SW융합트랙)"
LINKED_SUFFIX = "(SW연계전공)"
CONVERGENCE_SUFFIX = "(SW융합전공)"

TRACK_TOTAL_CREDITS = 21
LINKED_TOTAL_CREDITS = 48

# 적재에서 뺄 트랙이 생기면 여기에 이름을 넣는다.
_EXCLUDED_TRACKS: set[str] = set()

# 이수 기준상의 묶음. flat graduation_requirements의 이수구분(전공필수/교양…)과는
# 다른 축이라 program_courses.requirement_group에 담는다.
GROUP_DEPARTMENT_MAJOR = "학과전공과목"
GROUP_SW_COMMON = "SW융합공통교과목"

# SW융합 공통교과목 개설 주체. AIS 2026 시드는 학과 편제 기준이라 학과가 아닌
# 소프트웨어융합교육원 개설 과목이 통째로 빠져 있다(SF 접두 과목 0건). 공통교과목은
# 모든 트랙의 요건(6~9학점)에 걸리므로 여기서 개설 주체와 과목을 함께 만든다.
# 학위를 주는 학과가 아니므로 회원가입 학과 선택 목록에서는 제외한다
# (app/api/departments.py의 NON_DEGREE_DEPARTMENTS).
SW_COMMON_COLLEGE = "소프트웨어융합교육원"
SW_COMMON_DEPARTMENT = "소프트웨어융합교육원"

# 자료에 나온 SW융합 공통교과목. 전부 3학점, 학년·학기 무관, 이수구분 '일선'.
# courses에 없으면 만들고, 있으면 그대로 쓴다.
SW_COMMON_COURSE_DEFS = [
    ("SF1101073", "데이터분석입문"),
    ("SF1101074", "AI이해를위한파이썬기초"),
    ("SF1101080", "AI리터러시의이해"),
    ("SF1101084", "데이터리터러시의이해"),
]
SW_COMMON_CATEGORY = "일반선택"
SW_COMMON_CREDITS = 3.0
SW_COMMON_YEAR = "전학년"
SW_COMMON_SEMESTER = "전학기"

# 트랙별 인정 과목. (교과목번호, 교과목명, requirement_group) 3-튜플.
#
# 매칭은 course_code로만 한다 — 이름 매칭은 오매칭 위험이 크다(자료의
# '도서관데이터분석실습'은 실제로 LI2001639이고, 자료에 적힌 LI2001637은 현행
# '디지털자료관리'다). 다만 코드가 구버전인 경우도 있어(소셜미디어데이터분석은
# 자료 CO2001037이 DB에 없고 CO2001309가 현행), 그런 건 팀 확인 후 여기 코드를 고친다.
#
# requirement_group에 "(필수)"/"(택1-A)" 같은 하위 묶음을 담는다. flat
# graduation_requirements는 이수구분별 학점 합계만 담아 이런 조건을 표현할 수 없어서다.
# **판정 로직은 아직 없다** — 데이터만 보존하고, 14개 트랙을 다 받은 뒤 규칙 스키마를
# 설계한다.
TRACK_COURSES: dict[str, dict] = {
    "문헌정보데이터분석": {
        "rule": "학과전공과목 중 최소 4과목 이상 선택 + SW융합공통교과목 중 최소 2과목",
        "courses": [
            ("LI3400542", "정보시스템론", GROUP_DEPARTMENT_MAJOR),
            # 자료의 '문헌정보분석론'(LI3400427)은 2026 편제에 없고 이 과목으로 대체됨.
            ("LI2001635", "도서관데이터분석개론", GROUP_DEPARTMENT_MAJOR),
            ("LI3400547", "정보검색론", GROUP_DEPARTMENT_MAJOR),
            # 자료의 '도서관데이터분석실습' 자리. 코드는 그대로고 이름만 바뀌었다.
            ("LI2001637", "디지털자료관리", GROUP_DEPARTMENT_MAJOR),
            ("LI2001640", "메타데이터설계", GROUP_DEPARTMENT_MAJOR),
            ("LI2001645", "프로젝트관리론", GROUP_DEPARTMENT_MAJOR),
        ],
        # 공통교과목이 자료에 특정되지 않고 "중 최소 2과목"으로만 적혀 있어,
        # 개설된 공통교과목 전체를 후보로 붙인다.
        "sw_common_all": True,
    },
    "미디어데이터사이언스": {
        "rule": (
            "학과전공과목 15학점(7과목 중 5과목) + SW융합공통교과목 6학점. "
            "빅데이터분석의이해와활용 필수, 데이터저널리즘/소셜미디어데이터분석 중 1과목 필수. "
            "SW공통은 (데이터분석입문|AI이해를위한파이썬기초) 1과목 + "
            "(데이터리터러시의이해|AI리터러시의이해) 1과목."
        ),
        "courses": [
            ("CO3500882", "빅데이터분석의이해와활용", f"{GROUP_DEPARTMENT_MAJOR}(필수)"),
            ("CO2200100", "커뮤니케이션연구방법론", GROUP_DEPARTMENT_MAJOR),
            ("CO2300715", "뉴미디어와사회", GROUP_DEPARTMENT_MAJOR),
            ("CO3000486", "온라인PR", GROUP_DEPARTMENT_MAJOR),
            ("CO3600447", "커뮤니케이션기초통계", GROUP_DEPARTMENT_MAJOR),
            ("CO2001071", "데이터저널리즘", f"{GROUP_DEPARTMENT_MAJOR}(택1-A)"),
            # 자료는 CO2001037이지만 DB에 없다. 이름·학과·학점·이수구분이 모두 일치하는
            # 현행 코드가 CO2001309 하나뿐이라 팀 확인 후 이쪽으로 연결.
            ("CO2001309", "소셜미디어데이터분석", f"{GROUP_DEPARTMENT_MAJOR}(택1-A)"),
            ("SF1101073", "데이터분석입문", f"{GROUP_SW_COMMON}(택1-A)"),
            ("SF1101074", "AI이해를위한파이썬기초", f"{GROUP_SW_COMMON}(택1-A)"),
            ("SF1101084", "데이터리터러시의이해", f"{GROUP_SW_COMMON}(택1-B)"),
            ("SF1101080", "AI리터러시의이해", f"{GROUP_SW_COMMON}(택1-B)"),
        ],
    },
    "데이터사이언스와복지": {
        # 5과목 15학점이 전부 지정 과목이라 "N과목 중 선택" 조건이 없다.
        # 교과목번호의 SW 접두는 소프트웨어가 아니라 사회복지학과 코드다.
        "rule": "학과전공과목 15학점(지정 5과목 전부) + SW융합공통교과목 중 2과목(6학점)",
        "courses": [
            ("SW2400655", "사회복지조사론", GROUP_DEPARTMENT_MAJOR),
            ("SW2000092", "사회복지자료분석론", GROUP_DEPARTMENT_MAJOR),
            ("SW2000088", "지역사회복지론", GROUP_DEPARTMENT_MAJOR),
            ("SW2000090", "사회복지행정론", GROUP_DEPARTMENT_MAJOR),
            ("SW2000087", "사회복지정책론", GROUP_DEPARTMENT_MAJOR),
        ],
        "sw_common_all": True,
    },
    "소셜데이터사이언스": {
        "rule": "학과전공과목 15학점(6과목 중 5과목 선택) + SW융합공통교과목 중 2과목(6학점)",
        "courses": [
            ("SO2100703", "사회조사방법론", GROUP_DEPARTMENT_MAJOR),
            ("SO1500550", "사회통계학", GROUP_DEPARTMENT_MAJOR),
            # 자료는 띄어쓰기, DB(AIS)는 붙여쓰기 — 공백 차이는 _squash가 흡수한다.
            ("SO2001652", "디지털과 영상사회학", GROUP_DEPARTMENT_MAJOR),
            ("SO3600456", "과학기술과 사회", GROUP_DEPARTMENT_MAJOR),
            ("SO2001653", "소셜데이터의 이해와분석", GROUP_DEPARTMENT_MAJOR),
            ("SO2800973", "인터넷과 정보사회", GROUP_DEPARTMENT_MAJOR),
        ],
        "sw_common_all": True,
    },
    "심리데이터사이언스": {
        "rule": "학과전공과목 15학점(8과목 중 5과목 선택) + SW융합공통교과목 중 2과목(6학점)",
        "courses": [
            ("PY3600441", "심리통계및실습(I)", GROUP_DEPARTMENT_MAJOR),
            ("PY3500222", "연구설계및실습", GROUP_DEPARTMENT_MAJOR),
            ("PY1600548", "과학으로서의심리학", GROUP_DEPARTMENT_MAJOR),
            ("PY3800687", "사회신경과학", GROUP_DEPARTMENT_MAJOR),
            ("PY2100847", "공학심리학", GROUP_DEPARTMENT_MAJOR),
            ("PY3500220", "감정과학", GROUP_DEPARTMENT_MAJOR),
            ("PY3600439", "임상신경심리학", GROUP_DEPARTMENT_MAJOR),
            ("PY3500217", "뇌정보처리", GROUP_DEPARTMENT_MAJOR),
        ],
        "sw_common_all": True,
    },
}

# 개설 주체가 세부전공이라 상위 학과 밑에 붙인 것들 (기록용).
HOST_MAJOR_NOTE = {
    "디자인컴퓨팅": "디자인학과 디자인앤테크놀로지전공",
    "임베디드SW": "전기전자공학부 전자공학전공",
    "에너지IoT": "전기전자공학부 전기공학전공",
}

# (프로그램명, 단과대학, 개설학과)
TRACKS = [
    ("문헌정보데이터분석", "사회과학대학", "문헌정보학과"),
    ("미디어데이터사이언스", "사회과학대학", "미디어커뮤니케이션학과"),
    ("데이터사이언스와복지", "사회과학대학", "사회복지학과"),
    ("소셜데이터사이언스", "사회과학대학", "사회학과"),
    ("심리데이터사이언스", "사회과학대학", "심리학과"),
    ("정치데이터사이언스", "사회과학대학", "정치외교학과"),
    ("행정관리과학(DMS)", "사회과학대학", "행정학과"),
    ("공공데이터분석", "경제통상대학", "공공정책학부"),
    ("디지털패션", "생활과학대학", "의류학과"),
    ("AI 스포츠과학", "생활과학대학", "스포츠과학과"),
    ("디자인컴퓨팅", "예술대학", "디자인학과"),
    ("바이오메디컬디바이스&데이터", "정보의생명공학대학", "의생명융합공학부"),
    ("산업AI", "공과대학", "산업공학과"),
    ("도시·환경·생태 데이터분석", "생명자원과학대학", "조경학과"),
]

LINKED_MAJORS = [
    ("산업수학SW", "자연과학대학", "수학과"),
    ("빅데이터", "공과대학", "산업공학과"),
    ("임베디드SW", "공과대학", "전기전자공학부"),
    ("에너지IoT", "공과대학", "전기전자공학부"),
    ("산업AI", "공과대학", "산업공학과"),
]

# SW융합전공. 핀테크융합전공은 이미 `departments`에 독립 편제 단위로 존재하므로
# (경영대학 소속, 자체 과목 47개 + 주전공 졸업요건 보유) majors 행을 새로 만들지 않고,
# 그 학과에 다중전공용 요건 행만 추가한다. 같은 프로그램을 두 군데로 쪼개지 않기 위함.
CONVERGENCE_MAJORS_AS_DEPARTMENT = [
    ("핀테크융합전공", "경영대학", "핀테크융합전공"),
]


def _squash(name: str) -> str:
    """과목명 비교용 정규화. 공백 차이만 흡수한다."""
    return name.replace(" ", "").strip()


def _find_department(db, school_id: int, college_name: str, department_name: str) -> Department | None:
    return db.scalars(
        select(Department)
        .join(College, College.id == Department.college_id)
        .where(
            College.school_id == school_id,
            College.name == college_name,
            Department.name == department_name,
        )
    ).first()


def _get_or_create_major(db, department_id: int, name: str) -> tuple[Major, bool]:
    major = db.scalars(
        select(Major).where(Major.department_id == department_id, Major.name == name)
    ).first()
    if major is not None:
        return major, False
    major = Major(department_id=department_id, name=name)
    db.add(major)
    db.flush()
    return major, True


def _ensure_sw_common_courses(db, school_id: int) -> tuple[list[Course], int, int]:
    """소프트웨어융합교육원 학과와 SW융합 공통교과목을 만들어 둔다(멱등).

    AIS 시드가 학과 편제만 가져와서 이 과목들이 courses에 아예 없다. 트랙 요건의
    6~9학점을 차지하므로 여기서 직접 만든다.
    """
    college = db.scalars(
        select(College).where(College.school_id == school_id, College.name == SW_COMMON_COLLEGE)
    ).first()
    if college is None:
        college = College(school_id=school_id, name=SW_COMMON_COLLEGE)
        db.add(college)
        db.flush()

    department = db.scalars(
        select(Department).where(
            Department.college_id == college.id, Department.name == SW_COMMON_DEPARTMENT
        )
    ).first()
    if department is None:
        department = Department(college_id=college.id, name=SW_COMMON_DEPARTMENT)
        db.add(department)
        db.flush()

    courses: list[Course] = []
    created = existing = 0
    for code, name in SW_COMMON_COURSE_DEFS:
        course = db.scalars(select(Course).where(Course.course_code == code)).first()
        if course is None:
            course = Course(
                course_code=code,
                course_name=name,
                department_id=department.id,
                category=SW_COMMON_CATEGORY,
                credits=SW_COMMON_CREDITS,
                year=SW_COMMON_YEAR,
                semester=SW_COMMON_SEMESTER,
            )
            db.add(course)
            db.flush()
            created += 1
        else:
            existing += 1
        courses.append(course)
    return courses, created, existing


def _upsert_program_courses(
    db, department_id: int, major_id: int | None, spec: dict, sw_common: list[Course]
) -> tuple[int, int, list[str]]:
    """트랙의 인정 과목을 program_courses에 멱등 upsert한다.

    course_code로만 매칭하고, 못 찾았거나 이름이 다르면 조용히 넘기지 않고 돌려준다.
    """
    entries: list[tuple[str, str, str]] = list(spec["courses"])
    if spec.get("sw_common_all"):
        # 자료가 공통교과목을 특정하지 않고 "중 최소 N과목"으로만 적은 트랙.
        entries += [(c.course_code, c.course_name, GROUP_SW_COMMON) for c in sw_common]

    created = existing = 0
    missing: list[str] = []
    for code, expected_name, group in entries:
        course = db.scalars(select(Course).where(Course.course_code == code)).first()
        if course is None:
            missing.append(f"{code} ({expected_name}) — DB에 없음")
            continue
        # 공백만 다른 건 같은 과목으로 본다. 자료는 '과학기술과 사회'처럼 띄어 쓰고
        # DB(AIS)는 '과학기술과사회'로 붙여 쓰는 경우가 흔하다. 그 외 차이는
        # 코드 재부여/과목 개편일 수 있어 자동으로 넘기지 않고 사람이 확인한다.
        if _squash(course.course_name) != _squash(expected_name):
            missing.append(f"{code}: DB '{course.course_name}' != 자료 '{expected_name}'")
            continue
        row = db.scalars(
            select(ProgramCourse).where(
                ProgramCourse.department_id == department_id,
                ProgramCourse.major_id.is_(None)
                if major_id is None
                else ProgramCourse.major_id == major_id,
                ProgramCourse.course_id == course.id,
                ProgramCourse.curriculum_year == CURRICULUM_YEAR,
            )
        ).first()
        if row is not None:
            row.requirement_group = group
            row.category = course.category
            existing += 1
            continue
        db.add(
            ProgramCourse(
                department_id=department_id,
                major_id=major_id,
                course_id=course.id,
                requirement_group=group,
                category=course.category,
                curriculum_year=CURRICULUM_YEAR,
            )
        )
        created += 1
    return created, existing, missing


def _upsert_requirement(
    db, department_id: int, major_id: int | None, total_credits: int | None
) -> str:
    """같은 (department, major, program_type, curriculum_year) 행을 덮어쓴다(멱등)."""
    existing = db.scalars(
        select(GraduationRequirement).where(
            GraduationRequirement.department_id == department_id,
            GraduationRequirement.major_id.is_(None)
            if major_id is None
            else GraduationRequirement.major_id == major_id,
            GraduationRequirement.program_type == PROGRAM_TYPE,
            GraduationRequirement.curriculum_year == CURRICULUM_YEAR,
        )
    ).first()
    if existing is not None:
        existing.required_total_credits = total_credits
        return "updated"
    db.add(
        GraduationRequirement(
            department_id=department_id,
            major_id=major_id,
            program_type=PROGRAM_TYPE,
            curriculum_year=CURRICULUM_YEAR,
            required_total_credits=total_credits,
        )
    )
    return "created"


def seed(apply: bool) -> int:
    db = SessionLocal()
    created_majors = updated_reqs = created_reqs = 0
    created_courses = existing_courses = 0
    skipped: list[str] = []
    try:
        school = db.scalars(select(School).where(School.name == "부산대학교")).first()
        if school is None:
            print("!! 학교 '부산대학교'가 없습니다. seed_school_hierarchy를 먼저 실행하세요.")
            return 1

        sw_common_courses, sw_new, sw_old = _ensure_sw_common_courses(db, school.id)
        print(
            f"  [공통] {SW_COMMON_DEPARTMENT} 개설 SW융합공통교과목 "
            f"신규 {sw_new} / 기존 {sw_old}"
        )
        print()

        plan: list[tuple[str, str, str, str, int | None]] = []
        for name, college, dept in TRACKS:
            if name in _EXCLUDED_TRACKS:
                skipped.append(f"{name} (제외 목록)")
                continue
            plan.append((f"{name}{TRACK_SUFFIX}", college, dept, "트랙", TRACK_TOTAL_CREDITS))
        for name, college, dept in LINKED_MAJORS:
            plan.append((f"{name}{LINKED_SUFFIX}", college, dept, "연계", LINKED_TOTAL_CREDITS))

        for major_name, college_name, department_name, kind, credits in plan:
            department = _find_department(db, school.id, college_name, department_name)
            if department is None:
                skipped.append(f"{major_name} — 개설학과 미매칭({college_name}>{department_name})")
                continue
            major, is_new = _get_or_create_major(db, department.id, major_name)
            created_majors += int(is_new)
            action = _upsert_requirement(db, department.id, major.id, credits)
            created_reqs += int(action == "created")
            updated_reqs += int(action == "updated")
            base_name = major_name.split("(")[0]
            note = HOST_MAJOR_NOTE.get(base_name)
            suffix = f"  (실제 개설: {note})" if note else ""
            print(
                f"  [{kind}] {department_name:22} > {major_name:34} "
                f"{credits}학점 major={'NEW' if is_new else 'exist'} req={action}{suffix}"
            )

            spec = TRACK_COURSES.get(base_name)
            if spec is not None:
                c_new, c_old, c_missing = _upsert_program_courses(
                    db, department.id, major.id, spec, sw_common_courses
                )
                created_courses += c_new
                existing_courses += c_old
                print(f"         └ 인정과목 신규 {c_new} / 기존 {c_old}  (이수 규칙 판정 미구현)")
                for item in c_missing:
                    skipped.append(f"{major_name} 과목 {item}")

        # SW융합전공: 이미 독립 학과로 존재하는 프로그램은 요건 행만 추가한다.
        for label, college_name, department_name in CONVERGENCE_MAJORS_AS_DEPARTMENT:
            department = _find_department(db, school.id, college_name, department_name)
            if department is None:
                skipped.append(f"{label} — 학과 미매칭({college_name}>{department_name})")
                continue
            action = _upsert_requirement(db, department.id, None, None)
            created_reqs += int(action == "created")
            updated_reqs += int(action == "updated")
            print(
                f"  [융합] {department_name:22} > (학과 자체{CONVERGENCE_SUFFIX})".ljust(66)
                + f" 최소전공학점 미상 req={action}"
            )

        print()
        print(
            f"majors 신규 {created_majors} / 요건 신규 {created_reqs} 갱신 {updated_reqs}"
            f" / 인정과목 신규 {created_courses} 기존 {existing_courses}"
        )
        if skipped:
            print("건너뜀:")
            for item in skipped:
                print(f"  - {item}")

        if apply:
            db.commit()
            print(">>> 커밋 완료")
        else:
            db.rollback()
            print(">>> dry-run (롤백). 실제 반영하려면 --apply")
        return 0
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="실제 DB에 반영(기본은 dry-run)")
    args = parser.parse_args()
    return seed(apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
