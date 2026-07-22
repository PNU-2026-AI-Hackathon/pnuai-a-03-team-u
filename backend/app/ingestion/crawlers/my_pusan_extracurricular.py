"""my.pusan.ac.kr 학생 경력 인증서 페이지에서 완료된 비교과 이수 프로그램을 긁는다.

기존 pnu_session.login() 세션이 login.pusan.ac.kr 통합 SSO에 붙어있고, 그 세션
쿠키가 my.pusan.ac.kr 서브도메인에도 유효한 걸 전제로 한다(로그인 폼도 selector가
동일함을 확인함). 따라서 login()이 반환한 Page의 context에서 새 탭으로 certificate
URL을 열면 별도 재로그인 없이 로드된다(SSO 미공유 시 login 페이지로 리다이렉트되는데,
호출자가 그 상황을 감지할 수 있게 raw HTML 표본과 최종 URL도 함께 반환한다).

Certificate 페이지의 정확한 표 구조를 실계정 검증 전까지는 확정할 수 없어서,
extract_tables()로 원시 테이블을 다 뽑고 헤더 기반 dict로 정규화한다. 헤더 이름이
"프로그램명"/"활동명" 등 무엇이든 매핑 딕셔너리에서 흡수한다. 진행중인 활동은 이
페이지에는 완료 건만 노출되는 걸 전제로 별도 필터링을 하지 않는다.
"""

from __future__ import annotations

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from app.ingestion.crawlers.table_extract import extract_tables

CERTIFICATE_URL = "https://my.pusan.ac.kr/ko/extracurricular/career/certificate"

# 실계정 검증 후 표 헤더가 확정되면 여기 매핑을 조정한다. 지금은 알려진/예상 표기를
# 다 넣어두고, extract_tables()에서 실제로 나온 헤더 텍스트가 이 중 하나에 걸리면
# 그 컬럼값을 정규 필드로 매핑한다. 매칭 안 되는 헤더는 무시(로그에는 남음).
_HEADER_ALIASES = {
    "title": ("프로그램명", "활동명", "프로그램", "활동"),
    "category": ("영역", "카테고리", "분류", "구분"),
    "organization": ("주관부서", "주관기관", "기관", "부서", "운영기관"),
    "role": ("참여형태", "역할", "구분"),
    "start_date": ("시작일", "참여시작일", "활동시작일"),
    "end_date": ("종료일", "참여종료일", "활동종료일", "이수일자", "이수일"),
    "hours": ("이수시간", "인정시간", "시간", "시수"),
    "credits": ("이수학점", "인정학점", "학점"),
    "award": ("수상", "수상내역", "결과"),
    "description": ("비고", "내용"),
}


def _match_field(header_text: str) -> str | None:
    normalized = header_text.strip()
    for field, aliases in _HEADER_ALIASES.items():
        if normalized in aliases:
            return field
    return None


def _parse_row(header: list[str], row: list[str]) -> dict[str, str]:
    """헤더-셀 대응해서 이름 있는 dict로. 매핑 안 되는 헤더는 원문 텍스트를 그대로 키로 남긴다."""
    parsed: dict[str, str] = {}
    unknown: dict[str, str] = {}
    for idx, cell in enumerate(row):
        if idx >= len(header):
            continue
        header_text = header[idx].strip()
        field = _match_field(header_text)
        if field:
            parsed[field] = cell.strip()
        elif header_text:
            unknown[header_text] = cell.strip()
    if unknown:
        parsed["_extra"] = unknown  # 정규화 단계에서 참고
    return parsed


def fetch_extracurricular_certificate(page: Page) -> dict:
    """certificate 페이지를 열고 완료된 이수 프로그램 목록을 추출한다.

    반환 dict:
      - final_url: 실제 도달 URL. login 페이지로 튕겼으면 SSO 공유가 안 되는 것.
      - authenticated: SSO 공유 성공 여부 추정.
      - programs: 파싱된 행 목록 (각 행은 title/category/... 정규 키를 가진 dict).
      - raw_tables: 파싱 실패 진단용 원시 테이블 (첫 3개만).
    """
    context = page.context
    target = context.new_page()
    try:
        try:
            target.goto(CERTIFICATE_URL, wait_until="networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            # networkidle이 안 잡힐 때도 있어서 도착만 확인하고 넘어간다.
            pass
        final_url = target.url
        authenticated = "login.pusan.ac.kr" not in final_url

        programs: list[dict] = []
        raw_tables = extract_tables(target)
        # 완료 이수 프로그램이 담길 대표 표를 찾는다: header가 2개 이상, row가 1개 이상.
        for table in raw_tables:
            if len(table) < 2:
                continue
            header = table[0]
            if not any(cell.strip() for cell in header):
                continue
            row_dicts = [_parse_row(header, r) for r in table[1:] if any(c.strip() for c in r)]
            if not row_dicts:
                continue
            # 이 표에서 title로 매핑된 값이 하나라도 있으면 프로그램 표로 채택.
            if any(r.get("title") for r in row_dicts):
                programs.extend(row_dicts)

        return {
            "final_url": final_url,
            "authenticated": authenticated,
            "programs": programs,
            "raw_tables": raw_tables[:3],  # 진단용 (표 3개까지만 남긴다 — 페이지가 무거워도 응답 폭주 방지)
        }
    finally:
        target.close()
