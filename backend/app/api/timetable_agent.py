"""시간표 LLM 에이전트 엔드포인트 (스파이크).

기존 결정론적 `/me/roadmaps/{roadmap_id}/timetable/recommend`와 병존한다. 이 엔드포인트는
로드맵과 독립적으로 동작 — `roadmap_id` 불필요, 학생 수강기록·진로만으로 이번 학기 시간표
후보를 제안한다.

세션 영속화는 아직 없다 (스파이크 단계). 대화 히스토리는 클라이언트가 `history`로 전달.
Phase 3c에서 `CourseRoadmapChatSession.roadmap_id` nullable 마이그레이션 후 세션 저장 추가 예정.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.planning.timetable_chat import run_timetable_chat
from app.domains.users.models import User

router = APIRouter(prefix="/agent/timetable", tags=["timetable-agent"])


class HistoryTurn(BaseModel):
    role: str = Field(..., description="'user' | 'assistant'")
    content: str


class TimetableChatRequest(BaseModel):
    year: str = Field(..., description="달력 연도 (예: '2026')")
    semester: str = Field(..., description="학기 (예: '2학기')")
    message: str
    history: list[HistoryTurn] | None = None


class ScheduleSuggestion(BaseModel):
    offering_ids: list[int]
    rationale: str | None = None


class TimetableChatResponse(BaseModel):
    reply: str
    schedules: list[ScheduleSuggestion]
    iterations: int
    tool_calls: list[dict]


@router.post("/recommend", response_model=TimetableChatResponse)
def recommend_timetable_agent(
    payload: TimetableChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TimetableChatResponse:
    result = run_timetable_chat(
        db=db,
        user=current_user,
        year=payload.year,
        semester=payload.semester,
        message=payload.message,
        history=[h.model_dump() for h in (payload.history or [])],
    )
    return TimetableChatResponse(
        reply=result["reply"],
        schedules=[ScheduleSuggestion(**s) for s in result["schedules"]],
        iterations=result["iterations"],
        tool_calls=result["tool_calls"],
    )
