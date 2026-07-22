"""로드맵 AI 상담 API. 채팅으로 로드맵 변경을 "제안"받고, 사용자가 승인한 것만 반영한다.

human-in-the-loop: POST .../chat는 pending_roadmap_changes에 제안만 쌓고 절대
course_roadmap_items를 건드리지 않는다. 실제 반영은 POST .../confirm에서
사용자가 승인한 id만 골라 반영한다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.courses.models import Course
from app.domains.planning.models import (
    CourseRoadmap,
    CourseRoadmapChatMessage,
    CourseRoadmapItem,
    PendingRoadmapChange,
)
from app.domains.planning.roadmap_chat import apply_pending_changes, run_roadmap_chat
from app.domains.users.models import User

router = APIRouter(prefix="/me/roadmaps/{roadmap_id}/agent", tags=["roadmap-agent"])


def _get_owned_roadmap(db: Session, user_id: int, roadmap_id: int) -> CourseRoadmap:
    roadmap = db.get(CourseRoadmap, roadmap_id)
    if roadmap is None or roadmap.user_id != user_id:
        raise HTTPException(status_code=404, detail="로드맵을 찾을 수 없습니다")
    return roadmap


class ChatRequest(BaseModel):
    message: str


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
    def from_model(cls, change: PendingRoadmapChange, course_name: str | None) -> "PendingChangeResponse":
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
    pending_changes: list[PendingChangeResponse]


@router.post("/chat", response_model=ChatResponse)
def chat_with_roadmap_agent(
    roadmap_id: int,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI와 대화하며 로드맵 변경안을 받는다. 이 호출만으로는 아무것도 저장되지 않는다 —
    반환된 pending_changes를 /confirm으로 승인해야 실제 반영된다."""
    roadmap = _get_owned_roadmap(db, current_user.id, roadmap_id)
    result = run_roadmap_chat(db, current_user, roadmap, payload.message)
    name_map = _resolve_change_course_names(db, result["pending_changes"])
    return ChatResponse(
        reply=result["reply"],
        pending_changes=[
            PendingChangeResponse.from_model(c, name_map.get(c.id))
            for c in result["pending_changes"]
        ],
    )


class ConfirmRequest(BaseModel):
    approved: list[int] = []
    rejected: list[int] = []


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
    deleted_pending: int


@router.post("/reset", response_model=ResetResponse)
def reset_roadmap_agent_session(
    roadmap_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """이 로드맵의 상담 대화 기록과 아직 반영 안 된 pending change를 모두 지운다.
    프론트 '화면 대화 초기화' 버튼이 이 엔드포인트를 부른다. 이전에는 프론트에서만
    상태를 리셋하고 DB 히스토리가 남아있어, 다음 채팅 시작 시 백엔드가 여전히 과거
    대화를 다 로드해 LLM에 넘기던 문제가 있었다.
    """
    roadmap = _get_owned_roadmap(db, current_user.id, roadmap_id)
    deleted_messages = (
        db.query(CourseRoadmapChatMessage)
        .filter(CourseRoadmapChatMessage.roadmap_id == roadmap.id)
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
    return ResetResponse(deleted_messages=deleted_messages, deleted_pending=deleted_pending)
