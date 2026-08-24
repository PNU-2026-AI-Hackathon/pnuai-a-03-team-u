"""One-Stop 로그인 폼 진입 회귀 테스트."""

from contextlib import nullcontext

from app.ingestion.crawlers.pnu_session import _reach_login_form


class _PopupCloseLinks:
    def __init__(self, page):
        self.page = page

    def evaluate_all(self, _script):
        self.page.popup_visible = False
        self.page.events.append("popup_closed")
        return 1


class _LoginPageWithBlockingPopup:
    """아이디 로그인 탭 위를 공지 팝업이 덮은 실제 사이트 상태를 흉내낸다."""

    def __init__(self):
        self.popup_visible = True
        self.login_form_visible = False
        self.url = "https://login.pusan.ac.kr/onestop/loginPage"
        self.events: list[str] = []

    def goto(self, _url, **_kwargs):
        self.events.append("goto")

    def expect_navigation(self):
        return nullcontext()

    def click(self, selector):
        self.events.append(f"click:{selector}")
        if selector == "#idpwTab > a":
            if self.popup_visible:
                raise AssertionError("공지 팝업이 아이디 로그인 탭을 가리고 있음")
            self.login_form_visible = True

    def wait_for_load_state(self, _state):
        return None

    def wait_for_selector(self, selector, **_kwargs):
        if selector == "#login_id" and not self.login_form_visible:
            raise AssertionError("아이디 로그인 폼이 아직 보이지 않음")
        return None

    def wait_for_timeout(self, _timeout):
        return None

    def locator(self, _selector):
        return _PopupCloseLinks(self)

    def evaluate(self, _script):
        return self.login_form_visible


def test_reach_login_form_closes_notice_popup_before_clicking_id_tab():
    page = _LoginPageWithBlockingPopup()

    _reach_login_form(page)

    assert page.login_form_visible is True
    assert page.events.index("popup_closed") < page.events.index("click:#idpwTab > a")
