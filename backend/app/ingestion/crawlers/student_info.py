from playwright.sync_api import Page

from app.ingestion.crawlers import menu_codes
from app.ingestion.crawlers.pnu_session import goto_menu
from app.ingestion.crawlers.table_extract import extract_row_items, extract_tables


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


# 학적변동 표를 식별하는 헤더 조각. 학적부 페이지에는 표가 여러 개 있어서
# (수강/성적/장학 등) 헤더로 골라내야 한다.
_STATUS_CHANGE_HEADERS = ("학년도", "변동구분")


def fetch_academic_status_changes(page: Page) -> list[dict[str, str]]:
    """학적부의 "학적변동" 내역을 행 dict 목록으로 가져온다.

    실계정 확인(2026-08-19) 기준 헤더는
    `No | 학년도 | 학기 | 변동일자 | 변동구분 | 취소여부 | 취소일자 | 비고`이고,
    편입생은 `2026 | 1학기 | 2026-03-01 | 편입학 | N` 행을 갖는다. 이 값으로
    `admission_type`을 자동 판정한다 — 회원가입 때 사용자가 고르는 값에만 의존하면
    잘못 고른 순간 로드맵 학년이 통째로 어긋난다(편입생이 1학년으로 잡힘).

    이 함수는 `fetch_student_record`와 같은 학적부 메뉴를 쓴다. 표를 못 찾으면
    빈 목록을 돌려주고, 호출부는 그때 기존 `admission_type`을 유지한다.
    """
    goto_menu(page, menu_codes.STUDENT_RECORD)
    for table in extract_tables(page):
        if len(table) < 2:
            continue
        header = [cell.strip() for cell in table[0]]
        if not all(any(mark == cell for cell in header) for mark in _STATUS_CHANGE_HEADERS):
            continue
        return [
            dict(zip(header, row))
            for row in table[1:]
            if len(row) == len(header) and row != header
        ]
    return []
