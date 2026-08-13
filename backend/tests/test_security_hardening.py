"""보안 P0 조치 회귀 테스트 (docs/backend/security-privacy-plan.md).

레이트 리밋·토큰 무효화·응답 누출은 "돌아가는지"가 아니라 "막히는지"가 핵심이라,
각 항목마다 **막혀야 하는 시나리오**를 직접 태운다.
"""

import unittest

import pytest
from fastapi.testclient import TestClient

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    password_fingerprint,
)
from app.main import app


class TokenInvalidationTest(unittest.TestCase):
    """비밀번호를 바꾸면 그 전에 발급된 토큰이 즉시 무효가 되는지.

    옛 구현은 페이로드가 {sub, exp}뿐이라 비밀번호를 바꿔도 기존 토큰이 만료(7일)까지
    유효했다 — 토큰이 유출된 사용자가 비밀번호를 바꿔도 공격자 접근이 유지됐다.
    """

    def test_token_carries_password_fingerprint(self):
        pw_hash = hash_password("original-password")
        token = create_access_token(1, pw_hash)
        decoded = decode_access_token(token)
        self.assertIsNotNone(decoded)
        user_id, fingerprint = decoded
        self.assertEqual(1, user_id)
        self.assertEqual(password_fingerprint(pw_hash), fingerprint)

    def test_fingerprint_changes_when_password_changes(self):
        old_hash = hash_password("original-password")
        new_hash = hash_password("changed-password")
        token = create_access_token(1, old_hash)
        _, fingerprint = decode_access_token(token)
        # 인증부(get_current_user)는 이 불일치를 보고 401을 낸다.
        self.assertNotEqual(password_fingerprint(new_hash), fingerprint)

    def test_legacy_token_without_fingerprint_is_rejected(self):
        """`pv` 없는 옛 토큰을 통과시키면 무효화가 최대 7일간 무의미해진다."""
        import datetime

        from jose import jwt

        from app.core.config import settings

        legacy = jwt.encode(
            {"sub": "1", "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)},
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
        self.assertIsNone(decode_access_token(legacy))

    def test_tampered_token_is_rejected(self):
        token = create_access_token(1, hash_password("pw"))
        self.assertIsNone(decode_access_token(token[:-3] + "abc"))


class ValidationResponseLeakTest(unittest.TestCase):
    """422 응답이 입력값을 그대로 돌려주지 않는지.

    pydantic v2 에러 항목에는 검증에 실패한 입력값이 담긴다. portal-sync처럼 본문에
    One-Stop 비밀번호가 있는 요청에서 타입이 어긋나면 그 값이 응답으로 되돌아온다.
    """

    def setUp(self):
        self.client = TestClient(app)

    def test_invalid_body_does_not_echo_input(self):
        secret = "SUPER_SECRET_PW"
        r = self.client.post(
            "/auth/login", json={"email": "x@pusan.ac.kr", "password": {"leak": secret}}
        )
        self.assertEqual(422, r.status_code)
        self.assertNotIn(secret, r.text)

    def test_error_still_says_which_field_failed(self):
        """값은 빼되 어디가 왜 틀렸는지는 남아야 프론트가 안내할 수 있다."""
        r = self.client.post("/auth/login", json={"email": "x@pusan.ac.kr"})
        self.assertEqual(422, r.status_code)
        body = r.json()
        self.assertIn("password", str(body["detail"]))


@pytest.mark.ratelimit
class RateLimitTest(unittest.TestCase):
    """로그인 brute force가 실제로 차단되는지.

    conftest가 기본적으로 리밋을 꺼두므로 이 클래스만 `ratelimit` 마커로 켠다.
    """

    def setUp(self):
        self.client = TestClient(app)

    def test_login_is_blocked_after_burst(self):
        codes = [
            self.client.post(
                "/auth/login",
                json={"email": "nobody@pusan.ac.kr", "password": "wrong-password"},
            ).status_code
            for _ in range(8)
        ]
        self.assertIn(429, codes, f"brute force가 차단되지 않았다: {codes}")
        # 차단 전 시도는 정상적으로 401이어야 한다 (리밋이 전부를 삼키면 안 됨).
        self.assertIn(401, codes, codes)

    def test_blocked_response_is_korean_with_retry_after(self):
        for _ in range(8):
            r = self.client.post(
                "/auth/login",
                json={"email": "nobody2@pusan.ac.kr", "password": "wrong-password"},
            )
            if r.status_code == 429:
                break
        self.assertEqual(429, r.status_code)
        self.assertIn("잠시 후", r.json()["detail"])
        self.assertIsNotNone(r.headers.get("Retry-After"))


if __name__ == "__main__":
    unittest.main()
