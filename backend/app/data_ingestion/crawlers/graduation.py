from playwright.sync_api import Page

from app.data_ingestion.crawlers import menu_codes
from app.data_ingestion.crawlers.pnu_session import goto_menu
from app.data_ingestion.crawlers.table_extract import extract_tables


def fetch_graduation_requirement(page: Page) -> list[list[list[str]]]:
    """졸업요건기준 및 충족여부(이수학점/요건학점/남은학점 등) 원시 테이블을 가져온다."""
    goto_menu(page, menu_codes.GRADUATION_REQUIREMENT)
    return extract_tables(page)
