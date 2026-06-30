from playwright.sync_api import Page

_EXTRACT_TABLES_JS = """
() => {
  const tables = Array.from(document.querySelectorAll('main table, .content table, table'));
  return tables.map(table => {
    const rows = Array.from(table.querySelectorAll('tr'));
    return rows.map(row => {
      const cells = Array.from(row.querySelectorAll('th, td'));
      return cells.map(c => c.textContent.trim());
    });
  });
}
"""


def extract_tables(page: Page) -> list[list[list[str]]]:
    """현재 페이지의 모든 <table>을 행x셀 텍스트의 2차원 배열 목록으로 추출한다.

    실제 menuCD별 페이지 구조(가로형 정보 테이블 vs 세로형 목록 테이블)가
    제각각이라, 우선 원시 테이블 데이터를 그대로 반환하고 각 도메인 파서가
    필요한 형태로 가공한다.
    """
    return page.evaluate(_EXTRACT_TABLES_JS)


def table_to_label_value_pairs(rows: list[list[str]]) -> dict[str, str]:
    """th/td가 번갈아 나오는 가로형 정보 테이블을 dict로 변환한다."""
    result: dict[str, str] = {}
    for row in rows:
        for i in range(0, len(row) - 1, 2):
            label, value = row[i], row[i + 1]
            if label:
                result[label] = value
    return result


_EXTRACT_ROW_ITEMS_JS = """
(selector) => {
  const container = document.querySelector(selector);
  if (!container) return {};
  const rows = Array.from(container.querySelectorAll('.b-row-item'));
  const result = {};
  for (const row of rows) {
    const label = row.querySelector('.b-title-box')?.textContent.trim();
    const value = row.querySelector('.b-con-box')?.textContent.trim();
    if (label) result[label] = value ?? '';
  }
  return result;
}
"""


def extract_row_items(page: Page, selector: str) -> dict[str, str]:
    """`.b-row-item`(`.b-title-box` 라벨 + `.b-con-box` 값) 구조의 기본정보
    섹션(예: 학적부 학번/이름/소속학과)을 dict로 추출한다.
    """
    return page.evaluate(_EXTRACT_ROW_ITEMS_JS, selector)
