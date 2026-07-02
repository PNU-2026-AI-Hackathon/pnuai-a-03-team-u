import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class Department(Base):
    """부산대 정식 학부/학과/전공 목록.

    onestop 수강편람(공개 API, 로그인 불필요)에서 크롤링해 시드한다
    (scripts/seed_departments.py). 회원가입 시 department/major 값을
    이 테이블에 있는지로 검증한다.
    """

    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)


class AcademicProgram(Base):
    """졸업요건 기준 학사 프로그램 마스터.

    departments는 회원가입 입력값 검증용 이름 목록이고, 이 테이블은 학과코드가
    필요한 졸업요건/교육과정 연결 기준이다.
    """

    __tablename__ = "academic_programs"

    academic_program_code: Mapped[str] = mapped_column(String(50), primary_key=True)
    survey_year: Mapped[int | None] = mapped_column(Integer)
    survey_round: Mapped[int | None] = mapped_column(Integer)
    school_code: Mapped[str | None] = mapped_column(String(20))
    school_name: Mapped[str | None] = mapped_column(String(100))
    campus_code: Mapped[str | None] = mapped_column(String(20))
    campus_name: Mapped[str | None] = mapped_column(String(100))
    college_code: Mapped[str | None] = mapped_column(String(20))
    college_name: Mapped[str | None] = mapped_column(String(100), index=True)
    program_name: Mapped[str] = mapped_column(String(200), index=True)
    display_name: Mapped[str | None] = mapped_column(String(300))
    normalized_program_name: Mapped[str | None] = mapped_column(String(300), index=True)
    parent_department_name: Mapped[str | None] = mapped_column(String(200))
    major_name: Mapped[str | None] = mapped_column(String(200))
    day_night_code: Mapped[str | None] = mapped_column(String(20))
    day_night_name: Mapped[str | None] = mapped_column(String(50))
    program_feature_code: Mapped[str | None] = mapped_column(String(20))
    program_feature_name: Mapped[str | None] = mapped_column(String(100))
    duration_code: Mapped[str | None] = mapped_column(String(20))
    duration_name: Mapped[str | None] = mapped_column(String(50))
    status_code: Mapped[str | None] = mapped_column(String(20))
    status_name: Mapped[str | None] = mapped_column(String(50))
    education_ministry_5_category: Mapped[str | None] = mapped_column(String(100))
    degree_level: Mapped[str | None] = mapped_column(String(50))
    quota_adjustment_type: Mapped[str | None] = mapped_column(String(100))
    first_admission_year: Mapped[str | None] = mapped_column(String(10))
    free_major_type_code: Mapped[str | None] = mapped_column(String(20))
    free_major_type_name: Mapped[str | None] = mapped_column(String(100))
    kedi_7_category: Mapped[str | None] = mapped_column(String(100))
    source_updated_at: Mapped[str | None] = mapped_column(String(50))
    source_file: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_bachelor: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class AcademicProgramAlias(Base):
    """학사 프로그램명 검색/매칭용 별칭."""

    __tablename__ = "academic_program_aliases"
    __table_args__ = (
        UniqueConstraint(
            "academic_program_code",
            "alias_type",
            "alias_name",
            name="uq_academic_program_alias",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    academic_program_code: Mapped[str] = mapped_column(
        ForeignKey("academic_programs.academic_program_code", ondelete="CASCADE"),
        index=True,
    )
    alias_type: Mapped[str] = mapped_column(String(50))
    alias_name: Mapped[str] = mapped_column(String(300), index=True)
    normalized_alias_name: Mapped[str] = mapped_column(String(300), index=True)
    source: Mapped[str | None] = mapped_column(String(100))


class DepartmentAcademicProgramMapping(Base):
    """회원가입용 departments와 졸업요건용 academic_programs의 연결."""

    __tablename__ = "department_academic_program_mappings"
    __table_args__ = (
        UniqueConstraint(
            "department_id",
            "academic_program_code",
            "relation_type",
            name="uq_department_academic_program_mapping",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), index=True
    )
    academic_program_code: Mapped[str] = mapped_column(
        ForeignKey("academic_programs.academic_program_code", ondelete="CASCADE"),
        index=True,
    )
    relation_type: Mapped[str] = mapped_column(String(50), default="alias")
    source: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[float | None] = mapped_column(Float)


class UserAcademicProgram(TimestampMixin, Base):
    """사용자의 학적 프로그램(주전공/복수전공/부전공/연계전공 등)."""

    __tablename__ = "user_academic_programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    requirement_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirement_sets.id"), nullable=True
    )
    academic_program_code: Mapped[str | None] = mapped_column(
        ForeignKey("academic_programs.academic_program_code"), nullable=True, index=True
    )

    school: Mapped[str | None] = mapped_column(String(100))
    department: Mapped[str | None] = mapped_column(String(200))
    major: Mapped[str | None] = mapped_column(String(200))
    program_type: Mapped[str] = mapped_column(String(20), default="primary")
    curriculum_year: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="active")


class StudentCourseRecord(TimestampMixin, Base):
    """학생이 이수한 과목 기록. 크롤러의 grades 결과에서 매핑한다."""

    __tablename__ = "student_course_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)

    raw_course_code: Mapped[str | None] = mapped_column(String(50))
    raw_course_name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(50))
    credits: Mapped[float | None] = mapped_column(Numeric(4, 1))
    year: Mapped[str | None] = mapped_column(String(10))
    semester: Mapped[str | None] = mapped_column(String(20))
    grade: Mapped[str | None] = mapped_column(String(10))
    grade_point: Mapped[float | None] = mapped_column(Numeric(3, 2))
    is_retake: Mapped[bool] = mapped_column(default=False)
    match_status: Mapped[str] = mapped_column(String(20), default="unmatched")
    source: Mapped[str] = mapped_column(String(20), default="crawler")


class RequirementSet(TimestampMixin, Base):
    """학과/전공/교육과정연도별 졸업요건 세트.

    이 모델은 규칙 저장용이며, 실제 충족 여부 계산은 deterministic
    graduation audit logic에서 담당한다.
    """

    __tablename__ = "requirement_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    school: Mapped[str | None] = mapped_column(String(100))
    # department/major: 원본 텍스트(표시용). department_id: departments FK, 검증/조인 기준.
    # 부전공/복수전공 요건은 별도 테이블이 아니라 이 테이블의 program_type="minor"/"dual" 행으로 표현한다.
    department: Mapped[str | None] = mapped_column(String(200))
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id"), nullable=True, index=True
    )
    academic_program_code: Mapped[str | None] = mapped_column(
        ForeignKey("academic_programs.academic_program_code"), nullable=True, index=True
    )
    major: Mapped[str | None] = mapped_column(String(200))
    program_type: Mapped[str | None] = mapped_column(String(20))
    curriculum_year: Mapped[str | None] = mapped_column(String(10))
    name: Mapped[str | None] = mapped_column(String(255))
    required_total_credits: Mapped[int | None] = mapped_column()
    rule_metadata: Mapped[dict | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class GraduationAudit(TimestampMixin, Base):
    """졸업요건 충족 여부 스냅샷."""

    __tablename__ = "graduation_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    audit_year: Mapped[str | None] = mapped_column(String(10))
    audit_semester: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="crawled")
    summary_json: Mapped[dict | None] = mapped_column(JSON)
    crawled_at: Mapped[datetime.datetime | None] = mapped_column(nullable=True)


class GraduationAuditProgramResult(TimestampMixin, Base):
    __tablename__ = "graduation_audit_program_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("graduation_audits.id"), index=True)
    user_academic_program_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_academic_programs.id"), nullable=True
    )
    requirement_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirement_sets.id"), nullable=True
    )
    result_json: Mapped[dict | None] = mapped_column(JSON)
