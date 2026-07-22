"""my.pusan.ac.kr 학생 경력 인증서(#ModulePortfolioCertificate) 파싱.

2026-07-23 실제 마크업 확인 결과 페이지 구조:
  <form id="ModulePortfolioCertificate">
    <h5>이수 프로그램</h5><ul data-role="table" data-name="eco">
      <li class="thead">... span.title, span.count, span.schedule ...</li>
      <li class="tbody"><span.title>이름</span><span.count>1.01</span><span.schedule>2026-05-29(금)</span></li>
    </ul>
    <h5>수상실적</h5><ul data-name="award">...</ul>
    <h5>자격증</h5><ul data-name="certificate">...</ul>
    <h5>어학성적</h5><ul data-name="language">...</ul>
    <h5>연수실적</h5><ul data-name="performance">...</ul>
    <h5>동아리활동</h5><ul data-name="group">...</ul>
    <h5>봉사활동</h5><ul data-name="volunteer">...</ul>
    <h5>기타</h5><ul data-name="etc">...</ul>
  </form>

핵심:
- 각 섹션은 `data-name` 속성으로 유형이 명시된다 → 텍스트 매칭 필요 없음.
- 각 셀은 `<span class="필드명">` — class가 필드 이름 그 자체 (title/date/schedule/
  institution/type 등). 헤더 순서 흔들림에 영향받지 않는다.
- `<li class="tbody">` = 데이터 행, `<li class="empty">` = 등록 없음(스킵).
"""

from __future__ import annotations

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

CERTIFICATE_URL = "https://my.pusan.ac.kr/ko/extracurricular/career/certificate"

# data-name 값 → 어느 도메인 모델로 upsert할지. eco(이수 프로그램)/award(수상)/
# performance(연수)/group(동아리)/volunteer(봉사)/etc(기타)는 모두 UserActivity로 합친다.
_DATA_NAME_TO_KIND: dict[str, str] = {
    "eco": "activity",         # 비교과 이수 프로그램
    "award": "activity",       # 수상실적
    "performance": "activity", # 연수실적
    "group": "activity",       # 동아리활동
    "volunteer": "activity",   # 봉사활동
    "etc": "activity",         # 기타
    "certificate": "certification",
    "language": "language",
}

# 사람이 읽는 유형 라벨 → UserActivity.category에 저장할 값. data-name을 그대로
# 쓰면 사용자 화면에 "eco" 같은 코드가 뜨므로 한글화.
_ACTIVITY_CATEGORY_LABEL: dict[str, str] = {
    "eco": "이수 프로그램",
    "award": "수상실적",
    "performance": "연수실적",
    "group": "동아리활동",
    "volunteer": "봉사활동",
    "etc": "기타 활동",
}


# 페이지에서 #ModulePortfolioCertificate 내부의 모든 [data-role=table] ul을 순회해서
# {dataName, heading(h5 텍스트), rows[]}를 뽑는 JS. rows는 각 행을 {class:text} dict로.
_EXTRACT_JS = """
() => {
  const root = document.querySelector('#ModulePortfolioCertificate') || document;
  const uls = Array.from(root.querySelectorAll('ul[data-role="table"][data-name]'));
  return uls.map(ul => {
    // 가장 가까운 앞선 h5를 소제목으로 잡는다 (표시용).
    let heading = '';
    let node = ul.previousElementSibling;
    while (node) {
      if (node.tagName === 'H5') { heading = (node.textContent || '').trim(); break; }
      node = node.previousElementSibling;
    }
    const rows = [];
    for (const li of ul.querySelectorAll('li.tbody')) {
      const row = {};
      for (const child of li.children) {
        if (child.tagName !== 'SPAN') continue;
        if (child.classList.contains('checkbox')) continue; // checkbox 컬럼은 데이터 아님
        // center/left/right 같은 정렬 class는 무시하고 실제 필드 class 사용.
        const cls = Array.from(child.classList).filter(c =>
          !['center', 'left', 'right'].includes(c)
        );
        const field = cls[0] || 'unknown';
        const text = (child.textContent || '').trim();
        if (text) row[field] = text;
      }
      if (Object.keys(row).length) rows.push(row);
    }
    return {
      dataName: ul.getAttribute('data-name'),
      heading: heading,
      rows: rows,
    };
  });
}
"""


def fetch_extracurricular_certificate(page: Page) -> dict:
    """certificate 페이지에서 활동/자격증/어학 목록을 유형별로 뽑는다.

    반환:
      - final_url, authenticated: SSO 공유 여부 판정용
      - activities: list[dict] (UserActivity 필드로 매핑된 값)
      - certifications: list[dict] (UserCertification 매핑값)
      - language_scores: list[dict] (UserLanguageScore 매핑값)
      - unknown_sections: 매핑 안 된 data-name 목록 (진단용)
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

        sections: list[dict] = target.evaluate(_EXTRACT_JS) if authenticated else []

        activities: list[dict] = []
        certifications: list[dict] = []
        language_scores: list[dict] = []
        unknown_sections: list[str] = []

        for sec in sections:
            data_name = (sec.get("dataName") or "").strip()
            heading = sec.get("heading") or ""
            rows = sec.get("rows") or []
            kind = _DATA_NAME_TO_KIND.get(data_name)
            if kind is None:
                if rows:  # 빈 섹션은 알려도 소용없음
                    unknown_sections.append(data_name or heading)
                continue
            for raw in rows:
                if kind == "activity":
                    activities.append(_activity_from_row(data_name, heading, raw))
                elif kind == "certification":
                    certifications.append(_certification_from_row(raw))
                elif kind == "language":
                    language_scores.append(_language_from_row(raw))

        return {
            "final_url": final_url,
            "authenticated": authenticated,
            "activities": activities,
            "certifications": certifications,
            "language_scores": language_scores,
            "unknown_sections": unknown_sections,
        }
    finally:
        target.close()


def _activity_from_row(data_name: str, heading: str, raw: dict) -> dict:
    """각 활동 섹션(eco/award/performance/group/volunteer/etc)의 span.class 값을
    UserActivity 필드로 매핑한다. 섹션마다 컬럼 집합이 조금씩 다르지만 span class
    이름이 곧 필드명이라 여기서 통일된 사전으로 흡수 가능.
    """
    return {
        "data_name": data_name,
        "heading": heading,
        "category": _ACTIVITY_CATEGORY_LABEL.get(data_name, heading or data_name),
        "title": raw.get("title"),
        # 연수종류/동아리유형/활동구분 등 세부 유형이 있으면 heading보다 우선.
        "sub_type": raw.get("type"),
        # 활동기간 컬럼은 섹션마다 다른 이름(schedule/date/period)으로 온다.
        "raw_date": raw.get("schedule") or raw.get("date") or raw.get("period"),
        "institution": raw.get("institution"),
        "role": raw.get("study_agency"),  # 동아리활동의 직위
        "contents": raw.get("contents"),
        # eco 섹션의 역량지수는 count 컬럼에.
        "score_hint": raw.get("count"),
        # award 섹션의 분류/subcategory
        "sub_category": raw.get("category"),
    }


def _certification_from_row(raw: dict) -> dict:
    return {
        "name": raw.get("title"),
        "issued_at": raw.get("date"),
        "certificate_no": raw.get("certificate_no"),
        "issuer": raw.get("institution"),
    }


def _language_from_row(raw: dict) -> dict:
    return {
        "test_name": raw.get("title"),
        "score": raw.get("score"),
        "issued_at": raw.get("date"),
    }
