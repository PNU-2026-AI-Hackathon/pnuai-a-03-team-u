"""my.pusan.ac.kr 학생 경력 인증서 페이지에서 비교과활동/자격증/어학 성적을 한 번에 긁는다.

기존 pnu_session.login() 세션이 login.pusan.ac.kr 통합 SSO에 붙어있고, 그 세션 쿠키가
my.pusan.ac.kr 서브도메인에도 유효한 걸 전제로 한다. certificate 페이지엔 이수 프로그램,
자격증, 어학 점수가 각각 별도 <table>로 나열되는 것으로 확인됨(2026-07-23 사용자 확인).

전략: 페이지의 모든 <table>을 뽑고, 각 표의 헤더 텍스트로 유형(activity/certification/
language)을 분류. 헤더가 alias에 하나도 안 걸리는 표는 무시. 실제 관측 후 alias 확장 가능.
"""

from __future__ import annotations

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from app.ingestion.crawlers.table_extract import extract_tables

CERTIFICATE_URL = "https://my.pusan.ac.kr/ko/extracurricular/career/certificate"

# 각 표를 어떤 유형으로 볼지 판정하기 위한 대표 헤더 마커. 헤더 중 하나라도
# 해당 유형의 marker에 걸리면 그 유형으로 분류한다. 우선순위 순서(certification/
# language가 더 좁은 매칭이라 activity보다 앞에 둔다 — 예: "어학"이라는 단어가
# 비교과활동 표에 우연히 포함되는 것보다 어학 표일 확률이 훨씬 크다).
_TABLE_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("language", ("어학성적", "어학시험", "TOEIC", "TOEFL", "TEPS", "OPIc", "JLPT", "HSK")),
    ("certification", ("자격증", "자격명", "종목명", "종목", "취득일", "발급기관", "인정번호")),
    ("activity", ("프로그램명", "활동명", "이수시간", "이수학점", "참여기간", "영역", "주관부서")),
)

# 각 유형별 정규 필드 매핑. extract_tables()가 돌려주는 헤더 텍스트가 이 alias 중
# 하나면 대응 필드에 값을 넣는다.
_FIELD_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "activity": {
        "title": ("프로그램명", "활동명", "프로그램", "활동"),
        "category": ("영역", "카테고리", "분류", "구분"),
        "organization": ("주관부서", "주관기관", "기관", "부서", "운영기관"),
        "role": ("참여형태", "역할"),
        "start_date": ("시작일", "참여시작일", "활동시작일"),
        "end_date": ("종료일", "참여종료일", "활동종료일", "이수일자", "이수일"),
        "hours": ("이수시간", "인정시간", "시간", "시수"),
        "credits": ("이수학점", "인정학점", "학점"),
        "award": ("수상", "수상내역", "결과"),
        "description": ("비고", "내용"),
    },
    "certification": {
        "name": ("자격명", "종목명", "종목", "자격증명", "자격증"),
        "issuer": ("발급기관", "주관기관", "시행처", "기관"),
        "issued_at": ("취득일", "발급일", "인정일"),
        "expires_at": ("만료일", "유효기간"),
        "grade_or_number": ("등급", "점수", "인정번호", "자격번호"),
    },
    "language": {
        "test_name": ("어학시험", "시험명", "종목", "종류"),
        "score": ("점수", "등급", "성적"),
        "issued_at": ("취득일", "발급일", "응시일"),
        "expires_at": ("만료일", "유효기간"),
    },
}


def _classify_table(header: list[str]) -> str | None:
    """헤더 셀 텍스트 리스트에서 표 유형을 판정한다. 매칭 안 되면 None."""
    normalized_cells = [cell.strip() for cell in header]
    joined = " ".join(normalized_cells)
    for kind, markers in _TABLE_MARKERS:
        if any(marker in joined for marker in markers):
            return kind
    return None


def _parse_row(kind: str, header: list[str], row: list[str]) -> dict:
    """헤더-셀 대응. 매핑 안 되는 헤더는 _extra dict에 원문으로 보존."""
    aliases = _FIELD_ALIASES[kind]
    parsed: dict = {}
    extra: dict[str, str] = {}
    for idx, cell in enumerate(row):
        if idx >= len(header):
            continue
        header_text = header[idx].strip()
        value = cell.strip()
        matched_field = None
        for field, alias_list in aliases.items():
            if header_text in alias_list:
                matched_field = field
                break
        if matched_field:
            parsed[matched_field] = value
        elif header_text:
            extra[header_text] = value
    if extra:
        parsed["_extra"] = extra
    return parsed


def fetch_extracurricular_certificate(page: Page) -> dict:
    """certificate 페이지를 열고 표를 유형별로 분류해 목록으로 돌려준다.

    반환 dict:
      - final_url: 도달 URL. login 페이지로 튕겼으면 SSO 미공유.
      - authenticated: SSO 공유 성공 여부.
      - activities: 비교과활동 파싱 결과 (list[dict])
      - certifications: 자격증 파싱 결과
      - language_scores: 어학 점수 파싱 결과
      - raw_tables: 진단용 원시 테이블(전체 최대 5개까지)
      - unclassified_headers: 유형 판정 실패한 표의 헤더 목록(진단용)
    """
    context = page.context
    target = context.new_page()
    try:
        try:
            target.goto(CERTIFICATE_URL, wait_until="networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            pass
        final_url = target.url
        authenticated = "login.pusan.ac.kr" not in final_url

        buckets: dict[str, list[dict]] = {"activity": [], "certification": [], "language": []}
        unclassified: list[list[str]] = []
        raw_tables = extract_tables(target)
        for table in raw_tables:
            if len(table) < 2:
                continue
            header = table[0]
            if not any(cell.strip() for cell in header):
                continue
            kind = _classify_table(header)
            if kind is None:
                unclassified.append(header)
                continue
            for row in table[1:]:
                if not any(cell.strip() for cell in row):
                    continue
                parsed = _parse_row(kind, header, row)
                if not parsed or all(v == {} or v == "" or v is None for k, v in parsed.items() if k != "_extra"):
                    continue
                buckets[kind].append(parsed)

        return {
            "final_url": final_url,
            "authenticated": authenticated,
            "activities": buckets["activity"],
            "certifications": buckets["certification"],
            "language_scores": buckets["language"],
            "raw_tables": raw_tables[:5],
            "unclassified_headers": unclassified,
        }
    finally:
        target.close()
