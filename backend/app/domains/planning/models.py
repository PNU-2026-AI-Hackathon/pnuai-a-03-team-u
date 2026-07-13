from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
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


class CourseRoadmapChatMessage(TimestampMixin, Base):
    """로드맵 AI 상담 대화 기록.

    로드맵당 하나의 연속된 대화로 취급한다(멀티 세션/스레드 없음). 매 요청마다
    클라이언트가 전체 히스토리를 다시 보내는 대신 서버가 이 테이블에서 복원해
    Anthropic Messages API에 넘긴다.
    """

    __tablename__ = "course_roadmap_chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    roadmap_id: Mapped[int] = mapped_column(ForeignKey("course_roadmaps.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)


class PendingRoadmapChange(TimestampMixin, Base):
    """Agent가 제안했지만 아직 사용자가 승인/거절하지 않은 로드맵 변경안.

    Agent는 course_roadmap_items를 직접 쓰지 않는다 — 항상 이 테이블에 제안을
    먼저 쌓고, 사용자가 confirm 엔드포인트로 승인한 항목만 실제 반영한다
    (human-in-the-loop). action="create"는 item_id가 null이고 course_id/
    planned_year 등 after_* 값으로 새 항목을 만든다. action="update"/"delete"는
    기존 item_id를 가리키며, before_snapshot에 변경 전 값을 남겨 사용자가 대화창에서
    "무엇이 바뀌는지" 확인할 수 있게 한다.
    """

    __tablename__ = "pending_roadmap_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    roadmap_id: Mapped[int] = mapped_column(ForeignKey("course_roadmaps.id"), index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("course_roadmap_items.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(20))  # create | update | delete
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    planned_grade: Mapped[int | None] = mapped_column()
    planned_year: Mapped[str | None] = mapped_column(String(10))
    planned_semester: Mapped[str | None] = mapped_column(String(20))
    before_snapshot: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    # pending: 답변 대기 / approved·rejected: 사용자가 confirm에서 선택한 결과
    status: Mapped[str] = mapped_column(String(20), default="pending")
