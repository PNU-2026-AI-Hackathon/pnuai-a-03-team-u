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

import re

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


# rSSO 핸드셰이크가 실패하면 login.pusan.ac.kr/my/loginPage ↔ my.pusan.ac.kr의
# loginCheck.php 사이를 **무한히 왕복한다.** 그래서 `networkidle`은 영원히 안 온다.
#
# 2026-08-16~18에 실제로 겪었다: 학교 rSSO 에이전트가 자기 뒷단 SSO 검증 서버에
# 소켓을 못 열어(`4,-105 socket_connect() failed`) 토큰 검증이 계속 실패했다.
# 그때 이 함수는 30초 타임아웃을 다 쓰고, 그 다음 evaluate가 "Execution context was
# destroyed"로 터졌으며, 호출부는 그걸 광범위 except로 삼켜서 **사용자에게는 이수
# 프로그램·자격증·어학이 그냥 비어 보였다** — 왜 비었는지 알 방법이 없었다.
#
# 그래서 (a) 루프를 감지하는 즉시 포기하고 (b) 왜 실패했는지 사유를 돌려준다.
_ID_SEGMENT_RE = re.compile(r"(?<![0-9])[0-9]{6,}(?![0-9])")


def _mask_id_segments(path: str) -> str:
    """경로에 박힌 학번류 긴 숫자를 가린다.

    지금 알려진 my.pusan 경로엔 없지만, `/student/202012345/...` 같은 URL이 생기면
    쿼리스트링만 떼는 걸로는 안 막힌다 (독립 2차 리뷰 지적).
    """
    return _ID_SEGMENT_RE.sub("<id>", path)


def safe_location(url: str) -> str:
    """진단용 URL에서 쿼리스트링을 떼어낸다.

    rSSO 왕복 URL에는 SSO 토큰이나 학번이 파라미터로 붙을 수 있는데, 이 문자열은
    `failure_reason` → `PortalSyncResponse.my_pusan_error`로 **응답 본문에 실리고**
    서버 로그에도 남는다(CLAUDE.md 개인정보 원칙 2 — 독립 리뷰 지적).
    scheme+host+path만 남겨도 "어디서 멈췄나"는 그대로 알 수 있다.
    """
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url)
    except ValueError:
        return "(알 수 없음)"
    path = _mask_id_segments(parts.path)
    if not parts.scheme:
        return _mask_id_segments(url.split("?")[0].split("#")[0])
    return f"{parts.scheme}://{parts.netloc}{path}"


_LOGIN_HOST = "login.pusan.ac.kr"
_SSO_CHECK_PATH = "/modules/pusan/rsso/loginCheck.php"
# 총 폴링 예산. main은 `networkidle` 30초를 썼는데 이걸 15초로 줄이면 **느리지만 정상인
# 핸드셰이크의 성공 예산이 절반으로 준다** — 하필 이 코드가 겨냥한 "학교 SSO 부하"에서
# 그런 지연이 난다(독립 2차 리뷰 지적). 루프는 3초, 로그인 폼 고착은 8초에 이미 조기
# 반환하므로, 이 값을 30초로 되돌려도 **실패 조기감지 이득은 하나도 잃지 않는다.**
_PAGE_SETTLE_TIMEOUT_MS = 30_000
_PAGE_POLL_INTERVAL_MS = 500
# 실패로 단정하기 전에 최소한 이만큼은 지켜본다. **정상 핸드셰이크도 login.pusan.ac.kr을
# 거쳐 간다** — 첫 폴링에서 그 host를 봤다고 실패로 처리하면 멀쩡한 로그인을 실패로
# 오판한다(이 함수를 고치면서 실제로 그렇게 만들었다가 잡았다).
_MIN_OBSERVE_MS = 8_000
# 로그인 폼이 뜬 채로 **연속** 이만큼 관찰돼야 로그인 실패로 확정한다.
#
# 주의: 조기 실패를 막는 주된 장치는 위 `_MIN_OBSERVE_MS`(8초)다. 폼이 계속 떠 있으면
# 8초에 도달할 때 이 카운터는 이미 넘겨져 있어서, 이 상수는 실패 시점을 늦추지 않는다.
# 이게 실제로 일하는 경우는 **폼이 떴다 사라졌다 하는(flapping)** 상황 하나다 —
# 리다이렉트 중간에 로그인 폼이 잠깐 그려지는 경우가 그렇다. 두 겹의 안전장치가
# 아니라는 뜻이다(독립 2차 리뷰 지적).
_LOGIN_FORM_CONFIRM_POLLS = 4
# loginCheck.php를 이만큼 반복해서 보면 왕복 루프로 판단한다. 정상 핸드셰이크도 들어갈 때·
# 나올 때 2회 경유할 수 있어서 여유를 둔다.
_SSO_LOOP_HITS = 4
# 폼이 뜬 뒤 목록 XHR을 기다리는 상한.
_XHR_SETTLE_TIMEOUT_MS = 10_000
# goto 자체의 상한. 어차피 뒤에 폴링이 붙으므로 여기서 30초를 다 쓸 이유가 없다 —
# 그러면 루프가 아닌 실패에서 총 대기가 오히려 예전(30초)보다 길어진다(독립 리뷰 지적).
_GOTO_TIMEOUT_MS = 10_000


# 페이지가 "다 그려졌다"고 볼 조건: 폼 + 섹션 ul이 최소 하나.
_READY_JS = """
() => {
  const root = document.querySelector('#ModulePortfolioCertificate');
  if (!root) return false;
  return root.querySelectorAll('ul[data-role="table"][data-name]').length > 0;
}
"""


def _open_certificate_page(target: Page) -> str | None:
    """certificate 페이지를 연다. 성공하면 None, 실패하면 사유 문자열.

    `networkidle`로 기다리지 않는 이유: rSSO가 실패하면 login.pusan.ac.kr ↔
    loginCheck.php를 **무한히 왕복해서** networkidle이 영영 안 온다(2026-08-16~18 실제
    장애). 그때 이 함수는 30초를 다 쓰고 그 다음 evaluate가 "Execution context was
    destroyed"로 터졌고, 호출부가 광범위 except로 삼켜서 **사용자에게는 이수 프로그램·
    자격증·어학이 이유 없이 비어 보였다.**

    대신 `domcontentloaded`로 열고 폼이 그려질 때까지 폴링하면서, 실패 신호를
    **누적해서** 판단한다 — 한 시점의 URL만 보면 정상 리다이렉트 중간을 실패로 오판한다.
    """
    try:
        target.goto(CERTIFICATE_URL, wait_until="domcontentloaded", timeout=_GOTO_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        pass  # 실제 도달 지점을 아래에서 보고 판단한다

    elapsed = 0
    sso_check_hits = 0
    login_form_polls = 0
    last_url = ""
    while elapsed <= _PAGE_SETTLE_TIMEOUT_MS:
        url = target.url
        if _SSO_CHECK_PATH in url and url != last_url:
            sso_check_hits += 1
        last_url = url

        try:
            if target.evaluate(_READY_JS):
                # 폼이 보이면 인증은 된 것이고, 여기서부터는 리다이렉트 루프 위험이
                # 없다. 그러니 이 시점에만 networkidle을 기다린다 — 목록을 채우는
                # XHR이 폼보다 늦게 오기 때문이다.
                #
                # 실측(2026-08-19): 1.0s에 섹션 ul 8개가 전부 그려지지만 행은 0이고,
                # 1.5s에 데이터가 도착한다. 폼만 보고 반환하면 이수 프로그램 2건·
                # 어학 1건이 있는 계정에서 **전부 0건**이 나온다(고치면서 만든 회귀).
                # 로딩 전 상태에도 `li.empty` 플레이스홀더가 들어 있어서 DOM 모양만으론
                # "아직 안 옴"과 "진짜 없음"을 구분할 수 없다 — 그래서 네트워크로 판단한다.
                try:
                    target.wait_for_load_state("networkidle", timeout=_XHR_SETTLE_TIMEOUT_MS)
                except PlaywrightTimeoutError:
                    pass  # 느려도 아래 추출은 시도한다. 빈 결과가 나오면 그건 그대로 보고된다.
                return None
        except Exception:  # noqa: BLE001 - 리다이렉트 중이면 evaluate가 터진다. 다음 폴링에서 재시도.
            pass

        if sso_check_hits >= _SSO_LOOP_HITS:
            return (
                "학교 통합인증(rSSO) 핸드셰이크가 끝나지 않습니다. my.pusan.ac.kr이 "
                "로그인 페이지와 무한 왕복 중입니다 — 학교 SSO 서버 장애일 수 있습니다."
            )
        # 로그인 폼이 **연속으로** 떠 있고 관찰 유예도 지나야 로그인 실패로 확정한다.
        # 한 시점만 보면 경유 중인 정상 핸드셰이크를 실패로 뒤집는다.
        on_login_form = False
        if _LOGIN_HOST in url:
            try:
                on_login_form = bool(target.evaluate("!!document.querySelector('#login_id')"))
            except Exception:  # noqa: BLE001
                on_login_form = False
        login_form_polls = login_form_polls + 1 if on_login_form else 0
        if elapsed >= _MIN_OBSERVE_MS and login_form_polls >= _LOGIN_FORM_CONFIRM_POLLS:
            return "my.pusan.ac.kr 로그인이 되지 않아 로그인 페이지로 돌아왔습니다."

        elapsed += _PAGE_POLL_INTERVAL_MS
        if elapsed <= _PAGE_SETTLE_TIMEOUT_MS:
            target.wait_for_timeout(_PAGE_POLL_INTERVAL_MS)

    return (
        "my.pusan.ac.kr 이수 프로그램 페이지가 시간 내에 열리지 않았습니다 "
        f"(마지막 위치: {safe_location(target.url)})."
    )


def fetch_extracurricular_certificate(page: Page) -> dict:
    """certificate 페이지에서 활동/자격증/어학 목록을 유형별로 뽑는다.

    반환:
      - final_url, authenticated: SSO 공유 여부 판정용
      - failure_reason: 실패 사유(사용자에게 보여줄 문구). 성공이면 None
      - activities: list[dict] (UserActivity 필드로 매핑된 값)
      - certifications: list[dict] (UserCertification 매핑값)
      - language_scores: list[dict] (UserLanguageScore 매핑값)
      - unknown_sections: 매핑 안 된 data-name 목록 (진단용)
    """
    context = page.context
    target = context.new_page()
    try:
        failure = _open_certificate_page(target)
        final_url = target.url
        authenticated = failure is None
        if failure is not None:
            return {
                "final_url": final_url,
                "authenticated": False,
                "failure_reason": failure,
                "activities": [],
                "certifications": [],
                "language_scores": [],
                "unknown_sections": [],
            }

        sections: list[dict] = target.evaluate(_EXTRACT_JS)

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
            "failure_reason": None,
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
