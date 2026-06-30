from playwright.sync_api import Page

from app.data_ingestion.crawlers import menu_codes
from app.data_ingestion.crawlers.pnu_session import goto_menu
from app.data_ingestion.crawlers.table_extract import extract_row_items


def fetch_student_record(page: Page) -> dict[str, str]:
    """학적부 기본정보(학번, 이름, 소속학과, 학년/학기 등)를 dict로 가져온다.

    학적부 페이지의 "학적" 탭 상단 기본정보 영역은 <table>이 아니라
    .b-row-item(.b-title-box 라벨 + .b-con-box 값) 구조로 렌더링된다.
    """
    goto_menu(page, menu_codes.STUDENT_RECORD)
    return extract_row_items(page, "#tab-cont1")
