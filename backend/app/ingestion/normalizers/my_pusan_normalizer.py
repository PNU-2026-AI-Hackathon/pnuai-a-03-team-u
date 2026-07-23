"""my.pusan.ac.kr certificate 크롤 결과를 UserActivity/UserCertification/
UserLanguageScore로 idempotent upsert.

크롤러 스키마(2026-07-23 실제 마크업 반영):
  activity dict:
    { data_name, heading, category, title, sub_type, raw_date, institution,
      role, contents, score_hint, sub_category }
  certification dict:
    { name, issued_at, certificate_no, issuer }
  language dict:
    { test_name, score, issued_at }
"""

from __future__ import annotations

import datetime
import re

from sqlalchemy.orm import Session

from app.domains.users.models import UserActivity, UserCertification, UserLanguageScore

_DATE_RE = re.compile(r"(\d{4})[.\-/](\d{1,2})(?:[.\-/](\d{1,2}))?")


def _parse_date(text: str | None) -> datetime.date | None:
    """YYYY-MM-DD, YYYY.MM.DD, YYYY/MM/DD, YYYY-MM 형식과 뒤에 붙는 요일 접미사
    "(금)" 등을 흡수한다. 날짜만 있으면 그 값을, 연-월만 있으면 그 달 1일로."""
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    try:
        year = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3)) if m.group(3) else 1
        return datetime.date(year, month, day)
    except ValueError:
        return None


def _parse_date_range(text: str | None) -> tuple[datetime.date | None, datetime.date | None]:
    """활동기간 문자열에서 시작·종료일을 뽑는다. 하나만 있으면 (start, None).
    예: "2024-03 ~ 2025-02" → (2024-03-01, 2025-02-01)
    """
    if not text:
        return None, None
    matches = list(_DATE_RE.finditer(text))
    if not matches:
        return None, None
    start = _parse_date(matches[0].group(0))
    end = _parse_date(matches[1].group(0)) if len(matches) > 1 else None
    return start, end


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    v = str(value).strip()
    return v[:limit] if len(v) > limit else v


def upsert_extracurricular_activities(
    db: Session, user_id: int, rows: list[dict]
) -> tuple[int, int]:
    """활동 6개 섹션(eco/award/performance/group/volunteer/etc)을 UserActivity로 통합 upsert.
    Idempotency 키: (user_id, title, category, start_date). 사람이 봐서 같은 이력이면 같은 키.
    """
    created = updated = 0
    for row in rows:
        title = _clip(row.get("title"), 255)
        if not title:
            continue
        category = _clip(row.get("category"), 100)
        raw_date = row.get("raw_date")
        # date 컬럼이 단일 일자인지 활동기간인지에 따라 파싱.
        start_date, end_date = _parse_date_range(raw_date)
        # role은 동아리 직위. sub_category(award의 분류)나 sub_type(연수종류/동아리유형)이
        # 있으면 category에 " · "로 병기해서 화면에서 구분 가능하게.
        subtype = _clip(row.get("sub_type") or row.get("sub_category"), 100)
        if subtype and category and subtype not in category:
            category = _clip(f"{category} · {subtype}", 100)
        elif subtype and not category:
            category = subtype
        # 부가 정보를 description에 요약.
        description_bits = []
        for key, label in (("contents", "내용"), ("score_hint", "역량지수")):
            v = row.get(key)
            if v:
                description_bits.append(f"{label}={v}")
        description = _clip("; ".join(description_bits), 2000) if description_bits else None

        values = {
            "organization": _clip(row.get("institution"), 255),
            "category": category,
            "role": _clip(row.get("role"), 100),
            "award": None,
            "description": description,
        }
        existing = (
            db.query(UserActivity)
            .filter(
                UserActivity.user_id == user_id,
                UserActivity.title == title,
                UserActivity.category == category,
                UserActivity.start_date == start_date,
            )
            .one_or_none()
        )
        if existing is None:
            db.add(UserActivity(
                user_id=user_id, title=title, start_date=start_date, end_date=end_date,
                **values,
            ))
            created += 1
        else:
            changed = False
            if existing.end_date != end_date:
                existing.end_date = end_date
                changed = True
            for k, v in values.items():
                if getattr(existing, k) != v:
                    setattr(existing, k, v)
                    changed = True
            if changed:
                updated += 1
    db.commit()
    return created, updated


def upsert_certifications(db: Session, user_id: int, rows: list[dict]) -> tuple[int, int]:
    """UserCertification 스키마가 name/expires_at뿐이라 발급기관/취득일/자격증번호는
    표시 name에 병기해서 손실 없이 저장. Idempotency 키: (user_id, name)."""
    created = updated = 0
    for row in rows:
        base_name = _clip(row.get("name"), 200)
        if not base_name:
            continue
        issuer = _clip(row.get("issuer"), 100)
        certificate_no = _clip(row.get("certificate_no"), 100)
        issued_at = _parse_date(row.get("issued_at"))
        # 표시 name = 이름 (발급기관) [번호, 취득일]
        display_name = base_name
        if issuer:
            display_name = f"{display_name} ({issuer})"
        extras = []
        if certificate_no:
            extras.append(f"번호 {certificate_no}")
        if issued_at:
            extras.append(f"취득 {issued_at.isoformat()}")
        if extras:
            display_name = f"{display_name} [{'; '.join(extras)}]"
        display_name = _clip(display_name, 255)

        existing = (
            db.query(UserCertification)
            .filter(UserCertification.user_id == user_id, UserCertification.name == display_name)
            .one_or_none()
        )
        if existing is None:
            db.add(UserCertification(user_id=user_id, name=display_name, expires_at=None))
            created += 1
    db.commit()
    return created, updated


def upsert_language_scores(db: Session, user_id: int, rows: list[dict]) -> tuple[int, int]:
    """UserLanguageScore. Idempotency 키: (user_id, test_name, score)."""
    created = updated = 0
    for row in rows:
        test_name = _clip(row.get("test_name"), 100)
        score = _clip(row.get("score"), 50)
        if not test_name or not score:
            continue
        # UserLanguageScore.expires_at은 실제 만료일 없어서 취득일로 저장하지 않는다
        # (의미가 다름). 취득일은 별도 저장할 컬럼이 없어서 loss 발생 — 이후 스키마
        # 확장 시 issued_at 추가할 것.
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
                user_id=user_id, test_name=test_name, score=score, expires_at=None,
            ))
            created += 1
    db.commit()
    return created, updated
