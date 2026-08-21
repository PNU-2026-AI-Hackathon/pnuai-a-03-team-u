"""보존기간 정책(P2) — 장기 미접속 계정 선별 로직.

여기서 검증하는 건 "누구를 대상으로 고르는가"다. 실제 삭제 순서는 회원 탈퇴와
같은 `_ACCOUNT_DELETE_STEPS`를 재사용하므로 test_account_deletion.py가 이미
커버한다.

선별을 따로 테스트하는 이유: 기준일 계산이 하루만 어긋나도 멀쩡한 계정이
파기 대상이 되는데, 삭제는 되돌릴 수 없다.
"""

import datetime
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.domains.users.models import User
from scripts.purge_inactive_accounts import find_inactive_users

_TABLES = [User.__table__]


def _naive_days_ago(days: int) -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(days=days)


class FindInactiveUsersTest(unittest.TestCase):
    def _make_db(self) -> Session:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_TABLES)
        return Session(engine)

    def _add_user(self, db, uid, *, last_login_days=None, created_days=0):
        db.add(User(
            id=uid,
            email=f"u{uid}@pusan.ac.kr",
            password_hash="x",
            name=f"사용자{uid}",
            created_at=_naive_days_ago(created_days),
            updated_at=_naive_days_ago(created_days),
            last_login_at=_naive_days_ago(last_login_days) if last_login_days is not None else None,
        ))

    def test_selects_only_users_past_the_cutoff(self):
        db = self._make_db()
        self._add_user(db, 1, last_login_days=800, created_days=900)   # 26개월 전 → 대상
        self._add_user(db, 2, last_login_days=30, created_days=900)    # 최근 접속 → 유지
        db.commit()

        targets = find_inactive_users(db, months=24)

        self.assertEqual([1], [t[0] for t in targets])

    def test_never_logged_in_falls_back_to_created_at(self):
        """last_login_at이 NULL이면 가입일 기준. 가입만 하고 안 온 계정도 파기 대상이다."""
        db = self._make_db()
        self._add_user(db, 1, last_login_days=None, created_days=800)  # 가입 26개월 전 → 대상
        self._add_user(db, 2, last_login_days=None, created_days=10)   # 가입 직후 → 유지
        db.commit()

        targets = find_inactive_users(db, months=24)

        self.assertEqual([1], [t[0] for t in targets])

    def test_recent_login_protects_old_account(self):
        """가입은 3년 전이어도 최근에 접속했으면 절대 대상이 아니다.

        updated_at을 기준으로 삼았다면 프로필을 안 고친 활성 사용자가 여기서
        걸렸을 것이다 — last_login_at을 따로 둔 이유.
        """
        db = self._make_db()
        self._add_user(db, 1, last_login_days=5, created_days=1100)
        db.commit()

        self.assertEqual([], find_inactive_users(db, months=24))

    def test_months_argument_changes_the_cutoff(self):
        db = self._make_db()
        self._add_user(db, 1, last_login_days=400, created_days=500)  # 13개월 전

        db.commit()

        self.assertEqual([], find_inactive_users(db, months=24))      # 24개월 기준 → 유지
        self.assertEqual([1], [t[0] for t in find_inactive_users(db, months=12)])  # 12개월 → 대상


if __name__ == "__main__":
    unittest.main()
