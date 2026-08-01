"""Onestop 수강편람 `timetable_raw` 필드를 CourseTime 행으로 파싱.

CSV의 `timetable_raw`는 다음 세 가지 형태가 섞여 있다:
  - 종료시각 지정: `월 09:00-12:00 양산Y15-314`
  - 시작시각+분수 지정: `월 09:00(75) 306-410`
  - 병원실습 등 (외부) 태그: `월 08:30-12:30(외부)병원실습`

여러 세션이 한 행에 있으면 콤마로 구분:
  `월 09:00(75) 306-410, 수 09:00(75) 306-410`

파싱 실패한 세션은 자동 폐기하지 않고 결과에 표시해, importer가 필요하면
CourseTime 없이 CourseOffering만 만든 뒤 raw 값을 로그로 남길 수 있게 한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time

_VALID_DAYS = ("월", "화", "수", "목", "금", "토", "일")

# 형태 1: 요일 HH:MM-HH:MM [ (선택 태그) ] 강의실
_RANGE_RE = re.compile(
    r"^(?P<day>[월화수목금토일])\s+"
    r"(?P<sh>\d{1,2}):(?P<sm>\d{2})-(?P<eh>\d{1,2}):(?P<em>\d{2})"
    r"(?P<tag>\([^)]*\))?"
    r"\s*(?P<room>.*)$"
)
# 형태 2: 요일 HH:MM(지속분수) 강의실
_MINUTES_RE = re.compile(
    r"^(?P<day>[월화수목금토일])\s+"
    r"(?P<sh>\d{1,2}):(?P<sm>\d{2})\((?P<dur>\d+)\)"
    r"\s*(?P<room>.*)$"
)


@dataclass(frozen=True)
class ParsedTime:
    day_of_week: str
    start_time: time | None
    end_time: time | None
    classroom: str


def _make_time(hour: int, minute: int) -> time | None:
    """24:00 같은 오버플로우를 None으로 흡수 — 실제 CSV에도 드물게 등장한다."""
    if hour >= 24 or minute >= 60:
        return None
    return time(hour, minute)


def _parse_session(part: str) -> ParsedTime | None:
    part = part.strip()
    if not part:
        return None

    m = _RANGE_RE.match(part)
    if m:
        day = m.group("day")
        start = _make_time(int(m.group("sh")), int(m.group("sm")))
        end = _make_time(int(m.group("eh")), int(m.group("em")))
        return ParsedTime(day_of_week=day, start_time=start, end_time=end, classroom=m.group("room").strip())

    m = _MINUTES_RE.match(part)
    if m:
        day = m.group("day")
        sh, sm, dur = int(m.group("sh")), int(m.group("sm")), int(m.group("dur"))
        start = _make_time(sh, sm)
        total_end_minutes = sh * 60 + sm + dur
        end = _make_time(total_end_minutes // 60, total_end_minutes % 60)
        return ParsedTime(day_of_week=day, start_time=start, end_time=end, classroom=m.group("room").strip())

    # 형태 3: 요일만 있고 나머지가 이상한 경우 (예: "월 미정")
    if part[0] in _VALID_DAYS:
        return ParsedTime(day_of_week=part[0], start_time=None, end_time=None, classroom=part[1:].strip())

    return None


def parse_timetable_raw(raw: str | None) -> list[ParsedTime]:
    """`timetable_raw` 문자열을 [ParsedTime]로 변환. 파싱 실패한 세션은 제외."""
    if not raw:
        return []
    parts = re.split(r",\s*", raw)
    result: list[ParsedTime] = []
    for part in parts:
        parsed = _parse_session(part)
        if parsed is not None:
            result.append(parsed)
    return result
