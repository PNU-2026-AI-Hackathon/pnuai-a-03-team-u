from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class UserAcademicProgram(TimestampMixin, Base):
    """사용자의 학적 프로그램(주전공/복수전공/부전공/연계전공 등).

    크롤러의 학적부(student_info)에서 소속학과, 학위과정,
    교육과정적용년도를 매핑한다.
    """

    __tablename__ = "user_academic_programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    requirement_set_id: Mapped[int | None] = mapped_column(ForeignKey("requirement_sets.id"), nullable=True)

    school: Mapped[str | None] = mapped_column(String(100))
    department: Mapped[str | None] = mapped_column(String(200))
    major: Mapped[str | None] = mapped_column(String(200))
    program_type: Mapped[str] = mapped_column(String(20), default="primary")  # primary/dual/minor/interdisciplinary
    curriculum_year: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="active")  # active/completed/dropped


class StudentCourseRecord(TimestampMixin, Base):
    """학생이 이수한 과목 기록. 크롤러의 grades(전체 성적 조회)에서 매핑한다."""

    __tablename__ = "student_course_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)

    raw_course_code: Mapped[str | None] = mapped_column(String(50))
    raw_course_name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(50))  # 전공필수/전공선택/전공기초/교양 등
    credits: Mapped[float | None] = mapped_column(Numeric(4, 1))
    year: Mapped[str | None] = mapped_column(String(10))
    semester: Mapped[str | None] = mapped_column(String(20))  # 1학기/2학기/여름계절수업 등
    grade: Mapped[str | None] = mapped_column(String(10))  # A+, B0, S, F 등
    grade_point: Mapped[float | None] = mapped_column(Numeric(3, 2))
    is_retake: Mapped[bool] = mapped_column(default=False)
    match_status: Mapped[str] = mapped_column(String(20), default="unmatched")  # matched/unmatched/needs_review
    source: Mapped[str] = mapped_column(String(20), default="crawler")  # manual/csv/ocr/crawler
