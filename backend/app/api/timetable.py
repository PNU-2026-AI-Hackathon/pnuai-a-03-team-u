"""로드맵의 특정 학기에 대해 실제 개설 분반을 조합해 시간표를 추천한다.

이 엔드포인트는 결정론적 로직만 사용한다 — LLM을 태우지 않는다. 로드맵 자체를
변경하지도 않는다. 미개설/충돌로 시간표를 못 짜는 경우 대체 후보를 함께 반환하고,
실제 로드맵 변경은 기존 `/me/roadmaps/{id}/agent` 채팅 흐름에서 처리한다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.planning.models import CourseRoadmap
from app.domains.planning.timetable import recommend_timetable
from app.domains.users.models import User

router = APIRouter(prefix="/me/roadmaps/{roadmap_id}/timetable", tags=["timetable"])


@router.get("/recommend")
def recommend(
    roadmap_id: int,
    year: str = Query(..., description="달력 연도 (예: '2026')"),
    semester: str = Query(..., description="학기 표기 (예: '2학기')"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    roadmap = db.get(CourseRoadmap, roadmap_id)
    if roadmap is None or roadmap.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="로드맵을 찾을 수 없습니다")
    return recommend_timetable(db, current_user, roadmap, year=year, semester=semester)
