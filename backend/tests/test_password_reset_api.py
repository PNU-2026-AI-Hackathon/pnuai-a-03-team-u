"""비밀번호 재설정 API.

본인확인은 부산대 웹메일 수신으로만 한다. 여기서 검증하는 핵심은
"토큰을 가진 사람만, 한 번만, 기한 안에" 바꿀 수 있다는 것이다.
"""

import datetime
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.auth import (
    PasswordResetConfirm,
    PasswordResetRequest,
    confirm_password_reset,
    request_password_reset,
)
from app.core.db import Base
from app.core.security import hash_password, verify_password
from app.domains.users.models import PasswordResetToken, User


class PasswordResetApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            cls.engine, tables=[User.__table__, PasswordResetToken.__table__]
        )

    def setUp(self):
        self.db = Session(self.engine)
        self.db.query(PasswordResetToken).delete()
        self.db.query(User).delete()
        self.user = User(
            email="dowon@pusan.ac.kr",
            password_hash=hash_password("old-password-123"),
            name="이도원",
            student_id="202355699",
        )
        self.db.add(self.user)
        self.db.commit()
        # 메일은 실제로 보내지 않고, 링크에 실린 원본 토큰만 가로챈다.
        self.sent = []
        patcher = patch(
            "app.api.auth.send_password_reset_email",
            side_effect=lambda to, reset_url, ttl_minutes: self.sent.append((to, reset_url)) or True,
        )
        self.send_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.db.close()

    def _call_request(self, email="dowon@pusan.ac.kr", name="이도원"):
        """`request_password_reset`를 부르고, 예약된 백그라운드 작업까지 실행한다.

        메일 발송은 응답 뒤로 미뤄졌다(2026-08-20) — SMTP 왕복이 요청을 붙잡고 있어서
        사용자가 최대 38.6초를 기다렸다. 그래서 이제 `send_password_reset_email`은
        핸들러 안에서 곧바로 불리지 않고 `BackgroundTasks`에 실린다. 테스트가
        "메일이 나갔는가"를 계속 검증하려면 그 작업을 여기서 돌려줘야 한다.
        """
        tasks = BackgroundTasks()
        response = request_password_reset(
            request=None,
            payload=PasswordResetRequest(email=email, name=name),
            background_tasks=tasks,
            db=self.db,
        )
        for task in tasks.tasks:
            task.func(*task.args, **task.kwargs)
        return response

    def _request_token(self, email="dowon@pusan.ac.kr", name="이도원") -> str:
        self._call_request(email, name)
        return self.sent[-1][1].split("token=")[1]

    def test_request_sends_link_and_stores_only_hash(self):
        token = self._request_token()

        record = self.db.scalar(select(PasswordResetToken))
        self.assertEqual(self.sent[-1][0], "dowon@pusan.ac.kr")
        self.assertIsNotNone(record)
        # 토큰 원문이 DB에 남으면 유출 시 그대로 링크를 만들 수 있다.
        self.assertNotEqual(record.token_hash, token)
        self.assertEqual(len(record.token_hash), 64)

    def test_request_for_unknown_email_does_not_reveal_or_send(self):
        response = self._call_request("nobody@pusan.ac.kr", "이도원")

        # 가입 여부가 응답으로 드러나면 안 된다 — 문구가 같아야 한다.
        known = self._call_request("dowon@pusan.ac.kr", "이도원")
        self.assertEqual(response.message, known.message)
        self.assertEqual([to for to, _ in self.sent], ["dowon@pusan.ac.kr"])

    def test_name_mismatch_does_not_send_and_does_not_reveal(self):
        response = self._call_request("dowon@pusan.ac.kr", "다른사람")
        matched = self._call_request("dowon@pusan.ac.kr", "이도원")

        # 이름이 틀리면 메일도, 토큰도 만들어지지 않는다.
        self.assertEqual(response.message, matched.message)
        self.assertEqual([to for to, _ in self.sent], ["dowon@pusan.ac.kr"])
        self.assertEqual(len(self.db.query(PasswordResetToken).all()), 1)

    def test_confirm_changes_password(self):
        token = self._request_token()

        confirm_password_reset(
            PasswordResetConfirm(token=token, new_password="new-password-456"), self.db
        )

        self.db.refresh(self.user)
        self.assertTrue(verify_password("new-password-456", self.user.password_hash))
        self.assertFalse(verify_password("old-password-123", self.user.password_hash))

    def test_token_cannot_be_reused(self):
        token = self._request_token()
        confirm_password_reset(
            PasswordResetConfirm(token=token, new_password="new-password-456"), self.db
        )

        with self.assertRaises(HTTPException) as ctx:
            confirm_password_reset(
                PasswordResetConfirm(token=token, new_password="another-password-789"), self.db
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_expired_token_is_rejected(self):
        token = self._request_token()
        record = self.db.scalar(select(PasswordResetToken))
        record.expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
        self.db.commit()

        with self.assertRaises(HTTPException):
            confirm_password_reset(
                PasswordResetConfirm(token=token, new_password="new-password-456"), self.db
            )

    def test_new_request_invalidates_previous_token(self):
        first = self._request_token()
        second = self._request_token()

        # 이전 링크로는 못 바꾸고, 최신 링크로만 바뀐다.
        with self.assertRaises(HTTPException):
            confirm_password_reset(
                PasswordResetConfirm(token=first, new_password="new-password-456"), self.db
            )
        confirm_password_reset(
            PasswordResetConfirm(token=second, new_password="new-password-456"), self.db
        )
        self.db.refresh(self.user)
        self.assertTrue(verify_password("new-password-456", self.user.password_hash))

    def test_short_password_is_rejected(self):
        token = self._request_token()

        with self.assertRaises(HTTPException) as ctx:
            confirm_password_reset(PasswordResetConfirm(token=token, new_password="short"), self.db)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_unknown_token_is_rejected(self):
        with self.assertRaises(HTTPException):
            confirm_password_reset(
                PasswordResetConfirm(token="not-a-real-token", new_password="new-password-456"),
                self.db,
            )


if __name__ == "__main__":
    unittest.main()
