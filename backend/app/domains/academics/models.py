from sqlalchemy import JSON, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class School(TimestampMixin, Base):
    """학교(예: "부산대학교")."""

    __tablename__ = "schools"
    # unique=True(단일 unique 인덱스)가 아니라 UniqueConstraint + 일반 인덱스로 둔다 —
    # e6f7a8b9c0d1 마이그레이션이 실제로 만든(=라이브 Supabase의) 형태와 맞춰
    # alembic check drift를 없애기 위함. 의미는 동일하다.
    __table_args__ = (UniqueConstraint("name", name="schools_name_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), index=True)


class College(TimestampMixin, Base):
    """단과대학(예: "정보의생명공학대학")."""

    __tablename__ = "colleges"
    __table_args__ = (UniqueConstraint("school_id", "name", name="uq_college_school_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))


class Department(TimestampMixin, Base):
    """학부/학과(예: "의생명융합공학부", "컴퓨터공학과")."""

    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("college_id", "name", name="uq_department_college_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))


class Major(TimestampMixin, Base):
    """세부 전공(학부제일 때만 존재, 예: "데이터사이언스전공").

    "OO과"처럼 학과 자체가 곧 전공 단위라 세부 전공 구분이 없는 경우는
    이 테이블에 행을 만들지 않고, 참조하는 쪽(major_id)을 null로 둔다.
    """

    __tablename__ = "majors"
    __table_args__ = (UniqueConstraint("department_id", "name", name="uq_major_department_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))


class UserAcademicProgram(TimestampMixin, Base):
    """사용자의 학적 프로그램(주전공/복수전공/부전공/연계전공 등)."""

    __tablename__ = "user_academic_programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    major_id: Mapped[int | None] = mapped_column(ForeignKey("majors.id"), nullable=True, index=True)
    program_type: Mapped[str] = mapped_column(String(20), default="primary")
    curriculum_year: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="active")


class StudentCourseRecord(TimestampMixin, Base):
    """학생이 이수한 과목 기록. 크롤러의 grades 결과에서 매핑한다."""

    __tablename__ = "student_course_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    # 이 과목이 어느 학적 프로그램(주전공/복수전공/부전공) 이수요건으로 카운트되는지.
    # 성적표 원본에는 이 구분이 없어 크롤링만으로는 채울 수 없고, 졸업요건 판정
    # 로직이 규칙에 따라 나중에 채운다.
    user_academic_program_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_academic_programs.id"), nullable=True, index=True
    )

    raw_course_code: Mapped[str | None] = mapped_column(String(50))
    raw_course_name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(50))
    credits: Mapped[float | None] = mapped_column(Numeric(4, 1))
    year: Mapped[str | None] = mapped_column(String(10))
    semester: Mapped[str | None] = mapped_column(String(20))
    grade: Mapped[str | None] = mapped_column(String(10))
    grade_point: Mapped[float | None] = mapped_column(Numeric(3, 2))
    is_retake: Mapped[bool] = mapped_column(default=False)
    # 수강편람(courses)과 과목명으로 매칭했는지 여부: matched/ambiguous/unmatched
    match_status: Mapped[str] = mapped_column(String(20), default="unmatched")
    source: Mapped[str] = mapped_column(String(20), default="crawler")


class GraduationRequirement(TimestampMixin, Base):
    """학과(또는 세부전공)×이수유형×교육과정연도별 졸업요건 기준학점(flat).

    별표2(교육과정 편성표) 원문을 그대로 옮긴 기준학점 테이블이다. 카테고리별
    세부 규칙(택N/M, 개별 필수과목 등)은 담지 않고, 이수구분별 기준학점만 있어
    student_course_records.category 합계와 단순 대조하는 용도로 쓴다.
    """

    __tablename__ = "graduation_requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    major_id: Mapped[int | None] = mapped_column(ForeignKey("majors.id"), nullable=True, index=True)
    program_type: Mapped[str | None] = mapped_column(String(20))
    curriculum_year: Mapped[str | None] = mapped_column(String(10))
    required_total_credits: Mapped[int | None] = mapped_column(Integer)
    required_major_foundation: Mapped[int | None] = mapped_column(Integer)
    required_major_required: Mapped[int | None] = mapped_column(Integer)
    required_major_elective: Mapped[int | None] = mapped_column(Integer)
    required_general_required: Mapped[int | None] = mapped_column(Integer)
    required_general_elective: Mapped[int | None] = mapped_column(Integer)
    required_free_elective: Mapped[int | None] = mapped_column(Integer)
    # 프로그램별 특수 규칙(택N/M, exclude_categories 등). flat 학점 컬럼으로 담을 수 없는
    # 규칙만 여기 담는다. 상세 구조는 마이그레이션 d2913a8e3330 참고.
    # SQLite(골든테스트)에서는 JSON, Postgres에서는 JSONB로 자동 dispatch.
    special_rules: Mapped[dict | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=True)


class ProgramCourse(TimestampMixin, Base):
    """다중전공 프로그램(SW융합트랙·연계전공·융합전공)의 인정 과목.

    `courses`는 department_id/major_id를 하나씩만 가져서 "정보컴퓨터공학부 과목이면서
    동시에 경영학과 SW융합트랙 인정 과목"을 표현할 수 없다. 프로그램은 자기 학과
    과목과 타 학과 개설 과목(SW융합 공통교과목 등)을 함께 인정하므로 다대다가 필요하다.

    프로그램 식별은 (department_id, major_id)다 — majors 행으로 만든 트랙/연계전공은
    major_id가 차고, 핀테크융합전공처럼 학과 자체가 프로그램인 경우는 major_id가 null이다.

    `requirement_group`은 이수 기준의 축을 담는다. SW융합트랙은 "학과전공과목 12~15학점
    + SW융합 공통교과목 6~9학점"처럼 flat graduation_requirements의 이수구분 컬럼
    (전공필수/전공선택/교양…)과 다른 축으로 쪼개져 있어 그쪽에 담을 수 없다.
    """

    __tablename__ = "program_courses"
    __table_args__ = (
        UniqueConstraint(
            "department_id", "major_id", "course_id", "curriculum_year",
            name="uq_program_course",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    # 학과 자체가 프로그램 단위인 경우(핀테크융합전공)는 null.
    major_id: Mapped[int | None] = mapped_column(ForeignKey("majors.id"), nullable=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    # "학과전공과목" | "SW융합공통교과목" 등 이수 기준상의 묶음.
    requirement_group: Mapped[str | None] = mapped_column(String(50))
    # 프로그램 안에서의 이수구분(전선/일선 등). 원 학과에서의 category와 다를 수 있다.
    category: Mapped[str | None] = mapped_column(String(50))
    curriculum_year: Mapped[str | None] = mapped_column(String(10))
