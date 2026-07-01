"""공지사항 크롤러(notice_board_crawler)의 NoticeRow를
Activity 모델로 변환해 DB에 upsert한다.

카테고리 분류는 제목 키워드 기반 규칙으로 1차 처리하며,
임베딩 생성은 별도 배치(ai/embeddings)가 담당한다.
"""

from __future__ import annotations

import datetime
import re

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domains.activities.models import Activity
from app.ingestion.crawlers.notice_board_crawler import NoticeRow

# 제목 키워드 → 카테고리 매핑 (앞에서부터 첫 번째 매칭 사용)
_CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("공모전", re.compile(r"공모전|경진대회|챌린지|해커톤|contest|competition", re.I)),
    ("인턴십", re.compile(r"인턴|intern", re.I)),
    ("취업", re.compile(r"채용|취업|job|career|설명회|취준", re.I)),
    ("장학금", re.compile(r"장학|scholarship", re.I)),
    ("스터디", re.compile(r"스터디|study|러닝서클|독서모임", re.I)),
    ("교내활동", re.compile(r"동아리|학생회|총학|봉사|멘토|튜터", re.I)),
    ("강연/특강", re.compile(r"특강|강연|세미나|워크숍|포럼|lecture|seminar", re.I)),
    ("교육프로그램", re.compile(r"프로그램|캠프|부트캠프|교육|훈련|과정", re.I)),
    ("도서관", re.compile(r"도서관|열람실|대출|반납", re.I)),
    ("상담", re.compile(r"상담|counseling|심리|진로상담", re.I)),
]

# 마감일 패턴 — 제목에서 "~MM/DD", "D-N", "N월N일까지" 등을 뽑는다
_DEADLINE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[~～](\d{1,2})[./](\d{1,2})\b"),            # ~6/30 or ~6.30
    re.compile(r"(\d{1,2})월\s*(\d{1,2})일\s*(?:까지|마감)"),    # 6월 30일까지
    re.compile(r"\((\d{1,2})[./](\d{1,2})\s*(?:마감|까지)?\)"),  # (7/10) or (7/10마감)
    re.compile(r"(\d{1,2})[./](\d{1,2})\s*(?:마감|까지)\b"),     # 7/10마감, 7/10까지
]


def _infer_category(title: str) -> str | None:
    for category, pattern in _CATEGORY_RULES:
        if pattern.search(title):
            return category
    return None


def _infer_deadline(title: str, posted_date: datetime.date | None) -> datetime.date | None:
    for pattern in _DEADLINE_PATTERNS:
        m = pattern.search(title)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            ref_year = (posted_date or datetime.date.today()).year
            try:
                candidate = datetime.date(ref_year, month, day)
                # 마감일이 게시일보다 이전이면 다음 해로 처리
                if posted_date and candidate < posted_date:
                    candidate = datetime.date(ref_year + 1, month, day)
                return candidate
            except ValueError:
                continue
    return None


def upsert_activity(db: Session, row: NoticeRow) -> Activity:
    """NoticeRow 하나를 Activity로 변환해 upsert하고 ORM 객체를 반환한다.

    source + source_url이 이미 존재하면 title/posted_date/views만 갱신한다.
    embedding은 건드리지 않는다(별도 배치가 담당).
    """
    posted = datetime.date.fromisoformat(row.posted_date) if row.posted_date else None
    category = _infer_category(row.title)
    deadline = _infer_deadline(row.title, posted)

    values = {
        "source": row.source,
        "source_url": row.url,
        "title": row.title,
        "author": row.author or None,
        "posted_date": posted,
        "deadline": deadline,
        "category": category,
        "is_pinned": row.is_pinned,
        "views": row.views,
        "updated_at": datetime.datetime.now(datetime.UTC),
    }

    stmt = (
        insert(Activity)
        .values(**values, created_at=datetime.datetime.now(datetime.UTC))
        .on_conflict_do_update(
            constraint="uq_activity_source_url",
            set_={
                "title": values["title"],
                "posted_date": values["posted_date"],
                "deadline": values["deadline"],
                "category": values["category"],
                "is_pinned": values["is_pinned"],
                "views": values["views"],
                "updated_at": values["updated_at"],
            },
        )
        .returning(Activity.id)
    )
    result = db.execute(stmt)
    activity_id = result.scalar_one()
    db.flush()
    return db.get(Activity, activity_id)


def upsert_all_activities(db: Session, rows: list[NoticeRow]) -> list[Activity]:
    """NoticeRow 목록 전체를 upsert하고 Activity 목록을 반환한다."""
    activities = []
    for row in rows:
        activity = upsert_activity(db, row)
        if activity is not None:
            activities.append(activity)
    db.commit()
    return activities
