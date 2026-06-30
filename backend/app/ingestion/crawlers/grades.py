from playwright.sync_api import Page

from app.ingestion.crawlers import menu_codes
from app.ingestion.crawlers.pnu_session import goto_menu
from app.ingestion.crawlers.table_extract import extract_tables


def fetch_current_semester_grades(page: Page) -> list[list[list[str]]]:
    """금학기 성적표 원시 테이블(과목별 행 목록)을 가져온다."""
    goto_menu(page, menu_codes.GRADES_CURRENT_SEMESTER)
    return extract_tables(page)


def fetch_all_grades(page: Page) -> list[list[list[str]]]:
    """전체 학기 성적표 원시 테이블을 가져온다 (학기별 GPA 계산에 사용)."""
    goto_menu(page, menu_codes.GRADES_ALL)
    return extract_tables(page)
