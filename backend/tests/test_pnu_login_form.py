"""One-Stop 로그인 폼 진입 회귀 테스트."""

from app.ingestion.crawlers.pnu_session import (
    ONESTOP_LOGIN_URL,
    _ONESTOP_LOGIN_BUTTON_SELECTOR,
    _ONESTOP_LOGIN_ID_SELECTOR,
    _ONESTOP_LOGIN_PW_SELECTOR,
    _reach_login_form,
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
