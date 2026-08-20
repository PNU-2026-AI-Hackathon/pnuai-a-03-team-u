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


@pytest.mark.ratelimit
class LimiterSuccessPathTest(unittest.TestCase):
    """리밋이 걸린 엔드포인트의 **성공 응답**이 살아 있는지.

    이 테스트가 없어서 실제 사고가 났다. `Limiter(headers_enabled=True)`이면 slowapi가
    엔드포인트 반환값이 starlette Response가 아닐 때 `kwargs["response"]`에 헤더를
    주입하려 하고, 우리 엔드포인트는 Pydantic 모델을 반환하며 `response: Response`를
    선언하지 않으므로 None이 넘어가 예외 → **정상 요청이 500**이 됐다.

    위의 RateLimitTest가 이걸 못 잡은 이유: 401(인증 실패)과 429(리밋 초과)는 둘 다
    헤더 주입 지점 **전에** 빠져나간다. 그래서 리밋 테스트가 전부 초록인데 정작
    로그인 성공은 죽어 있는 상태가 만들어졌다.

    그래서 여기서는 실제 DB나 계정에 기대지 않고, 우리 `limiter`를 그대로 쓰는 최소
    앱을 세워 "Pydantic을 반환하는 리밋 엔드포인트가 200을 준다"는 계약만 본다.
    새 리밋 엔드포인트가 늘어나도 이 계약은 그대로 유효하다.
    """

    def test_pydantic_returning_endpoint_still_returns_200(self):
        from fastapi import FastAPI, Request
        from pydantic import BaseModel

        from app.core.ratelimit import limiter

        class Probe(BaseModel):
            ok: bool

        probe_app = FastAPI()
        probe_app.state.limiter = limiter

        @probe_app.get("/probe", response_model=Probe)
        @limiter.limit("30/minute")
        def probe_endpoint(request: Request):  # noqa: ARG001 - slowapi가 요구하는 인자
            return Probe(ok=True)

        response = TestClient(probe_app).get("/probe")

        self.assertEqual(
            200,
            response.status_code,
            "리밋이 걸린 엔드포인트가 성공 경로에서 죽었다. "
            "Limiter(headers_enabled=...)를 켰다면 리밋이 걸린 모든 엔드포인트에 "
            f"`response: Response`가 필요하다. 응답: {response.text[:300]}",
        )
        self.assertEqual({"ok": True}, response.json())

    def test_limiter_does_not_require_response_param(self):
        """설정 자체를 못박아 둔다.

        위 테스트가 근본 원인을 잡지만, 실패 메시지가 500 하나뿐이면 원인을 다시
        추적해야 한다. 어떤 설정 때문인지 이름으로 바로 드러나게 한 줄 더 둔다.
        """
        from app.core.ratelimit import limiter

        self.assertFalse(
            limiter._headers_enabled,
            "headers_enabled를 켜려면 리밋이 걸린 모든 엔드포인트 시그니처에 "
            "`response: Response`를 먼저 추가해야 한다 (app/core/ratelimit.py 주석 참고).",
        )


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


class RagIngestRateLimitTest(unittest.TestCase):
    """`POST /rag/ingest`에 리밋이 실제로 등록돼 있는지.

    이 엔드포인트는 **전체 RAG 청크 재구축 + OpenAI 임베딩 호출**인데, 인증만 통과하면
    학생 누구나 부를 수 있고 리밋이 없었다. 프론트에서 아무도 호출하지 않는 운영 작업이라
    순수 비용/부하 공격면이었다 — 보안 계획의 "비용 남용" 항목이 챗만 덮고 있었다.

    **HTTP로는 검증할 수 없다**: 미인증 호출은 `get_current_user` 의존성이 먼저 401로
    끊어서 핸들러(=리미터)에 도달하지 않고, 인증하려면 DB가 필요하다. 그래서 조용히
    깨지는 두 지점을 직접 본다:

      1. 리밋이 limiter에 등록됐는가 (데코레이터를 떼면 조용히 사라진다 — 변이 테스트로
         확인함)
      2. 핸들러 시그니처에 `request: Request`가 있는가

    2번은 slowapi가 데코레이션 시점에 `No "request" or "websocket" argument`로 터뜨려서
    앱 import 자체가 실패한다(직접 확인). 즉 조용히 새는 경로는 아니지만, 그 예외를
    보고 "인자를 빼자"가 아니라 "리밋을 떼자"로 잘못 고치는 걸 막으려고 함께 남긴다.
    """

    _ROUTE_KEY = "app.api.rag.ingest_rag_chunks"

    def test_ingest_limit_is_registered(self):
        from app.core.ratelimit import limiter

        self.assertIn(
            self._ROUTE_KEY, getattr(limiter, "_route_limits", {}),
            "/rag/ingest에 @limiter.limit이 걸려 있지 않다 — 로그인한 학생 누구나 "
            "전체 RAG 재구축과 임베딩 비용을 유발할 수 있다.",
        )

    def test_ingest_handler_takes_request(self):
        import inspect

        from app.api import rag

        self.assertIn(
            "request", inspect.signature(rag.ingest_rag_chunks).parameters,
            "핸들러에 `request: Request` 인자가 없다 — slowapi가 조용히 무력화된다.",
        )


class StudentRecordResponseLeakTest(unittest.TestCase):
    """학적부 응답이 개인정보를 그대로 실어 보내지 않는지.

    One-Stop 학적부 화면에는 `주민등록번호`·`주소`·`보호자성명`/`보호자전화번호`·
    `이메일`·`휴대폰번호`가 같이 있고, 크롤러는 그 영역을 라벨:값 dict로 통째로 읽는다.
    저장은 안 하지만 예전에는 `PortalSyncResponse.student_record`에 **원문 그대로**
    실려서 브라우저까지 흘러갔다 — CLAUDE.md 개인정보 원칙 2.

    실계정 크롤이 필요 없도록 응답 경계 함수(`_public_student_record`)만 직접 태운다.
    """

    # 실계정(2026-08-19 확인) 학적부에서 실제로 나온 라벨 구성.
    _RECORD = {
        "성명": "홍길동",
        "학번": "202455494",
        "주민등록번호": "030101-3******",
        "주소": "부산광역시 금정구 부산대학로63번길 2",
        "휴대폰번호": "010-1234-5678",
        "이메일": "hong@pusan.ac.kr",
        "보호자성명": "홍부모",
        "보호자전화번호": "010-8765-4321",
        "소속학과": "정보의생명공학대학 정보컴퓨터공학부 컴퓨터공학전공",
        "학년/학기": "3",
        "학적상태": "재학",
        "교육과정적용년도": "2024",
        "지도교수": "김교수",
    }

    def test_sensitive_labels_are_dropped(self):
        from app.api.portal_sync import _public_student_record

        public = _public_student_record(self._RECORD)

        for label in ("주민등록번호", "주소", "휴대폰번호", "이메일", "보호자성명", "보호자전화번호"):
            self.assertNotIn(
                label, public,
                f"학적부 응답에 `{label}`이 그대로 실린다 — 화이트리스트에서 빼야 한다.",
            )
        # 값 기준으로도 한 번 더 본다(라벨명이 바뀌어도 값이 새면 잡힌다).
        serialized = str(public)
        # 라벨명이 바뀌어도 값이 새면 잡히도록. 예전에는 라벨 6개 대비 값 4개만 봐서
        # 이메일·보호자성명이 검사에서 빠져 있었다(독립 리뷰 지적).
        for value in ("030101-3******", "부산대학로63번길", "010-1234-5678",
                      "hong@pusan.ac.kr", "홍부모", "010-8765-4321"):
            self.assertNotIn(value, serialized, f"응답에 개인정보 값이 남아 있다: {value}")

    def test_fields_the_frontend_uses_survive(self):
        """지우기만 하면 회원가입 STEP 2 미리보기 카드가 통째로 빈다."""
        from app.api.portal_sync import _public_student_record

        public = _public_student_record(self._RECORD)

        self.assertEqual("홍길동", public.get("성명"))
        self.assertEqual("202455494", public.get("학번"))
        self.assertEqual(
            "정보의생명공학대학 정보컴퓨터공학부 컴퓨터공학전공", public.get("소속학과")
        )
        self.assertEqual("3", public.get("학년/학기"))
        self.assertEqual("재학", public.get("학적상태"))

        # 프론트가 읽는 키 **전수**. 예전에는 5개만 봐서 `이름`·`학부`·`전공`을
        # 화이트리스트에서 빼도 테스트가 통과했다(독립 리뷰 지적).
        from app.api.portal_sync import STUDENT_RECORD_PUBLIC_KEYS

        for key in ("성명", "이름", "학번", "소속학과", "학부", "전공",
                    "학년/학기", "학년", "학적상태"):
            with self.subTest(key=key):
                self.assertIn(
                    key, STUDENT_RECORD_PUBLIC_KEYS,
                    f"프론트가 읽는 `{key}`가 화이트리스트에서 빠지면 그 칸이 조용히 빈다",
                )

    def test_response_actually_uses_the_whitelist(self):
        """**필터가 응답에 실제로 연결돼 있는지.** 이게 이 PR의 전부다.

        독립 리뷰(2026-08-20)가 잡았다 — 아래 배선을 원래대로 되돌려 유출을 완전히
        부활시켜도 456개 테스트가 전부 통과했다. 위 테스트들은 `_public_student_record`를
        **직접만** 부르므로, 그 함수가 어디에도 안 쓰이면 그냥 죽은 코드가 된다.
        같은 종류의 결함이 바로 앞 PR(#187)에서도 나왔다.

        `/me/portal-sync`는 Playwright 크롤이 필요해 엔드투엔드로 태울 수 없다. 그래서
        같은 파일의 `RagIngestRateLimitTest`가 쓰는 방식(소스 검사)을 따른다.
        """
        import inspect

        from app.api import portal_sync

        source = inspect.getsource(portal_sync.sync_portal_data)
        self.assertIn(
            "student_record=_public_student_record(student_record)", source,
            "portal-sync 응답이 화이트리스트를 안 거치고 원문을 그대로 싣는다 — "
            "주민등록번호·주소·보호자 연락처가 프론트로 나간다.",
        )

    def test_unknown_labels_are_not_passed_through(self):
        """학적부 화면에 라벨이 추가돼도 자동으로 새지 않아야 한다(화이트리스트 계약)."""
        from app.api.portal_sync import _public_student_record

        public = _public_student_record({**self._RECORD, "군필여부": "미필"})
        self.assertNotIn("군필여부", public)

    def test_missing_labels_do_not_raise(self):
        from app.api.portal_sync import _public_student_record

        self.assertEqual({}, _public_student_record({}))


if __name__ == "__main__":
    unittest.main()
