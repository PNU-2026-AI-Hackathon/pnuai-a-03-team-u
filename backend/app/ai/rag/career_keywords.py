from __future__ import annotations


CAREER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ai": ("인공지능", "AI", "머신러닝", "딥러닝", "데이터", "알고리즘", "확률", "통계"),
    "data": ("데이터", "통계", "분석", "머신러닝", "데이터베이스", "시각화", "빅데이터"),
    "backend": ("백엔드", "서버", "웹", "데이터베이스", "운영체제", "네트워크", "소프트웨어", "분산"),
    "security": ("보안", "암호", "네트워크", "시스템", "운영체제"),
    "bio": ("바이오", "의생명", "생명", "의료", "헬스", "데이터"),
}

CAREER_ALIASES: dict[str, tuple[str, ...]] = {
    "ai": ("ai", "인공지능", "머신러닝", "딥러닝", "ml"),
    "data": ("데이터", "분석", "data", "데이터사이언스", "scientist"),
    "backend": ("백엔드", "backend", "서버", "웹"),
    "security": ("보안", "security", "해킹"),
    "bio": ("바이오", "의생명", "bio", "헬스"),
}


def career_alias_groups(query: str) -> tuple[str, ...]:
    """진로 문구가 걸리는 알려진 진로군 키들. 하나도 안 걸리면 빈 튜플.

    `expand_career_query`는 매칭 실패 시 원문 토큰으로 폴백하지만, 이 함수는 폴백하지
    않는다 — 호출부가 "우리가 아는 진로군인가"를 판정 근거로 삼기 때문이다. 빈 튜플은
    "이 진로에 대해 우리가 아는 게 없다"는 뜻이고, 그때는 진로 기반 판단을 하면 안 된다.
    """
    normalized = query.lower()
    return tuple(
        key for key, aliases in CAREER_ALIASES.items()
        if any(alias.lower() in normalized for alias in aliases)
    )


def expand_career_query(query: str) -> tuple[str, ...]:
    normalized = query.lower()
    selected: list[str] = []
    for key, aliases in CAREER_ALIASES.items():
        if any(alias.lower() in normalized for alias in aliases):
            selected.extend(CAREER_KEYWORDS[key])
    selected.extend(term.strip() for term in query.replace("/", " ").split() if term.strip())
    return tuple(dict.fromkeys(selected))
