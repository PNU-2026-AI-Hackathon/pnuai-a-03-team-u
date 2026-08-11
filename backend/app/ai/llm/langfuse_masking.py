"""Langfuse trace 페이로드에서 개인정보를 지우는 마스킹 훅.

`docs/backend/features/llm-privacy-audit.md`에서 정한 4개 패턴을 적용한다.
학과·과목·성적 같은 quasi-identifier는 그대로 통과 — 개선 분석에 필수라
마스킹 대상이 아님. 접근 통제(Langfuse 프로젝트 seat)로 커버한다.
"""

from __future__ import annotations

import re
from typing import Any

# 각 패턴은 앞뒤에 다른 digit이 붙는 경우만 배제한다.
# `\b` 워드 바운더리는 파이썬 `\w`가 한글을 포함하기 때문에 "202112345인데요"
# 같이 한글이 붙으면 매칭이 깨진다 — 대신 `(?<!\d)` / `(?!\d)`로 digit-only
# 바운더리를 쓴다. 한글·공백·기호 뒤에서는 정상 매칭된다.

# 학번: 연도 앵커(1990~2029)로 좁혀서 dept_id/course_id 같은 랜덤 정수 오탐 방지.
# 앞 4자리 연도 + 뒤 4~6자리(학과·순번).
_STUDENT_ID = re.compile(r"(?<!\d)(?:19|20)\d{2}\d{4,6}(?!\d)")
_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_MOBILE = re.compile(r"(?<!\d)01[0-9]-?\d{3,4}-?\d{4}(?!\d)")
# 유선 지역번호: 서울(02) + 3~5단위 지역 (031~064 대역).
_LANDLINE = re.compile(r"(?<!\d)0(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4])-?\d{3,4}-?\d{4}(?!\d)")


def redact_text(s: str) -> str:
    """문자열 하나에 4개 패턴을 순차 적용."""
    if not s:
        return s
    s = _EMAIL.sub("<EMAIL>", s)
    s = _MOBILE.sub("<PHONE>", s)
    s = _LANDLINE.sub("<PHONE>", s)
    # 학번은 이메일/전화 뒤에 처리해야 이메일 로컬파트 안 숫자 오탐이 안 남는다
    # (실제로는 이메일이 이미 <EMAIL>로 치환된 뒤라 학번 패턴이 안 걸리지만
    # 명시적으로 순서를 지킨다).
    s = _STUDENT_ID.sub("<STUDENT_ID>", s)
    return s


def mask_data(data: Any) -> Any:
    """Langfuse client `mask=` 훅으로 넘길 재귀 마스킹 함수.

    dict/list/tuple을 재귀적으로 훑어 문자열 리프에만 redact_text를 적용한다.
    Langfuse가 trace input/output(HumanMessage content 포함)에 이 훅을 적용해
    Cloud로 나가기 전에 값을 바꾼다. 원본 LLM 호출에는 영향 없음.
    """
    if isinstance(data, str):
        return redact_text(data)
    if isinstance(data, dict):
        return {k: mask_data(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        masked = [mask_data(v) for v in data]
        return type(data)(masked) if isinstance(data, tuple) else masked
    return data
