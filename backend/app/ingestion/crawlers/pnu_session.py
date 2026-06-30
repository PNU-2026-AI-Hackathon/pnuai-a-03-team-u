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
    page.wait_for_timeout(500)  # 로그인 레이어 오픈 애니메이션 대기
    page.click("#idpwTab > a")  # 기본 활성 탭은 "스마트 로그인" — "아이디 로그인" 탭으로 전환
    page.wait_for_selector("#login_id", state="visible")
    page.fill("#login_id", login_id)
    page.fill("#login_pw", login_pw)
    page.click("#btnLogin")

    page.wait_for_load_state("networkidle")

    if page.url.rstrip("/").endswith("/login"):
        context.close()
        raise PnuLoginError("로그인 실패: 아이디/비밀번호를 확인하세요.")

    if "UpdatePassword" in page.url:
        # "다음에 변경하기" 링크는 href="javascript:onclick=changeNextPw();" 형태라
        # 클릭 대신 해당 JS 함수를 직접 호출해야 한다. 호출이 페이지 이동을
        # 유발하므로 expect_navigation으로 감싸야 evaluate 중 context가
        # 파괴되는 에러를 피할 수 있다.
        with page.expect_navigation():
            page.evaluate("changeNextPw()")
        page.wait_for_load_state("networkidle")

    return page


def goto_menu(page: Page, menu_cd: str) -> None:
    """로그인된 page에서 menuCD에 해당하는 메뉴로 이동한다.

    selectMenu()는 AJAX 콘텐츠 교체가 아니라 실제 페이지 네비게이션
    (?menuCD=...)을 일으키므로 expect_navigation으로 감싸야 한다.
    """
    with page.expect_navigation():
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
