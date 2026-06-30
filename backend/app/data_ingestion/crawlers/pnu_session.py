from contextlib import contextmanager

from playwright.sync_api import Browser, Page, sync_playwright

from app.core.config import settings

LOGIN_URL = "https://onestop.pusan.ac.kr/login"


class PnuLoginError(Exception):
    pass


def login(browser: Browser, login_id: str | None = None, login_pw: str | None = None) -> Page:
    """One-Stop 포털에 로그인하고, 인증된 세션을 유지하는 Page를 반환한다.

    이 Page는 닫지 않고 그대로 재사용해야 한다 — 메뉴 이동이 selectMenu() JS
    호출(AJAX)로 이루어지고, 새 URL로 직접 navigate하면 세션이 끊겨 로그인
    페이지로 리다이렉트된다.
    """
    login_id = login_id or settings.PNU_LOGIN_ID
    login_pw = login_pw or settings.PNU_LOGIN_PW
    if not login_id or not login_pw:
        raise PnuLoginError("PNU_LOGIN_ID / PNU_LOGIN_PW가 설정되지 않았습니다 (.env 확인).")

    context = browser.new_context()
    page = context.new_page()
    page.goto(LOGIN_URL, wait_until="networkidle")

    page.click('a[href="#global_login"]')
    page.fill("#login_id", login_id)
    page.fill("#login_pw", login_pw)
    page.click("#btnLogin")

    page.wait_for_load_state("networkidle")

    if page.url.rstrip("/").endswith("/login"):
        context.close()
        raise PnuLoginError("로그인 실패: 아이디/비밀번호를 확인하세요.")

    return page


def goto_menu(page: Page, menu_cd: str) -> None:
    """로그인된 page에서 menuCD에 해당하는 메뉴 콘텐츠를 AJAX로 불러온다."""
    page.evaluate(f"selectMenu('{menu_cd}')")
    page.wait_for_load_state("networkidle")


@contextmanager
def pnu_session(login_id: str | None = None, login_pw: str | None = None):
    """로그인된 Page를 with 블록으로 사용할 수 있게 해주는 헬퍼."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = login(browser, login_id, login_pw)
        try:
            yield page
        finally:
            browser.close()
