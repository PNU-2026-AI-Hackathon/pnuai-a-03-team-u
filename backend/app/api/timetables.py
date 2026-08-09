"""시간표(수강계획) CRUD.

시간표 화면에서 "2026-2 시간표 A"처럼 이름 붙인 시간표를 여러 개 만들고,
강좌를 담았다 빼며 비교하는 단위다. 여기 담긴 것은 아직 계획일 뿐이고,
로드맵 반영은 기존 POST /me/roadmaps/{id}/timetable/apply가 담당한다 —
시간표를 지워도 로드맵은 건드리지 않는다.

course_plans/course_plan_items는 초기 스키마부터 있었지만 아무 API도 쓰지
않던 테이블이다(0행). 새 테이블을 만드는 대신 이걸 살려 쓴다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.timetable_agent import SuggestedOffering, _load_offerings
from app.core.db import get_db
from app.domains.courses.models import Course, CourseOffering
from app.domains.planning.models import CoursePlan, CoursePlanItem
from app.domains.users.models import User

router = APIRouter(prefix="/me/timetables", tags=["timetables"])


class TimetableSummary(BaseModel):
    id: int
    title: str
    year: str | None
    semester: str | None
    item_count: int
    total_credits: float


class TimetableDetail(TimetableSummary):
    offerings: list[SuggestedOffering]


class CreateTimetableRequest(BaseModel):
    year: str
    semester: str
    title: str | None = None


class RenameTimetableRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class AddItemsRequest(BaseModel):
    offering_ids: list[int] = Field(min_length=1)


def _get_owned_plan(db: Session, user_id: int, plan_id: int) -> CoursePlan:
    plan = db.get(CoursePlan, plan_id)
    if plan is None or plan.user_id != user_id:
        raise HTTPException(status_code=404, detail="시간표를 찾을 수 없습니다")
    return plan


def _display_title(plan: CoursePlan) -> str:
    # title 컬럼이 나중에 생겨서 옛 행은 비어 있을 수 있다.
    return (plan.title or "").strip() or f"시간표 {plan.id}"


def _plan_offerings(db: Session, plan_id: int) -> list[SuggestedOffering]:
    offering_ids = list(
        db.scalars(
            select(CoursePlanItem.offering_id)
            .where(CoursePlanItem.plan_id == plan_id, CoursePlanItem.offering_id.is_not(None))
            .order_by(CoursePlanItem.id)
        )
    )
    detail_by_id = _load_offerings(db, offering_ids)
    # 담은 순서를 유지한다. dict 순회는 조회 순서라 보장이 없다.
    return [detail_by_id[oid] for oid in offering_ids if oid in detail_by_id]


def _to_detail(db: Session, plan: CoursePlan) -> TimetableDetail:
    offerings = _plan_offerings(db, plan.id)
    return TimetableDetail(
        id=plan.id,
        title=_display_title(plan),
        year=plan.year,
        semester=plan.semester,
        item_count=len(offerings),
        total_credits=sum(o.credits or 0 for o in offerings),
        offerings=offerings,
    )


@router.get("", response_model=list[TimetableSummary])
def list_timetables(
    year: str | None = None,
    semester: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = select(CoursePlan).where(CoursePlan.user_id == current_user.id)
    if year:
        query = query.where(CoursePlan.year == year)
    if semester:
        query = query.where(CoursePlan.semester == semester)
    plans = db.scalars(query.order_by(CoursePlan.id)).all()
    if not plans:
        return []

    # 학점 합계는 목록에서도 보여준다. 개수·학점을 시간표별로 한 번에 집계.
    rows = db.execute(
        select(
            CoursePlanItem.plan_id,
            func.count(CoursePlanItem.id),
            func.coalesce(func.sum(Course.credits), 0.0),
        )
        .join(CourseOffering, CourseOffering.id == CoursePlanItem.offering_id)
        .join(Course, Course.id == CourseOffering.course_id)
        .where(CoursePlanItem.plan_id.in_([p.id for p in plans]))
        .group_by(CoursePlanItem.plan_id)
    ).all()
    stats = {plan_id: (count, float(credits)) for plan_id, count, credits in rows}

    return [
        TimetableSummary(
            id=plan.id,
            title=_display_title(plan),
            year=plan.year,
            semester=plan.semester,
            item_count=stats.get(plan.id, (0, 0.0))[0],
            total_credits=stats.get(plan.id, (0, 0.0))[1],
        )
        for plan in plans
    ]


@router.post("", response_model=TimetableDetail)
def create_timetable(
    payload: CreateTimetableRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    title = (payload.title or "").strip()
    if not title:
        # "시간표 1", "시간표 2"… 같은 학기 안에서만 순번을 센다.
        count = db.scalar(
            select(func.count(CoursePlan.id)).where(
                CoursePlan.user_id == current_user.id,
                CoursePlan.year == payload.year,
                CoursePlan.semester == payload.semester,
            )
        )
        title = f"시간표 {(count or 0) + 1}"

    plan = CoursePlan(
        user_id=current_user.id,
        year=payload.year,
        semester=payload.semester,
        title=title,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _to_detail(db, plan)


@router.get("/{plan_id}", response_model=TimetableDetail)
def get_timetable(
    plan_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = _get_owned_plan(db, current_user.id, plan_id)
    return _to_detail(db, plan)


@router.patch("/{plan_id}", response_model=TimetableDetail)
def rename_timetable(
    plan_id: int,
    payload: RenameTimetableRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = _get_owned_plan(db, current_user.id, plan_id)
    plan.title = payload.title.strip()
    db.commit()
    db.refresh(plan)
    return _to_detail(db, plan)


@router.delete("/{plan_id}", status_code=204)
def delete_timetable(
    plan_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """시간표와 담긴 항목을 지운다. 로드맵에 이미 반영한 항목은 건드리지 않는다."""
    plan = _get_owned_plan(db, current_user.id, plan_id)
    db.execute(delete(CoursePlanItem).where(CoursePlanItem.plan_id == plan.id))
    db.delete(plan)
    db.commit()


@router.post("/{plan_id}/items", response_model=TimetableDetail)
def add_timetable_items(
    plan_id: int,
    payload: AddItemsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """분반을 시간표에 담는다. 이미 담긴 분반은 조용히 건너뛴다(멱등).

    AI 추천 승인이 여러 개를 한 번에 담으므로 리스트로 받는다.
    """
    plan = _get_owned_plan(db, current_user.id, plan_id)

    existing = set(
        db.scalars(
            select(CoursePlanItem.offering_id).where(CoursePlanItem.plan_id == plan.id)
        )
    )
    for offering_id in payload.offering_ids:
        if offering_id in existing:
            continue
        if db.get(CourseOffering, offering_id) is None:
            raise HTTPException(status_code=404, detail=f"분반 {offering_id}이 없습니다")
        db.add(CoursePlanItem(plan_id=plan.id, offering_id=offering_id, source="manual"))
        existing.add(offering_id)
    db.commit()
    return _to_detail(db, plan)


@router.delete("/{plan_id}/items/{offering_id}", response_model=TimetableDetail)
def remove_timetable_item(
    plan_id: int,
    offering_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = _get_owned_plan(db, current_user.id, plan_id)
    db.execute(
        delete(CoursePlanItem).where(
            CoursePlanItem.plan_id == plan.id,
            CoursePlanItem.offering_id == offering_id,
        )
    )
    db.commit()
    return _to_detail(db, plan)
