"""One-Stop 수강편람 "교수계획표"(강의계획서) PDF 크롤러.

로그인이 필요 없다 — 개설강좌 검색 자체가 공개 API라 `pnu_session`을 안 쓴다.
검색은 Playwright로 실제 폼을 조작해서 한다(순수 HTTP 재현은 리포트 렌더링
단계(ClipReport5, `rpt.pusan.ac.kr`)에서 막힌다 — `local.md` 2026-08-24 항목 참고).

**막혔던 지점과 그 이유(재현 시 반드시 순서를 지킬 것)**:
1. 검색방법 라디오를 "교과목명 직접입력"(`#SEARCH_GBN2`)으로 바꿔야 `#SCH_SUBJ_NM`이
   보인다.
2. `대학/대학원`(`#SCH_COLL_GRAD_GCD`)은 네이티브 `<select>`가 아니라 커스텀
   `select-pure` 위젯이다 — `.select-pure__select`를 클릭해서 연 뒤
   `.select-pure__option[data-value='0001']`(대학)을 클릭해야 값이 채워진다.
   필수 필드인데 안 채우면 `fn_sch()`가 커스텀 alert만 띄우고(= `page.on("dialog")`로도
   안 잡힘) 조용히 `false`를 리턴한다.
3. **순서가 중요하다.** `SCH_COLL_GRAD_GCD`를 바꾸면 change 핸들러(`fn_VisibleSet(false)`)가
   `#SCH_SUBJ_NM`을 강제로 비운다 — 교과목명은 **맨 마지막에** 채워야 한다.
4. 교수계획표 열람은 `.kor`/`.eng` 버튼 클릭 대신 `fn_openReport($(tr).data(), 'KOR')`를
   `page.evaluate`로 직접 호출하는 쪽이 안정적이다.
5. 렌더링 결과는 진짜 DOM 텍스트가 아니라 `<canvas>`다(중첩 iframe 안). 대신 툴바의
   **SAVE 버튼**(`#report_menu_save_button`)을 누르면 파일형식 드롭다운에 PDF가 있고,
   `#select_label`에서 `pdf`를 고르고 저장하면 실제 텍스트 레이어가 있는 PDF를 받는다
   (스크린샷+OCR/비전 호출 불필요 — `pdftotext -layout`만으로 충분, 파서는
   `app/ingestion/parsers/onestop_syllabus.py` 참고).

Raw PDF는 `raw_data/`(gitignore 대상) 아래에 쓴다.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE_URL = "https://onestop.pusan.ac.kr"
SYLLABUS_SEARCH_PAGE = f"{BASE_URL}/page?menuCD=000000000000335"

_SEARCH_DEBOUNCE_S = 0.3
_REPORT_TIMEOUT_S = 20
_DOWNLOAD_TIMEOUT_MS = 20_000


@dataclass
class SyllabusOffering:
    """검색 결과 한 행(분반). PDF가 있는지(`has_kor`)까지만 담는다 — 실제 다운로드는
    `download_syllabus_pdf`가 별도로 한다(검색 따로/다운로드 따로라야 검색 1회로
    여러 분반을 고를 수 있다)."""

    subj_no: str
    class_no: str
    subj_nm: str
    prof_no: str
    prof_nm: str | None
    dept_nm: str | None
    has_kor: bool
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class SyllabusCrawlResult:
    offering: SyllabusOffering
    pdf_path: Path | None
    error: str | None = None


def _select_college_grad(page: Page, value: str = "0001") -> None:
    """대학/대학원 select-pure 위젯. value="0001"=대학, "0002"=대학원."""
    page.locator("#SCH_COLL_GRAD_GCD_multi .select-pure__select").click()
    time.sleep(_SEARCH_DEBOUNCE_S)
    page.locator(
        f"#SCH_COLL_GRAD_GCD_multi .select-pure__option[data-value='{value}']"
    ).click()
    time.sleep(_SEARCH_DEBOUNCE_S)


def search_offerings_by_name(
    page: Page, year: int, semester_code: str, course_name: str
) -> list[SyllabusOffering]:
    """교과목명으로 검색해서 해당 학기 개설 분반 전부를 돌려준다.

    `semester_code`는 `selectAtlectManual_v2025`가 쓰는 raw 코드다(정규학기
    1학기="0010", 2학기="0020" — `onestop_course_catalog.TERM_CODES`와 동일 체계).

    `#SCH_SYEAR`/`#SCH_TERM_GCD`는 (대학/대학원과 달리) 순수 네이티브 `<select>`다
    — `page.select_option()`으로 바꾸면 실제 change 이벤트가 정상 발생한다(2026-08-25
    실측 확인 및 검색+PDF 다운로드까지 end-to-end 검증 완료). 예전엔 JS로 `.value`만
    세팅하고 `dispatchEvent`로 change를 흉내 냈다가 검색방법 라디오가 조작 불가능해지는
    회귀가 났었는데(2026-08-24), 그건 `dispatchEvent` 흉내가 문제였지 select 자체가
    커스텀 위젯이라서가 아니었다 — `select_option()`은 별도 문제가 없었다. 다른 필드를
    만지기 전에 **맨 먼저** 전환한다(전환 순서를 바꿨을 때 다른 필드가 초기화되는지는
    확인 안 했으니 항상 이 순서를 지킨다).
    """
    page.goto(SYLLABUS_SEARCH_PAGE, wait_until="networkidle", timeout=30_000)
    time.sleep(1)

    page.select_option("#SCH_SYEAR", str(year))
    page.select_option("#SCH_TERM_GCD", semester_code)
    time.sleep(_SEARCH_DEBOUNCE_S)

    page_syear = page.eval_on_selector("#SCH_SYEAR", "el => el.value")
    page_term = page.eval_on_selector("#SCH_TERM_GCD", "el => el.value")
    if page_syear != str(year) or page_term != semester_code:
        raise RuntimeError(
            f"학기 전환 실패: 선택 후에도 페이지가 {page_syear}/{page_term}로 남아있음"
            f"(요청 {year}/{semester_code}) — semester_code/year 값 자체가 select의"
            " option에 없는 값일 수 있다."
        )

    page.check("#SEARCH_GBN2", force=True)
    time.sleep(_SEARCH_DEBOUNCE_S)
    _select_college_grad(page)
    # 순서 중요 — 대학/대학원 선택이 SCH_SUBJ_NM을 비우므로 마지막에 채운다.
    page.check("#SEARCH_GBN2", force=True)
    page.fill("#SCH_SUBJ_NM", course_name)

    with page.expect_response(
        lambda r: "selectAtlectManual" in r.url, timeout=15_000
    ) as resp_info:
        page.click("text=조회")
    body = json.loads(resp_info.value.text())

    offerings = []
    for row in body.get("data", []):
        offerings.append(
            SyllabusOffering(
                subj_no=row.get("SUBJ_NO", ""),
                class_no=row.get("CLASS_NO", ""),
                subj_nm=row.get("SUBJ_NM", ""),
                prof_no=row.get("PROF_NO") or "",
                prof_nm=row.get("PROF_NM"),
                dept_nm=row.get("MNG_DEPT_NM"),
                has_kor=bool(row.get("PRT_KOR")),
                raw=row,
            )
        )
    return offerings


def download_syllabus_pdf(
    page: Page, offering: SyllabusOffering, out_path: Path, lang: str = "KOR"
) -> Path:
    """이미 검색 결과 페이지에 있다는 전제(직전에 `search_offerings_by_name`을
    호출한 그 `page`)로, 특정 분반의 교수계획표를 PDF로 저장한다.

    `fn_openReport`가 필요로 하는 값은 검색 결과 행의 raw dict 그대로다(`param` —
    JS 쪽 `$(tr).data()`와 동일한 모양)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # page.evaluate(script, arg)는 인자를 하나만 넘긴다 — arrow function엔 자체
    # `arguments` 객체도 없다(외부 스코프를 봤겠지만 evaluate 안에는 외부 스코프가
    # 없다). param/lang을 한 객체로 묶어서 구조분해한다.
    console_msgs: list[str] = []

    def _on_console(msg) -> None:
        console_msgs.append(msg.text)

    page.on("console", _on_console)
    try:
        page.evaluate(
            "({ param, lang }) => { "
            "if (param.PROF_NO == null) param.PROF_NO = ''; "
            "fn_openReport(param, lang); }",
            {"param": offering.raw, "lang": lang},
        )

        deadline = time.monotonic() + _REPORT_TIMEOUT_S
        while time.monotonic() < deadline:
            if any("completed successfully" in m for m in console_msgs):
                break
            time.sleep(0.5)
    finally:
        page.remove_listener("console", _on_console)
    time.sleep(1.5)

    frame = page.frame_locator("#pop_grp_report_clip_iframe")
    frame.locator("#report_menu_save_button").click()
    time.sleep(1)
    frame.locator("#select_label").select_option("pdf")
    time.sleep(0.5)

    with page.expect_download(timeout=_DOWNLOAD_TIMEOUT_MS) as dl_info:
        frame.locator("button:has-text('저장')").first.click()
    dl_info.value.save_as(out_path)

    # 팝업 닫기는 jQuery `.hide('fast', callback)` 애니메이션이라 클릭 즉시 DOM이
    # 사라지지 않는다 — 여기서 안 기다리고 바로 다음 분반의 fn_openReport를 부르면
    # `#pop_grp_report`/`#pop_grp_report_clip_iframe`가 아직 이전 팝업 것이라 새
    # 리포트가 안 열린 것처럼 보이는 타임아웃이 났다(2026-08-24 실측 — 자료구조
    # 7분반 중 3분반이 이 경합으로 실패, 성공/실패가 거의 정확히 번갈아 났다).
    # 애니메이션이 끝나 iframe이 실제로 사라질 때까지 기다린 뒤에 돌아간다.
    try:
        page.click("a.pop_close", timeout=3_000)
        page.locator("#pop_grp_report_clip_iframe").wait_for(state="detached", timeout=5_000)
    except Exception:  # noqa: BLE001 - 팝업이 이미 닫혀 있거나 못 찾아도 다음 분반은 계속 진행
        pass
    return out_path


def crawl_syllabi_for_course_names(
    course_names: list[str],
    year: int,
    semester_code: str,
    out_dir: Path,
    lang: str = "KOR",
    allowed_course_codes: set[str] | None = None,
) -> list[SyllabusCrawlResult]:
    """과목명 목록을 순회하며 검색→(PRT_KOR 있는 분반만) PDF 저장까지 한 세션에서 처리한다.

    브라우저는 재사용하지만 **분반 하나 열 때마다 검색 페이지를 새로 띄운다**
    (`search_offerings_by_name`가 매번 `page.goto`부터 시작). 처음엔 검색 1번 →
    같은 결과 페이지에서 팝업만 여러 번 열고 닫는 방식으로 짰는데, One-Stop의 팝업
    닫기(`gfn_com_closeModalWall`)가 jQuery 애니메이션 이후 `#popupWrap`을
    DOM에서 완전히 제거하지 않고(내용만 비움 + 카운트 기반 suffix로 다음 팝업을
    또 새로 쌓음) 계속 재사용하다 보니, 몇 번 열고 닫으면 같은 id
    (`#pop_grp_report_clip_iframe`)를 가진 iframe이 여러 개 쌓여 Playwright가
    "strict mode violation: resolved to N elements"로 터졌다(2026-08-24 실측 —
    같은 과목 분반을 연달아 열수록 실패율이 올라감, 사이트 자체의 팝업 스택 정리
    로직이 반복 자동화를 상정하고 안 짜인 것으로 보임). 검색 페이지를 통째로
    새로 로드하면 이 누적 자체가 안 생긴다 — 느리지만(분반 하나당 검색 3초
    가량 더 붙음) 확실하다.
    """
    results: list[SyllabusCrawlResult] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(accept_downloads=True).new_page()

        for course_name in course_names:
            try:
                offerings = search_offerings_by_name(page, year, semester_code, course_name)
            except Exception as exc:  # noqa: BLE001 - 크롤링 중 한 과목 실패로 전체를 막지 않는다
                results.append(
                    SyllabusCrawlResult(
                        offering=SyllabusOffering(
                            subj_no="", class_no="", subj_nm=course_name,
                            prof_no="", prof_nm=None, dept_nm=None, has_kor=False,
                        ),
                        pdf_path=None,
                        error=f"검색 실패: {exc}",
                    )
                )
                continue

            for offering in offerings:
                # 동명 과목이 전교에 여러 개 있을 때는 교육과정에서 확인한 코드만 받는다.
                if allowed_course_codes is not None and offering.subj_no not in allowed_course_codes:
                    continue
                if not offering.has_kor:
                    results.append(SyllabusCrawlResult(offering=offering, pdf_path=None))
                    continue

                pdf_name = f"{offering.subj_no}_{offering.class_no}_{lang}.pdf"
                out_path = out_dir / pdf_name
                # 재실행은 누락분 보완 용도다. 이미 받은 원본을 다시 열고 저장하면
                # OneStop 부하와 실행 시간만 늘어나므로 그대로 재사용한다.
                if out_path.exists():
                    results.append(SyllabusCrawlResult(offering=offering, pdf_path=out_path))
                    continue

                # 팝업 DOM 누적을 피하려고 분반마다 검색 페이지를 새로 띄운다(위
                # docstring 참고). 방금 목록에서 받은 offering.raw를 그대로 재사용하지
                # 않고, 같은 검색을 다시 태워서 이 분반 행을 새로 찾는다.
                try:
                    fresh_offerings = search_offerings_by_name(
                        page, year, semester_code, course_name
                    )
                    fresh_offering = next(
                        (
                            o for o in fresh_offerings
                            if o.subj_no == offering.subj_no and o.class_no == offering.class_no
                        ),
                        None,
                    )
                    if fresh_offering is None:
                        raise RuntimeError(
                            f"재검색 결과에서 {offering.subj_no}/{offering.class_no}를 못 찾음"
                        )
                    download_syllabus_pdf(page, fresh_offering, out_path, lang=lang)
                    results.append(SyllabusCrawlResult(offering=offering, pdf_path=out_path))
                except Exception as exc:  # noqa: BLE001 - 한 분반 실패로 나머지를 막지 않는다
                    results.append(
                        SyllabusCrawlResult(offering=offering, pdf_path=None, error=str(exc))
                    )

        browser.close()
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawl PNU Onestop 교수계획표(syllabus) PDFs by course name"
    )
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--semester-code", required=True, help="0010=1학기, 0020=2학기 (raw term code)"
    )
    parser.add_argument("--course-names", nargs="+", required=True)
    parser.add_argument(
        "--allowed-course-codes", nargs="+", default=None,
        help="동명 타 학과 과목을 제외할 교과목코드 목록 (선택)",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("raw_data/crawled_data/onestop_syllabus")
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = crawl_syllabi_for_course_names(
        args.course_names, args.year, args.semester_code, args.output_dir,
        allowed_course_codes=set(args.allowed_course_codes) if args.allowed_course_codes else None,
    )
    summary = {
        "total_offerings": len(results),
        "downloaded": sum(1 for r in results if r.pdf_path is not None),
        "no_syllabus": sum(1 for r in results if r.pdf_path is None and r.error is None),
        "errors": [
            {"subj_no": r.offering.subj_no, "class_no": r.offering.class_no, "error": r.error}
            for r in results
            if r.error is not None
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
