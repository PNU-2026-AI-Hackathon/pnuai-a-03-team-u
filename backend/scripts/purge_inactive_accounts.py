"""보존기간 정책 — 장기 미접속 계정의 학사 데이터 파기.

보안·개인정보 계획(docs/backend/security-privacy-plan.md) P2 항목. 개인정보는
목적을 다하면 파기해야 하는데, 지금까지는 회원이 직접 탈퇴하지 않는 한 이수내역·
로드맵·대화가 무기한 남았다.

## 왜 자동 배치(APScheduler)가 아니라 스크립트인가

삭제는 되돌릴 수 없다. 그런데 지금 이 프로젝트는:

  1. **검증된 백업이 없다.** 같은 계획서의 P2 "DB 백업 + 복구 리허설"이 아직
     미완이다. 복구가 안 되는 상태에서 자동 삭제부터 켜는 건 순서가 뒤바뀐 것이다.
  2. **팀 공유 DB 하나를 5명이 쓴다.** 날짜·타임존 계산이 하루만 어긋나도
     남의 실데이터가 사라지고, 아무도 눈치채기 전에 다음 실행이 또 돈다.

그래서 이 스크립트는 **기본이 dry-run**이고, 실제 삭제는 `--commit`을 명시해야
일어난다. 자동 스케줄 등록은 백업·복구 리허설이 끝난 뒤에 하는 것이 맞다
(계획서 P2에 그 순서로 적어 두었다).

## 무엇을 지우나

`app.api.profile._ACCOUNT_DELETE_STEPS`를 그대로 재사용한다 — 회원 탈퇴 API가
쓰는, 커버리지 테스트가 붙어 있는 바로 그 순서다. 여기서 목록을 새로 만들면
테이블이 추가될 때마다 두 곳이 어긋나고, 한쪽에만 빠진 테이블이 조용히 남는다.

## 기준

마지막 로그인이 N개월(기본 24) 이전이면 대상. `last_login_at`이 NULL인 계정은
가입 후 한 번도 로그인하지 않은 것이므로 `created_at`을 대신 쓴다.

실행:
    python -m scripts.purge_inactive_accounts                # dry-run (기본)
    python -m scripts.purge_inactive_accounts --months 12    # 기준 변경
    python -m scripts.purge_inactive_accounts --commit       # 실제 삭제
"""

from __future__ import annotations

import argparse
import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.profile import _ACCOUNT_DELETE_STEPS
from app.core.db import SessionLocal

DEFAULT_RETENTION_MONTHS = 24

# 한 번에 이 비율을 넘겨 지우려 하면 멈춘다. 날짜 계산이 어긋났을 때
# (예: cutoff가 미래로 잡혀 전원이 대상이 되는 경우) 마지막 방어선이다.
MAX_PURGE_RATIO = 0.5


def find_inactive_users(db: Session, months: int) -> list[tuple[int, str, str, datetime.datetime]]:
    """(id, email, name, 기준시각) 목록. 기준시각 = last_login_at ?? created_at."""
    cutoff = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(
        days=30 * months
    )
    rows = db.execute(
        text("""
            SELECT id, email, name, COALESCE(last_login_at, created_at) AS last_seen
            FROM users
            WHERE COALESCE(last_login_at, created_at) < :cutoff
            ORDER BY last_seen
        """),
        {"cutoff": cutoff},
    ).all()
    return [(r[0], r[1], r[2], r[3]) for r in rows]


def purge_user(db: Session, user_id: int) -> dict[str, int]:
    """회원 탈퇴 API와 같은 순서로 지운다. 존재하지 않는 테이블은 건너뛴다."""
    existing = {
        row[0]
        for row in db.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        ).all()
    }
    deleted: dict[str, int] = {}
    for table, statement in _ACCOUNT_DELETE_STEPS:
        if table not in existing:
            continue
        count = db.execute(text(statement), {"uid": user_id}).rowcount
        if count:
            deleted[table] = count
    return deleted


def run(months: int, commit: bool) -> None:
    db = SessionLocal()
    try:
        total_users = db.execute(text("SELECT count(*) FROM users")).scalar() or 0
        targets = find_inactive_users(db, months)

        print(f"기준: 마지막 접속이 {months}개월 이전 | 전체 계정 {total_users}건")
        if not targets:
            print("대상 없음 — 파기할 계정이 없습니다.")
            return

        print(f"대상 {len(targets)}건:")
        for user_id, email, name, last_seen in targets:
            print(f"  #{user_id} {name} <{email}> — 마지막 접속 {last_seen:%Y-%m-%d}")

        if total_users and len(targets) / total_users > MAX_PURGE_RATIO:
            print(
                f"\n중단: 전체의 {len(targets) / total_users:.0%}를 지우려 합니다. "
                "기준(--months)이나 시스템 시각이 잘못됐을 가능성이 큽니다. "
                "확인 후 다시 실행하세요."
            )
            return

        if not commit:
            print("\n[dry-run] 실제로 지우려면 --commit 을 붙여 다시 실행하세요.")
            return

        for user_id, email, name, _ in targets:
            deleted = purge_user(db, user_id)
            print(f"삭제 완료 #{user_id} {name} <{email}>: {deleted}")
        db.commit()
        print(f"\n총 {len(targets)}건 파기 완료.")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=int, default=DEFAULT_RETENTION_MONTHS)
    parser.add_argument(
        "--commit", action="store_true", help="실제로 삭제한다 (기본은 dry-run)"
    )
    args = parser.parse_args()
    run(months=args.months, commit=args.commit)
