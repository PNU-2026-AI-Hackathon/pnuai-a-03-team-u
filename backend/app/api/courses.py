"""과목 검색(자동완성). 로드맵/시간표 화면에서 과목을 직접 입력할 때 쓴다.

사용자가 과목명을 자유롭게 타이핑해서 그대로 저장하게 두면 오타/부정확한
이름이 그대로 DB에 들어간다. 그래서 저장은 항상 이 검색 결과에서 고른
course_id를 통해서만 이뤄지게 하고(roadmaps.py의 아이템 생성 참고),
프론트는 자동완성 목록에서 클릭해야만 입력칸이 채워지게 만든다.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.academics.models import Major
from app.domains.courses.models import Course, CourseOffering, CourseTime
from app.domains.users.models import User

router = APIRouter(prefix="/courses", tags=["courses"])


class CourseSearchResult(BaseModel):
    id: int
    course_name: str
    course_code: str | None
    department_id: int | None
    major_id: int | None
    category: str | None
    credits: float | None

    model_config = {"from_attributes": True}


@router.get("/search", response_model=list[CourseSearchResult])
def search_courses(
    q: str,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """과목명으로 검색하되, 사용자 본인 학과/전공 과목을 먼저 보여준다."""
    q = q.strip()
    if not q:
        return []

    # 본인 학과/전공이면 0, 아니면 1 — 정렬 시 본인 것이 먼저 오게
    own_department_rank = case((Course.department_id == current_user.department_id, 0), else_=1)
    own_major_rank = case((Course.major_id == current_user.major_id, 0), else_=1)

    rows = db.scalars(
        select(Course)
        .where(Course.course_name.ilike(f"%{q}%"))
        .order_by(own_department_rank, own_major_rank, Course.course_name)
        .limit(limit)
    ).all()
    return rows


class OfferingTime(BaseModel):
    day_of_week: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    classroom: str | None = None


class OfferingSearchResult(BaseModel):
    """시간표 화면의 "과목 추가" 목록 한 줄.

    시간표 에이전트 추천(timetable_agent.SuggestedOffering)과 같은 모양이라
    프론트가 담기 로직을 하나로 쓴다.
    """

    offering_id: int
    course_id: int | None = None
    course_name: str | None = None
    course_code: str | None = None
    category: str | None = None
    credits: float | None = None
    section: str | None = None
    professor: str | None = None
    times: list[OfferingTime] = []


def _format_time(value: datetime.time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


@router.get("/offerings", response_model=list[OfferingSearchResult])
def search_offerings(
    year: str,
    semester: str,
    department_id: int | None = None,
    # 전공은 이름으로 받는다. 학부 자동완성(/departments/search)이 전공을 이름
    # 목록으로만 주기 때문에, id를 요구하면 프론트가 한 번 더 조회해야 한다.
    major: str | None = None,
    category: str | None = None,
    q: str = "",
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """대상 학기에 실제로 개설된 강좌를 학부/전공으로 좁혀 찾는다.

    시간표의 "과목 추가"가 쓰던 목록은 로드맵에 이미 담긴 과목에서 파생된
    것이라, 아직 계획에 없는 과목은 아예 보이지 않았다. 다른 학부 과목을
    담으려면 여기서 직접 찾아야 한다.

    학부만 주면 그 학부의 모든 전공이 함께 나온다(전공 미지정 과목 포함) —
    학부 공통 과목을 놓치지 않게 하려는 것이다.
    """
    query = (
        select(CourseOffering, Course)
        .join(Course, Course.id == CourseOffering.course_id)
        .where(CourseOffering.year == year, CourseOffering.semester == semester)
    )
    if department_id is not None:
        query = query.where(Course.department_id == department_id)
    if major and major.strip():
        major_query = select(Major.id).where(Major.name == major.strip())
        if department_id is not None:
            major_query = major_query.where(Major.department_id == department_id)
        matched_major_ids = list(db.scalars(major_query))
        # 같은 이름의 전공이 여러 학부에 있을 수 있어 in_으로 받는다.
        # 이름이 안 맞으면 빈 결과가 맞다 — 조건을 조용히 무시하면 엉뚱한
        # 전공 과목까지 섞여 나온다.
        query = query.where(Course.major_id.in_(matched_major_ids))
    if category:
        # "전공"으로 전공기초·전공필수·전공선택을 한 번에 훑을 수 있게 부분 일치를 쓴다.
        query = query.where(Course.category.ilike(f"%{category}%"))
    q = q.strip()
    if q:
        query = query.where(
            Course.course_name.ilike(f"%{q}%") | CourseOffering.professor.ilike(f"%{q}%")
        )

    rows = db.execute(
        query.order_by(Course.course_name, CourseOffering.section).limit(limit)
    ).all()
    if not rows:
        return []

    offering_ids = [offering.id for offering, _ in rows]
    times_by_offering: dict[int, list[OfferingTime]] = {}
    for row in db.scalars(select(CourseTime).where(CourseTime.offering_id.in_(offering_ids))):
        times_by_offering.setdefault(row.offering_id, []).append(
            OfferingTime(
                day_of_week=row.day_of_week,
                start_time=_format_time(row.start_time),
                end_time=_format_time(row.end_time),
                classroom=row.classroom,
            )
        )

    return [
        OfferingSearchResult(
            offering_id=offering.id,
            course_id=course.id,
            course_name=course.course_name,
            course_code=course.course_code,
            category=course.category,
            credits=course.credits,
            section=offering.section,
            professor=offering.professor,
            times=times_by_offering.get(offering.id, []),
        )
        for offering, course in rows
    ]
