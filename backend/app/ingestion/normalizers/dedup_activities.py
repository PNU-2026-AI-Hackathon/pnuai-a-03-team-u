"""제목이 완전히 동일하고 게시일이 3일 이내인 Activity를
중복으로 간주해 하나만 남기고 삭제한다. 출처(source)가 달라도 적용된다.

- 같은 출처 중복: 크롤러가 같은 글을 다른 board_seq/URL로 두 번 수집한 경우
  (재게시, 페이지네이션 경계 중복 등)
- 다른 출처 중복: pusan_main(대학 본부 포털)이 전문 게시판(job, pnucounsel 등)의
  공지를 재게시하는 경우 — 추천 top-k에 같은 공지가 두 번 노출되는 원인

회차별/재모집 공고처럼 제목만 비슷하고 실제로는 다른 공지는 건드리지 않는다
(제목이 정확히 같아야 하고 게시일도 3일 이내여야 함).
"""

from __future__ import annotations

import datetime
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.activities.models import Activity, UserActivityRecommendation

_MAX_DATE_GAP_DAYS = 3


def _keep_activity(group: list[Activity]) -> Activity:
    """임베딩이 이미 있는 쪽을 최우선으로 남긴다(재임베딩 방지).

    삭제된 쪽 출처는 다음 크롤에서 새 행으로 다시 upsert되는데, 임베딩 유무를
    안 보면 매일 밤 '기존 임베딩된 행을 지우고 새 행을 다시 임베딩'하는
    순환이 생길 수 있다. 그다음 기준은 views, posted_date 순.
    """
    return max(
        group,
        key=lambda a: (
            a.embedding is not None,
            a.views or 0,
            a.posted_date or datetime.date.min,
            a.id,
        ),
    )


def find_duplicate_groups(db: Session) -> list[list[Activity]]:
    activities = db.scalars(select(Activity)).all()
    by_title: dict[str, list[Activity]] = defaultdict(list)
    for activity in activities:
        by_title[activity.title.strip()].append(activity)

    groups = []
    for candidates in by_title.values():
        if len(candidates) < 2:
            continue
        candidates.sort(key=lambda a: a.posted_date or datetime.date.min)
        cluster = [candidates[0]]
        for activity in candidates[1:]:
            last = cluster[-1]
            gap = abs((activity.posted_date or datetime.date.min) - (last.posted_date or datetime.date.min)).days
            if gap <= _MAX_DATE_GAP_DAYS:
                cluster.append(activity)
            else:
                if len(cluster) > 1:
                    groups.append(cluster)
                cluster = [activity]
        if len(cluster) > 1:
            groups.append(cluster)
    return groups


def remove_duplicate_activities(db: Session) -> int:
    """중복 그룹을 찾아 하나만 남기고 삭제한다. 삭제된 Activity 수를 반환한다."""
    groups = find_duplicate_groups(db)
    deleted = 0
    for group in groups:
        keeper = _keep_activity(group)
        for activity in group:
            if activity.id == keeper.id:
                continue
            db.query(UserActivityRecommendation).filter(
                UserActivityRecommendation.activity_id == activity.id
            ).delete()
            db.delete(activity)
            deleted += 1
    db.commit()
    return deleted
