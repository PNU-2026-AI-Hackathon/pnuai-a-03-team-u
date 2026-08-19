"""my.pusan certificate 페이지 열기 판정 (`_open_certificate_page`) 테스트.

2026-08-16~18에 학교 rSSO 에이전트가 자기 뒷단 검증 서버에 소켓을 못 열어
(`4,-105 socket_connect() failed`) my.pusan이 로그인 페이지와 **무한 왕복**했다.
그때 크롤러는 30초 타임아웃을 다 쓰고 그 다음 evaluate가 터졌으며, 호출부가 광범위
except로 삼켜서 **사용자에게는 이수 프로그램·자격증·어학이 이유 없이 비어 보였다.**

여기서는 네트워크 없이 판정 로직만 검증한다 — 페이지를 가짜로 만들어 URL 전이와
DOM 상태를 시나리오로 주입한다.
"""

import unittest

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.ingestion.crawlers.my_pusan_extracurricular import _open_certificate_page


class _FakePage:
    """URL/DOM 상태를 스텝별로 흉내내는 최소 Page."""

    def __init__(self, steps, *, ready_at=None, login_form=False, goto_timeout=False):
        # steps: 폴링마다 돌려줄 URL 목록 (모자라면 마지막 값을 반복)
        self._steps = steps
        self._i = -1
        self._ready_at = ready_at        # 이 인덱스부터 certificate 폼이 준비됨
        self._login_form = login_form    # 로그인 페이지에 #login_id가 떠 있는가
        self._goto_timeout = goto_timeout
        self.waited_networkidle = False

    @property
    def url(self):
        return self._steps[min(self._i, len(self._steps) - 1)] if self._i >= 0 else self._steps[0]

    def goto(self, url, **kwargs):
        self._i = 0
        if self._goto_timeout:
            raise PlaywrightTimeoutError("timeout")

    def evaluate(self, script):
        if "ModulePortfolioCertificate" in script and "data-role" in script:
            return self._ready_at is not None and self._i >= self._ready_at
        if "login_id" in script:
            return self._login_form
        return False

    def wait_for_timeout(self, ms):
        self._i += 1

    def wait_for_load_state(self, state, timeout=None):
        self.waited_networkidle = True


_CERT = "https://my.pusan.ac.kr/ko/extracurricular/career/certificate"
_LOGIN = "https://login.pusan.ac.kr/my/loginPage"
_SSO = "https://my.pusan.ac.kr/modules/pusan/rsso/loginCheck.php"


class OpenCertificatePageTest(unittest.TestCase):
    def test_normal_load_returns_none(self):
        page = _FakePage([_CERT] * 10, ready_at=2)
        self.assertIsNone(_open_certificate_page(page))
        # 폼을 본 뒤에는 목록 XHR을 기다려야 한다. 안 기다리면 행이 0으로 나온다.
        self.assertTrue(page.waited_networkidle)

    def test_handshake_passing_through_login_host_is_not_a_failure(self):
        """정상 핸드셰이크도 login.pusan.ac.kr을 거쳐 간다.

        첫 폴링에서 그 host를 봤다고 실패로 처리하면 **멀쩡한 로그인이 실패로 뒤집힌다**
        (이 함수를 고치다 실제로 그렇게 만들었다).
        """
        page = _FakePage([_LOGIN, _LOGIN, _CERT, _CERT, _CERT], ready_at=3, login_form=True)
        self.assertIsNone(_open_certificate_page(page))

    def test_sso_redirect_loop_is_reported(self):
        # loginCheck.php ↔ loginPage 왕복. 폼은 영영 안 뜬다.
        page = _FakePage([_SSO, _LOGIN, _SSO, _LOGIN, _SSO, _LOGIN] * 10)
        reason = _open_certificate_page(page)
        self.assertIsNotNone(reason)
        self.assertIn("무한 왕복", reason)

    def test_stuck_on_login_page_is_reported(self):
        page = _FakePage([_LOGIN] * 60, login_form=True)
        reason = _open_certificate_page(page)
        self.assertIsNotNone(reason)
        self.assertIn("로그인이 되지 않아", reason)

    def test_never_settles_reports_timeout(self):
        # 로그인 폼도 없고 루프도 아닌 알 수 없는 페이지에 머무는 경우.
        page = _FakePage(["https://my.pusan.ac.kr/ko/etc"] * 60)
        reason = _open_certificate_page(page)
        self.assertIsNotNone(reason)
        self.assertIn("시간 내에 열리지 않았습니다", reason)

    def test_goto_timeout_still_judges_by_final_location(self):
        """goto가 타임아웃 나도 실제 도달 지점으로 판단해야 한다."""
        page = _FakePage([_CERT] * 10, ready_at=1, goto_timeout=True)
        self.assertIsNone(_open_certificate_page(page))


if __name__ == "__main__":
    unittest.main()
