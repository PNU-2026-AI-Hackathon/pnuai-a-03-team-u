"""PNU One-Stop 크롤러(app.ingestion.crawlers)의 raw 출력을
도메인 모델(users/academics)에 매핑/저장한다.

DB 매핑만 담당하며, 졸업요건 충족 여부의 최종 판정은 domains/academics의
GraduationRequirement 기준과 StudentCourseRecord를 그때그때 대조해서
계산한다(별도 스냅샷 테이블을 두지 않는다).
"""

import re

from sqlalchemy.orm import Session

from app.core.security import encrypt_secret
from app.domains.academics.hierarchy import get_or_create_major, resolve_hierarchy
from app.domains.academics.models import Department, StudentCourseRecord, UserAcademicProgram
from app.domains.courses.models import Course
from app.domains.users.models import PortalCredential, User

_GRADE_TABLE_HEADER = "학년도"
_GRADE_DATA_COLUMNS = 8  # 학년도, 학기, 성적분류, 교과구분, 교과목명, 학점, 성적등급, 비고

# graduation_expected_info 테이블 0("주전공 및 학적신청(부전공,복수전공,연합전공) 정보")의
# "학적신청구분" 값 → UserAcademicProgram.program_type. auth.py의 _VALID_PROGRAM_TYPES와 값을 맞춘다.
_PROGRAM_LABEL_TO_TYPE = {
    "주전공": "primary",
    "복수전공": "dual",
    "부전공": "minor",
    "연합전공": "interdisciplinary",
    "연계전공": "interdisciplinary",
}


def save_portal_credential(db: Session, user_id: int, login_id: str, password: str) -> PortalCredential:
    """학교 포털 비밀번호를 암호화해 저장(또는 갱신)한다."""
    credential = db.query(PortalCredential).filter_by(user_id=user_id).one_or_none()
    if credential is None:
        credential = PortalCredential(user_id=user_id, login_id=login_id)
        db.add(credential)
    credential.login_id = login_id
    credential.encrypted_password = encrypt_secret(password)
    db.flush()
    return credential


def _split_college_department_major(raw: str | None) -> tuple[str | None, str | None, str | None]:
    """학적부 "소속학과" 원문(예: "정보의생명공학대학 의생명융합공학부 데이터사이언스전공")을
    단과대학/학부·학과/세부전공으로 나눈다.

    마지막 단어가 "전공"으로 끝나면 major로 분리한다. "OO과"처럼 세부 전공
    구분이 없으면 major는 null. 남은 단어 중 첫 단어가 "대학"으로 끝나면
    college로 분리하고, 그런 단어가 없으면 college도 null(학과 표기만 있는 경우).
    """
    if not raw:
        return None, None, None

    tokens = raw.split()
    major = None
    if tokens and tokens[-1].endswith("전공"):
        major = tokens[-1]
        tokens = tokens[:-1]

    college = None
    if tokens and tokens[0].endswith("대학"):
        college = tokens[0]
        tokens = tokens[1:]

    department = " ".join(tokens) or None
    return college, department, major


def map_student_record(db: Session, user_id: int, record: dict[str, str]) -> UserAcademicProgram:
    """학적부 기본정보(student_info.fetch_student_record 결과)를
    User 기본정보 갱신 + UserAcademicProgram(주전공) upsert로 매핑한다.
    """
    college, department, major = _split_college_department_major(record.get("소속학과"))
    department_id, major_id = resolve_hierarchy(db, None, college, department, major)

    user = db.get(User, user_id)
    if user is not None:
        if record.get("성명"):
            user.name = record["성명"]
        if record.get("학번"):
            user.student_id = record["학번"]
        if department_id:
            user.department_id = department_id
        user.major_id = major_id

    program = (
        db.query(UserAcademicProgram)
        .filter_by(user_id=user_id, program_type="primary")
        .one_or_none()
    )
    if program is None:
        program = UserAcademicProgram(user_id=user_id, program_type="primary")
        db.add(program)

    program.department_id = department_id
    program.major_id = major_id
    program.curriculum_year = record.get("교육과정적용년도")
    program.status = "active" if record.get("학적상태") == "재학" else record.get("학적상태", "active")

    db.flush()
    return program


def _resolve_registration_hierarchy(
    db: Session, college: str | None, department_name: str | None, major_name: str | None
) -> tuple[int | None, int | None]:
    """학적신청 정보 행에는 단과대 표기가 없는 경우가 많다. college가 없으면
    이름이 같은 기존 Department를 먼저 찾아 재사용해서, 학적부에서 이미
    만들어둔 진짜 단과대 소속 department와 별개의 "미지정" 행이 중복 생성되는
    것을 피한다.
    """
    if not department_name:
        return None, None
    if college:
        return resolve_hierarchy(db, None, college, department_name, major_name)

    existing = db.query(Department).filter_by(name=department_name).first()
    if existing is not None:
        department_id = existing.id
    else:
        department_id, _ = resolve_hierarchy(db, None, None, department_name, None)

    major_id = get_or_create_major(db, department_id, major_name).id if major_name else None
    return department_id, major_id


def map_academic_program_registrations(
    db: Session, user_id: int, registration_rows: list[list[str]]
) -> list[UserAcademicProgram]:
    """졸업예정정보(menuCD=000000000000089) 테이블 0의 학적신청 행을
    UserAcademicProgram(주전공/복수전공/부전공/연합전공)에 upsert한다.

    이 정보는 성적표나 졸업요건표에는 없고 이 페이지에서만 확인 가능하다.
    행 형식 예: ['1', '주전공', '의생명융합공학부 데이터사이언스전공', 'N', '선택']
    (마지막 칸은 UI 버튼 라벨이 섞여 들어온 것이라 사용하지 않는다.)
    """
    saved: list[UserAcademicProgram] = []
    for row in registration_rows:
        if len(row) < 3:
            continue
        label, raw_text = row[1], row[2]
        program_type = _PROGRAM_LABEL_TO_TYPE.get(label)
        if program_type is None or not raw_text:
            continue  # 헤더 행이거나 인식 못하는 구분

        college, department, major = _split_college_department_major(raw_text)
        # 이 테이블(학적신청 정보)에는 단과대 표기가 없는 경우가 많다. college가
        # 없으면 resolve_hierarchy가 "미지정" 단과대를 쓰는데, 이미 학적부에서
        # 만들어둔 진짜 단과대와 다른 department 행이 생길 수 있으니 주의가 필요하다.
        # -> 기존에 같은 department 이름으로 이미 만들어진 행이 있으면 그걸 우선 재사용한다.
        department_id, major_id = _resolve_registration_hierarchy(db, college, department, major)

        program = (
            db.query(UserAcademicProgram)
            .filter_by(user_id=user_id, program_type=program_type, major_id=major_id)
            .one_or_none()
        )
        if program is None:
            program = UserAcademicProgram(user_id=user_id, program_type=program_type)
            db.add(program)
        program.department_id = department_id
        program.major_id = major_id
        saved.append(program)

    db.flush()
    return saved


def map_grades(db: Session, user_id: int, grades_tables: list[list[list[str]]]) -> list[StudentCourseRecord]:
    """grades.fetch_all_grades()의 raw 테이블 목록을 StudentCourseRecord로 매핑한다.

    각 학기 표는 헤더 행(8열) + 과목별 데이터 행(8열) + 학기 요약 행(2열, 건너뜀)
    으로 구성된다.
    """
    saved: list[StudentCourseRecord] = []
    for table in grades_tables:
        for row in table:
            if not row or row[0] == _GRADE_TABLE_HEADER:
                continue
            if len(row) < _GRADE_DATA_COLUMNS:
                continue  # 학기 요약 행 (신청학점/취득학점/평점평균 등)

            year, semester, _grade_class, category, course_name, credits, grade, _remark = row[:8]

            normalized_category = _normalize_category(category)
            if normalized_category not in _ALLOWED_CATEGORIES:
                continue  # 실제 과목이 아닌 행

            # 주의: 과목명이 이수구분명과 같은 행(예: 과목명="교양선택")은 소계가
            # 아니라 "전적학교성적"(입학 전 인정된 학점) 같은 정상 데이터일 수 있으므로
            # 과목명만으로 걸러내면 안 된다. len(row) < _GRADE_DATA_COLUMNS 체크로
            # 실제 소계/요약 행은 이미 위에서 걸러진다.

            existing = (
                db.query(StudentCourseRecord)
                .filter_by(
                    user_id=user_id,
                    raw_course_name=course_name,
                    year=year,
                    semester=semester,
                )
                .one_or_none()
            )
            record = existing or StudentCourseRecord(
                user_id=user_id,
                raw_course_name=course_name,
                year=year,
                semester=semester,
                source="crawler",
            )
            record.category = normalized_category
            record.credits = _to_float(credits)
            record.grade = grade or None
            record.is_retake = _is_retake_eligible(grade)
            _link_course_catalog(db, record, course_name)
            db.add(record)
            saved.append(record)

    db.flush()
    return saved


# 실제 이수구분으로 인정하는 값만 저장한다. 성적표에는 소계/구분 헤더 행이
# 데이터 행과 같은 8열 구조로 섞여 나오는 경우가 있어(과목명 칸에 "교양선택"
# 같은 구분명 자체가 들어있는 행), 이 목록에 없으면 실제 과목이 아닌 것으로 보고 건너뛴다.
_ALLOWED_CATEGORIES = {
    "전공기초",
    "전공필수",
    "전공선택",
    "일반선택",
    "교양필수",
    "교양선택",
    "교직과목",
}

# 재수강 가능 기준: C+ 이하(C+, C0, D+, D0, F 등). 이 등급들은 재수강해서
# 성적을 다시 받을 수 있는 과목이라는 뜻으로 is_retake를 True로 표시한다.
_RETAKE_ELIGIBLE_GRADES = {"C+", "C0", "C", "D+", "D0", "D", "F"}

# 학교마다/학과마다 다르게 표기되지만 실제로는 허용 카테고리 중 하나와 같은 의미인 이름들.
_CATEGORY_ALIASES = {
    "기초교양": "교양선택",
}


def _is_retake_eligible(grade: str) -> bool:
    return (grade or "").strip().upper() in _RETAKE_ELIGIBLE_GRADES


def _normalize_category(category: str) -> str | None:
    """성적표의 이수구분을 허용 카테고리 중 하나로 정규화한다.

    1. "(학부)" 같은 괄호 주석 제거: "전공기초(학부)" -> "전공기초"
    2. 표기만 다르고 의미가 같은 이름을 표준 이름으로 치환: "기초교양" -> "교양선택"
    """
    if not category:
        return None
    stripped = re.sub(r"\([^)]*\)", "", category).strip()
    return _CATEGORY_ALIASES.get(stripped, stripped)


def _link_course_catalog(db: Session, record: StudentCourseRecord, course_name: str) -> None:
    """수강편람(courses 테이블)에서 과목명이 일치하는 강좌를 찾아 연결한다.

    성적표 원본에는 course_code가 없어 이름으로만 매칭한다. 동일 과목명이
    여러 강좌(분반/학과)로 개설된 경우 어느 것인지 특정할 수 없으므로
    "ambiguous"로 남기고 course_id는 비워둔다(오매칭보다 안전).
    """
    matches = db.query(Course).filter_by(course_name=course_name).all()
    if len(matches) == 1:
        record.course_id = matches[0].id
        record.match_status = "matched"
    elif len(matches) > 1:
        record.course_id = None
        record.match_status = "ambiguous"
    else:
        record.course_id = None
        record.match_status = "unmatched"


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
