from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class CoursePlan(TimestampMixin, Base):
    """특정 학기 수강계획(시간표 문서).

    시간표 화면에서 "2026-2 시간표 A"처럼 이름 붙여 여러 개 만들고, 강좌를
    담았다 빼며 비교하다가 마음에 드는 것을 로드맵에 반영하는 단위다.
    스키마만 있고 아무도 안 쓰던 테이블을 시간표 CRUD가 살려 쓴다.
    """

    __tablename__ = "course_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    year: Mapped[str | None] = mapped_column(String(10))
    semester: Mapped[str | None] = mapped_column(String(20))
    # 사용자가 붙이는 이름. "시간표 A", "공강 몰빵안" 같은 것.
    title: Mapped[str | None] = mapped_column(String(100))
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
    # 어느 프로그램(주전공/부전공/복수전공/융합)용 항목인지. NULL=주전공/미지정.
    # 판정 로직이 program별로 필터할 때 사용.
    program_type: Mapped[str | None] = mapped_column(String(20), nullable=True)


class CourseRoadmapChatSession(TimestampMixin, Base):
    """같은 로드맵 안에서 독립된 대화 스레드를 구분하는 세션.

    사용자가 "새 대화 시작" 버튼을 누를 때마다 하나가 생기고, 각 세션은 자기
    스레드의 메시지만 컨텍스트로 삼는다. pending_roadmap_changes는 세션이 아닌
    로드맵 전역이라 어느 세션에서 제안받든 승인 대상은 하나의 로드맵이다.
    """

    __tablename__ = "course_roadmap_chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    roadmap_id: Mapped[int] = mapped_column(ForeignKey("course_roadmaps.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(255))


class CourseRoadmapChatMessage(TimestampMixin, Base):
    """로드맵 AI 상담 대화 기록.

    이제 (roadmap_id, session_id)로 스레드를 구분한다. 히스토리 복원은 session_id
    기준으로 좁혀서 하고, 세션이 다르면 서로의 대화가 컨텍스트에 섞이지 않는다.
    """

    __tablename__ = "course_roadmap_chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    roadmap_id: Mapped[int] = mapped_column(ForeignKey("course_roadmaps.id"), index=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("course_roadmap_chat_sessions.id"), index=True
    )
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
    # 어느 프로그램(주전공/부전공/복수전공/융합)용 제안인지. NULL=주전공/미지정.
    # confirm 시 CourseRoadmapItem.program_type으로 그대로 복사된다.
    program_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
