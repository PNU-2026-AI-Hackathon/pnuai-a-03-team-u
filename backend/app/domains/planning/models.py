from sqlalchemy import Boolean, ForeignKey, String, Text
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
    # 로드맵 전체에 대한 AI/사용자의 요약 설명 (예: "취업 준비 중심, 3학년부터 인턴 배치").
    summary: Mapped[str | None] = mapped_column(Text)


class CourseRoadmapItem(TimestampMixin, Base):
    """로드맵에 배치된 개별 과목/계획 항목."""

    __tablename__ = "course_roadmap_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    roadmap_id: Mapped[int] = mapped_column(ForeignKey("course_roadmaps.id"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    planned_grade: Mapped[int | None] = mapped_column()
    planned_year: Mapped[str | None] = mapped_column(String(10))
    planned_semester: Mapped[str | None] = mapped_column(String(20))
    # course_id가 null이거나 모호한 경우(동명 과목이 여러 학과에 개설된 경우가 흔해서
    # 실제로 자주 발생함)에도 항상 보여줘야 해서 스냅샷으로 저장한다.
    # course_name/category/credits는 "쓰는 시점"에 확정된 값(과거 이력은
    # StudentCourseRecord, 신규/수정은 선택한 course_id)을 그대로 복사한다 —
    # 매칭이 필요 없는 값들이라 join과 무관하게 항상 정확하다.
    # department_name/major_name만 course_id가 있을 때 courses(+departments+majors)
    # join으로 채운다 — 과거 이력은 성적표 원본에 학과 정보가 아예 없어서 스냅샷 불가.
    course_name: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(50))
    credits: Mapped[float | None] = mapped_column()
    # planned: 계획만 세운 상태 / completed: 실제로 이수함 / dropped: 계획에서 뺌
    status: Mapped[str] = mapped_column(String(20), default="planned")
    # source="ai"로 제안된 항목을 사용자가 실제로 받아들였는지. source만으로는
    # "AI가 제안했다"는 알 수 있어도 "사용자가 확정했다"는 구분이 안 돼서 별도로 둔다.
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="manual")
