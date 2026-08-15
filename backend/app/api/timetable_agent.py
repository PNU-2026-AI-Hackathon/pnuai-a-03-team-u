"""시간표 LLM 에이전트 엔드포인트.

로드맵과 독립 아키텍처(2026-08-03 결정). 세션 영속화 도입 (2026-08-11):
- 프론트가 매번 history 배열을 전달하던 스테이트리스 모델 → DB에 (user, year, semester)
  스코프의 세션·메시지 저장. 새로고침·재접속 시 대화 유지.
- 로드맵 챗 세션(course_roadmap_chat_sessions)과 별개 테이블(timetable_chat_sessions).
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.courses.models import Course, CourseOffering, CourseTime
from app.domains.planning.models import TimetableChatMessage, TimetableChatSession
from app.domains.planning.timetable_chat import (
    clear_chat_messages,
    create_chat_session,
    delete_chat_session,
    list_chat_sessions,
    load_chat_messages,
    run_timetable_chat,
)
from app.domains.users.models import User

router = APIRouter(prefix="/agent/timetable", tags=["timetable-agent"])


# --- 세션 CRUD ---------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    year: str
    semester: str
    title: str | None = None


class SessionResponse(BaseModel):
    session_id: int
    year: str
    semester: str
    title: str | None
    created_at: str
    updated_at: str
    message_count: int

    @classmethod
    def from_model(cls, s: TimetableChatSession, message_count: int) -> "SessionResponse":
        return cls(
            session_id=s.id,
            year=s.year,
            semester=s.semester,
            title=s.title,
            created_at=s.created_at.isoformat() if s.created_at else "",
            updated_at=s.updated_at.isoformat() if s.updated_at else "",
            message_count=message_count,
        )


@router.post("/sessions", response_model=SessionResponse)
def create_session(
    payload: CreateSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionResponse:
    s = create_chat_session(db, current_user, payload.year, payload.semester, title=payload.title)
    return SessionResponse.from_model(s, message_count=0)


@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(
    year: str | None = None,
    semester: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SessionResponse]:
    sessions = list_chat_sessions(db, current_user, year=year, semester=semester)
    if not sessions:
        return []
    counts = dict(
        db.execute(
            select(TimetableChatMessage.session_id, func.count(TimetableChatMessage.id))
            .where(TimetableChatMessage.session_id.in_([s.id for s in sessions]))
            .group_by(TimetableChatMessage.session_id)
        ).all()
    )
    return [SessionResponse.from_model(s, counts.get(s.id, 0)) for s in sessions]


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: str


@router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
def get_session_messages(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MessageResponse]:
    messages = load_chat_messages(db, current_user, session_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")
    return [
        MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            created_at=m.created_at.isoformat() if m.created_at else "",
        )
        for m in messages
    ]


@router.delete("/sessions/{session_id}/messages")
def clear_session_messages(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """세션은 남기고 메시지만 비운다 — 로드맵 챗의 '이 대화 비우기'와 동일."""
    deleted = clear_chat_messages(db, current_user, session_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")
    return {"deleted_messages": deleted}


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not delete_chat_session(db, current_user, session_id):
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")
    return {"deleted": session_id}


# --- 추천 (기존 유지, 시그니처만 확장) --------------------------------------


class TimetableChatRequest(BaseModel):
    year: str = Field(..., description="달력 연도 (예: '2026')")
    semester: str = Field(..., description="학기 (예: '2학기')")
    message: str
    # 신규: session_id를 넘기면 그 세션에 이어붙이고, 없으면 최근 세션 이어쓰기
    # (또는 첫 요청이면 자동 생성).
    session_id: int | None = None


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
    session_id: int


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
    try:
        result = run_timetable_chat(
            db=db,
            user=current_user,
            year=payload.year,
            semester=payload.semester,
            message=payload.message,
            session_id=payload.session_id,
        )
    except ValueError as e:
        # session_id 소유자·학기 불일치 등
        raise HTTPException(status_code=400, detail=str(e))

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
        session_id=result["session_id"],
    )
