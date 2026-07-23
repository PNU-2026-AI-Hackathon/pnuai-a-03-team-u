import logging
from contextlib import contextmanager

from playwright.sync_api import Browser, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.core.config import settings

_logger = logging.getLogger(__name__)

ONESTOP_URL = "https://onestop.pusan.ac.kr"

_LOGIN_FORM_ATTEMPTS = 3
_LOGIN_FORM_TIMEOUT_MS = 12_000


class PnuLoginError(Exception):
    pass


def _evaluate_stable(page: Page, script: str, attempts: int = 3):
    """로그인 성공 시 리다이렉트가 몇 단계 이어지는데, 그 중간에 evaluate를 걸면
    "Execution context was destroyed, most likely because of a navigation"로
    터진다(2026-07-22 실계정 테스트로 실제로 겪음 — networkidle+타임아웃까지
    기다린 뒤에도 그 다음 순간에 또 네비게이션이 걸렸다). 로드 상태를 다시
    기다리고 재시도해서 이 레이스를 흡수한다.
    """
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return page.evaluate(script)
        except Exception as exc:  # noqa: BLE001 - Playwright 내부 에러 타입이 버전마다 달라 광범위하게 잡는다
            last_error = exc
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(300)
    assert last_error is not None
    raise last_error


def _wait_for_select_menu(page: Page, timeout_ms: int = 8000, interval_ms: int = 500) -> bool:
    """window.selectMenu가 정의될 때까지 짧은 간격으로 폴링한다.

    2026-07-22 실계정 테스트로 확인: 로그인이 성공해 onestop.pusan.ac.kr/main까지
    도달해도, 그 페이지의 JS가 아직 초기화 중이라 곧바로 확인하면 selectMenu가
    일시적으로 undefined일 수 있다(networkidle+1초 대기로도 부족했던 사례가 있음).
    이건 예외를 던지지 않고 그냥 "아직 없음"을 반환하는 경우라 _evaluate_stable의
    예외 기반 재시도로는 못 잡는다 — 값 자체를 폴링해야 한다.
    """
    elapsed = 0
    while elapsed <= timeout_ms:
        if _evaluate_stable(page, "typeof window.selectMenu") == "function":
            return True
        page.wait_for_timeout(interval_ms)
        elapsed += interval_ms
    return _evaluate_stable(page, "typeof window.selectMenu") == "function"


def _reach_login_form(page: Page) -> None:
    """onestop.pusan.ac.kr을 거쳐 login.pusan.ac.kr의 "아이디 로그인" 입력폼(#login_id)이
    실제로 보일 때까지 페이지를 연다.

    **반드시 onestop.pusan.ac.kr에서 "#global_login" 링크를 클릭해서 들어가야 한다.**
    2026-07-22 실계정 테스트로 확인: login.pusan.ac.kr/onestop/loginPage로 직접
    이동(직링크)하면 로그인 페이지의 `csrfToken` JS 전역변수가 빈 문자열로 렌더링돼서,
    로그인 자체(아이디/비밀번호 검증, sToken 발급)는 성공해도 그 다음 단계인
    onestop.pusan.ac.kr로의 세션 핸드오프(`restoreSite()`가 만드는 폼 POST의 `_csrf`
    필드)가 서버에서 거부돼 `/login`으로 되돌아온다. onestop.pusan.ac.kr에서 자연스럽게
    "#global_login"을 클릭해 들어가야만(리퍼러 체인) csrfToken이 정상적으로 채워진다 —
    직링크가 더 간단해 보여서 한 번 바꿨다가 이걸로 한참 헤맸다.

    이 사이트는 같은 코드를 여러 번 돌려도 렌더링 타이밍이 매번 조금씩 달라서
    (networkidle 이후에도 #idpwTab이 아직 없거나, 있어도 탭 전환 클릭이 안 먹는 경우가
    재현 시마다 달랐다), 한 시퀀스 안에서 미세하게 맞추기보다 안 되면 페이지를 통째로
    다시 열어 재시도한다.
    """
    last_error: PlaywrightTimeoutError | None = None
    for _ in range(_LOGIN_FORM_ATTEMPTS):
        page.goto(ONESTOP_URL, wait_until="networkidle")
        try:
            with page.expect_navigation():
                page.click('a[href="#global_login"]')
            page.wait_for_load_state("networkidle")
            page.wait_for_selector("#idpwTab > a", state="visible", timeout=_LOGIN_FORM_TIMEOUT_MS)
            if not page.evaluate("document.querySelector('#login_id')?.offsetParent !== null"):
                page.click("#idpwTab > a")
            page.wait_for_selector("#login_id", state="visible", timeout=_LOGIN_FORM_TIMEOUT_MS)
            return
        except PlaywrightTimeoutError as exc:
            last_error = exc
    assert last_error is not None
    raise PnuLoginError(
        "One-Stop 로그인 페이지 로딩에 실패했습니다(사이트 응답 지연). 잠시 후 다시 시도해주세요."
    ) from last_error


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

    # 로그인 실패 시 이 사이트는 페이지 이동 없이 브라우저 네이티브 alert()로만
    # 에러를 띄운다(예: "아이디 또는 비밀번호 정보를 확인해주세요!"). 핸들러가
    # 없으면 Playwright가 dialog를 조용히 자동 닫아버려서 실패 사유를 전혀 알 수
    # 없다 — 반드시 캡처해서 진단에 쓴다. 2차 인증(2FA) 대상 계정은 alert 대신
    # popupLinkTo('2FALogin', ...)로 새 팝업 창을 띄우는 별도 분기라 그것도 감지한다.
    diagnostics: dict[str, list[str]] = {
        "alerts": [],
        "sso_responses": [],
        "popups": [],
        "console": [],
        "pageerrors": [],
    }

    def _capture_dialog(dialog):
        diagnostics["alerts"].append(dialog.message)
        dialog.dismiss()

    def _capture_console(msg):
        if msg.type == "error":
            diagnostics["console"].append(msg.text)

    def _capture_pageerror(exc):
        diagnostics["pageerrors"].append(str(exc))

    def _capture_sso_response(response):
        if "/common/sso/" not in response.url:
            return
        try:
            diagnostics["sso_responses"].append(f"{response.url} -> {response.text()[:500]}")
        except Exception:  # noqa: BLE001 - 진단 목적이라 응답 본문을 못 읽어도 로그인 흐름을 막지 않는다
            pass

    def _capture_popup(popup):
        diagnostics["popups"].append(popup.url)

    page.on("dialog", _capture_dialog)
    page.on("response", _capture_sso_response)
    page.on("console", _capture_console)
    page.on("pageerror", _capture_pageerror)
    context.on("page", _capture_popup)

    _reach_login_form(page)
    page.fill("#login_id", login_id)
    page.fill("#login_pw", login_pw)
    page.click("#btnLogin")

    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)  # 2FA 팝업/alert가 뜨는 데 약간의 지연이 있어 캡처를 놓치지 않게 여유를 둔다

    if page.url.rstrip("/").endswith("/login"):
        _logger.warning(
            "로그인 후 /login으로 리다이렉트됨 — 실패로 판단. url=%s diagnostics=%s",
            page.url,
            diagnostics,
        )
        context.close()
        if diagnostics["popups"]:
            raise PnuLoginError(
                "로그인 실패: 이 계정은 2차 인증(이메일)이 필요해 자동 로그인을 지원하지 않습니다. "
                "One-Stop 포털에서 직접 로그인해주세요."
            )
        if diagnostics["alerts"]:
            raise PnuLoginError(f"로그인 실패: {diagnostics['alerts'][-1]}")
        raise PnuLoginError("로그인 실패: 아이디/비밀번호를 확인하세요.")

    if "UpdatePassword" in page.url:
        # "다음에 변경하기" 링크는 href="javascript:onclick=changeNextPw();" 형태라
        # 클릭 대신 해당 JS 함수를 직접 호출해야 한다. 호출이 페이지 이동을
        # 유발하므로 expect_navigation으로 감싸야 evaluate 중 context가
        # 파괴되는 에러를 피할 수 있다.
        with page.expect_navigation():
            page.evaluate("changeNextPw()")
        page.wait_for_load_state("networkidle")

    # URL만으로는 로그인 실패를 못 잡는 경우가 있다(로그인 페이지에 에러 배너만
    # 뜨고 URL이 안 바뀌거나, 실패해도 리다이렉트되는 경로가 "/login"으로 안
    # 끝나는 경우). 여기서 못 잡으면 goto_menu()의 selectMenu() 호출이
    # "ReferenceError: selectMenu is not defined"로 알 수 없이 터진다 — 그
    # 전에 실제로 인증된 포털 페이지인지(selectMenu가 정의돼 있는지) 확인해서
    # 명확한 PnuLoginError로 실패시킨다. UpdatePassword 처리가 끝난 뒤에
    # 검사해야 그 중간 페이지를 로그인 실패로 오탐하지 않는다.
    if not _wait_for_select_menu(page):
        # PnuLoginError는 api/portal_sync.py에서 별도 로깅 없이 401로 변환되므로,
        # "왜" 실패했는지(2차 인증 요구 화면인지, 다른 안내 페이지인지) 원인 추적이
        # 안 남는다. raise 전에 진단용으로 남긴다.
        try:
            page_title = page.title()
        except Exception:  # noqa: BLE001 - 진단 로그용이라 실패해도 로그인 흐름을 막지 않는다
            page_title = None
        try:
            body_snippet = page.inner_text("body")[:300] if page.query_selector("body") else None
        except Exception:  # noqa: BLE001
            body_snippet = None
        _logger.warning(
            "selectMenu 없음 — 로그인 실패로 판단. url=%s title=%s diagnostics=%s body_snippet=%r",
            page.url,
            page_title,
            diagnostics,
            body_snippet,
        )
        context.close()
        if diagnostics["popups"]:
            raise PnuLoginError(
                "로그인 실패: 이 계정은 2차 인증(이메일)이 필요해 자동 로그인을 지원하지 않습니다. "
                "One-Stop 포털에서 직접 로그인해주세요."
            )
        if diagnostics["alerts"]:
            raise PnuLoginError(f"로그인 실패: {diagnostics['alerts'][-1]}")
        raise PnuLoginError(
            "로그인 실패: 포털 인증에 실패했습니다(아이디/비밀번호를 확인하거나 잠시 후 다시 시도하세요)."
        )

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
