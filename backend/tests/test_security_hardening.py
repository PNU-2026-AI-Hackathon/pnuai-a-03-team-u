"""보안 P0/P1 조치 회귀 테스트 (docs/backend/security-privacy-plan.md).

레이트 리밋·토큰 무효화·응답 누출은 "돌아가는지"가 아니라 "막히는지"가 핵심이라,
각 항목마다 **막혀야 하는 시나리오**를 직접 태운다.
"""

import unittest
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.ingestion.crawlers.pnu_session import (
    PnuLoginError,
    _resolve_credentials,
    login as pnu_login,
)
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


class CrawlerCredentialFallbackTest(unittest.TestCase):
    """P1-4: `.env`의 개인 부산대 계정이 크롤러 기본 계정으로 쓰이지 않는지.

    `.env`는 팀 채널로 공유되므로, 배포 환경에서 폴백이 살아 있으면 아무나 크롤러를
    돌릴 때 개발자 개인 계정으로 One-Stop에 로그인된다. 로컬 개발 편의만 남긴다.
    """

    ENV_FIXTURE_ID = "test-login-id"
    ENV_FIXTURE_PW = "test-login-pw"

    def _with_env(self, env: str, env_id=ENV_FIXTURE_ID, env_pw=ENV_FIXTURE_PW):
        """settings를 임시로 바꾼다. 값은 전부 테스트용 더미다(실제 계정 아님)."""
        return (
            patch.object(settings, "ENV", env),
            patch.object(settings, "PNU_LOGIN_ID", env_id),
            patch.object(settings, "PNU_LOGIN_PW", env_pw),
        )

    def _resolve(self, env, login_id=None, login_pw=None, env_id=ENV_FIXTURE_ID, env_pw=ENV_FIXTURE_PW):
        p1, p2, p3 = self._with_env(env, env_id, env_pw)
        with p1, p2, p3:
            return _resolve_credentials(login_id, login_pw)

    def test_fallback_allowed_in_local(self):
        self.assertEqual(
            (self.ENV_FIXTURE_ID, self.ENV_FIXTURE_PW), self._resolve("local")
        )

    def test_fallback_allowed_in_dev(self):
        for env in ("dev", "development", "LOCAL"):
            with self.subTest(env=env):
                self.assertEqual(
                    (self.ENV_FIXTURE_ID, self.ENV_FIXTURE_PW), self._resolve(env)
                )

    def test_fallback_blocked_outside_local(self):
        for env in ("production", "prod", "staging", ""):
            with self.subTest(env=env):
                with self.assertRaises(PnuLoginError) as ctx:
                    self._resolve(env)
                # 왜 막혔는지 알 수 있어야 한다 — 인자를 넘기라는 안내가 있어야 함.
                self.assertIn("login_id", str(ctx.exception))

    def test_explicit_credentials_work_everywhere(self):
        self.assertEqual(
            ("caller-id", "caller-pw"),
            self._resolve("production", login_id="caller-id", login_pw="caller-pw"),
        )

    def test_partial_credentials_never_mix_with_env(self):
        """한쪽만 넘기면 남은 한쪽이 .env 개인 계정으로 채워지면 안 된다."""
        for env in ("local", "production"):
            for login_id, login_pw in (("caller-id", None), (None, "caller-pw"), ("caller-id", "")):
                with self.subTest(env=env, login_id=login_id, login_pw=login_pw):
                    with self.assertRaises(PnuLoginError):
                        self._resolve(env, login_id=login_id, login_pw=login_pw)

    def test_local_without_env_values_raises_clear_error(self):
        with self.assertRaises(PnuLoginError) as ctx:
            self._resolve("local", env_id=None, env_pw=None)
        self.assertIn("PNU_LOGIN_ID", str(ctx.exception))

    def test_login_fails_before_opening_a_browser(self):
        """검증이 브라우저/네트워크보다 먼저 일어나야 한다."""

        class ExplodingBrowser:
            def new_context(self, *args, **kwargs):
                raise AssertionError("자격증명 검증 전에 브라우저를 열면 안 된다")

        p1, p2, p3 = self._with_env("production")
        with p1, p2, p3, self.assertRaises(PnuLoginError):
            pnu_login(ExplodingBrowser())


class CorsCredentialsTest(unittest.TestCase):
    """P1-5: 쿠키를 안 쓰는데 CORS가 credentials를 허용하지 않는지.

    인증은 Authorization 헤더(localStorage 토큰)로만 한다. `allow_credentials=True`는
    동작에 필요 없으면서 공격면만 넓힌다.
    """

    ORIGIN = "http://localhost:5173"

    def setUp(self):
        self.client = TestClient(app)

    def test_preflight_does_not_allow_credentials(self):
        r = self.client.options(
            "/health",
            headers={
                "Origin": self.ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(200, r.status_code)
        # 허용된 origin이라는 것 자체는 그대로여야 한다 (프론트가 계속 붙는다).
        self.assertEqual(self.ORIGIN, r.headers.get("access-control-allow-origin"))
        self.assertIsNone(r.headers.get("access-control-allow-credentials"))

    def test_actual_request_does_not_allow_credentials(self):
        r = self.client.get("/health", headers={"Origin": self.ORIGIN})
        self.assertEqual(200, r.status_code)
        self.assertEqual(self.ORIGIN, r.headers.get("access-control-allow-origin"))
        self.assertIsNone(r.headers.get("access-control-allow-credentials"))

    def test_no_endpoint_sets_a_cookie(self):
        """쿠키를 굽는 엔드포인트가 생기면 P1-5 전제가 깨지므로 여기서 잡는다."""
        for method, path, kwargs in (
            ("get", "/health", {}),
            # 본문을 일부러 틀려 422로 끝낸다 — DB를 건드리지 않고 auth 라우터 응답 경로만 태운다.
            ("post", "/auth/login", {"json": {"email": "x@pusan.ac.kr"}}),
        ):
            with self.subTest(path=path):
                r = getattr(self.client, method)(path, **kwargs)
                self.assertIsNone(r.headers.get("set-cookie"), f"{path}가 쿠키를 굽는다")


if __name__ == "__main__":
    unittest.main()


class EnvDefaultFailsClosedTest(unittest.TestCase):
    """`ENV` 기본값은 안전한 쪽(production)이어야 한다.

    실제로 있었던 구멍: 기본값이 `"local"`인데 배포 설정(infra/, CI, Dockerfile)
    어디에서도 ENV를 지정하지 않았다. 그래서 운영에서도 `settings.ENV == "local"`로
    평가돼, 이 값에 걸린 가드가 **전부 열린 채**였다:

      - P0-4: 비밀번호 재설정 링크가 로그에 평문으로 찍힌다
      - P1-4: 크롤러가 개발자 개인 부산대 계정으로 폴백한다

    설정을 빠뜨렸을 때 로컬에서 눈에 띄게 실패하는 편이, 운영이 조용히 노출되는
    것보다 낫다. `.env.example`의 `ENV=local`이 로컬 쪽을 책임진다.
    """

    def test_default_env_is_not_a_dev_environment(self):
        from app.core.config import Settings

        # env_file/환경변수 영향을 받지 않는 순수 기본값을 본다.
        default_env = Settings.model_fields["ENV"].default
        self.assertNotIn(
            str(default_env).lower(), {"local", "dev", "development"},
            "ENV 기본값이 개발 환경이면, 배포에서 ENV를 안 넣었을 때 보안 가드가 "
            "조용히 전부 열린다 (fail-open).",
        )

    def test_env_example_documents_local_override(self):
        """로컬 개발자가 ENV=local을 켤 수 있도록 .env.example이 안내해야 한다."""
        from pathlib import Path

        example = Path(__file__).resolve().parents[1] / ".env.example"
        self.assertTrue(example.exists(), ".env.example이 없다")
        self.assertRegex(
            example.read_text(), r"(?m)^ENV=local\b",
            ".env.example에 ENV=local이 없다 — 기본값이 production이라 로컬 개발 "
            "편의 기능이 아무 안내 없이 꺼진다.",
        )
