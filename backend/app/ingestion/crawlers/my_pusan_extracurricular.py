"""my.pusan.ac.kr 학생 경력 인증서 페이지에서 비교과활동/자격증/어학 성적을 한 번에 긁는다.

기존 pnu_session.login() 세션이 login.pusan.ac.kr 통합 SSO에 붙어있고, 그 세션 쿠키가
my.pusan.ac.kr 서브도메인에도 유효한 걸 전제로 한다. certificate 페이지는 각 유형(활동
/자격증/어학)마다 `<h5>` 소제목 + 그 아래 `data-role="table"` 컨테이너 안의 `<table>`로
구성됨(2026-07-23 사용자 확인).

전략: 페이지에서 `<h5>` + 다음 `data-role="table"` 쌍을 순서대로 잡고, h5 텍스트로
유형을 분류. 표 헤더 셀 텍스트가 어떻든 h5가 "비교과활동"/"자격증"/"어학"이면 해당
유형으로 확정한다. 필드 매핑은 표 헤더 alias로 흡수하고, 못 맞춘 헤더는 _extra에 원문
보존해서 상위 계층에서 알아서 살린다.
"""

from __future__ import annotations

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

CERTIFICATE_URL = "https://my.pusan.ac.kr/ko/extracurricular/career/certificate"

# 소제목 텍스트 → 유형. 실제 페이지에서 확인된 표기:
#   - 비교과활동: <h5>이수 프로그램</h5>
#   - 자격증: <h5>자격증</h5>
#   - 어학: <h5> 없이 시험 종목별 <span class="title center">TOEIC</span> 등의 라벨.
# 그래서 시험 종목명(TOEIC/TOEFL/...)이 소제목이면 그 자체로 language로 확정하고,
# 표에는 시험명이 없더라도 이 라벨을 test_name으로 주입한다.
_LABEL_TO_KIND: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("activity", ("비교과", "이수 프로그램", "이수프로그램", "활동")),
    ("certification", ("자격증", "자격")),
    (
        "language",
        (
            "어학", "외국어",
            "TOEIC", "TOEFL", "TEPS", "IELTS", "OPIc", "OPIC", "JLPT", "HSK", "TSC",
            "DELE", "DELF", "SPA", "CEFR",
        ),
    ),
)

# 유형별 정규 필드 매핑. 표 헤더가 이 alias 중 하나면 그 필드로 채운다. 못 걸린
# 헤더는 파싱 결과의 _extra dict에 원문 그대로 남겨서 후속 매핑/저장 시 참고.
_FIELD_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "activity": {
        "title": ("프로그램명", "활동명", "프로그램", "활동", "제목"),
        "category": ("영역", "카테고리", "분류", "구분", "유형"),
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


# 소제목 후보 + 그 아래 첫 번째 data-role="table" 컨테이너 안의 <table>을 뽑는 JS.
# 소제목은 h5뿐 아니라 어학 시험 종목별 라벨(`<span class="title center">TOEIC</span>` 등)도
# 잡아야 하므로 셀렉터를 넓힌다. 문서 순서 기준으로 label과 다음 data-role="table"이
# 짝지어져 나온다는 걸 이용.
_EXTRACT_SECTIONED_TABLES_JS = """
() => {
  // 소제목 후보: h5는 물론이고 span.title 계열(어학 시험 종목 라벨)도 포함.
  const labels = Array.from(document.querySelectorAll(
    'h5, span.title, span[class*="title"]'
  ));
  const tables = Array.from(document.querySelectorAll('[data-role="table"]'));
  // 문서 순서를 유지하기 위해 각 label의 절대 위치를 뽑고, 그 뒤 첫 번째 table을 매칭.
  const nodePos = (node) => {
    // TreeWalker 없이 간단히: comparing document order via compareDocumentPosition.
    return node;
  };
  const out = [];
  for (const label of labels) {
    const title = (label.textContent || '').trim();
    if (!title) continue;
    // label 이후로 문서 순서상 가장 가까운 [data-role="table"]을 찾는다.
    let picked = null;
    for (const t of tables) {
      const rel = label.compareDocumentPosition(t);
      // Node.DOCUMENT_POSITION_FOLLOWING = 4
      if (rel & 4) { picked = t; break; }
    }
    if (!picked) continue;
    const table = picked.querySelector('table') || picked;
    const rows = Array.from(table.querySelectorAll('tr')).map(tr =>
      Array.from(tr.querySelectorAll('th,td')).map(c => (c.textContent || '').trim())
    );
    out.push({ heading: title, rows });
  }
  return out;
}
"""


def _classify_heading(heading: str) -> str | None:
    for kind, markers in _LABEL_TO_KIND:
        if any(marker in heading for marker in markers):
            return kind
    return None


def _test_name_from_heading(heading: str) -> str | None:
    """어학 소제목이 시험 종목명 그 자체(예: "TOEIC")인 경우, 표 안에 test_name
    컬럼이 없더라도 이 값을 test_name으로 주입할 수 있게 뽑아낸다."""
    up = heading.strip().upper()
    for marker in ("TOEIC", "TOEFL", "TEPS", "IELTS", "OPIC", "JLPT", "HSK", "TSC", "DELE", "DELF", "SPA", "CEFR"):
        if marker in up:
            return marker
    return None


def _parse_row(kind: str, header: list[str], row: list[str]) -> dict:
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
    """certificate 페이지에서 h5+[data-role=table] 섹션별로 표를 뽑고 유형별로 분류.

    반환:
      - final_url: 도달 URL. login 페이지로 튕겼으면 SSO 미공유.
      - authenticated: SSO 공유 성공 여부.
      - activities/certifications/language_scores: 파싱 결과 list[dict]
      - unclassified_headings: h5 텍스트가 alias 매칭 실패한 목록 (진단용)
      - raw_sections: 원시 {heading, rows} 리스트 (진단용, 상위 5개까지만)
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

        sections = target.evaluate(_EXTRACT_SECTIONED_TABLES_JS) if authenticated else []

        buckets: dict[str, list[dict]] = {"activity": [], "certification": [], "language": []}
        unclassified: list[str] = []
        for sec in sections:
            heading = sec.get("heading") or ""
            rows = sec.get("rows") or []
            if len(rows) < 1:
                continue
            kind = _classify_heading(heading)
            if kind is None:
                unclassified.append(heading)
                continue
            header = rows[0]
            if not any(cell.strip() for cell in header):
                continue
            # 어학 소제목이 시험 종목명 그 자체(예: "TOEIC")면, 표 안에 시험명 컬럼이
            # 없을 것이므로 소제목을 test_name으로 주입한다.
            heading_test_name = _test_name_from_heading(heading) if kind == "language" else None
            for row in rows[1:]:
                if not any(cell.strip() for cell in row):
                    continue
                parsed = _parse_row(kind, header, row)
                if kind == "language" and heading_test_name and not parsed.get("test_name"):
                    parsed["test_name"] = heading_test_name
                # 정규 필드가 하나도 안 걸리고 _extra만 있으면 사실상 매핑 실패. 그래도
                # description 폴백으로 저장은 가능하니 남겨둔다.
                if not parsed:
                    continue
                buckets[kind].append(parsed)

        return {
            "final_url": final_url,
            "authenticated": authenticated,
            "activities": buckets["activity"],
            "certifications": buckets["certification"],
            "language_scores": buckets["language"],
            "unclassified_headings": unclassified,
            "raw_sections": sections[:5],
        }
    finally:
        target.close()
