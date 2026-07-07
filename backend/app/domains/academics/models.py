from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class UserAcademicProgram(TimestampMixin, Base):
    """사용자의 학적 프로그램(주전공/복수전공/부전공/연계전공 등)."""

    __tablename__ = "user_academic_programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    school: Mapped[str | None] = mapped_column(String(100))
    college: Mapped[str | None] = mapped_column(String(200))
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
    """학과/전공/교육과정연도별 졸업요건 기준.

    실제 충족 여부는 이 기준과 StudentCourseRecord를 대조해 그때그때
    계산한다(별도 스냅샷 테이블을 두지 않는다).
    """

    __tablename__ = "graduation_requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    school: Mapped[str | None] = mapped_column(String(100))
    department: Mapped[str | None] = mapped_column(String(200))
    major: Mapped[str | None] = mapped_column(String(200))
    program_type: Mapped[str | None] = mapped_column(String(20))
    curriculum_year: Mapped[str | None] = mapped_column(String(10))
    required_total_credits: Mapped[int | None] = mapped_column()
    required_major_required: Mapped[int | None] = mapped_column()
    required_major_elective: Mapped[int | None] = mapped_column()
    required_general_required: Mapped[int | None] = mapped_column()
    required_general_elective: Mapped[int | None] = mapped_column()
    required_free_elective: Mapped[int | None] = mapped_column()
