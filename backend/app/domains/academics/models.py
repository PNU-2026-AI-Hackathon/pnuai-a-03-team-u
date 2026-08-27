import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    # One-Stop 동기화 학적과 사용자가 로드맵에서 임시로 저장한 이수 계획을 구분한다.
    # 실제 학적은 절대 화면의 "취소"로 변경하면 안 된다.
    source: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)


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
    # 균형/창의교양 세부영역(사상과역사·사회와문화 …). category(교양선택)는 졸업요건
    # 학점 집계용 상위 이수구분이고, 이 값은 세부영역이라 의미가 다르므로 별도 보존.
    # 매 portal-sync마다 다시 계산된다: 학생 지정(override) > One-Stop 학교판정 >
    # 수강편람 카탈로그(`courses.general_education_area`) 순.
    liberal_area: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # `liberal_area`가 어떤 근거로 채워졌는지: 'override' | 'onestop' | 'catalog' | None.
    liberal_area_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 학생이 "내 정보"에서 직접 고른 세부영역. sync가 덮어쓰지 않는다 — 자동 매칭이
    # 틀렸을 때 학생이 고쳐 둘 수 있게. None이면 자동 매칭에 맡긴다.
    liberal_area_override: Mapped[str | None] = mapped_column(String(50), nullable=True)
    credits: Mapped[float | None] = mapped_column(Numeric(4, 1))
    year: Mapped[str | None] = mapped_column(String(10))
    semester: Mapped[str | None] = mapped_column(String(20))
    grade: Mapped[str | None] = mapped_column(String(10))
    grade_point: Mapped[float | None] = mapped_column(Numeric(3, 2))
    is_retake: Mapped[bool] = mapped_column(default=False)
    # 수강편람(courses)과 과목명으로 매칭했는지 여부: matched/ambiguous/unmatched
    match_status: Mapped[str] = mapped_column(String(20), default="unmatched")
    source: Mapped[str] = mapped_column(String(20), default="crawler")

    # 편입생이 직접 등록한 대체 관계. 한 줄이 여러 PNU 과목/영역을 대체할 수 있어
    # 별도 테이블로 둔다 — 전적대 `교양선택 15학점` 한 줄은 균형·창의 여러 세부영역에
    # 걸쳐 인정받는 게 보통이고, 반대로 전적대 두 과목이 PNU 한 과목을 대체하기도 한다.
    # 지연 로딩이다(selectin 아님). 이수기록은 졸업요건·시간표·로드맵 등 거의 모든
    # 경로에서 통째로 읽는데, 그 대부분은 대체 관계를 보지 않는다 — 매번 조인을
    # 딸려 보내면 쓰지도 않는 쿼리가 붙는다. 목록 응답은 관계 대신 명시적 조인으로
    # 한 번에 모은다(`portal_sync._course_record_responses`).
    substitutions: Mapped[list["StudentCourseSubstitution"]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )


class StudentCourseSubstitution(TimestampMixin, Base):
    """전적대 이수기록 한 줄이 대체한 PNU 과목(또는 교양 세부영역) 하나.

    편입 학점 인정은 학칙에 표로 정해진 게 아니라 학과가 개별 학생에게 "이건 인정,
    저건 불인정"을 통보하는 방식이라, 데이터 어디에도 근거가 없다. 그래서 이름
    유사도로 추정하지 않는다 — `데이터구조`와 `자료구조`가 아무리 비슷해 보여도
    학교가 실제로 그렇게 인정했는지는 학생만 안다. 틀리게 추정하면 학생이 졸업
    요건을 잘못 믿게 되므로, **학생이 화면에서 직접 고른 값만** 여기 들어간다.

    한 이수기록에 여러 행이 붙는다(N:M). 전적대 `교양선택 15학점` 한 줄은 개별
    과목이 아니라 여러 **세부영역**을 채운 것으로 인정받고(`courses`의 `ZFz…`
    placeholder 행이 그 영역이다), 반대로 전적대 두 과목이 PNU 한 과목을 대체한
    경우도 각 이수기록이 같은 `course_id`를 가리키면 된다.

    학점은 건드리지 않는다. 전적대에서 인정받은 학점은 이수기록 행에 그대로 있고
    졸업요건 엔진은 category별 합계만 보므로, 대체를 등록해도 학점 계산은 그대로다.
    실제 효과는 추천에서 대체된 PNU 과목을 빼는 것이다
    (`app/domains/planning/timetable.py::_completed_course_norms`).
    """

    __tablename__ = "student_course_substitutions"
    __table_args__ = (
        # 같은 과목을 두 번 체크해도 한 행. 화면에서 전체 집합을 통째로 저장하므로
        # 중복이 들어올 일은 없지만, 재시도/동시요청에 대한 안전장치로 둔다.
        UniqueConstraint("record_id", "course_id", name="uq_student_course_substitution"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("student_course_records.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)

    record: Mapped["StudentCourseRecord"] = relationship(back_populates="substitutions")


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


class StudentGraduationCategory(TimestampMixin, Base):
    """One-Stop 졸업예정정보의 **학교 공식** 이수구분별 판정 스냅샷.

    `graduation_requirements`(학과별 기준학점 원문)와 혼동하면 안 된다. 그건 "학과 규정"
    이고 이건 **이 학생에 대한 학교의 판정 결과**다. 우리 엔진이 성적 합계로 추정하는
    `/me/graduation`과 달리 학교가 직접 계산한 값이라, 어긋나면 이쪽이 맞다.

    학교 원문(menuCD 000000000000089, 표 1 `subject_category_completion`) 예:

        학적신청구분  사정구분      기준학점  취득학점  이수여부  졸업불가사유
        주전공        전공필수      33        26        N         전공필수학점미달
        주전공        총이수학점    133       87        N         총이수학점 학점미달

    `category`에는 이수구분(전공필수/교양선택…)뿐 아니라 총이수학점·졸업기준평점평균·
    최소전공인정학점 같은 **집계 항목도 같은 표에 섞여 온다.** 원문 구조가 그러하므로
    분리하지 않고 그대로 담는다 — 가공하면 학교 판정과 대조가 안 된다.
    """

    __tablename__ = "student_graduation_categories"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "program_type", "category",
            name="uq_student_graduation_categories_scope",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # 학적신청구분 원문 (주전공/복수전공/부전공/연합전공).
    program_type: Mapped[str] = mapped_column(String(30))
    # 사정구분 원문 (전공필수/교양선택/총이수학점/졸업기준평점평균 …).
    category: Mapped[str] = mapped_column(String(50))
    required_credits: Mapped[float | None] = mapped_column(Numeric(6, 2))
    earned_credits: Mapped[float | None] = mapped_column(Numeric(6, 2))
    registered_credits: Mapped[float | None] = mapped_column(Numeric(6, 2))
    expected_credits: Mapped[float | None] = mapped_column(Numeric(6, 2))
    # 이수여부 Y/N을 그대로 두지 않고 bool로. 원문에 Y/N 외 값이 오면 None.
    satisfied: Mapped[bool | None] = mapped_column()
    # 졸업불가사유 원문 ("전공필수학점미달" 등). 없으면 빈 문자열이 아니라 None.
    failure_reason: Mapped[str | None] = mapped_column(String(200))
    synced_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))


class StudentGraduationRequirement(TimestampMixin, Base):
    """One-Stop 졸업예정정보의 **학교 공식** 졸업요건(자격) 판정 스냅샷.

    표준외국어능력시험·TOPCIT·졸업과제처럼 **학점이 아닌 요건**이다. 원래 이걸 못
    가져온다고 알고 있었는데(2026-08-16), 실은 크롤링은 되고 있었고 `portal_sync`가
    버리고 있었다.

    학교 원문(menuCD 000000000000089, 표 6 `graduation_requirement_completion`) 예:

        학적신청구분  졸업요건명           상세졸업요건명  합격구분  취득일자  이수여부
        주전공        표준외국어능력시험                                     N
        주전공        TOPCIT                                                 N
        주전공        졸업과제                                               N

    어학 **점수**의 주된 출처는 my.pusan(`user_language_scores`)이다. 다만 `note`가
    원문의 `학생이수정보_비고_예외사항_상세내역_점수` 컬럼에서 오므로 **점수가 실릴 수
    있는 자리**다. 이 테이블의 역할은 "학교가 그 요건을 충족으로 봤는가"이고, 점수
    조회는 `user_language_scores`를 쓰는 게 맞다.
    """

    __tablename__ = "student_graduation_requirements"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "program_type", "requirement_name", "detail_name",
            name="uq_student_graduation_requirements_scope",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    program_type: Mapped[str] = mapped_column(String(30))
    requirement_name: Mapped[str] = mapped_column(String(100))
    # 상세졸업요건명. 원문에서 비어 있는 경우가 많아 빈 문자열로 정규화한다 —
    # UNIQUE 키에 들어가는데 NULL이면 Postgres가 서로 다른 행으로 본다.
    detail_name: Mapped[str] = mapped_column(String(200), default="")
    pass_type: Mapped[str | None] = mapped_column(String(50))
    acquired_date: Mapped[str | None] = mapped_column(String(30))
    satisfied: Mapped[bool | None] = mapped_column()
    note: Mapped[str | None] = mapped_column(String(500))
    synced_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
