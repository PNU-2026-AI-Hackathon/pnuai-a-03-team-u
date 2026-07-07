import datetime

from sqlalchemy import ForeignKey, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class Course(TimestampMixin, Base):
    """과목 자체(강좌 개설과 무관한 과목 정의). 학년/학기는 처음 확인된 개설
    시점 기준 참고값이며, 실제 학기별 개설 정보는 CourseOffering이 담당한다.
    """

    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    school: Mapped[str | None] = mapped_column(String(100))
    course_code: Mapped[str | None] = mapped_column(String(50), index=True)
    course_name: Mapped[str] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(200))
    major: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(50))
    credits: Mapped[float | None] = mapped_column()
    year: Mapped[str | None] = mapped_column(String(10))
    semester: Mapped[str | None] = mapped_column(String(20))


class CourseOffering(TimestampMixin, Base):
    """특정 학기에 실제 개설된 강좌(수강편람)."""

    __tablename__ = "course_offerings"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    school: Mapped[str | None] = mapped_column(String(100))
    year: Mapped[str | None] = mapped_column(String(10))
    semester: Mapped[str | None] = mapped_column(String(20))
    section: Mapped[str | None] = mapped_column(String(20))
    professor: Mapped[str | None] = mapped_column(String(100))
    capacity: Mapped[int | None] = mapped_column()
    enrolled_count: Mapped[int | None] = mapped_column()


class CourseTime(TimestampMixin, Base):
    """강좌의 요일/시간/강의실."""

    __tablename__ = "course_times"

    id: Mapped[int] = mapped_column(primary_key=True)
    offering_id: Mapped[int] = mapped_column(ForeignKey("course_offerings.id"), index=True)
    day_of_week: Mapped[str | None] = mapped_column(String(10))
    start_time: Mapped[datetime.time | None] = mapped_column(Time)
    end_time: Mapped[datetime.time | None] = mapped_column(Time)
    classroom: Mapped[str | None] = mapped_column(String(100))
