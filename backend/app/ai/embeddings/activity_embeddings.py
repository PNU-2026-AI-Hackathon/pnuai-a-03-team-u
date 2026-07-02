"""embedding이 비어있는 Activity를 찾아 OpenAI로 임베딩을 생성해 저장한다.

크롤러(app.core.scheduler)가 새 활동을 upsert한 직후에 호출되며,
title + category + description을 합쳐 하나의 텍스트로 임베딩한다.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.embeddings.openai_client import embed_texts
from app.domains.activities.models import Activity

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100


def _build_embedding_text(activity: Activity) -> str:
    parts = [activity.title]
    if activity.category:
        parts.append(activity.category)
    if activity.description:
        parts.append(activity.description)
    return " ".join(parts)


def embed_pending_activities(db: Session, batch_size: int = _BATCH_SIZE) -> int:
    """embedding이 NULL인 Activity를 모두 임베딩해 저장한다. 처리한 개수를 반환한다."""
    pending = db.scalars(
        select(Activity).where(Activity.embedding.is_(None), Activity.title != "")
    ).all()
    if not pending:
        return 0

    total = 0
    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        texts = [_build_embedding_text(a) for a in batch]
        embeddings = embed_texts(texts)
        for activity, embedding in zip(batch, embeddings):
            activity.embedding = embedding
        db.commit()
        total += len(batch)
        logger.info("activity embedding %d/%d 완료", total, len(pending))

    return total
