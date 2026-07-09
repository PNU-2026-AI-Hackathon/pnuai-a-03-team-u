"""과목 검색(자동완성). 로드맵/시간표 화면에서 과목을 직접 입력할 때 쓴다.

사용자가 과목명을 자유롭게 타이핑해서 그대로 저장하게 두면 오타/부정확한
이름이 그대로 DB에 들어간다. 그래서 저장은 항상 이 검색 결과에서 고른
course_id를 통해서만 이뤄지게 하고(roadmaps.py의 아이템 생성 참고),
프론트는 자동완성 목록에서 클릭해야만 입력칸이 채워지게 만든다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.courses.models import Course
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
