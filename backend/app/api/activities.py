"""사용자별 비교과 활동 추천 그리드 API.

인증 시스템이 아직 없어 user_id를 경로 파라미터로 받는다.
로그인 붙으면 get_current_user 의존성으로 교체 예정.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.recommendations.extracurricular_recommender import recommend_for_user
from app.core.db import get_db
from app.domains.activities.models import Activity, UserActivityRecommendation
from app.domains.users.models import User

router = APIRouter(prefix="/activities", tags=["activities"])


class RecommendedActivity(BaseModel):
    activity_id: int
    title: str
    category: str | None
    source: str
    source_url: str
    posted_date: datetime.date | None
    deadline: datetime.date | None
    d_day: int | None
    recommendation_score: float  # 0~100 사이 퍼센트


def _to_d_day(deadline: datetime.date | None) -> int | None:
    if deadline is None:
        return None
    return (deadline - datetime.date.today()).days


@router.get("/recommendations/{user_id}", response_model=list[RecommendedActivity])
def get_recommendations(user_id: int, limit: int = 20, db: Session = Depends(get_db)):
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="존재하지 않는 user_id입니다")

    rows = db.execute(
        select(UserActivityRecommendation, Activity)
        .join(Activity, Activity.id == UserActivityRecommendation.activity_id)
        .where(UserActivityRecommendation.user_id == user_id)
        .order_by(UserActivityRecommendation.final_score.desc())
        .limit(limit)
    ).all()

    if not rows:
        recommend_for_user(db, user_id)
        rows = db.execute(
            select(UserActivityRecommendation, Activity)
            .join(Activity, Activity.id == UserActivityRecommendation.activity_id)
            .where(UserActivityRecommendation.user_id == user_id)
            .order_by(UserActivityRecommendation.final_score.desc())
            .limit(limit)
        ).all()

    if not rows:
        raise HTTPException(status_code=404, detail="추천 결과가 없습니다")

    return [
        RecommendedActivity(
            activity_id=activity.id,
            title=activity.title,
            category=activity.category,
            source=activity.source,
            source_url=activity.source_url,
            posted_date=activity.posted_date,
            deadline=activity.deadline,
            d_day=_to_d_day(activity.deadline),
            recommendation_score=round(min(max(rec.final_score or 0.0, 0.0), 1.0) * 100, 1),
        )
        for rec, activity in rows
    ]
