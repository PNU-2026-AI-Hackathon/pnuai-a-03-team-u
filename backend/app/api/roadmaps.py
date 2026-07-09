"""성장 로드맵 작성/수정. 사용자가 직접 학기별 과목을 채워 넣는 화면용 API.

항목(item) 생성/수정은 항상 실제 존재하는 course_id를 받아서 서버가
courses/departments/majors를 조회해 course_name 등 스냅샷을 채운다 —
프론트가 자동완성(GET /courses/search)에서 고른 course_id만 보내게 만들면,
오타나 존재하지 않는 과목명으로는 애초에 저장 자체가 안 된다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.academics.models import Department, Major
from app.domains.courses.models import Course
from app.domains.planning.history import sync_completed_courses_to_roadmap
from app.domains.planning.models import CourseRoadmap, CourseRoadmapItem
from app.domains.users.models import User

router = APIRouter(prefix="/me/roadmaps", tags=["roadmaps"])


# --- 로드맵 ---


class RoadmapCreateRequest(BaseModel):
    title: str | None = None
    start_year: str | None = None
    target_graduation_year: str | None = None


class RoadmapUpdateRequest(BaseModel):
    title: str | None = None
    target_graduation_year: str | None = None
    status: str | None = None
    summary: str | None = None


class RoadmapItemResponse(BaseModel):
    id: int
    course_id: int | None
    planned_grade: int | None
    planned_year: str | None
    planned_semester: str | None
    course_name: str | None
    department_name: str | None
    major_name: str | None
    category: str | None
    credits: float | None
    status: str
    is_confirmed: bool
    reason: str | None
    source: str

    model_config = {"from_attributes": True}


class RoadmapResponse(BaseModel):
    id: int
    title: str | None
    start_year: str | None
    target_graduation_year: str | None
    status: str
    summary: str | None

    model_config = {"from_attributes": True}


class RoadmapDetailResponse(RoadmapResponse):
    items: list[RoadmapItemResponse]


def _get_owned_roadmap(db: Session, user_id: int, roadmap_id: int) -> CourseRoadmap:
    roadmap = db.get(CourseRoadmap, roadmap_id)
    if roadmap is None or roadmap.user_id != user_id:
        raise HTTPException(status_code=404, detail="로드맵을 찾을 수 없습니다")
    return roadmap


@router.get("", response_model=list[RoadmapResponse])
def list_roadmaps(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(CourseRoadmap).where(CourseRoadmap.user_id == current_user.id).order_by(CourseRoadmap.id.desc())
    ).all()


def _create_roadmap(db: Session, user_id: int, payload: RoadmapCreateRequest | None = None) -> CourseRoadmap:
    payload = payload or RoadmapCreateRequest()
    roadmap = CourseRoadmap(
        user_id=user_id,
        title=payload.title,
        start_year=payload.start_year,
        target_graduation_year=payload.target_graduation_year,
    )
    db.add(roadmap)
    db.flush()
    sync_completed_courses_to_roadmap(db, user_id=user_id, roadmap_id=roadmap.id)
    db.commit()
    db.refresh(roadmap)
    return roadmap


@router.post("", response_model=RoadmapDetailResponse, status_code=201)
def create_roadmap(
    payload: RoadmapCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """새 로드맵을 만들고, 이미 이수한 과목을 바로 채워 넣는다."""
    roadmap = _create_roadmap(db, current_user.id, payload)
    return _with_items(db, roadmap)


@router.get("/current", response_model=RoadmapDetailResponse)
def get_or_create_current_roadmap(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """"수정하기" 버튼 하나로 쓰기 위한 진입점.

    사용자가 로드맵을 아직 안 만들었으면 자동으로 하나 만들어서(이수내역
    자동 반영 포함) 돌려주고, 이미 있으면(가장 최근 것) 그대로 돌려준다.
    프론트는 "작성하기"/"수정하기"를 구분할 필요 없이 이 엔드포인트 하나만
    호출하고 항상 편집 화면을 띄우면 된다.
    """
    roadmap = db.scalars(
        select(CourseRoadmap)
        .where(CourseRoadmap.user_id == current_user.id)
        .order_by(CourseRoadmap.id.desc())
        .limit(1)
    ).first()
    if roadmap is None:
        roadmap = _create_roadmap(db, current_user.id)
    return _with_items(db, roadmap)


@router.get("/{roadmap_id}", response_model=RoadmapDetailResponse)
def get_roadmap(
    roadmap_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    roadmap = _get_owned_roadmap(db, current_user.id, roadmap_id)
    return _with_items(db, roadmap)


@router.patch("/{roadmap_id}", response_model=RoadmapDetailResponse)
def update_roadmap(
    roadmap_id: int,
    payload: RoadmapUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    roadmap = _get_owned_roadmap(db, current_user.id, roadmap_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(roadmap, field, value)
    db.commit()
    db.refresh(roadmap)
    return _with_items(db, roadmap)


@router.delete("/{roadmap_id}", status_code=204)
def delete_roadmap(
    roadmap_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    roadmap = _get_owned_roadmap(db, current_user.id, roadmap_id)
    db.query(CourseRoadmapItem).filter_by(roadmap_id=roadmap.id).delete()
    db.delete(roadmap)
    db.commit()


def _with_items(db: Session, roadmap: CourseRoadmap) -> CourseRoadmap:
    roadmap.items = db.scalars(  # type: ignore[attr-defined]
        select(CourseRoadmapItem)
        .where(CourseRoadmapItem.roadmap_id == roadmap.id)
        .order_by(CourseRoadmapItem.planned_year, CourseRoadmapItem.planned_semester)
    ).all()
    return roadmap


# --- 로드맵 항목 ---


class RoadmapItemCreateRequest(BaseModel):
    course_id: int  # 반드시 courses 테이블에 실재하는 과목이어야 함 (자동완성에서 고른 값)
    planned_grade: int | None = None
    planned_year: str | None = None
    planned_semester: str | None = None
    reason: str | None = None


class RoadmapItemUpdateRequest(BaseModel):
    course_id: int | None = None
    planned_grade: int | None = None
    planned_year: str | None = None
    planned_semester: str | None = None
    status: str | None = None
    is_confirmed: bool | None = None
    reason: str | None = None


def _fill_course_snapshot(db: Session, item: CourseRoadmapItem, course_id: int) -> None:
    """course_id로 courses/departments/majors를 조회해 스냅샷 필드를 채운다.

    course_id가 courses 테이블에 없으면 404 — 오타/존재하지 않는 과목명으로는
    저장 자체가 안 되는 지점이 여기다.
    """
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 과목입니다")

    department = db.get(Department, course.department_id) if course.department_id else None
    major = db.get(Major, course.major_id) if course.major_id else None

    item.course_id = course.id
    item.course_name = course.course_name
    item.department_name = department.name if department else None
    item.major_name = major.name if major else None
    item.category = course.category
    item.credits = course.credits


@router.post("/{roadmap_id}/items", response_model=RoadmapItemResponse, status_code=201)
def create_roadmap_item(
    roadmap_id: int,
    payload: RoadmapItemCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    roadmap = _get_owned_roadmap(db, current_user.id, roadmap_id)
    item = CourseRoadmapItem(
        roadmap_id=roadmap.id,
        planned_grade=payload.planned_grade,
        planned_year=payload.planned_year,
        planned_semester=payload.planned_semester,
        reason=payload.reason,
        source="manual",
    )
    _fill_course_snapshot(db, item, payload.course_id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _get_owned_item(db: Session, user_id: int, roadmap_id: int, item_id: int) -> CourseRoadmapItem:
    _get_owned_roadmap(db, user_id, roadmap_id)  # 소유권 확인
    item = db.get(CourseRoadmapItem, item_id)
    if item is None or item.roadmap_id != roadmap_id:
        raise HTTPException(status_code=404, detail="로드맵 항목을 찾을 수 없습니다")
    return item


@router.patch("/{roadmap_id}/items/{item_id}", response_model=RoadmapItemResponse)
def update_roadmap_item(
    roadmap_id: int,
    item_id: int,
    payload: RoadmapItemUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = _get_owned_item(db, current_user.id, roadmap_id, item_id)
    data = payload.model_dump(exclude_unset=True, exclude={"course_id"})
    for field, value in data.items():
        setattr(item, field, value)
    if payload.course_id is not None:
        _fill_course_snapshot(db, item, payload.course_id)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{roadmap_id}/items/{item_id}", status_code=204)
def delete_roadmap_item(
    roadmap_id: int,
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = _get_owned_item(db, current_user.id, roadmap_id, item_id)
    db.delete(item)
    db.commit()
