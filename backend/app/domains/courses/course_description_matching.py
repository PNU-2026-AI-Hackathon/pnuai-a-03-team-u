"""과목명 정규화 — course_descriptions <-> courses 매칭용 (scripts/import_course_descriptions.py,
scripts/sync_course_descriptions_to_courses.py에서 사용).

이름이 완전히 같을 때만 매칭시킨다는 전제이므로, 여기서 하는 정규화는
"공백/표기 차이" 수준만 흡수하고 의미 추론은 하지 않는다 (예: "일반물리학Ⅰ"과
"일반물리학1"은 여기선 다르게 정규화되면 그냥 매칭 실패로 남는다 — 잘못 붙는 것보다
안전).
"""
from __future__ import annotations

import re
import unicodedata

_ROMAN_TO_ASCII = str.maketrans({
    "Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V", "Ⅵ": "VI",
})


def normalize_course_name(name: str) -> str:
    name = unicodedata.normalize("NFC", name or "")
    name = name.translate(_ROMAN_TO_ASCII)
    name = re.sub(r"\s+", "", name)
    return name


def _top_level_paren_groups(text: str) -> tuple[str, list[str]]:
    """text를 (첫 '(' 앞부분, 최상위 괄호 그룹 문자열 리스트)로 나눈다. 중첩 괄호 지원."""
    depth = 0
    head_end: int | None = None
    start: int | None = None
    groups: list[str] = []
    for i, ch in enumerate(text):
        if ch == "(":
            if depth == 0:
                if head_end is None:
                    head_end = i
                start = i
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
            if depth == 0 and start is not None:
                groups.append(text[start : i + 1])
                start = None
    head = text[:head_end] if head_end is not None else text
    return head, groups


_SEQUENCE_MARKER = re.compile(r"^\(([IVXⅠ-Ⅵ]{1,4}|\d{1,2})\)$")


def strip_korean_name(raw_title: str) -> str:
    """"일반물리학(I)(General Physics(I))" 같은 원문 표제에서 국문 과목명(+순번)만 뽑는다.

    "(I)"/"(II)" 같은 순번 괄호는 실제 courses.course_name에도 그대로 붙어있는
    과목 식별의 일부라(예: "일반물리학(I)"과 "일반물리학(II)"는 DB에도 별개 과목으로
    존재) 버리면 안 된다 — 순번 괄호는 이름에 남기고, 그 뒤에 오는 영문명 괄호부터만
    버린다.
    """
    raw_title = unicodedata.normalize("NFC", raw_title or "").strip()
    head, groups = _top_level_paren_groups(raw_title)
    name = head.strip()
    for group in groups:
        if _SEQUENCE_MARKER.match(group):
            name += group
        else:
            break
    return name
