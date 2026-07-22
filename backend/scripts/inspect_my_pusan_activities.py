"""my.pusan.ac.kr 학생 경력 인증서 페이지 HTML 정찰용 스크립트.

/ko/extracurricular/career/certificate 한 페이지에 완료된 비교과 이수 프로그램이
종합 리포트로 나오는 것으로 파악. 이 페이지가 실제로 그런지 확인하고 표 골격을
/tmp/my_pusan_certificate.html로 덤프한다. 이 산출물을 바탕으로 실제 크롤러를 작성.

진행중 상태 프로그램은 이 페이지엔 안 뜰 것으로 예상 — 어차피 완료돼야 활동이수로
인정되므로 완료본만 있어도 충분하다는 정책(2026-07-23 결정).

실행:
    ./.venv/bin/python -m scripts.inspect_my_pusan_activities \
        --login-id <학번> --login-pw <비번>

또는 환경변수 PNU_LOGIN_ID / PNU_LOGIN_PW를 세팅하고 인자 없이 실행.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.ingestion.crawlers.pnu_session import login

DUMP_DIR = Path("/tmp")

TARGETS = [
    ("certificate", "https://my.pusan.ac.kr/ko/extracurricular/career/certificate"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login-id", default=os.environ.get("PNU_LOGIN_ID"))
    parser.add_argument("--login-pw", default=os.environ.get("PNU_LOGIN_PW"))
    parser.add_argument("--headless", action="store_true", default=False,
                        help="브라우저 헤드리스 모드. 기본은 창 띄워 육안 확인")
    args = parser.parse_args()
    # 인자가 없어도 pnu_session.login()이 settings.PNU_LOGIN_ID/PW로 자동 폴백한다.

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        try:
            page = login(browser, login_id=args.login_id, login_pw=args.login_pw)
            context = page.context
            for label, url in TARGETS:
                print(f"\n[{label}] navigating {url}")
                target = context.new_page()
                try:
                    target.goto(url, wait_until="networkidle", timeout=30000)
                except Exception as exc:  # noqa: BLE001
                    print(f"  goto 실패: {exc}")
                # 로그인 화면으로 튕겼는지 즉시 확인
                final_url = target.url
                title = target.title() or ""
                print(f"  final_url = {final_url}")
                print(f"  title     = {title}")
                # dump
                out = DUMP_DIR / f"my_pusan_activities_{label}.html"
                out.write_text(target.content(), encoding="utf-8")
                print(f"  saved -> {out} ({out.stat().st_size} bytes)")
                target.close()
        finally:
            browser.close()

    print("\n정찰 완료. /tmp/my_pusan_activities_*.html 을 열어보고 표 구조를 확인하세요.")
    print("헤드풀 모드였으면 창에서도 확인 가능. 결과 요약을 공유하면 파서를 이어 작성합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
