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

from app.ingestion.crawlers.my_pusan_extracurricular import (
    LEGACY_MY_LOGIN_URL,
    _LEGACY_LOGIN_BUTTON_SELECTOR,
    _LEGACY_LOGIN_ID_SELECTOR,
    _LEGACY_LOGIN_PW_SELECTOR,
    _login_to_legacy_my_pusan,
    _open_certificate_page,
)


class _FakePage:
    """URL/DOM 상태를 스텝별로 흉내내는 최소 Page."""

    def __init__(self, steps, *, ready_at=None, login_form=False, goto_timeout=False,
                 evaluate_raises_until=0, networkidle_timeout=False):
        # steps: 폴링마다 돌려줄 URL 목록 (모자라면 마지막 값을 반복)
        self._steps = steps
        self._i = -1
        self._ready_at = ready_at        # 이 인덱스부터 certificate 폼이 준비됨
        self._login_form = login_form    # 로그인 페이지에 #login_id가 떠 있는가
        self._goto_timeout = goto_timeout
        # 리다이렉트 중이면 실제 Playwright는 "Execution context was destroyed"를 던진다.
        # 이 사태의 발단이 정확히 그거였는데 가짜 Page가 절대 안 던져서 그 경로가
        # 테스트되지 않았다(독립 리뷰 지적).
        self._evaluate_raises_until = evaluate_raises_until
        self._networkidle_timeout = networkidle_timeout
        self.waited_networkidle = False
        self.goto_kwargs: dict = {}

    @property
    def url(self):
        return self._steps[min(self._i, len(self._steps) - 1)] if self._i >= 0 else self._steps[0]

    def goto(self, url, **kwargs):
        self._i = 0
        # 어떤 인자로 열었는지 기록한다. `wait_until`이 networkidle로 되돌아가면 이
        # 사태의 원인(무한 왕복에서 networkidle이 영영 안 옴)이 그대로 재발하는데,
        # 예전 가짜 Page는 kwargs를 버려서 **근본 수정 자체가 테스트로 고정되지
        # 않았다**(독립 2차 리뷰의 뮤테이션에서 생존).
        self.goto_kwargs = dict(kwargs)
        if self._goto_timeout:
            raise PlaywrightTimeoutError("timeout")

    def evaluate(self, script):
        if self._i < self._evaluate_raises_until:
            raise RuntimeError("Execution context was destroyed, most likely because of a navigation")
        if "ModulePortfolioCertificate" in script and "data-role" in script:
            return self._ready_at is not None and self._i >= self._ready_at
        if "login_id" in script:
            return self._login_form
        return False

    def wait_for_timeout(self, ms):
        self._i += 1

    def wait_for_load_state(self, state, timeout=None):
        self.waited_networkidle = True
        if self._networkidle_timeout:
            raise PlaywrightTimeoutError("networkidle timeout")


_CERT = "https://my.pusan.ac.kr/ko/extracurricular/career/certificate"
_LOGIN = "https://login.pusan.ac.kr/my/loginPage"
_SSO = "https://my.pusan.ac.kr/modules/pusan/rsso/loginCheck.php"


class _LegacyLoginPage:
    """One-Stop 신규 로그인 뒤 My Pusan 구형 폼이 다시 나타난 상태."""

    def __init__(self):
        self.url = _LOGIN
        self.events: list[tuple] = []

    def goto(self, url, **kwargs):
        self.events.append(("goto", url, kwargs))
        self.url = _LOGIN

    def wait_for_selector(self, selector, **_kwargs):
        self.events.append(("wait", selector))

    def fill(self, selector, value):
        self.events.append(("fill", selector, value))

    def click(self, selector):
        self.events.append(("click", selector))
        self.url = "https://my.pusan.ac.kr/"

    def wait_for_load_state(self, state, **_kwargs):
        self.events.append(("load", state))

    def wait_for_timeout(self, ms):
        self.events.append(("sleep", ms))


class OpenCertificatePageTest(unittest.TestCase):
    def test_legacy_my_pusan_login_uses_its_own_form_after_onestop_login(self):
        page = _LegacyLoginPage()

        self.assertIsNone(_login_to_legacy_my_pusan(page, "20260001", "test-password"))

        self.assertEqual(("goto", LEGACY_MY_LOGIN_URL, {
            "wait_until": "domcontentloaded", "timeout": 10_000,
        }), page.events[0])
        self.assertIn(("wait", _LEGACY_LOGIN_ID_SELECTOR), page.events)
        self.assertIn(("wait", _LEGACY_LOGIN_PW_SELECTOR), page.events)
        self.assertIn(("fill", _LEGACY_LOGIN_ID_SELECTOR, "20260001"), page.events)
        self.assertIn(("fill", _LEGACY_LOGIN_PW_SELECTOR, "test-password"), page.events)
        self.assertIn(("click", _LEGACY_LOGIN_BUTTON_SELECTOR), page.events)

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

    def test_page_is_opened_without_waiting_for_networkidle(self):
        """`networkidle`로 열면 이 사태의 원인이 그대로 재발한다.

        rSSO가 무한 왕복하면 networkidle은 영영 오지 않는다 — 30초를 버리고 그 다음
        evaluate가 터진 게 이 크롤러가 조용히 실패하던 이유였다.
        """
        page = _FakePage([_CERT] * 5, ready_at=1)
        _open_certificate_page(page)
        self.assertEqual("domcontentloaded", page.goto_kwargs.get("wait_until"))
        # goto 타임아웃도 고정한다. 뒤에 폴링이 붙으므로 30초를 다 쓰면 루프가 아닌
        # 실패에서 총 대기가 오히려 예전보다 길어진다.
        self.assertLessEqual(page.goto_kwargs.get("timeout", 10**9), 10_000)

    def test_repeated_same_sso_url_is_not_counted_as_loop(self):
        """같은 loginCheck.php URL에 오래 머무는 건 왕복이 아니다.

        URL 중복 제거를 빼면 "느리게 한 번 지나가는 중"을 루프로 오판한다.
        (독립 리뷰 1·2차 모두에서 생존한 뮤테이션 — 이번에 덮는다.)
        """
        page = _FakePage([_SSO] * 6 + [_CERT] * 5, ready_at=6)
        self.assertIsNone(_open_certificate_page(page))

    def test_flapping_login_form_does_not_trigger_failure(self):
        """폼이 떴다 사라졌다 하면 연속 카운터가 리셋돼야 한다.

        `_LOGIN_FORM_CONFIRM_POLLS`가 실제로 일하는 유일한 경우다 — 리셋이 없으면
        경유 중 잠깐 그려진 폼이 누적돼 "로그인 실패"로 오판한다.
        """
        page = _FakePage([_LOGIN, _CERT] * 20 + [_CERT] * 5, ready_at=41, login_form=True)
        reason = _open_certificate_page(page)
        self.assertNotIn("로그인이 되지 않아", reason or "")

    def test_settle_budget_is_not_shorter_than_before(self):
        """느리지만 정상인 핸드셰이크의 성공 예산을 줄이면 안 된다.

        main은 networkidle 30초 예산이었다. 총 폴링 예산을 15초로 줄이면 학교 SSO가
        느릴 때(=이 코드가 겨냥한 바로 그 상황) 정상 로그인이 하드 실패로 뒤집힌다.
        루프·폼 고착은 각각 3초·8초에 이미 조기 반환하므로 예산을 길게 둬도 손해가 없다.
        """
        from app.ingestion.crawlers.my_pusan_extracurricular import _PAGE_SETTLE_TIMEOUT_MS

        self.assertGreaterEqual(_PAGE_SETTLE_TIMEOUT_MS, 25_000)

    def test_slow_handshake_through_login_page_still_succeeds(self):
        """느리지만 복구되는 핸드셰이크를 하드 실패로 뒤집으면 안 된다.

        독립 리뷰가 4초짜리 핸드셰이크로 재현했다. 하필 이 코드가 겨냥한 상황
        (학교 SSO 부하)에서 정확히 그런 지연이 난다. 로그인 폼이 **연속**으로 관찰될
        때만 실패로 확정해야 한다.
        """
        # 0.5초 폴링 기준 12스텝(=6초) 동안 로그인 호스트에 머물다 착지.
        steps = [_LOGIN] * 12 + [_CERT] * 10
        page = _FakePage(steps, ready_at=13, login_form=True)
        self.assertIsNone(_open_certificate_page(page))

    def test_login_form_must_be_present_to_declare_login_failure(self):
        """로그인 호스트에 있어도 폼이 없으면(리다이렉트 경유 중) 실패로 보지 않는다.

        관찰 유예(8초)를 훌쩍 넘겨 20스텝(=10초)을 머물러도, 폼이 없으면
        "로그인이 되지 않아…"로 단정하면 안 된다.
        """
        page = _FakePage([_LOGIN] * 20 + [_CERT] * 10, ready_at=21, login_form=False)
        self.assertIsNone(_open_certificate_page(page))

    def test_single_sso_check_passthrough_is_not_a_loop(self):
        """정상 핸드셰이크도 loginCheck.php를 몇 번 경유할 수 있다 — 루프로 보면 안 된다."""
        page = _FakePage([_SSO, _CERT, _SSO, _CERT, _CERT], ready_at=4)
        self.assertIsNone(_open_certificate_page(page))

    def test_evaluate_exception_during_redirect_is_survived(self):
        """리다이렉트 중 evaluate가 터져도 다음 폴링에서 회복해야 한다.

        이 사태의 발단이 "Execution context was destroyed"였다.
        """
        page = _FakePage([_CERT] * 10, ready_at=2, evaluate_raises_until=4)
        self.assertIsNone(_open_certificate_page(page))

    def test_networkidle_timeout_does_not_fail_the_page(self):
        """목록 XHR이 느려도 추출은 시도한다 — 빈 결과면 그건 그대로 보고된다."""
        page = _FakePage([_CERT] * 10, ready_at=1, networkidle_timeout=True)
        self.assertIsNone(_open_certificate_page(page))
        self.assertTrue(page.waited_networkidle)

    def test_failure_reason_does_not_leak_query_string(self):
        """실패 사유는 응답 본문·로그로 나간다. rSSO URL에는 토큰·학번이 붙을 수 있다."""
        leaky = "https://my.pusan.ac.kr/x?ssoToken=SECRET123&sid=202012345"
        page = _FakePage([leaky] * 60)
        reason = _open_certificate_page(page)
        self.assertIsNotNone(reason)
        self.assertNotIn("SECRET123", reason)
        self.assertNotIn("202012345", reason)
        self.assertIn("my.pusan.ac.kr/x", reason)   # 어디서 멈췄는지는 남는다

    def test_failure_reason_masks_id_in_path(self):
        """쿼리스트링만 떼면 경로에 박힌 학번은 그대로 나간다."""
        page = _FakePage(["https://my.pusan.ac.kr/student/202012345/detail"] * 70)
        reason = _open_certificate_page(page)
        self.assertNotIn("202012345", reason or "")

    def test_goto_timeout_still_judges_by_final_location(self):
        """goto가 타임아웃 나도 실제 도달 지점으로 판단해야 한다."""
        page = _FakePage([_CERT] * 10, ready_at=1, goto_timeout=True)
        self.assertIsNone(_open_certificate_page(page))


if __name__ == "__main__":
    unittest.main()
