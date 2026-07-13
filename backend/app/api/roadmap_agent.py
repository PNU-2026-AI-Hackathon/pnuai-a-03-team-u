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
from app.domains.planning.models import CourseRoadmap, PendingRoadmapChange
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
    planned_year: str | None
    planned_semester: str | None
    planned_grade: int | None
    before_snapshot: dict | None
    reason: str | None

    @classmethod
    def from_model(cls, change: PendingRoadmapChange) -> "PendingChangeResponse":
        return cls(
            change_id=change.id,
            action=change.action,
            item_id=change.item_id,
            course_id=change.course_id,
            planned_year=change.planned_year,
            planned_semester=change.planned_semester,
            planned_grade=change.planned_grade,
            before_snapshot=change.before_snapshot,
            reason=change.reason,
        )


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
    return ChatResponse(
        reply=result["reply"],
        pending_changes=[PendingChangeResponse.from_model(c) for c in result["pending_changes"]],
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
