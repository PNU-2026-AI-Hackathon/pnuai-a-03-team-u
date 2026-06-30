"""PNU One-Stop 크롤러(app.ingestion.crawlers)의 raw 출력을
도메인 모델(users/academics)에 매핑/저장한다.

DB 매핑만 담당하며, 졸업요건 충족 여부의 최종 판정은 domains/academics의
결정론적 로직이 맡는다 (여기서는 크롤링된 원본을 GraduationAudit
스냅샷으로 그대로 보관한다).
"""

import datetime

from sqlalchemy.orm import Session

from app.core.security import encrypt_secret
from app.domains.academics.models import (
    GraduationAudit,
    StudentCourseRecord,
    UserAcademicProgram,
)
from app.domains.users.models import PortalCredential, User

_GRADE_TABLE_HEADER = "학년도"
_GRADE_DATA_COLUMNS = 8  # 학년도, 학기, 성적분류, 교과구분, 교과목명, 학점, 성적등급, 비고


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


def map_student_record(db: Session, user_id: int, record: dict[str, str]) -> UserAcademicProgram:
    """학적부 기본정보(student_info.fetch_student_record 결과)를
    User 기본정보 갱신 + UserAcademicProgram(주전공) upsert로 매핑한다.
    """
    user = db.get(User, user_id)
    if user is not None:
        if record.get("성명"):
            user.name = record["성명"]
        if record.get("학번"):
            user.student_id = record["학번"]
        if record.get("소속학과"):
            user.department = record["소속학과"]

    program = (
        db.query(UserAcademicProgram)
        .filter_by(user_id=user_id, program_type="primary")
        .one_or_none()
    )
    if program is None:
        program = UserAcademicProgram(user_id=user_id, program_type="primary")
        db.add(program)

    program.department = record.get("소속학과")
    program.curriculum_year = record.get("교육과정적용년도")
    program.status = "active" if record.get("학적상태") == "재학" else record.get("학적상태", "active")

    db.flush()
    return program


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
            record.category = category or None
            record.credits = _to_float(credits)
            record.grade = grade or None
            db.add(record)
            saved.append(record)

    db.flush()
    return saved


def map_graduation_requirement(
    db: Session, user_id: int, graduation_tables: list[list[list[str]]]
) -> GraduationAudit:
    """graduation.fetch_graduation_requirement()의 raw 테이블을
    GraduationAudit 스냅샷(summary_json)으로 저장한다.
    """
    audit = GraduationAudit(
        user_id=user_id,
        status="crawled",
        summary_json={"tables": graduation_tables},
        crawled_at=datetime.datetime.now(datetime.UTC),
    )
    db.add(audit)
    db.flush()
    return audit


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
