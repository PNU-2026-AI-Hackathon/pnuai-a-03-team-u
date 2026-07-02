"""OpenAI 임베딩 API 얇은 래퍼.

text-embedding-3-small은 1536차원을 반환하며,
Activity.embedding / 사용자 프로필 벡터 계산 모두 이 함수를 공유한다.
"""

from __future__ import annotations

from openai import OpenAI

from app.core.config import settings

EMBEDDING_MODEL = "text-embedding-3-small"

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다 (.env 확인)")
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def embed_texts(texts: list[str]) -> list[list[float]]:
    """여러 텍스트를 한 번의 API 호출로 임베딩한다. 빈 문자열은 건너뛰고 자리에 None을 채운다."""
    if not texts:
        return []
    client = _get_client()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
