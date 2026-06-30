from playwright.sync_api import Page

from app.data_ingestion.crawlers import menu_codes
from app.data_ingestion.crawlers.pnu_session import goto_menu
from app.data_ingestion.crawlers.table_extract import extract_tables, table_to_label_value_pairs


def fetch_student_record(page: Page) -> dict[str, str]:
    """학적부(학번, 이름, 학부, 전공, 학년 등)를 dict로 가져온다."""
    goto_menu(page, menu_codes.STUDENT_RECORD)
    tables = extract_tables(page)
    record: dict[str, str] = {}
    for rows in tables:
        record.update(table_to_label_value_pairs(rows))
    return record
