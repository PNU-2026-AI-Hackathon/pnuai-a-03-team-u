"""my.pusan.ac.kr 크롤러 결과를 UserActivity 도메인 모델로 매핑한다.

fetch_extracurricular_certificate가 돌려주는 dict의 programs[] 각 원소는
_HEADER_ALIASES로 정규 필드에 매핑된 값들이다. 여기서 UserActivity 컬럼에 맞게
날짜 파싱·기본값 세팅 후 idempotent upsert한다.

Idempotency 키는 (user_id, title, start_date, end_date) 조합. 크롤링 페이지에는
프로그램 고유 id가 표에 노출되지 않아서, 사람이 봐서 같은 이수 이력이면 같은 키가
되는 조합을 쓴다.
"""

from __future__ import annotations

import datetime
import re

from sqlalchemy.orm import Session

from app.domains.users.models import UserActivity


_DATE_RE = re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})")


def _parse_date(text: str | None) -> datetime.date | None:
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return v[:limit] if len(v) > limit else v


def upsert_extracurricular_activities(
    db: Session, user_id: int, programs: list[dict]
) -> tuple[int, int]:
    """이수 프로그램 목록을 UserActivity로 upsert. (created, updated) 반환."""
    created = updated = 0
    for row in programs:
        title = _clip(row.get("title"), 255)
        if not title:
            continue  # 제목 없는 행은 무시 (합계 행 등)
        start_date = _parse_date(row.get("start_date"))
        end_date = _parse_date(row.get("end_date"))
        # extra 필드에 이수시간/이수학점이 있으면 description에 요약해서 담아둔다
        # (UserActivity에 별도 시간/학점 컬럼이 없어 손실 없이 저장하기 위함).
        extra = row.get("_extra") or {}
        summary_bits: list[str] = []
        for k in ("hours", "credits"):
            v = row.get(k)
            if v:
                summary_bits.append(f"{k}={v}")
        for label, value in extra.items():
            if value:
                summary_bits.append(f"{label}={value}")
        description = "; ".join(summary_bits) if summary_bits else None

        existing = (
            db.query(UserActivity)
            .filter(
                UserActivity.user_id == user_id,
                UserActivity.title == title,
                UserActivity.start_date == start_date,
                UserActivity.end_date == end_date,
            )
            .one_or_none()
        )
        values = {
            "organization": _clip(row.get("organization"), 255),
            "category": _clip(row.get("category"), 100),
            "role": _clip(row.get("role"), 100),
            "award": _clip(row.get("award"), 100),
            "description": _clip(description, 2000),
        }
        if existing is None:
            db.add(UserActivity(
                user_id=user_id, title=title, start_date=start_date, end_date=end_date,
                **values,
            ))
            created += 1
        else:
            changed = False
            for k, v in values.items():
                if getattr(existing, k) != v:
                    setattr(existing, k, v)
                    changed = True
            if changed:
                updated += 1
    db.commit()
    return created, updated
