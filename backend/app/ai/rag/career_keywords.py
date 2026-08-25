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
    """진로 문구를 매칭용 토큰으로 쪼갠다.

    예전엔 `CAREER_ALIASES`에 걸리면 그 진로군의 고정 키워드 목록(`CAREER_KEYWORDS`)을
    덧붙였다 — 하지만 이 5개 진로군(ai/data/backend/security/bio)은 실제 학생들이
    입력하는 진로 문구의 극히 일부만 커버하고("시스템 프로그래머"조차 안 걸림,
    2026-08-25 실측), 걸렸을 때도 진로군 전체 키워드를 더하는 게 오히려 무관한
    과목에 우연히 걸리는 노이즈를 늘렸다(`hits/len(terms)` 분모만 커지고 실제
    관련성 신호는 안 늘어남). 지금은 원문 토큰만 쓴다 — 과목 설명(`_course_evidence`)이
    실제 강의계획서 원문(교수목표/강의개요)이라 원문 토큰만으로도 직접 매칭된다.
    """
    return tuple(dict.fromkeys(term.strip() for term in query.replace("/", " ").split() if term.strip()))
