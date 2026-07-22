"""my.pusan.ac.kr certificate 크롤러 결과를 각 도메인 모델로 upsert한다.

세 유형(비교과활동/자격증/어학성적)을 각각 UserActivity / UserCertification /
UserLanguageScore로 매핑한다. Idempotency 키는 각 테이블별로 사람 눈에 같은 이수
이력이면 같은 키가 되는 조합을 쓴다(원본에 고유 id가 표에 안 노출되어서).
"""

from __future__ import annotations

import datetime
import re

from sqlalchemy.orm import Session

from app.domains.users.models import UserActivity, UserCertification, UserLanguageScore

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


def _extra_summary(row: dict, keys: tuple[str, ...] = ()) -> str | None:
    """정규 필드에 못 담긴 값들을 description 스타일로 요약. label=value 세미콜론 join."""
    bits: list[str] = []
    for k in keys:
        v = row.get(k)
        if v:
            bits.append(f"{k}={v}")
    for label, value in (row.get("_extra") or {}).items():
        if value:
            bits.append(f"{label}={value}")
    return "; ".join(bits) if bits else None


def upsert_extracurricular_activities(
    db: Session, user_id: int, rows: list[dict]
) -> tuple[int, int]:
    created = updated = 0
    for row in rows:
        title = _clip(row.get("title"), 255)
        if not title:
            continue
        start_date = _parse_date(row.get("start_date"))
        end_date = _parse_date(row.get("end_date"))
        description = _extra_summary(row, ("hours", "credits"))
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


def upsert_certifications(db: Session, user_id: int, rows: list[dict]) -> tuple[int, int]:
    """UserCertification은 필드가 name과 expires_at뿐이라 부가 정보(발급기관/취득일/등급)는
    표시용으로 name에 요약해서 붙인다(스키마 확장 없이 손실 없이 저장).
    Idempotency 키는 (user_id, 이름 원문+발급기관) 조합.
    """
    created = updated = 0
    for row in rows:
        base_name = _clip(row.get("name"), 200)
        if not base_name:
            continue
        issuer = _clip(row.get("issuer"), 100)
        issued_at = _parse_date(row.get("issued_at"))
        expires_at = _parse_date(row.get("expires_at"))
        # 표시 이름에 발급기관을 병기하면 idempotency 키가 자연스러워진다
        # (예: "정보처리기사 (한국산업인력공단)"). issuer가 없으면 base_name 그대로.
        display_name = _clip(f"{base_name} ({issuer})", 255) if issuer else base_name
        # 부가 정보(취득일/등급 등)는 뒤에 요약으로 붙인다.
        extras = _extra_summary(row, ("grade_or_number",))
        if issued_at:
            extras = ("; " if extras else "") .join(filter(None, [extras, f"issued_at={issued_at.isoformat()}"]))
        # UserCertification.name은 String(255)이라 truncate.
        full_name = _clip(f"{display_name} [{extras}]" if extras else display_name, 255)

        existing = (
            db.query(UserCertification)
            .filter(UserCertification.user_id == user_id, UserCertification.name == full_name)
            .one_or_none()
        )
        if existing is None:
            db.add(UserCertification(user_id=user_id, name=full_name, expires_at=expires_at))
            created += 1
        else:
            if existing.expires_at != expires_at:
                existing.expires_at = expires_at
                updated += 1
    db.commit()
    return created, updated


def upsert_language_scores(db: Session, user_id: int, rows: list[dict]) -> tuple[int, int]:
    """UserLanguageScore는 (test_name, score, expires_at)만 있다.
    Idempotency 키는 (user_id, test_name, score) — 같은 시험 같은 점수면 동일 이력.
    """
    created = updated = 0
    for row in rows:
        test_name = _clip(row.get("test_name"), 100)
        score = _clip(row.get("score"), 50)
        if not test_name or not score:
            continue
        expires_at = _parse_date(row.get("expires_at"))
        existing = (
            db.query(UserLanguageScore)
            .filter(
                UserLanguageScore.user_id == user_id,
                UserLanguageScore.test_name == test_name,
                UserLanguageScore.score == score,
            )
            .one_or_none()
        )
        if existing is None:
            db.add(UserLanguageScore(
                user_id=user_id, test_name=test_name, score=score, expires_at=expires_at,
            ))
            created += 1
        else:
            if existing.expires_at != expires_at:
                existing.expires_at = expires_at
                updated += 1
    db.commit()
    return created, updated
