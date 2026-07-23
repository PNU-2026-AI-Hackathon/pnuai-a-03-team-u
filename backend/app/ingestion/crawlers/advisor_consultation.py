"""지도교수 상담내역 크롤링 — 해당 학기 상담의 "상태" 값만 필요하다.

실계정으로 확인한 테이블 구조(<table>, extract_tables로 바로 파싱 가능):
['상담구분', '상담형태', '교수', '상담내용', '학생신청일자', '상담희망일시', '상태']
"학기" 컬럼은 따로 없어서 "상담희망일시"의 연/월로 학기를 역산한다(frontend의
getCurrentAcademicTerm과 동일한 규칙: 1~2월=전년도 2학기, 3~8월=1학기, 9~12월=2학기).
"""

from playwright.sync_api import Page

from app.ingestion.crawlers import menu_codes
from app.ingestion.crawlers.pnu_session import goto_menu
from app.ingestion.crawlers.table_extract import extract_tables

_DATE_COLUMN = "상담희망일시"
_STATUS_COLUMN = "상태"


def _row_to_academic_term(date_str: str) -> tuple[int, int] | None:
    try:
        year, month = int(date_str[:4]), int(date_str[5:7])
    except (ValueError, IndexError):
        return None
    if month <= 2:
        return year - 1, 2
    if month <= 8:
        return year, 1
    return year, 2


def fetch_current_term_consultation_status(page: Page, year: int, semester: int) -> str | None:
    """지정한 학년도/학기에 해당하는 상담 신청의 "상태"를 가져온다.

    같은 학기에 여러 건이 있으면 상담희망일시가 가장 최근인 것을 쓴다.
    해당 학기 신청 내역이 없으면 None.
    """
    goto_menu(page, menu_codes.ADVISOR_CONSULTATION)
    tables = extract_tables(page)
    if not tables or len(tables[0]) < 2:
        return None

    header, rows = tables[0][0], tables[0][1:]
    if _DATE_COLUMN not in header or _STATUS_COLUMN not in header:
        return None
    date_idx, status_idx = header.index(_DATE_COLUMN), header.index(_STATUS_COLUMN)

    matches = []
    for row in rows:
        if len(row) <= max(date_idx, status_idx):
            continue
        term = _row_to_academic_term(row[date_idx])
        if term == (year, semester):
            matches.append((row[date_idx], row[status_idx]))

    if not matches:
        return None
    matches.sort(key=lambda m: m[0], reverse=True)
    return matches[0][1]
