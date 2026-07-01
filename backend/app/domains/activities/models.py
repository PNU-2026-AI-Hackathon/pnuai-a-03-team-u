"""비교과 활동 도메인 모델.

공지사항 크롤러(ingestion/crawlers/notice_board_crawler.py)가 수집한
raw NoticeRow를 normalizer가 이 모델로 변환해 저장한다.

추천 순위는 pgvector 임베딩 유사도 + 사용자 프로필 가중치로 계산하며,
Activity.embedding 컬럼에 미리 계산된 임베딩을 저장한다.
"""

from __future__ import annotations

import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Date, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

EMBEDDING_DIM = 1536  # text-embedding-3-small 기준


class Activity(TimestampMixin, Base):
    """크롤링된 비교과 활동 공고."""

    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)

    # 출처 식별
    source: Mapped[str] = mapped_column(String(50), index=True)  # swedu/uitc/job/lib/...
    source_url: Mapped[str] = mapped_column(String(500))

    # 공고 내용
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)  # 상세 본문 (나중에 추가 크롤링)
    author: Mapped[str | None] = mapped_column(String(100))
    posted_date: Mapped[datetime.date | None] = mapped_column(Date, index=True)
    deadline: Mapped[datetime.date | None] = mapped_column(Date, index=True)  # 마감일 (본문 파싱)

    # 분류 태그 (예: 공모전/인턴십/교내활동/비교과/스터디 등)
    category: Mapped[str | None] = mapped_column(String(100), index=True)

    # 임베딩 (title + description 합쳐서 생성)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    # 크롤 메타
    is_pinned: Mapped[bool] = mapped_column(default=False)
    views: Mapped[int | None] = mapped_column()

    __table_args__ = (
        # 같은 출처의 동일 URL은 중복 저장하지 않는다
        UniqueConstraint("source", "source_url", name="uq_activity_source_url"),
        # 임베딩 유사도 검색용 IVFFlat 인덱스 (데이터가 쌓이면 CONCURRENTLY로 생성 권장)
        Index("ix_activities_embedding", "embedding", postgresql_using="ivfflat",
              postgresql_with={"lists": 100}, postgresql_ops={"embedding": "vector_cosine_ops"}),
    )


class UserActivityRecommendation(TimestampMixin, Base):
    """사용자별 활동 추천 결과 캐시.

    매 요청마다 벡터 검색을 반복하지 않도록 추천 점수를 저장해두고,
    스케줄러가 주기적으로 갱신한다.
    """

    __tablename__ = "user_activity_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(index=True)
    activity_id: Mapped[int] = mapped_column(index=True)

    # 점수 구성
    similarity_score: Mapped[float | None] = mapped_column()   # 임베딩 코사인 유사도
    career_weight: Mapped[float | None] = mapped_column()      # career_goal 가중치
    recency_weight: Mapped[float | None] = mapped_column()     # 최신성 가중치
    final_score: Mapped[float | None] = mapped_column(index=True)  # 최종 정렬 점수

    computed_at: Mapped[datetime.datetime | None] = mapped_column()

    __table_args__ = (
        UniqueConstraint("user_id", "activity_id", name="uq_user_activity_rec"),
    )
