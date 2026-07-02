"""사용자 프로필(전공/진로) 임베딩과 Activity 임베딩의 코사인 유사도를 기반으로
비교과 활동 추천 점수를 계산해 UserActivityRecommendation에 저장한다.

최종 점수 = similarity_score * career_weight * recency_weight
- career_weight: career_goal이 있으면 유사도를 더 크게 반영(1.2배), 없으면 1.0
- recency_weight: 게시일이 최근일수록 1.0에 가깝고, 90일에 가까울수록 0.5로 감쇠
"""

from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.embeddings.openai_client import embed_text
from app.domains.academics.models import UserAcademicProgram
from app.domains.activities.models import Activity, UserActivityRecommendation
from app.domains.users.models import User

_LOOKBACK_DAYS = 90
_TOP_K = 50
_NO_CAREER_GOAL_WEIGHT = 1.0
_HAS_CAREER_GOAL_WEIGHT = 1.2


def _build_profile_text(user: User, majors: list[str]) -> str | None:
    parts = [p for p in [user.department, *majors, user.career_goal] if p]
    if not parts:
        return None
    return " ".join(parts)


def _recency_weight(posted_date: datetime.date | None) -> float:
    if posted_date is None:
        return 0.5
    age_days = (datetime.date.today() - posted_date).days
    if age_days <= 0:
        return 1.0
    if age_days >= _LOOKBACK_DAYS:
        return 0.5
    return 1.0 - 0.5 * (age_days / _LOOKBACK_DAYS)


def recommend_for_user(db: Session, user_id: int, top_k: int = _TOP_K) -> list[UserActivityRecommendation]:
    """사용자 한 명에 대한 추천을 계산하고 upsert 후 결과를 반환한다."""
    user = db.get(User, user_id)
    if user is None:
        raise ValueError(f"user {user_id} not found")

    majors = list(
        db.scalars(
            select(UserAcademicProgram.major).where(
                UserAcademicProgram.user_id == user_id,
                UserAcademicProgram.major.is_not(None),
            )
        )
    )
    profile_text = _build_profile_text(user, majors)
    if profile_text is None:
        return []

    profile_embedding = embed_text(profile_text)
    career_weight = _HAS_CAREER_GOAL_WEIGHT if user.career_goal else _NO_CAREER_GOAL_WEIGHT

    cutoff = datetime.date.today() - datetime.timedelta(days=_LOOKBACK_DAYS)
    similarity = (1 - Activity.embedding.cosine_distance(profile_embedding)).label("similarity_score")
    rows = db.execute(
        select(Activity, similarity)
        .where(Activity.embedding.is_not(None))
        .where((Activity.deadline.is_(None)) | (Activity.deadline >= datetime.date.today()))
        .where((Activity.posted_date.is_(None)) | (Activity.posted_date >= cutoff))
        .order_by(similarity.desc())
        .limit(top_k)
    ).all()

    now = datetime.datetime.now(datetime.UTC)
    recommendations = []
    for activity, similarity_score in rows:
        recency_weight = _recency_weight(activity.posted_date)
        final_score = similarity_score * career_weight * recency_weight

        rec = db.scalar(
            select(UserActivityRecommendation).where(
                UserActivityRecommendation.user_id == user_id,
                UserActivityRecommendation.activity_id == activity.id,
            )
        )
        if rec is None:
            rec = UserActivityRecommendation(user_id=user_id, activity_id=activity.id)
            db.add(rec)

        rec.similarity_score = similarity_score
        rec.career_weight = career_weight
        rec.recency_weight = recency_weight
        rec.final_score = final_score
        rec.computed_at = now
        recommendations.append(rec)

    db.commit()
    return recommendations


def recommend_for_all_users(db: Session, top_k: int = _TOP_K) -> int:
    """모든 사용자에 대해 추천을 재계산한다. 처리한 사용자 수를 반환한다."""
    user_ids = list(db.scalars(select(User.id)))
    for user_id in user_ids:
        recommend_for_user(db, user_id, top_k=top_k)
    return len(user_ids)
