"""시간표 LLM 에이전트 엔드포인트 (스파이크).

기존 결정론적 `/me/roadmaps/{roadmap_id}/timetable/recommend`와 병존한다. 이 엔드포인트는
로드맵과 독립적으로 동작 — `roadmap_id` 불필요, 학생 수강기록·진로만으로 이번 학기 시간표
후보를 제안한다.

세션 영속화는 아직 없다 (스파이크 단계). 대화 히스토리는 클라이언트가 `history`로 전달.
Phase 3c에서 `CourseRoadmapChatSession.roadmap_id` nullable 마이그레이션 후 세션 저장 추가 예정.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.courses.models import Course, CourseOffering, CourseTime
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


class OfferingTime(BaseModel):
    day_of_week: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    classroom: str | None = None


class SuggestedOffering(BaseModel):
    """추천 분반 하나. 사용자가 승인 화면에서 무엇을 담는지 알아볼 수 있어야 한다."""

    offering_id: int
    course_id: int | None = None
    course_name: str | None = None
    course_code: str | None = None
    category: str | None = None
    credits: float | None = None
    section: str | None = None
    professor: str | None = None
    times: list[OfferingTime] = []


class ScheduleSuggestion(BaseModel):
    offering_ids: list[int]
    rationale: str | None = None
    # offering_ids만 주면 프론트가 "무엇을 담을지" 보여줄 수 없어서 승인 UI를
    # 만들 수 없다. 화면에 필요한 최소 정보를 여기서 채워 보낸다.
    offerings: list[SuggestedOffering] = []
    total_credits: float = 0.0


class TimetableChatResponse(BaseModel):
    reply: str
    schedules: list[ScheduleSuggestion]
    iterations: int
    tool_calls: list[dict]


def _format_time(value: datetime.time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


def _load_offerings(db: Session, offering_ids: list[int]) -> dict[int, SuggestedOffering]:
    """추천된 offering_id들을 화면에 보여줄 수 있는 형태로 한 번에 읽어온다."""
    if not offering_ids:
        return {}

    rows = db.execute(
        select(CourseOffering, Course)
        .join(Course, Course.id == CourseOffering.course_id, isouter=True)
        .where(CourseOffering.id.in_(offering_ids))
    ).all()

    times_by_offering: dict[int, list[OfferingTime]] = {}
    for time_row in db.scalars(
        select(CourseTime).where(CourseTime.offering_id.in_(offering_ids))
    ):
        times_by_offering.setdefault(time_row.offering_id, []).append(
            OfferingTime(
                day_of_week=time_row.day_of_week,
                start_time=_format_time(time_row.start_time),
                end_time=_format_time(time_row.end_time),
                classroom=time_row.classroom,
            )
        )

    return {
        offering.id: SuggestedOffering(
            offering_id=offering.id,
            course_id=offering.course_id,
            course_name=course.course_name if course else None,
            course_code=course.course_code if course else None,
            category=course.category if course else None,
            credits=course.credits if course else None,
            section=offering.section,
            professor=offering.professor,
            times=times_by_offering.get(offering.id, []),
        )
        for offering, course in rows
    }


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

    all_ids = [oid for s in result["schedules"] for oid in s.get("offering_ids", [])]
    detail_by_id = _load_offerings(db, list(dict.fromkeys(all_ids)))

    schedules: list[ScheduleSuggestion] = []
    for suggestion in result["schedules"]:
        offering_ids = suggestion.get("offering_ids", [])
        offerings = [detail_by_id[oid] for oid in offering_ids if oid in detail_by_id]
        schedules.append(
            ScheduleSuggestion(
                offering_ids=offering_ids,
                rationale=suggestion.get("rationale"),
                offerings=offerings,
                total_credits=sum(o.credits or 0 for o in offerings),
            )
        )

    return TimetableChatResponse(
        reply=result["reply"],
        schedules=schedules,
        iterations=result["iterations"],
        tool_calls=result["tool_calls"],
    )
