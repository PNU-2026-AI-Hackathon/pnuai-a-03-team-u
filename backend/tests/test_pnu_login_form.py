"""One-Stop 로그인 폼 진입 회귀 테스트."""

from app.ingestion.crawlers.pnu_session import (
    ONESTOP_LOGIN_URL,
    _LOGIN_RESULT_TIMEOUT_MS,
    _ONESTOP_LOGIN_BUTTON_SELECTOR,
    _ONESTOP_LOGIN_ID_SELECTOR,
    _ONESTOP_LOGIN_PW_SELECTOR,
    _login_failure_message,
    _reach_login_form,
    _wait_for_initial_login_result,
)


class _CurrentOneStopLoginPage:
    """2026-08 개편 후 ``/login``의 로그인 블록을 흉내낸다."""

    def __init__(self):
        self.url = ONESTOP_LOGIN_URL
        self.events: list[str] = []

    def goto(self, url, **_kwargs):
        self.events.append(f"goto:{url}")

    def wait_for_selector(self, selector, **_kwargs):
        self.events.append(f"wait:{selector}")


def test_reach_login_form_uses_current_onestop_login_block():
    page = _CurrentOneStopLoginPage()

    _reach_login_form(page)

    assert page.events == [
        f"goto:{ONESTOP_LOGIN_URL}",
        f"wait:{_ONESTOP_LOGIN_ID_SELECTOR}",
        f"wait:{_ONESTOP_LOGIN_PW_SELECTOR}",
        f"wait:{_ONESTOP_LOGIN_BUTTON_SELECTOR}",
    ]


class _FailedLoginPage:
    def __init__(self, diagnostics, *, alert_after_first_poll=False):
        self.url = ONESTOP_LOGIN_URL
        self.diagnostics = diagnostics
        self.alert_after_first_poll = alert_after_first_poll
        self.polls = 0

    def wait_for_timeout(self, _ms):
        self.polls += 1
        if self.alert_after_first_poll and self.polls == 1:
            self.diagnostics["alerts"].append("아이디 또는 비밀번호 정보를 확인해주세요!")


def test_wrong_password_alert_is_detected_before_full_networkidle_wait():
    diagnostics = {"alerts": [], "popups": [], "sso_responses": [], "console": [], "pageerrors": []}
    page = _FailedLoginPage(diagnostics, alert_after_first_poll=True)

    assert _wait_for_initial_login_result(page, diagnostics) is False
    assert page.polls == 1
    assert "비밀번호" in _login_failure_message(diagnostics)


def test_login_page_without_any_response_is_not_false_failed_before_sso_budget():
    diagnostics = {"alerts": [], "popups": [], "sso_responses": [], "console": [], "pageerrors": []}
    page = _FailedLoginPage(diagnostics)

    # 4초는 alert를 빠르게 받을 기회일 뿐 실패 확정 기준이 아니다. 학교 SSO가
    # 느리면 이 뒤 기존 networkidle/selectMenu 검증으로 계속 진행해야 한다.
    assert _wait_for_initial_login_result(page, diagnostics) is None
    assert page.polls == _LOGIN_RESULT_TIMEOUT_MS // 100
