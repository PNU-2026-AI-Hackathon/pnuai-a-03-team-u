"""과목 검색(자동완성). 로드맵/시간표 화면에서 과목을 직접 입력할 때 쓴다.

사용자가 과목명을 자유롭게 타이핑해서 그대로 저장하게 두면 오타/부정확한
이름이 그대로 DB에 들어간다. 그래서 저장은 항상 이 검색 결과에서 고른
course_id를 통해서만 이뤄지게 하고(roadmaps.py의 아이템 생성 참고),
프론트는 자동완성 목록에서 클릭해야만 입력칸이 채워지게 만든다.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.academics.models import Major, ProgramCourse
from app.domains.courses.models import Course, CourseOffering, CourseTime
from app.domains.users.models import User

router = APIRouter(prefix="/courses", tags=["courses"])


class CourseSearchResult(BaseModel):
    id: int
    course_name: str
    course_code: str | None
    department_id: int | None
    major_id: int | None
    # 목록에서 전공 이름까지 보여주려고 조인해서 채운다(Course 자체엔 없음).
    major_name: str | None = None
    category: str | None
    credits: float | None
    # 로드맵 학기 배치 실수를 화면에서 미리 걸러내려고 노출한다(2026-08-26,
    # 개설 학기 안 맞는 과목이 로드맵에 잘못 꽂힌 실제 사고 이후 추가).
    year: str | None = None
    semester: str | None = None

    model_config = {"from_attributes": True}


@router.get("/search", response_model=list[CourseSearchResult])
def search_courses(
    q: str = "",
    # 학과를 골라 그 학과 과목을 쭉 훑어보는 용도(로드맵 "과목 추가"의 학과별
    # 브라우징 화면). q 없이 department_id만 와도 결과를 낸다.
    department_id: int | None = None,
    # 전공은 이름으로 받는다 — /departments/search가 전공을 이름 목록으로만
    # 주므로 search_offerings와 같은 관례를 따른다.
    major: str | None = None,
    category: str | None = None,
    limit: int = Query(40, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """과목명으로 검색하거나(q), 학과를 골라 훑어본다(department_id).

    로드맵 학기 카드에서 바로 여러 과목을 골라 담는 화면을 지원하려고
    department_id/major/category 브라우징을 추가했다(2026-08-26). search_offerings의
    program_courses 교차인정(핀테크융합전공처럼 다른 학과 개설 과목을 인정하는
    경우)은 아직 여기 안 옮겼다 — 그런 과목은 이름 검색(q)으로는 여전히 찾힌다.
    """
    q = q.strip()
    if not q and department_id is None:
        return []

    conditions = []
    if q:
        conditions.append(Course.course_name.ilike(f"%{q}%"))
    if department_id is not None:
        conditions.append(Course.department_id == department_id)
    if major and major.strip():
        major_query = select(Major.id).where(Major.name == major.strip())
        if department_id is not None:
            major_query = major_query.where(Major.department_id == department_id)
        # 이름이 안 맞으면 빈 결과가 맞다 — 조건을 조용히 무시하면 엉뚱한 전공
        # 과목까지 섞여 나온다(search_offerings와 동일 원칙).
        conditions.append(Course.major_id.in_(list(db.scalars(major_query))))
    if category:
        conditions.append(Course.category == category)

    # 본인 학과/전공이면 0, 아니면 1 — 정렬 시 본인 것이 먼저 오게
    own_department_rank = case((Course.department_id == current_user.department_id, 0), else_=1)
    own_major_rank = case((Course.major_id == current_user.major_id, 0), else_=1)

    rows = db.execute(
        select(Course, Major.name)
        .outerjoin(Major, Major.id == Course.major_id)
        .where(*conditions)
        .order_by(own_department_rank, own_major_rank, Course.year, Course.category, Course.course_name)
        .limit(limit)
    ).all()
    return [
        CourseSearchResult(
            id=course.id,
            course_name=course.course_name,
            course_code=course.course_code,
            department_id=course.department_id,
            major_id=course.major_id,
            major_name=major_name,
            category=course.category,
            credits=course.credits,
            year=course.year,
            semester=course.semester,
        )
        for course, major_name in rows
    ]


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
    # 학부만 고르면 그 학부의 모든 전공 과목이 함께 나온다. 어느 전공 과목인지
    # 줄마다 보여주지 않으면 "엉뚱한 과목이 섞였다"로 보인다(전공 미지정이면 None).
    major_name: str | None = None
    # 효원균형·창의교양 세부영역(사상과역사 등). 그 갈래가 아닌 과목은 항상 None.
    general_education_area: str | None = None
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
    # 여러 번 넘길 수 있다. "효원(균형·창의)교양"처럼 화면의 한 갈래가 DB에서는
    # 두 개 이상의 이수구분으로 나뉘어 있기 때문이다.
    category: list[str] | None = Query(None),
    # 효원균형·창의교양 갈래는 카테고리 2개로만 좁혀도 300건대가 그대로 나온다
    # (2026-2학기 357건). 세부영역(사상과역사 등)으로 한 번 더 좁히는 용도 —
    # courses.general_education_area의 정확한 값과 일치해야 한다(부분 일치 아님,
    # "세계와 소통"처럼 다른 영역명에 부분 포함되는 값이 없어 안전). 여러 번 넘길 수
    # 있다 — "균형교양 최소 2개 영역에서 2과목" 같은 요건은 사상과역사/사회와문화 중
    # 아무거나 담아도 되니, 후보를 한 영역으로만 좁히면 오히려 못 찾는다.
    general_education_area: list[str] | None = Query(None),
    q: str = "",
    # 상한을 둔 건 실수로 큰 값이 들어와 전 학기 개설(3천여 건)을 통째로
    # 내보내는 걸 막기 위해서다. 지금 데이터에서 가장 큰 갈래(음악학과 전공
    # 전체 368건)는 상한 안에 들어온다.
    limit: int = Query(50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """대상 학기에 실제로 개설된 강좌를 학부/전공으로 좁혀 찾는다.

    시간표의 "과목 추가"가 쓰던 목록은 로드맵에 이미 담긴 과목에서 파생된
    것이라, 아직 계획에 없는 과목은 아예 보이지 않았다. 다른 학부 과목을
    담으려면 여기서 직접 찾아야 한다.

    학부만 주고 전공을 안 주면 그 학부의 모든 전공이 함께 나온다(전공 미지정
    과목 포함) — 학부 안의 어느 전공 과목도 놓치지 않게 하려는 것이다.
    """
    query = (
        select(CourseOffering, Course, Major.name)
        .join(Course, Course.id == CourseOffering.course_id)
        .outerjoin(Major, Major.id == Course.major_id)
        .where(CourseOffering.year == year, CourseOffering.semester == semester)
    )
    program_course_conditions = None
    if department_id is not None:
        # 핀테크융합전공처럼 교육과정은 자기 학과에 있지만 실제 분반은 다른
        # 개설 주체(경영학과·컴퓨터공학전공)에 있는 경우가 있다. 과목 추가 화면도
        # ``program_courses``의 공식 교차인정 연결을 따라가야 실제로 담을 수 있다.
        # 교육과정 연도는 수강편람 학년도와 맞춘다.
        program_course_conditions = [
            ProgramCourse.department_id == department_id,
            ProgramCourse.curriculum_year == year,
        ]
    matched_major_ids = None
    if major and major.strip():
        major_query = select(Major.id).where(Major.name == major.strip())
        if department_id is not None:
            major_query = major_query.where(Major.department_id == department_id)
        matched_major_ids = list(db.scalars(major_query))
        # 같은 이름의 전공이 여러 학부에 있을 수 있어 in_으로 받는다.
        # 이름이 안 맞으면 빈 결과가 맞다 — 조건을 조용히 무시하면 엉뚱한
        # 전공 과목까지 섞여 나온다.
        # 세부전공을 선택한 경우에도, 그 프로그램이 공식 인정한 타 학과 과목은
        # 원 개설학과의 major_id가 달라도 남겨야 한다.
        if program_course_conditions is not None:
            program_course_conditions.append(ProgramCourse.major_id.in_(matched_major_ids))
        else:
            query = query.where(Course.major_id.in_(matched_major_ids))
    if department_id is not None:
        # 전공 미선택이면 학부 전체의 교차인정 과목을, 세부전공 선택이면 그
        # 세부전공 프로그램의 교차인정 과목만 합친다.
        program_course_ids = select(ProgramCourse.course_id).where(*program_course_conditions)
        query = query.where(
            or_(
                Course.department_id == department_id,
                Course.id.in_(program_course_ids),
            )
        )
        if matched_major_ids is not None:
            query = query.where(
                or_(
                    Course.major_id.in_(matched_major_ids),
                    Course.id.in_(program_course_ids),
                )
            )
    wanted = [value.strip() for value in (category or []) if value.strip()]
    if wanted:
        # 부분 일치라 "전공" 하나로 전공기초·전공필수·전공선택을 함께 훑을 수 있다.
        conditions = [Course.category.ilike(f"%{value}%") for value in wanted]
        query = query.where(or_(*conditions))
    wanted_areas = [value.strip() for value in (general_education_area or []) if value.strip()]
    if wanted_areas:
        query = query.where(Course.general_education_area.in_(wanted_areas))
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

    offering_ids = [offering.id for offering, _, _ in rows]
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
            major_name=major_name,
            general_education_area=course.general_education_area,
            times=times_by_offering.get(offering.id, []),
        )
        for offering, course, major_name in rows
    ]
