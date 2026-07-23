from playwright.sync_api import Page

from app.ingestion.crawlers import menu_codes
from app.ingestion.crawlers.pnu_session import goto_menu
from app.ingestion.crawlers.table_extract import extract_row_items


def fetch_student_record(page: Page) -> dict[str, str]:
    """학적부 기본정보(학번, 이름, 소속학과, 학년/학기 등)를 dict로 가져온다.

    학적부 페이지의 "학적" 탭 상단 기본정보 영역은 <table>이 아니라
    .b-row-item(.b-title-box 라벨 + .b-con-box 값) 구조로 렌더링된다.

    "지도교수" 항목은 예외 — 그 라벨의 값 영역(`data-bind="text: ADVICE_PROF_NO"`)이
    지도교수 사번을 담는 필드인데 실계정으로 확인해보니 늘 빈 값이었다. 실제
    이름은 화면엔 안 뜨지만 이 페이지가 로드하는 API 응답(selectStdtInfo)의
    `HB_ADVICE_PROF_NM` 필드에 들어있어서, 그 응답을 가로채 보정한다.
    """
    advisor_name = ""

    def _capture_advisor(response):
        nonlocal advisor_name
        if "selectStdtInfo" not in response.url:
            return
        try:
            data = response.json().get("data", {})
        except Exception:  # noqa: BLE001 - 응답 파싱 실패해도 나머지 학적부 크롤링은 계속한다
            return
        advisor_name = (data.get("HB_ADVICE_PROF_NM") or "").strip()

    page.on("response", _capture_advisor)
    goto_menu(page, menu_codes.STUDENT_RECORD)
    record = extract_row_items(page, "#tab-cont1")
    page.remove_listener("response", _capture_advisor)

    if advisor_name:
        record["지도교수"] = advisor_name
    return record
