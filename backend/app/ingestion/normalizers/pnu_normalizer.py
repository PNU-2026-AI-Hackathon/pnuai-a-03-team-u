"""PNU One-Stop 크롤러(app.ingestion.crawlers)의 raw 출력을
도메인 모델(users/academics)에 매핑/저장한다.

DB 매핑만 담당하며, 졸업요건 충족 여부의 최종 판정은 domains/academics의
GraduationRequirement 기준과 StudentCourseRecord를 그때그때 대조해서
계산한다(별도 스냅샷 테이블을 두지 않는다).
"""

import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import encrypt_secret
from app.domains.academics.hierarchy import get_or_create_major, resolve_hierarchy
from app.domains.academics.models import Department, StudentCourseRecord, UserAcademicProgram
from app.domains.users.admission import infer_admission_type_from_status_changes
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

    # 학적신청 표의 부·복수전공이나 융합전공 소속처럼 "…전공" 한 토큰만 온 경우,
    # 그건 세부전공이 아니라 그 프로그램 자체(우리 스키마의 Department)다. major로
    # 떼어내 department를 None으로 두면 `_resolve_registration_hierarchy`가
    # `if not department_name: return None, None`으로 곧장 빠져나가, 부전공
    # UserAcademicProgram 행이 department_id·major_id 없이 저장된다
    # (핀테크융합전공 부전공이 학적에 안 붙는 실제 증상, 2026-08-27).
    if department is None and major is not None:
        department, major = major, None

    return college, department, major


def map_student_record(
    db: Session,
    user_id: int,
    record: dict[str, str],
    status_changes: list[dict[str, str]] | None = None,
) -> UserAcademicProgram:
    """학적부 기본정보(student_info.fetch_student_record 결과)를
    User 기본정보 갱신 + UserAcademicProgram(주전공) upsert로 매핑한다.

    `status_changes`(학적변동 내역)를 주면 편입 여부를 자동 판정한다. 안 주거나
    편입 행이 없으면 기존 `admission_type`을 건드리지 않는다.
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
        # 학적부의 실제 라벨은 "학년/학기"다(값 예: "3"). 예전에는 `record["학년"]`을
        # 찾아서 **항상 빈 문자열**이었고, academic_year가 영영 None으로 남았다.
        # 그러면 로드맵이 학년을 모른 채 1학년으로 잡는다. 라벨이 또 바뀔 수 있으니
        # 두 표기를 모두 받아주고, "3/1"처럼 학기까지 붙어 나와도 맨 앞 숫자만 쓴다
        # (\D 제거로는 "31"이 되어버린다).
        raw_grade = record.get("학년/학기") or record.get("학년") or ""
        grade_match = re.match(r"\s*(\d+)", raw_grade)
        if grade_match:
            user.academic_year = int(grade_match.group(1))

        # 편입 여부는 학적변동 내역이 있을 때만 판정한다(없으면 기존 값 유지).
        inferred = infer_admission_type_from_status_changes(status_changes)
        if inferred is not None:
            user.admission_type = inferred

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
    db: Session,
    user_id: int,
    registration_rows: list[list[str]],
    *,
    reconcile_portal_snapshot: bool = False,
) -> list[UserAcademicProgram]:
    """졸업예정정보(menuCD=000000000000089) 테이블 0의 학적신청 행을
    UserAcademicProgram(주전공/복수전공/부전공/연합전공)에 upsert한다.

    이 정보는 성적표나 졸업요건표에는 없고 이 페이지에서만 확인 가능하다.
    행 형식 예: ['1', '주전공', '의생명융합공학부 데이터사이언스전공', 'N', '선택']
    (마지막 칸은 UI 버튼 라벨이 섞여 들어온 것이라 사용하지 않는다.)

    `reconcile_portal_snapshot=True`는 호출자가 실제 표의 헤더까지 정상적으로
    받았을 때만 준다. 이 경우 이번 표에 없는 기존 포털 출처 부·복수·연계전공은
    ``inactive``로 바꾼다. 파싱 실패/부분 응답을 빈 스냅샷으로 오인해 학적을 지우지
    않으며, 로드맵에서 사용자가 저장한 ``source='fusion_plan'``은 절대 건드리지 않는다.
    """
    saved: list[UserAcademicProgram] = []
    seen_portal_programs: set[tuple[str, int | None, int | None]] = set()
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
            .filter(
                UserAcademicProgram.user_id == user_id,
                UserAcademicProgram.program_type == program_type,
                UserAcademicProgram.major_id == major_id,
                # 로드맵에서 저장한 계획은 실제 One-Stop 학적 동기화가 덮어쓰거나
                # .one_or_none()을 다중행 오류로 만들면 안 된다.
                or_(
                    UserAcademicProgram.source.is_(None),
                    UserAcademicProgram.source == "portal",
                ),
            )
            .one_or_none()
        )
        if program is None:
            program = UserAcademicProgram(user_id=user_id, program_type=program_type)
            db.add(program)
        program.department_id = department_id
        program.major_id = major_id
        program.source = "portal"
        program.status = "active"
        saved.append(program)
        seen_portal_programs.add((program_type, department_id, major_id))

    # 주전공은 학생기본정보 표가 별도 authoritative source라 여기서 비활성화하지
    # 않는다. 나머지는 학적신청 표가 매번 현재 수강생의 전체 목록을 주므로, 이번
    # 스냅샷에 없는 과거 portal/legacy 행을 활성 상태로 남겨두면 졸업 판정이 중복된다.
    # 헤더만 오고 데이터 행이 비었거나 라벨이 바뀌어 전부 skip된 응답은 완전한
    # 스냅샷이 아니다. 주전공을 포함해 적어도 하나의 인식 가능한 공식 행이 있어야
    # "표에 없음"을 실제 해제로 해석한다.
    if reconcile_portal_snapshot and seen_portal_programs:
        existing_portal_programs = (
            db.query(UserAcademicProgram)
            .filter(
                UserAcademicProgram.user_id == user_id,
                UserAcademicProgram.program_type != "primary",
                or_(
                    UserAcademicProgram.source.is_(None),
                    UserAcademicProgram.source == "portal",
                ),
            )
            .all()
        )
        for program in existing_portal_programs:
            identity = (program.program_type, program.department_id, program.major_id)
            if identity not in seen_portal_programs:
                program.status = "inactive"

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
            # 같은 학생을 다시 동기화할 때 과거 졸업예정정보 판정이 남지 않게 먼저
            # 비운다. portal_sync가 이번 크롤의 학교 공식 판정으로 다시 채운다.
            record.liberal_area = None
            record.credits = _to_float(credits)
            record.grade = grade or None
            record.grade_point = _grade_to_point(grade)
            record.is_retake = _is_retake_eligible(grade)
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

# 성적등급 → 평점(4.5 만점). 부산대 표기 기준.
#
# **이걸 안 채우면 재수강 기능이 통째로 죽는다.** `roadmap_chat._compute_retake_candidates`
# 가 `grade_point is None`인 행을 "판단 불가"로 전부 제외하기 때문이다. 2026-08-14 실측:
# 운영 DB 87개 이수기록 전부 grade는 있는데 grade_point가 NULL이라(채우는 코드가 아예
# 없었다) 재수강 후보가 항상 빈 목록이었다 — 감지도, 안내도, propose_change도 동작한 적이 없다.
#
# 'S'(Pass)처럼 평점이 없는 등급은 None으로 남긴다. 그래야 "성적이 나빠서 재수강 후보"와
# "평점 자체가 없는 과목"이 섞이지 않는다.
_GRADE_TO_POINT: dict[str, float] = {
    "A+": 4.5, "A0": 4.0, "A": 4.0,
    "B+": 3.5, "B0": 3.0, "B": 3.0,
    "C+": 2.5, "C0": 2.0, "C": 2.0,
    "D+": 1.5, "D0": 1.0, "D": 1.0,
    "F": 0.0,
}

# 학교마다/학과마다 다르게 표기되지만 실제로는 허용 카테고리 중 하나와 같은 의미인 이름들.
_CATEGORY_ALIASES = {
    "기초교양": "교양선택",
}


def _is_retake_eligible(grade: str) -> bool:
    return (grade or "").strip().upper() in _RETAKE_ELIGIBLE_GRADES


def _grade_to_point(grade: str | None) -> float | None:
    """성적등급 문자열 → 평점. 평점이 없는 등급(S/P/NP 등)은 None."""
    return _GRADE_TO_POINT.get((grade or "").strip().upper())


def _normalize_category(category: str) -> str | None:
    """성적표의 이수구분을 허용 카테고리 중 하나로 정규화한다.

    1. "(학부)" 같은 괄호 주석 제거: "전공기초(학부)" -> "전공기초"
    2. 표기만 다르고 의미가 같은 이름을 표준 이름으로 치환: "기초교양" -> "교양선택"
    """
    if not category:
        return None
    stripped = re.sub(r"\([^)]*\)", "", category).strip()
    return _CATEGORY_ALIASES.get(stripped, stripped)


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
