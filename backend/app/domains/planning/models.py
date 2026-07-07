from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class CoursePlan(TimestampMixin, Base):
    """특정 학기 수강계획."""

    __tablename__ = "course_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    year: Mapped[str | None] = mapped_column(String(10))
    semester: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    total_credits: Mapped[float | None] = mapped_column()


class CoursePlanItem(TimestampMixin, Base):
    """수강계획에 담긴 개별 강좌."""

    __tablename__ = "course_plan_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("course_plans.id"), index=True)
    offering_id: Mapped[int | None] = mapped_column(ForeignKey("course_offerings.id"), nullable=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="manual")


class CourseRoadmap(TimestampMixin, Base):
    """1~4학년 장기 성장 로드맵."""

    __tablename__ = "course_roadmaps"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    start_year: Mapped[str | None] = mapped_column(String(10))
    target_graduation_year: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="draft")


class CourseRoadmapItem(TimestampMixin, Base):
    """로드맵에 배치된 개별 과목/계획 항목."""

    __tablename__ = "course_roadmap_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    roadmap_id: Mapped[int] = mapped_column(ForeignKey("course_roadmaps.id"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    planned_grade: Mapped[int | None] = mapped_column()
    planned_year: Mapped[str | None] = mapped_column(String(10))
    planned_semester: Mapped[str | None] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="manual")
