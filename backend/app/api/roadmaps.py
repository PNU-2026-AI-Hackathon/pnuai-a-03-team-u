"""성장 로드맵 작성/수정. 사용자가 직접 학기별 과목을 채워 넣는 화면용 API.

항목(item) 생성/수정은 항상 실제 존재하는 course_id를 받아서 서버가
course_name/category/credits를 그 course에서 그대로 복사해 저장한다
(오타/존재하지 않는 과목명으로는 저장 자체가 안 됨). department_name/major_name은
course_id가 있을 때만 courses(+departments+majors)를 조인해 응답 시점에 채운다 —
과거 이수내역은 course_id가 매칭 안 된 경우가 흔한데(동명 과목이 여러 학과에
걸쳐 있어서), 그런 경우도 학과 정보만 없을 뿐 과목명/학점/이수구분은 성적표
원본에 그대로 있어서 스냅샷으로 보존한다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.academics.models import Department, Major
from app.domains.courses.models import Course, CourseOffering
from app.domains.planning.history import project_curriculum_term, sync_completed_courses_to_roadmap
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


def _item_to_response(db: Session, item: CourseRoadmapItem) -> RoadmapItemResponse:
    """department_name/major_name은 course_id가 있을 때만 join으로 채운다.

    course_name/category/credits는 이미 item에 스냅샷으로 저장돼 있어 join이
    필요 없다 — 과거 이력은 course_id가 없어도(unmatched) 이 값들이 있어야 하기 때문.
    """
    department_name = major_name = None
    if item.course_id is not None:
        course = db.get(Course, item.course_id)
        if course is not None:
            department = db.get(Department, course.department_id) if course.department_id else None
            major = db.get(Major, course.major_id) if course.major_id else None
            department_name = department.name if department else None
            major_name = major.name if major else None

    return RoadmapItemResponse(
        id=item.id,
        course_id=item.course_id,
        planned_grade=item.planned_grade,
        planned_year=item.planned_year,
        planned_semester=item.planned_semester,
        course_name=item.course_name,
        department_name=department_name,
        major_name=major_name,
        category=item.category,
        credits=item.credits,
        status=item.status,
        is_confirmed=item.is_confirmed,
        reason=item.reason,
        source=item.source,
    )


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
    raw_items = db.scalars(
        select(CourseRoadmapItem)
        .where(CourseRoadmapItem.roadmap_id == roadmap.id)
        .order_by(CourseRoadmapItem.planned_year, CourseRoadmapItem.planned_semester)
    ).all()
    roadmap.items = [_item_to_response(db, item) for item in raw_items]  # type: ignore[attr-defined]
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


def _set_course(db: Session, item: CourseRoadmapItem, course_id: int) -> None:
    """course_id로 courses를 조회해 course_id/course_name/category/credits를 채운다.

    course_id가 courses 테이블에 없으면 404 — 오타/존재하지 않는 과목명으로는
    저장 자체가 안 되는 지점이 여기다.
    """
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 과목입니다")
    item.course_id = course.id
    item.course_name = course.course_name
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
    _set_course(db, item, payload.course_id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return _item_to_response(db, item)


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
        _set_course(db, item, payload.course_id)
    db.commit()
    db.refresh(item)
    return _item_to_response(db, item)


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


# --- 시간표 에이전트 결과를 로드맵에 반영 ---


class TimetableApplyRequest(BaseModel):
    """시간표 UI에서 사용자가 저장 버튼을 눌렀을 때 오는 페이로드.

    year/semester는 UI에서 요청한 학기(예: 2026 2학기)와 일치해야 하고, offering_ids는
    사용자가 최종 선택한 분반 목록이다. 중복 회피(이미 이수/이미 로드맵에 있음)는 시간표
    에이전트가 upstream에서 사용자에게 미리 알려주고 걸러낸 상태를 전제로 한다 —
    여기서는 (course_id, planned_year, planned_semester) 완전 중복만 조용히 스킵한다.
    """

    year: str
    semester: str
    offering_ids: list[int]
    planned_grade: int | None = None  # 프론트가 알면 넘김. 없으면 null 저장(수동 편집 가능)


class TimetableApplySkipped(BaseModel):
    offering_id: int
    course_id: int | None
    course_name: str | None
    reason: str


class TimetableApplyRemovedFromFuture(BaseModel):
    item_id: int
    course_id: int | None
    course_name: str | None
    planned_year: str | None
    planned_semester: str | None


class TimetableApplyResult(BaseModel):
    applied: list[RoadmapItemResponse]
    skipped: list[TimetableApplySkipped]
    removed_from_future: list[TimetableApplyRemovedFromFuture]


def _semester_sort_key(year: str | None, semester: str | None) -> tuple[int, int] | None:
    """(planned_year, planned_semester)를 비교 가능한 (년, 학기 int) 튜플로 만든다.
    파싱 실패 시 None — 호출부는 None이면 "비교 불가"로 취급해 손대지 않는다.
    계절수업/입학전성적 같은 비정규 학기도 여기서 None으로 걸러진다."""
    if not year or not semester:
        return None
    try:
        y = int(year)
    except (TypeError, ValueError):
        return None
    s = semester.strip()
    if s.startswith("1") and "2" not in s:
        return (y, 1)
    if s.startswith("2") and "1" not in s.replace("2", "", 1):
        return (y, 2)
    return None


@router.post("/{roadmap_id}/timetable/apply", response_model=TimetableApplyResult)
def apply_timetable_to_roadmap(
    roadmap_id: int,
    payload: TimetableApplyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TimetableApplyResult:
    """시간표 에이전트가 추천하고 사용자가 UI에서 최종 선택한 분반들을 로드맵 항목으로 반영.

    각 offering을 course로 해석해 (course_id, planned_year, planned_semester) 기준으로
    upsert 한다. 이미 같은 학기에 같은 과목이 있으면 skipped에 넣고 넘어간다 —
    프론트는 이 목록을 사용자에게 보여줘서 왜 일부가 반영 안 됐는지 알려줄 수 있다.
    """
    roadmap = _get_owned_roadmap(db, current_user.id, roadmap_id)
    target_key = _semester_sort_key(payload.year, payload.semester)

    # planned_grade가 비면 로드맵 화면이 이 항목을 학년 슬롯에 넣지 못하고
    # "2026년 2학기" 같은 기타 칸으로 떨어뜨린다. 프론트가 안 넘겨주면
    # 이수 기록에서 커리큘럼 학년을 직접 계산한다.
    planned_grade = payload.planned_grade
    curriculum_semester = payload.semester
    if planned_grade is None:
        planned_grade, projected_semester = project_curriculum_term(
            db, current_user.id, payload.year, payload.semester
        )
        if planned_grade is not None and projected_semester is not None:
            curriculum_semester = projected_semester

    applied: list[CourseRoadmapItem] = []
    skipped: list[TimetableApplySkipped] = []
    removed_from_future: list[TimetableApplyRemovedFromFuture] = []

    for offering_id in payload.offering_ids:
        offering = db.get(CourseOffering, offering_id)
        if offering is None:
            skipped.append(TimetableApplySkipped(
                offering_id=offering_id, course_id=None, course_name=None,
                reason="존재하지 않는 분반입니다",
            ))
            continue

        # 요청 학기와 실제 개설 학기 불일치 방지 (프론트 오류/이전 캐시 등)
        if (offering.year or "") != payload.year or (offering.semester or "") != payload.semester:
            skipped.append(TimetableApplySkipped(
                offering_id=offering_id, course_id=offering.course_id, course_name=None,
                reason=f"분반이 실제로 개설된 학기({offering.year} {offering.semester})가 "
                       f"요청 학기({payload.year} {payload.semester})와 다릅니다",
            ))
            continue

        course = db.get(Course, offering.course_id)
        if course is None:
            skipped.append(TimetableApplySkipped(
                offering_id=offering_id, course_id=offering.course_id, course_name=None,
                reason="분반에 연결된 과목이 존재하지 않습니다",
            ))
            continue

        # 같은 학기·같은 과목 중복 → 조용히 스킵 (LLM이 upstream에서 이미 안내한 전제)
        # 저장하는 값(curriculum_semester)과 같은 기준으로 찾아야 한다. 달력 학기로
        # 찾으면 방금 저장한 항목을 다음 호출에서 못 찾아 중복이 쌓인다.
        existing = db.scalar(
            select(CourseRoadmapItem).where(
                CourseRoadmapItem.roadmap_id == roadmap.id,
                CourseRoadmapItem.course_id == course.id,
                CourseRoadmapItem.planned_year == payload.year,
                CourseRoadmapItem.planned_semester == curriculum_semester,
            )
        )
        if existing is not None:
            skipped.append(TimetableApplySkipped(
                offering_id=offering_id, course_id=course.id, course_name=course.course_name,
                reason="이미 같은 학기에 이 과목이 로드맵에 있습니다",
            ))
            continue

        # 이 과목이 로드맵의 이후 학기에도 계획돼 있으면 그 항목을 삭제한다 —
        # 이번 학기에 이수하기로 확정했으니 미래 학기 계획은 중복. completed 항목은
        # 실제 이수 기록이라 절대 손대지 않는다.
        if target_key is not None:
            future_dupes = db.scalars(
                select(CourseRoadmapItem).where(
                    CourseRoadmapItem.roadmap_id == roadmap.id,
                    CourseRoadmapItem.course_id == course.id,
                    CourseRoadmapItem.status != "completed",
                )
            ).all()
            for dupe in future_dupes:
                dupe_key = _semester_sort_key(dupe.planned_year, dupe.planned_semester)
                if dupe_key is None or dupe_key <= target_key:
                    continue
                removed_from_future.append(TimetableApplyRemovedFromFuture(
                    item_id=dupe.id, course_id=dupe.course_id, course_name=dupe.course_name,
                    planned_year=dupe.planned_year, planned_semester=dupe.planned_semester,
                ))
                db.delete(dupe)

        item = CourseRoadmapItem(
            roadmap_id=roadmap.id,
            course_id=course.id,
            course_name=course.course_name,
            category=course.category,
            credits=course.credits,
            planned_grade=planned_grade,
            planned_year=payload.year,
            # planned_year는 달력 연도, planned_semester는 커리큘럼 학기다
            # (history.py가 이수 기록을 옮길 때 쓰는 것과 같은 규약). 휴학으로
            # 달력과 커리큘럼이 어긋나도 로드맵의 학년 슬롯에 정확히 들어간다.
            planned_semester=curriculum_semester,
            source="ai",  # AI(시간표 에이전트)가 후보를 제시
            is_confirmed=True,  # 사용자가 UI에서 명시적으로 저장 눌러서 확정
            status="planned",
        )
        db.add(item)
        applied.append(item)

    db.commit()
    for item in applied:
        db.refresh(item)

    return TimetableApplyResult(
        applied=[_item_to_response(db, item) for item in applied],
        skipped=skipped,
        removed_from_future=removed_from_future,
    )
