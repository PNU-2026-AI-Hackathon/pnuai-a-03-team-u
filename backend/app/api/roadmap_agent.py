"""로드맵 AI 상담 API. 채팅으로 로드맵 변경을 "제안"받고, 사용자가 승인한 것만 반영한다.

human-in-the-loop: POST .../chat는 pending_roadmap_changes에 제안만 쌓고 절대
course_roadmap_items를 건드리지 않는다. 실제 반영은 POST .../confirm에서
사용자가 승인한 id만 골라 반영한다.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.core.ratelimit import CHAT_LIMITS, limiter
from app.domains.courses.models import Course
from app.domains.planning.models import (
    CourseRoadmap,
    CourseRoadmapChatMessage,
    CourseRoadmapChatSession,
    CourseRoadmapItem,
    PendingRoadmapChange,
)
from app.domains.planning.roadmap_chat import (
    apply_pending_changes,
    create_chat_session,
    delete_chat_session,
    list_chat_sessions,
    run_roadmap_chat,
)
from app.domains.users.models import User

router = APIRouter(prefix="/me/roadmaps/{roadmap_id}/agent", tags=["roadmap-agent"])


def _get_owned_roadmap(db: Session, user_id: int, roadmap_id: int) -> CourseRoadmap:
    roadmap = db.get(CourseRoadmap, roadmap_id)
    if roadmap is None or roadmap.user_id != user_id:
        raise HTTPException(status_code=404, detail="로드맵을 찾을 수 없습니다")
    return roadmap


class ChatRequest(BaseModel):
    message: str
    session_id: int | None = None


class SuggestedActionResponse(BaseModel):
    label: str
    prompt: str


class PendingChangeResponse(BaseModel):
    change_id: int
    action: str
    item_id: int | None
    course_id: int | None
    course_name: str | None
    planned_year: str | None
    planned_semester: str | None
    planned_grade: int | None
    before_snapshot: dict | None
    reason: str | None

    @classmethod
    def from_model(
        cls,
        change: PendingRoadmapChange,
        course_name: str | None = None,
    ) -> "PendingChangeResponse":
        return cls(
            change_id=change.id,
            action=change.action,
            item_id=change.item_id,
            course_id=change.course_id,
            course_name=course_name,
            planned_year=change.planned_year,
            planned_semester=change.planned_semester,
            planned_grade=change.planned_grade,
            before_snapshot=change.before_snapshot,
            reason=change.reason,
        )


def _resolve_change_course_names(
    db: Session, changes: list[PendingRoadmapChange]
) -> dict[int, str | None]:
    """각 pending change가 어떤 과목에 대한 것인지 사용자에게 보여주기 위해 이름을 찾는다.
    - create/update with course_id: Course.course_name
    - update/delete (course_id 없음): before_snapshot["course_name"] → 기존 item.course_name 폴백
    """
    course_ids = {c.course_id for c in changes if c.course_id is not None}
    course_names: dict[int, str] = {}
    if course_ids:
        rows = db.execute(
            Course.__table__.select().where(Course.id.in_(course_ids))
        ).mappings().all()
        course_names = {r["id"]: r["course_name"] for r in rows}
    item_ids = {c.item_id for c in changes if c.item_id is not None and c.course_id is None}
    item_names: dict[int, str] = {}
    if item_ids:
        rows = db.execute(
            CourseRoadmapItem.__table__.select().where(CourseRoadmapItem.id.in_(item_ids))
        ).mappings().all()
        item_names = {r["id"]: r["course_name"] for r in rows}
    resolved: dict[int, str | None] = {}
    for c in changes:
        if c.course_id is not None:
            resolved[c.id] = course_names.get(c.course_id)
        elif c.before_snapshot and c.before_snapshot.get("course_name"):
            resolved[c.id] = c.before_snapshot["course_name"]
        elif c.item_id is not None:
            resolved[c.id] = item_names.get(c.item_id)
        else:
            resolved[c.id] = None
    return resolved


class ChatResponse(BaseModel):
    reply: str
    session_id: int
    pending_changes: list[PendingChangeResponse]
    suggested_actions: list[SuggestedActionResponse]


class ChatMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    messages: list[ChatMessageResponse]
    pending_changes: list[PendingChangeResponse]
    suggested_actions: list[SuggestedActionResponse]


def _suggested_actions(messages: list[CourseRoadmapChatMessage]) -> list[SuggestedActionResponse]:
    latest_user_message = next(
        (message.content for message in reversed(messages) if message.role == "user"),
        "",
    )
    if any(keyword in latest_user_message for keyword in ("필수", "전공필수")):
        actions = [
            ("필수 과목 학기 배치", "남은 필수 과목을 학기별로 배치해줘."),
            ("선수 과목 점검", "필수 과목의 선수 관계와 이수 순서를 점검해줘."),
            ("학점 부담 조정", "필수 과목을 유지하면서 학기별 학점 부담을 조정해줘."),
        ]
    elif any(keyword in latest_user_message for keyword in ("학점", "부담", "가볍")):
        actions = [
            ("가장 무거운 학기", "현재 계획에서 학점 부담이 가장 큰 학기를 찾아줘."),
            ("과목 재배치", "학기별 학점이 비슷해지도록 과목을 재배치해줘."),
            ("남은 요건 확인", "재배치 후에도 부족한 졸업요건이 있는지 확인해줘."),
        ]
    elif any(keyword in latest_user_message for keyword in ("추천", "진로", "취업")):
        actions = [
            ("추천 과목 배치", "방금 추천한 과목을 적절한 학기에 배치해줘."),
            ("진로 연관성 확인", "현재 로드맵이 제 진로 목표와 어떻게 연결되는지 설명해줘."),
            ("필수 요건 점검", "추천 과목을 반영해도 필수 요건을 충족하는지 확인해줘."),
        ]
    else:
        actions = [
            ("남은 요건 확인", "현재 계획에서 아직 부족한 졸업요건을 정리해줘."),
            ("필수 과목 점검", "남은 전공 필수 과목을 우선해서 점검해줘."),
            ("학점 부담 조정", "학기별 예정 학점을 균형 있게 조정해줘."),
        ]
    return [SuggestedActionResponse(label=label, prompt=prompt) for label, prompt in actions]


def _load_conversation(
    db: Session, roadmap_id: int, session_id: int | None = None
) -> ConversationResponse:
    """로드맵의 대화 기록을 읽는다.

    session_id를 주면 그 스레드의 메시지만 돌려준다. 주지 않으면 로드맵의 모든
    메시지를 섞어서 돌려주는데, 이건 세션 도입 이전 호출부와의 호환을 위한
    동작이라 세션 UI가 있는 화면은 반드시 session_id를 넘겨야 한다.

    pending_changes는 세션이 아닌 로드맵 전역이라 session_id와 무관하게 같다.
    """
    conditions = [CourseRoadmapChatMessage.roadmap_id == roadmap_id]
    if session_id is not None:
        conditions.append(CourseRoadmapChatMessage.session_id == session_id)
    messages = db.scalars(
        select(CourseRoadmapChatMessage)
        .where(*conditions)
        .order_by(CourseRoadmapChatMessage.id)
    ).all()
    pending_changes = db.scalars(
        select(PendingRoadmapChange)
        .where(
            PendingRoadmapChange.roadmap_id == roadmap_id,
            PendingRoadmapChange.status == "pending",
        )
        .order_by(PendingRoadmapChange.id)
    ).all()
    name_map = _resolve_change_course_names(db, pending_changes)
    return ConversationResponse(
        messages=[ChatMessageResponse.model_validate(message) for message in messages],
        pending_changes=[
            PendingChangeResponse.from_model(change, name_map.get(change.id))
            for change in pending_changes
        ],
        suggested_actions=_suggested_actions(messages),
    )


def _assert_session_belongs(db: Session, roadmap_id: int, session_id: int) -> None:
    session = db.get(CourseRoadmapChatSession, session_id)
    if session is None or session.roadmap_id != roadmap_id:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")


@router.get("/messages", response_model=ConversationResponse)
def get_roadmap_messages(
    roadmap_id: int,
    session_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_roadmap(db, current_user.id, roadmap_id)
    if session_id is not None:
        _assert_session_belongs(db, roadmap_id, session_id)
    return _load_conversation(db, roadmap_id, session_id)


@router.delete("/messages", status_code=204)
def delete_roadmap_messages(
    roadmap_id: int,
    session_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """대화를 지운다. session_id를 주면 그 스레드만, 없으면 로드맵 전체를 지운다.

    pending_changes는 로드맵 전역이라 특정 세션만 지울 때는 남겨둔다 — 다른
    세션에서 받은 제안까지 같이 날아가면 안 된다.
    """
    _get_owned_roadmap(db, current_user.id, roadmap_id)
    if session_id is not None:
        _assert_session_belongs(db, roadmap_id, session_id)
        db.execute(
            delete(CourseRoadmapChatMessage).where(
                CourseRoadmapChatMessage.roadmap_id == roadmap_id,
                CourseRoadmapChatMessage.session_id == session_id,
            )
        )
        db.commit()
        return
    db.execute(
        delete(PendingRoadmapChange).where(PendingRoadmapChange.roadmap_id == roadmap_id)
    )
    db.execute(
        delete(CourseRoadmapChatMessage).where(
            CourseRoadmapChatMessage.roadmap_id == roadmap_id
        )
    )
    db.commit()


@router.post("/chat", response_model=ChatResponse)
@limiter.limit(CHAT_LIMITS)
def chat_with_roadmap_agent(
    request: Request,
    roadmap_id: int,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI와 대화하며 로드맵 변경안을 받는다. 이 호출만으로는 아무것도 저장되지 않는다 —
    반환된 pending_changes를 /confirm으로 승인해야 실제 반영된다.

    session_id를 지정하면 그 세션 컨텍스트로 이어 대화한다. 지정하지 않으면 이 로드맵의
    가장 최근 세션을 이어 쓰거나, 아예 세션이 없으면 이번 메시지로 새 세션을 만든다.
    """
    roadmap = _get_owned_roadmap(db, current_user.id, roadmap_id)
    try:
        result = run_roadmap_chat(
            db, current_user, roadmap, payload.message, session_id=payload.session_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    name_map = _resolve_change_course_names(db, result["pending_changes"])
    return ChatResponse(
        reply=result["reply"],
        session_id=result["session_id"],
        pending_changes=[
            PendingChangeResponse.from_model(c, name_map.get(c.id))
            for c in result["pending_changes"]
        ],
        # 추천 액션은 "직전 사용자 발화"를 보고 정하므로 이번 대화가 벌어진
        # 세션으로 좁혀야 한다. 로드맵 전체로 보면 다른 스레드의 마지막 발화가
        # 끼어들어 엉뚱한 버튼이 뜬다.
        suggested_actions=_load_conversation(
            db, roadmap_id, result["session_id"]
        ).suggested_actions,
    )


class SessionResponse(BaseModel):
    session_id: int
    title: str | None
    created_at: str
    updated_at: str
    message_count: int

    @classmethod
    def from_model(cls, session: CourseRoadmapChatSession, message_count: int) -> "SessionResponse":
        return cls(
            session_id=session.id,
            title=session.title,
            created_at=session.created_at.isoformat() if session.created_at else "",
            updated_at=session.updated_at.isoformat() if session.updated_at else "",
            message_count=message_count,
        )


class CreateSessionRequest(BaseModel):
    title: str | None = None


@router.post("/sessions", response_model=SessionResponse)
def create_session(
    roadmap_id: int,
    payload: CreateSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    roadmap = _get_owned_roadmap(db, current_user.id, roadmap_id)
    session = create_chat_session(db, roadmap, title=payload.title)
    return SessionResponse.from_model(session, message_count=0)


@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(
    roadmap_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    roadmap = _get_owned_roadmap(db, current_user.id, roadmap_id)
    sessions = list_chat_sessions(db, roadmap)
    if not sessions:
        return []
    # 각 세션의 메시지 수를 한 번의 쿼리로 계산
    from sqlalchemy import func

    counts = dict(
        db.execute(
            CourseRoadmapChatMessage.__table__.select()
            .with_only_columns(
                CourseRoadmapChatMessage.session_id,
                func.count(CourseRoadmapChatMessage.id),
            )
            .where(CourseRoadmapChatMessage.session_id.in_([s.id for s in sessions]))
            .group_by(CourseRoadmapChatMessage.session_id)
        ).all()
    )
    return [SessionResponse.from_model(s, counts.get(s.id, 0)) for s in sessions]


@router.delete("/sessions/{session_id}")
def delete_session(
    roadmap_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    roadmap = _get_owned_roadmap(db, current_user.id, roadmap_id)
    if not delete_chat_session(db, roadmap, session_id):
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")
    return {"deleted": session_id}


class ConfirmRequest(BaseModel):
    approved: list[int] = Field(default_factory=list)
    rejected: list[int] = Field(default_factory=list)


class ConfirmResponse(BaseModel):
    applied: list[int]
    rejected: list[int]


@router.post("/confirm", response_model=ConfirmResponse)
def confirm_pending_changes(
    roadmap_id: int,
    payload: ConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """승인된 pending change만 실제 course_roadmap_items에 반영한다."""
    roadmap = _get_owned_roadmap(db, current_user.id, roadmap_id)
    result = apply_pending_changes(db, roadmap, payload.approved, payload.rejected)
    return ConfirmResponse(**result)


class ResetResponse(BaseModel):
    deleted_messages: int
    deleted_sessions: int
    deleted_pending: int


@router.post("/reset", response_model=ResetResponse)
def reset_roadmap_agent_session(
    roadmap_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """이 로드맵의 모든 대화 세션·메시지·아직 반영 안 된 pending change를 지운다.

    세션 개념 도입 후에도 "전체 초기화" 진입점은 유지한다 — 개별 세션만 지우려면
    DELETE /sessions/{session_id}를 쓰면 된다. 이후 새 채팅 요청은 새 세션을 만든다.
    """
    roadmap = _get_owned_roadmap(db, current_user.id, roadmap_id)
    deleted_messages = (
        db.query(CourseRoadmapChatMessage)
        .filter(CourseRoadmapChatMessage.roadmap_id == roadmap.id)
        .delete(synchronize_session=False)
    )
    deleted_sessions = (
        db.query(CourseRoadmapChatSession)
        .filter(CourseRoadmapChatSession.roadmap_id == roadmap.id)
        .delete(synchronize_session=False)
    )
    deleted_pending = (
        db.query(PendingRoadmapChange)
        .filter(
            PendingRoadmapChange.roadmap_id == roadmap.id,
            PendingRoadmapChange.status == "pending",
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return ResetResponse(
        deleted_messages=deleted_messages,
        deleted_sessions=deleted_sessions,
        deleted_pending=deleted_pending,
    )
