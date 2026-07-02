"""사용자 프로필(전공/진로) 임베딩과 Activity 임베딩의 코사인 유사도를 기반으로
비교과 활동 추천 점수를 계산해 UserActivityRecommendation에 저장한다.

최종 점수 = similarity_score * career_weight * recency_weight
- career_weight: career_goal이 있으면 유사도를 더 크게 반영(1.2배), 없으면 1.0
- recency_weight: 게시일 기준 지수 감쇠(반감기 30일) — 최신 공지가 확실히 위로 오도록 함

신청 기간이 끝난 공지 필터링:
- 마감일이 파싱된 공지(전체의 약 11%)는 마감일 지난 것을 정확히 제외
- 마감일이 파싱되지 않은 나머지는 제목에 마감일 표기가 없거나 파싱 실패한 경우인데,
  이런 공지 대부분은 신청 기간이 길어야 한두 달이므로 게시일이 45일(_NO_DEADLINE_ACTIVE_DAYS)
  넘은 것은 마감으로 간주해 제외한다.
"""

from __future__ import annotations

import datetime
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.embeddings.openai_client import _get_client, embed_text
from app.domains.academics.models import UserAcademicProgram
from app.domains.activities.models import Activity, UserActivityRecommendation
from app.domains.users.models import User

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 90
_TOP_K = 50
_NO_CAREER_GOAL_WEIGHT = 1.0
_HAS_CAREER_GOAL_WEIGHT = 1.2

# 마감일이 파싱되지 않은 공지는 게시일이 이만큼 지나면 신청 기간이 끝났다고 보고 제외
_NO_DEADLINE_ACTIVE_DAYS = 45
# recency_weight 지수 감쇠 반감기: 게시 후 이 기간이 지날 때마다 가중치가 절반이 됨
_RECENCY_HALF_LIFE_DAYS = 30
_MIN_RECENCY_WEIGHT = 0.1

_EXPANSION_MODEL = "gpt-4o-mini"

# 프로필 텍스트("행정학과 행정직 공무원")만으로는 임베딩이 진로 분야보다
# "채용/모집"이라는 공지 형식에 끌리는 문제가 있어(오프라인 평가에서 확인),
# 임베딩 전에 관련 키워드로 확장한다(query expansion).
_EXPANSION_PROMPT = """대학생의 전공/진로 프로필입니다:
{profile}

이 학생에게 관련 있는 교내 공지(공모전, 채용, 교육, 특강, 장학금 등)를
임베딩 검색으로 찾으려 합니다. 검색 품질을 높이도록 이 프로필과 직접 관련된
구체적 키워드 15~20개를 한국어로 나열하세요. 진로 분야의 시험/자격증/기관명/
직무명/활동 유형을 포함하되, 모든 전공에 통하는 범용 단어(채용, 모집, 취업 등)는
제외하세요. 쉼표로 구분해 키워드만 출력하세요."""

# 같은 프로필은 프로세스 내에서 한 번만 확장한다 (자정 배치 중 반복 호출 방지)
_expansion_cache: dict[str, str] = {}


def _expand_profile_text(profile_text: str) -> str:
    """프로필을 진로 분야 키워드로 확장한다. 실패하면 원문을 그대로 쓴다."""
    if profile_text in _expansion_cache:
        return _expansion_cache[profile_text]
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=_EXPANSION_MODEL,
            messages=[
                {"role": "user", "content": _EXPANSION_PROMPT.format(profile=profile_text)}
            ],
            temperature=0,
        )
        keywords = response.choices[0].message.content.strip()
        expanded = f"{profile_text} {keywords}"
    except Exception:
        logger.exception("profile expansion failed, falling back to raw profile")
        expanded = profile_text
    _expansion_cache[profile_text] = expanded
    return expanded


def _profile_embedding(profile_text: str) -> list[float]:
    """원본 프로필과 확장 프로필의 임베딩을 평균해 사용한다.

    확장 임베딩만 쓰면 코퍼스에 해당 분야 공지가 거의 없는 경우(예: 화학)
    상위권 유사도가 전부 낮아져 순위가 노이즈가 되는 문제가 오프라인 평가에서
    확인됐다. 원본 임베딩을 절반 섞어 안전망으로 삼는다.
    """
    from app.ai.embeddings.openai_client import embed_texts

    expanded = _expand_profile_text(profile_text)
    if expanded == profile_text:
        return embed_text(profile_text)
    original_vec, expanded_vec = embed_texts([profile_text, expanded])
    return [(o + e) / 2 for o, e in zip(original_vec, expanded_vec)]


def _build_profile_text(user: User, majors: list[str]) -> str | None:
    parts = [p for p in [user.department, *majors, user.career_goal] if p]
    if not parts:
        return None
    return " ".join(parts)


def _recency_weight(posted_date: datetime.date | None) -> float:
    if posted_date is None:
        return _MIN_RECENCY_WEIGHT
    age_days = (datetime.date.today() - posted_date).days
    if age_days <= 0:
        return 1.0
    weight = 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)
    return max(weight, _MIN_RECENCY_WEIGHT)


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

    profile_embedding = _profile_embedding(profile_text)
    career_weight = _HAS_CAREER_GOAL_WEIGHT if user.career_goal else _NO_CAREER_GOAL_WEIGHT

    today = datetime.date.today()
    lookback_cutoff = today - datetime.timedelta(days=_LOOKBACK_DAYS)
    no_deadline_cutoff = today - datetime.timedelta(days=_NO_DEADLINE_ACTIVE_DAYS)
    similarity = (1 - Activity.embedding.cosine_distance(profile_embedding)).label("similarity_score")
    rows = db.execute(
        select(Activity, similarity)
        .where(Activity.embedding.is_not(None))
        .where((Activity.posted_date.is_(None)) | (Activity.posted_date >= lookback_cutoff))
        .where(
            # 마감일이 있으면 안 지난 것만, 없으면 게시일이 너무 오래되지 않은 것만
            (Activity.deadline.is_not(None) & (Activity.deadline >= today))
            | (
                Activity.deadline.is_(None)
                & ((Activity.posted_date.is_(None)) | (Activity.posted_date >= no_deadline_cutoff))
            )
        )
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
