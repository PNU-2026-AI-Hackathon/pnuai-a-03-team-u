from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
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
    __table_args__ = (
        UniqueConstraint("college_id", "name", name="uq_department_college_name"),
        Index(
            "uq_departments_academic_program_code",
            "academic_program_code",
            unique=True,
            postgresql_where=text("academic_program_code IS NOT NULL"),
            sqlite_where=text("academic_program_code IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    # 계층(회원가입/조회) ↔ 졸업요건(academic_programs) 브리지. 학부제 학과처럼
    # 코드가 세부 전공(majors) 쪽에만 있는 경우 여기는 null.
    academic_program_code: Mapped[str | None] = mapped_column(
        ForeignKey("academic_programs.academic_program_code"), nullable=True
    )


class Major(TimestampMixin, Base):
    """세부 전공(학부제일 때만 존재, 예: "데이터사이언스전공").

    "OO과"처럼 학과 자체가 곧 전공 단위라 세부 전공 구분이 없는 경우는
    이 테이블에 행을 만들지 않고, 참조하는 쪽(major_id)을 null로 둔다.
    """

    __tablename__ = "majors"
    __table_args__ = (
        UniqueConstraint("department_id", "name", name="uq_major_department_name"),
        Index(
            "uq_majors_academic_program_code",
            "academic_program_code",
            unique=True,
            postgresql_where=text("academic_program_code IS NOT NULL"),
            sqlite_where=text("academic_program_code IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    academic_program_code: Mapped[str | None] = mapped_column(
        ForeignKey("academic_programs.academic_program_code"), nullable=True
    )


class AcademicProgram(Base):
    """졸업요건 기준 학사 프로그램 마스터(AIS 편제 코드 기준).

    schools~majors 계층은 회원가입/조회용 이름 계층이고, 이 테이블은 학과코드
    (academic_program_code)가 필요한 졸업요건/교육과정 연결 기준이다. 두 축은
    departments.academic_program_code / majors.academic_program_code로 잇는다.
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
    # display_name("{college_name} {program_name}")은 저장하지 않고 필요 시 조합한다.
    # normalized_program_name은 이름 매칭 인덱스 조회용 계산 컬럼이라 유지.
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


class UserAcademicProgram(TimestampMixin, Base):
    """사용자의 학적 프로그램(주전공/복수전공/부전공/연계전공 등)."""

    __tablename__ = "user_academic_programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    major_id: Mapped[int | None] = mapped_column(ForeignKey("majors.id"), nullable=True, index=True)
    # 졸업요건 세트 룩업용. department/major의 브리지 컬럼에서 resolve해 채운다
    # (portal-sync/가입 시점 — 엔진 어댑테이션은 후속 작업).
    academic_program_code: Mapped[str | None] = mapped_column(
        ForeignKey("academic_programs.academic_program_code"), nullable=True, index=True
    )
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


class RequirementSet(TimestampMixin, Base):
    """프로그램(학과/전공)×이수유형×교육과정연도별 졸업요건 세트.

    이 모델은 규칙 저장용이며, 실제 충족 여부 계산은 규칙 기반 판정 엔진
    (graduation_engine)이 담당한다.

    - 부전공/복수전공/연계전공 요건은 별도 테이블이 아니라 program_type="minor"/
      "dual"/"interdisciplinary" 행으로 표현한다. 교직은 program_type이 아니라
      primary 세트의 teacher_training_* 카테고리로 표현한다.
    - scope="university_default" + academic_program_code IS NULL 행은 학사운영규정의
      대학 공통 기본규칙(예: 부전공 21학점/필수 9학점 포함)이다. 프로그램별 행이
      없을 때 폴백으로 쓴다.
    - 규정상 부전공/복수전공을 제공하지 않는 학과는 offering_status="not_offered"
      행으로 명시한다(offering_note에 근거 규정).
    """

    __tablename__ = "requirement_sets"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'program') = (academic_program_code IS NOT NULL)",
            name="ck_requirement_sets_scope_code",
        ),
        UniqueConstraint(
            "academic_program_code",
            "program_type",
            "curriculum_year",
            name="uq_requirement_sets_program_type_year",
        ),
        # NULL academic_program_code는 위 UNIQUE 제약을 타지 않으므로,
        # university_default 행의 중복은 부분 인덱스로 막는다.
        Index(
            "uq_requirement_sets_default",
            "program_type",
            "curriculum_year",
            unique=True,
            postgresql_where=text("academic_program_code IS NULL"),
            sqlite_where=text("academic_program_code IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(20), default="program", server_default="program")
    academic_program_code: Mapped[str | None] = mapped_column(
        ForeignKey("academic_programs.academic_program_code"), nullable=True, index=True
    )
    # 계층 FK — seed가 브리지 컬럼 매칭으로 채우며, 엔진의 타학과 과목 필터가
    # courses.department_id와 비교한다. 학과 단위 조회는 major_id IS NULL 필터 필수.
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id"), nullable=True, index=True
    )
    major_id: Mapped[int | None] = mapped_column(ForeignKey("majors.id"), nullable=True, index=True)
    program_type: Mapped[str] = mapped_column(String(20), index=True)
    curriculum_year: Mapped[str] = mapped_column(String(10))
    offering_status: Mapped[str] = mapped_column(
        String(20), default="offered", server_default="offered"
    )
    offering_note: Mapped[str | None] = mapped_column(Text)
    required_total_credits: Mapped[int | None] = mapped_column()
    rule_metadata: Mapped[dict | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class RequirementCategory(TimestampMixin, Base):
    """졸업요건 세트의 카테고리별 학점/규칙 후보.

    교직과정은 category_code="teacher_training_basic"(△ 기본이수과목,
    rule_type="required_courses") / "teacher_training_pedagogy"(□ 교과교육영역,
    rule_type="minimum_credits", 8학점)로 표현한다. 적성·인성검사처럼 성적표로
    확인할 수 없는 요건은 rule_type="manual_check" 행으로 남겨 판정 불가로 노출한다.
    """

    __tablename__ = "requirement_categories"
    __table_args__ = (
        UniqueConstraint("external_id", name="uq_requirement_categories_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    # 프로그램 식별(코드/이름/타입)은 requirement_set_id → requirement_sets에서 가져온다.
    requirement_set_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_sets.id", ondelete="CASCADE"), index=True
    )
    category_code: Mapped[str] = mapped_column(String(80), index=True)
    category_name: Mapped[str | None] = mapped_column(String(120))
    minimum_credits: Mapped[str | None] = mapped_column(String(50))
    rule_type: Mapped[str | None] = mapped_column(String(80))
    source_kind: Mapped[str | None] = mapped_column(String(80))
    source_file: Mapped[str | None] = mapped_column(String(1000))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    review_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class RequirementCourse(TimestampMixin, Base):
    """졸업요건 세트에 연결된 과목 후보."""

    __tablename__ = "requirement_courses"
    __table_args__ = (
        UniqueConstraint("external_id", name="uq_requirement_courses_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    # 프로그램 식별(코드/이름/단과대/타입)은 requirement_set_id → requirement_sets에서 가져온다.
    requirement_set_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_sets.id", ondelete="CASCADE"), index=True
    )
    # curriculum_year: 세트의 적용연도와 다를 수 있는 원본 값(입학년도별 적용 등)이라 유지.
    curriculum_year: Mapped[str | None] = mapped_column(String(10), index=True)
    category_code: Mapped[str | None] = mapped_column(String(80), index=True)
    recommended_year: Mapped[str | None] = mapped_column(String(20))
    recommended_semester: Mapped[str | None] = mapped_column(String(20))
    raw_course_code: Mapped[str | None] = mapped_column(Text)
    raw_course_name: Mapped[str | None] = mapped_column(String(255))
    raw_credit: Mapped[str | None] = mapped_column(String(50))
    matched_course_code: Mapped[str | None] = mapped_column(Text, index=True)
    matched_course_name: Mapped[str | None] = mapped_column(String(255))
    match_status: Mapped[str | None] = mapped_column(String(50), index=True)
    match_method: Mapped[str | None] = mapped_column(String(100))
    matched_terms: Mapped[str | None] = mapped_column(Text)
    matched_departments: Mapped[str | None] = mapped_column(Text)
    choice_rule_types: Mapped[str | None] = mapped_column(String(200))
    choice_rule_raw: Mapped[str | None] = mapped_column(Text)
    source_table: Mapped[str | None] = mapped_column(String(100))
    source_file: Mapped[str | None] = mapped_column(String(1000))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    review_reason: Mapped[str | None] = mapped_column(Text)


class RequirementConditionGroup(TimestampMixin, Base):
    """택N/M형 이수 조건 그룹(예: "부전공필수 9과목 중 3과목 선택").

    부전공 교육과정표의 택N/M 규칙에서 출발했지만 전 program_type에 공통으로 쓴다.
    후보 과목 목록은 requirement_condition_group_courses에 담는다.
    """

    __tablename__ = "requirement_condition_groups"
    __table_args__ = (
        UniqueConstraint("external_id", name="uq_requirement_condition_groups_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    requirement_set_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_sets.id", ondelete="CASCADE"), index=True
    )
    category_code: Mapped[str | None] = mapped_column(String(80), index=True)
    condition_type: Mapped[str] = mapped_column(String(50))  # 예: choose_at_least_n_courses
    group_name: Mapped[str | None] = mapped_column(String(255))
    rule_summary: Mapped[str | None] = mapped_column(Text)
    min_courses: Mapped[int | None] = mapped_column(Integer)
    min_credits: Mapped[float | None] = mapped_column(Numeric(4, 1))
    max_courses: Mapped[int | None] = mapped_column(Integer)
    max_credits: Mapped[float | None] = mapped_column(Numeric(4, 1))
    excess_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text)
    source_file: Mapped[str | None] = mapped_column(String(1000))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    review_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class RequirementConditionGroupCourse(TimestampMixin, Base):
    """조건 그룹의 후보/필수/제외 과목.

    원본 CSV에 행 단위 external_id가 없어 행 unique 제약을 두지 않는다 —
    시드는 그룹 단위 delete-and-reinsert로 멱등성을 확보한다.
    """

    __tablename__ = "requirement_condition_group_courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    condition_group_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_condition_groups.id", ondelete="CASCADE"), index=True
    )
    course_role: Mapped[str] = mapped_column(
        String(30), default="candidate", server_default="candidate"
    )  # candidate | required | excluded
    raw_course_name: Mapped[str | None] = mapped_column(String(255))
    course_code: Mapped[str | None] = mapped_column(Text)  # 파이프 구분 대안 코드 보존
    course_name: Mapped[str | None] = mapped_column(String(255))
    credits: Mapped[float | None] = mapped_column(Numeric(4, 1))
    category_code: Mapped[str | None] = mapped_column(String(80))
    match_status: Mapped[str | None] = mapped_column(String(50))
    recognition_status: Mapped[str | None] = mapped_column(String(50))
    source_note: Mapped[str | None] = mapped_column(Text)
