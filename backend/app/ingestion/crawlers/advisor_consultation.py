"""지도교수 상담내역 크롤링 — 해당 학기 상담의 "상태" 값만 필요하다.

실계정으로 확인한 테이블 구조(<table>, extract_tables로 바로 파싱 가능):
['상담구분', '상담형태', '교수', '상담내용', '학생신청일자', '상담희망일시', '상태']
"학기" 컬럼은 따로 없어서 "상담희망일시"의 연/월로 학기를 역산한다(frontend의
getCurrentAcademicTerm과 동일한 규칙: 1~2월=전년도 2학기, 3~8월=1학기, 9~12월=2학기).
"""

import logging

from playwright.sync_api import Page

from app.ingestion.crawlers import menu_codes
from app.ingestion.crawlers.pnu_session import goto_menu
from app.ingestion.crawlers.table_extract import extract_tables

_logger = logging.getLogger(__name__)

_DATE_COLUMN = "상담희망일시"
_STATUS_COLUMN = "상태"

# 표를 못 읽었을 때 한 번 더 시도한다. 2026-08-19에 이 조회가 `None`을 돌려줘서
# 상담 완료 학생의 `advisor_consulted`가 갱신되지 않는 걸 관측했는데, 곧바로 다시
# 돌리니 정상이었다(단독 5회 + 동일 메뉴 순서 1회 전부 재현 실패). 간헐적이라
# 원인은 특정 못 했지만, 실패해도 조용히 넘어가서 **아무도 모른다**는 게 더 문제였다.
_FETCH_ATTEMPTS = 2
_RETRY_WAIT_MS = 1500


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


def _find_consultation_table(tables: list[list[list[str]]]) -> tuple[list[str], list[list[str]]] | None:
    """여러 표 중 기대한 컬럼을 가진 표를 찾는다. 없으면 None.

    예전엔 `tables[0]`만 봤다. `extract_tables`는 `'main table, .content table, table'`로
    **페이지의 모든 표**를 문서 순서대로 돌려주므로, 검색 필터나 레이아웃용 표가 앞에
    하나 끼면 상담내역 표가 있어도 못 찾는다. 재시도로는 절대 안 고쳐지는 실패 유형이고,
    원인 미상 간헐 실패의 유력 가설 중 하나다(독립 리뷰 지적).
    """
    for table in tables:
        if not table:
            continue
        header = table[0]
        if _DATE_COLUMN in header and _STATUS_COLUMN in header:
            return header, table[1:]
    return None


def _describe_tables(tables: list[list[list[str]]]) -> str:
    """로그용 표 구조 요약. 컬럼명과 행 수만 — 상담내용·교수명 같은 값은 넣지 않는다
    (CLAUDE.md 개인정보 원칙). 헤더와 행 수는 PII가 아니고, 그게 있어야 나중에
    "표가 왜 안 잡혔는지"를 판별할 수 있다."""
    if not tables:
        return "표 없음"
    return " | ".join(
        f"[{i}] 행{len(tbl)} 헤더={tbl[0] if tbl else []}" for i, tbl in enumerate(tables[:4])
    )


def _fetch_consultation_table(
    page: Page, user_id: int | None = None
) -> tuple[list[str], list[list[str]]] | None:
    """상담내역 표를 (헤더, 데이터행)으로 읽는다. 못 읽으면 None.

    **"표가 안 그려졌다"와 "신청 내역이 없다"를 구분한다.** 예전엔 둘 다 `None`이라
    호출부가 실패를 알 방법이 없었다 — 상담을 완료한 학생인데도 조용히 갱신이 안 됐다.

    - 기대한 컬럼을 가진 표를 못 찾으면 **크롤 실패**로 보고 한 번 더 시도한다.
    - 헤더는 정상인데 행이 0이면 **정상적인 "신청 내역 없음"** 이므로 재시도하지 않는다
      (상담을 한 번도 신청 안 한 학생이 흔하고, 그 경우 재시도는 순수 낭비다).
      다만 관측된 간헐 실패가 이 형태였을 가능성이 남아 있어 warning으로 남긴다.

    네비게이션/추출 예외는 **이번 시도의 실패로만 처리한다.** 감싸지 않으면 재시도가
    portal-sync 전체를 502로 만든다 — 원래는 상담 여부만 갱신 안 되고 학적부·성적·
    졸업요건은 정상 저장되던 상황이라, 문제를 보이게 만들려다 blast radius를 키우게 된다
    (독립 리뷰 지적). 재시도는 정의상 "페이지가 이상한 상태"에서만 도는데, `goto_menu`는
    그 상태에서 `selectMenu` 미정의로 터질 수 있다(`pnu_session` 참고).
    """
    scope = f"user_id={user_id}" if user_id is not None else "user_id=?"
    for attempt in range(1, _FETCH_ATTEMPTS + 1):
        tables: list[list[list[str]]] = []
        try:
            goto_menu(page, menu_codes.ADVISOR_CONSULTATION)
            tables = extract_tables(page)
        except Exception as exc:  # noqa: BLE001 - 이번 시도만 실패로 처리 (위 docstring 참고)
            _logger.warning(
                "지도교수 상담내역 조회 중 예외 (%s, 시도 %d/%d): %s",
                scope, attempt, _FETCH_ATTEMPTS, exc,
            )
        else:
            found = _find_consultation_table(tables)
            if found is not None:
                header, rows = found
                if not rows:
                    _logger.warning(
                        "지도교수 상담내역 표에 데이터 행이 없다 (%s, 헤더는 정상). "
                        "신청 내역이 없는 게 정상이지만, 간헐적 크롤 실패도 이 형태로 "
                        "보일 수 있다. 표 구조: %s",
                        scope, _describe_tables(tables),
                    )
                return header, rows
            _logger.warning(
                "지도교수 상담내역 표를 찾지 못했다 (%s, 시도 %d/%d). 표 구조: %s",
                scope, attempt, _FETCH_ATTEMPTS, _describe_tables(tables),
            )

        if attempt < _FETCH_ATTEMPTS:
            page.wait_for_timeout(_RETRY_WAIT_MS)

    _logger.warning(
        "지도교수 상담내역 표를 %d회 시도했지만 읽지 못했다 (%s) — 이번 동기화에서는 "
        "상담 여부를 갱신하지 않는다(기존 값 유지).", _FETCH_ATTEMPTS, scope,
    )
    return None


def fetch_current_term_consultation_status(
    page: Page, year: int, semester: int, user_id: int | None = None
) -> str | None:
    """지정한 학년도/학기에 해당하는 상담 신청의 "상태"를 가져온다.

    같은 학기에 여러 건이 있으면 상담희망일시가 가장 최근인 것을 쓴다.
    해당 학기 신청 내역이 없으면 None.
    """
    fetched = _fetch_consultation_table(page, user_id=user_id)
    if fetched is None:
        return None
    header, rows = fetched
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
