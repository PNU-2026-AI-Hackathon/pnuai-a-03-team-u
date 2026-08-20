"""메일 발송 폴백 회귀 테스트.

**실제로 있었던 함정**: `.env.example`이 `SMTP_HOST=smtp.resend.com`(값 있음) +
`SMTP_PASSWORD=`(빈 값)이었다. 그 파일을 그대로 `.env`로 복사하면
`is_smtp_configured()`가 True라 "미설정 폴백"(링크를 로그에 남기기)을 건너뛰는데,
정작 발송은 인증 실패로 죽고 예외는 삼켜졌다. 결과적으로 **메일도 안 오고 로그에
링크도 없어서** 비밀번호 재설정 흐름을 아무도 확인할 수 없는 상태가 됐다
— 설정을 안 한 것보다 나쁘다 (2026-08-20 실측).

여기서 고정하는 계약:
  1. 발송이 실패해도 **개발 환경이면** 링크가 로그에 남는다 (흐름을 확인할 수 있다).
  2. 운영 환경에서는 실패해도 링크를 **절대** 로그에 남기지 않는다 (P0-4).
  3. `.env.example`을 그대로 복사해도 그 반쪽 설정 상태가 되지 않는다.
"""

import pathlib
import unittest
from unittest.mock import patch

from app.core import mailer


class SendFailureFallbackTest(unittest.TestCase):
    """SMTP는 설정됐는데 발송이 실패하는 경우."""

    def _send_with_smtp_failing(self, env: str):
        with patch.object(mailer.settings, "SMTP_HOST", "smtp.resend.com"), \
             patch.object(mailer.settings, "SMTP_USER", "resend"), \
             patch.object(mailer.settings, "SMTP_PASSWORD", ""), \
             patch.object(mailer.settings, "RESEND_API", None), \
             patch.object(mailer.settings, "ENV", env), \
             patch.object(mailer.smtplib, "SMTP", side_effect=OSError("auth failed")):
            with self.assertLogs("app.core.mailer", level="WARNING") as logs:
                sent = mailer.send_email(
                    "student@pusan.ac.kr",
                    "[Plan U] 비밀번호 재설정 안내",
                    "링크: http://localhost:5173/reset-password?token=SECRET_TOKEN_123",
                )
        return sent, "\n".join(logs.output)

    def test_dev_logs_the_link_when_send_fails(self):
        sent, output = self._send_with_smtp_failing("local")

        self.assertFalse(sent, "발송에 실패했으면 False여야 한다")
        self.assertIn(
            "SECRET_TOKEN_123", output,
            "개발 환경에서 발송이 실패했는데 링크가 로그에도 없으면, 비밀번호 재설정 "
            "흐름을 아예 확인할 수 없다 (설정을 안 한 것보다 나쁜 상태).",
        )

    def test_production_never_logs_the_link_even_on_failure(self):
        """P0-4 — 본문에는 계정 탈취에 바로 쓰이는 링크가 들어 있다."""
        sent, output = self._send_with_smtp_failing("production")

        self.assertFalse(sent)
        self.assertNotIn(
            "SECRET_TOKEN_123", output,
            "운영 로그에 재설정 링크가 남으면 로그 접근자가 임의 계정을 가져갈 수 있다",
        )

    def test_unconfigured_dev_still_logs_the_link(self):
        """기존 동작(SMTP_HOST 자체가 없음)을 되돌리지 않았는지."""
        with patch.object(mailer.settings, "SMTP_HOST", None), \
             patch.object(mailer.settings, "RESEND_API", None), \
             patch.object(mailer.settings, "ENV", "local"):
            with self.assertLogs("app.core.mailer", level="WARNING") as logs:
                sent = mailer.send_email("s@pusan.ac.kr", "제목", "token=PLAIN_LINK_456")

        self.assertFalse(sent)
        self.assertIn("PLAIN_LINK_456", "\n".join(logs.output))


class ResendOneLineConfigTest(unittest.TestCase):
    """`.env`에 `RESEND_API=re_...` 한 줄만 있어도 발송이 되어야 한다.

    사용자가 실제로 `.env`에 `RESEND_API`만 넣었는데, 코드는 `SMTP_HOST`를 봐서
    "설정했는데 여전히 메일이 안 간다" 상태였다(2026-08-20). 키를 두 벌
    (RESEND_API와 SMTP_PASSWORD) 적게 하지 않으려고 한쪽으로 통일했다.
    """

    def test_resend_api_alone_configures_smtp(self):
        with patch.object(mailer.settings, "SMTP_HOST", None), \
             patch.object(mailer.settings, "SMTP_USER", None), \
             patch.object(mailer.settings, "SMTP_PASSWORD", None), \
             patch.object(mailer.settings, "RESEND_API", "re_test_key"):
            smtp = mailer.resolve_smtp()

        self.assertEqual("smtp.resend.com", smtp.host)
        self.assertEqual(587, smtp.port)
        self.assertEqual("resend", smtp.user, "Resend는 사용자명이 고정값 'resend'다")
        self.assertEqual("re_test_key", smtp.password, "API 키가 비밀번호 자리에 들어간다")
        self.assertTrue(smtp.use_tls)

    def test_explicit_smtp_host_wins_over_resend(self):
        """다른 메일 서버를 쓰는 사람의 기존 설정을 뺏으면 안 된다."""
        with patch.object(mailer.settings, "SMTP_HOST", "smtp.gmail.com"), \
             patch.object(mailer.settings, "SMTP_USER", "me"), \
             patch.object(mailer.settings, "SMTP_PASSWORD", "pw"), \
             patch.object(mailer.settings, "RESEND_API", "re_test_key"):
            smtp = mailer.resolve_smtp()

        self.assertEqual("smtp.gmail.com", smtp.host)
        self.assertEqual("pw", smtp.password)

    def test_smtp_host_without_password_falls_back_to_resend_api(self):
        """팀원들이 가장 밟기 쉬운 경로 (독립 리뷰 지적).

        기존 `.env`는 옛 `.env.example`에서 복사해 `SMTP_HOST=smtp.resend.com`이 이미
        들어 있다. 거기에 새 안내대로 `RESEND_API=`만 채우면, 예전에는 SMTP_HOST 분기를
        타면서 password가 None이 되어 **로그인을 건너뛰고 발송이 실패**했다.
        `.env.example`을 고쳐도 이미 존재하는 `.env`는 안 고쳐진다.
        """
        with patch.object(mailer.settings, "SMTP_HOST", "smtp.resend.com"), \
             patch.object(mailer.settings, "SMTP_USER", "resend"), \
             patch.object(mailer.settings, "SMTP_PASSWORD", None), \
             patch.object(mailer.settings, "RESEND_API", "re_test_key"):
            smtp = mailer.resolve_smtp()

        self.assertEqual("re_test_key", smtp.password)
        self.assertTrue(
            smtp.user and smtp.password,
            "사용자/비밀번호가 다 있어야 login()을 탄다 — 하나라도 비면 인증을 건너뛰고 "
            "Resend가 발송을 거부한다",
        )

    def test_nothing_set_means_unconfigured(self):
        with patch.object(mailer.settings, "SMTP_HOST", None), \
             patch.object(mailer.settings, "RESEND_API", None):
            self.assertIsNone(mailer.resolve_smtp().host)
            self.assertFalse(mailer.is_smtp_configured())


class UnconfiguredProductionNeverLogsLinkTest(unittest.TestCase):
    """SMTP **미설정** 경로에서도 운영이면 링크를 안 남기는가 (P0-4의 나머지 절반).

    독립 리뷰(2026-08-20)가 잡은 구멍이다. 위 `SendFailureFallbackTest`는 *발송 실패*
    경로만 고정하고 있었고, *미설정* 경로는 dev 쪽 테스트(`test_unconfigured_dev_...`)만
    있어 production 쌍이 없었다. 실제로 `mailer.py`의 미설정 폴백에서 `is_dev_environment()`
    가드를 `True`로 바꿔도 464개 테스트가 전부 통과했다 — **운영 로그에 재설정 링크를
    찍는 회귀를 아무도 못 잡는 상태**였다.
    """

    def test_production_unconfigured_does_not_log_the_link(self):
        with patch.object(mailer.settings, "SMTP_HOST", None), \
             patch.object(mailer.settings, "RESEND_API", None), \
             patch.object(mailer.settings, "ENV", "production"):
            with self.assertLogs("app.core.mailer", level="ERROR") as logs:
                sent = mailer.send_email(
                    "s@pusan.ac.kr", "제목",
                    "링크: http://x/reset-password?token=UNCONFIGURED_PROD_TOKEN",
                )

        output = "\n".join(logs.output)
        self.assertFalse(sent)
        self.assertNotIn(
            "UNCONFIGURED_PROD_TOKEN", output,
            "SMTP 미설정 상태의 운영 로그에 재설정 링크가 남으면 로그 접근자가 "
            "임의 계정을 가져갈 수 있다 (P0-4).",
        )
        # 링크는 막되 "왜 메일이 안 갔는지"는 남아야 추적이 된다.
        self.assertIn("SMTP", output)


class ResetUrlBaseGuardTest(unittest.TestCase):
    """배포에서 메일 링크가 localhost를 가리키면 경고하는가.

    독립 리뷰가 잡았다 — 이 가드를 `if False:`로 죽여도 테스트가 전부 통과했다.
    메일은 정상 발송되는데 링크가 받는 사람 PC의 localhost를 가리켜 열리지 않고,
    발송이 성공하니 아무도 눈치채지 못한다.
    """

    def _startup_logs(self, env: str, base: str):
        """가드는 매 발송이 아니라 **기동 시 한 번**(`startup_log`) 검사한다 —
        요청마다 같은 error를 반복해 찍으면 로그가 무의미해진다."""
        with patch.object(mailer.settings, "SMTP_HOST", None), \
             patch.object(mailer.settings, "RESEND_API", None), \
             patch.object(mailer.settings, "ENV", env), \
             patch.object(mailer.settings, "PASSWORD_RESET_URL_BASE", base):
            with self.assertLogs("app.core.mailer", level="WARNING") as logs:
                mailer.startup_log()
        return "\n".join(logs.output)

    def test_production_with_local_url_base_warns(self):
        for base in (
            "http://localhost:5173/reset-password",
            "http://127.0.0.1:5173/reset-password",
        ):
            with self.subTest(base=base):
                self.assertIn("PASSWORD_RESET_URL_BASE", self._startup_logs("production", base))

    def test_production_with_deployed_url_base_is_quiet(self):
        output = self._startup_logs("production", "https://planu-pnu.netlify.app/reset-password")
        self.assertNotIn("PASSWORD_RESET_URL_BASE", output)

    def test_dev_with_local_url_base_is_not_flagged(self):
        """로컬 개발자에게 오탐을 띄우면 진짜 경고를 무시하게 된다."""
        output = self._startup_logs("local", "http://localhost:5173/reset-password")
        self.assertNotIn("PASSWORD_RESET_URL_BASE", output)


class EnvExampleDoesNotCreateHalfConfiguredStateTest(unittest.TestCase):
    """`.env.example`을 그대로 복사해도 위 함정에 빠지지 않아야 한다."""

    def _example(self) -> str:
        path = pathlib.Path(__file__).resolve().parents[1] / ".env.example"
        self.assertTrue(path.exists(), ".env.example이 없다")
        return path.read_text()

    def test_smtp_host_is_not_enabled_by_default(self):
        text = self._example()
        offending = [
            line for line in text.splitlines()
            if line.strip().startswith("SMTP_HOST=") and line.strip() != "SMTP_HOST="
        ]
        self.assertEqual(
            [], offending,
            "SMTP_HOST가 주석 없이 값과 함께 들어 있다. SMTP_PASSWORD가 빈 채로 복사되면 "
            "메일도 안 가고 로그에 링크도 안 남는 상태가 된다 — 주석 처리해 두어야 한다.",
        )

    def test_smtp_password_is_not_shipped_with_a_value(self):
        """예시 파일에 실제 키가 섞여 들어가는 사고 방지."""
        for line in self._example().splitlines():
            stripped = line.strip()
            if stripped.startswith("SMTP_PASSWORD=") and stripped != "SMTP_PASSWORD=":
                self.fail(f".env.example에 SMTP_PASSWORD 값이 들어 있다: {stripped[:30]}")


class StartupLogTest(unittest.TestCase):
    """모듈 docstring이 "기동 로그에 경고가 남는다"고 적어놓고 실제로는 아무 데서도
    부르지 않았다 — 배포에서 SMTP를 빠뜨려도 조용했다."""

    def test_main_calls_mailer_startup_log(self):
        import inspect

        from app import main

        self.assertIn(
            "mailer_startup_log", inspect.getsource(main.lifespan),
            "기동 시 메일 설정 경고를 부르지 않으면, SMTP를 빠뜨린 배포가 조용히 나간다",
        )

    def test_production_without_smtp_logs_an_error(self):
        with patch.object(mailer.settings, "SMTP_HOST", None), \
             patch.object(mailer.settings, "RESEND_API", None), \
             patch.object(mailer.settings, "ENV", "production"):
            with self.assertLogs("app.core.mailer", level="ERROR") as logs:
                mailer.startup_log()
        self.assertIn("비밀번호", "\n".join(logs.output))

    def test_host_without_credentials_warns(self):
        """반쪽 설정을 기동 시점에 잡아준다."""
        with patch.object(mailer.settings, "SMTP_HOST", "smtp.resend.com"), \
             patch.object(mailer.settings, "SMTP_USER", "resend"), \
             patch.object(mailer.settings, "SMTP_PASSWORD", ""), \
             patch.object(mailer.settings, "RESEND_API", None):
            with self.assertLogs("app.core.mailer", level="WARNING") as logs:
                mailer.startup_log()
        self.assertIn("비밀번호가 비어", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
