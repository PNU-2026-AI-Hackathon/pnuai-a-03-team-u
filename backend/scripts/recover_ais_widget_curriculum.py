"""부산대 여러 단과대 홈페이지가 쓰는 AIS 동적 위젯(`fnctId=curriculum`,
`/curriculum/{siteId}/{fnctNo}/view` POST)은 크롤링 당시 "등록된 데이터가 없습니다"라는
빈 응답을 줄 때가 있다. 크롤러가 그 빈 스냅샷을 그대로 저장해버리면, 학과 공식
교육과정표가 있는데도 파이프라인이 카탈로그 추정으로 빠진다. 이 위젯은 플레이키해서
같은 요청을 여러 번 재시도하면 실제 데이터가 나오기도 한다 — 이 스크립트가 그 재시도를
자동화한다.

대상: `requirement_course_seed_candidates.csv`에서 source_table이
`department_courses_from_catalog`뿐인(=학과 공식 문서를 못 찾아 카탈로그 추정에만 의존하는)
학과 중, 로컬 소스 폴더에 `fnctId=curriculum` + "등록된 데이터가 없습니다"가 이미 있는
경우만 자동으로 골라 재시도한다. 성공하면 `AIS_교육과정_2026_{학과명}.html`로 저장하고,
이후 `build_department_curriculum_structured_candidates.py`를 다시 돌리면 반영된다.

주의: 대학원(대학원생) 페이지가 아니라 학부(undergrad) 페이지만 받도록
`findUnivType=UNIV`로 고정한다. 대학원 데이터는 이 프로젝트 범위가 아니다.

실행:
    python scripts/recover_ais_widget_curriculum.py
"""

from __future__ import annotations

import csv
import re
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = REPO_ROOT / "raw_data/parsed_experiments/graduation_requirement_seed_tables"
COURSE_CANDIDATES_PATH = SEED_DIR / "requirement_course_seed_candidates.csv"
TARGETS_INDEX_PATH = (
    REPO_ROOT / "raw_data/manual_staging/01_graduation_requirements/by_department/_collection_targets_index.csv"
)
BY_DEPARTMENT_DIR = REPO_ROOT / "raw_data/manual_staging/01_graduation_requirements/by_department"

MAX_RETRIES = 8
SLEEP_SECONDS = 1.5


def find_catalog_only_programs() -> list[str]:
    """source_table이 department_courses_from_catalog뿐인 학과명 목록."""
    by_program: dict[str, set[str]] = {}
    with COURSE_CANDIDATES_PATH.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            by_program.setdefault(row["program_name"], set()).add(row["source_table"])
    return [name for name, sources in by_program.items() if sources == {"department_courses_from_catalog"}]


def find_source_html(program_name: str) -> Path | None:
    for college_dir in BY_DEPARTMENT_DIR.iterdir():
        if not college_dir.is_dir():
            continue
        for dept_dir in college_dir.iterdir():
            if program_name not in dept_dir.name:
                continue
            for sub in ("00_sources", "00_sources_discovered"):
                d = dept_dir / sub
                if not d.exists():
                    continue
                for f in d.iterdir():
                    if f.suffix.lower() not in (".html", ".htm"):
                        continue
                    try:
                        text = f.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        continue
                    if "fnctId=curriculum" in text and "등록된 데이터가 없습니다" in text:
                        return f
    return None


def find_college_name(program_name: str) -> str | None:
    with TARGETS_INDEX_PATH.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row["program_name"] == program_name:
                return row["college_name"]
    return None


def extract_fnct_no(text: str) -> str | None:
    m = re.search(r"fnctId=curriculum,fnctNo=(\d+)", text)
    return m.group(1) if m else None


def extract_site_id(text: str) -> str | None:
    m = re.search(r'defaultTextSiteId\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else None


def get_college_code(site_id: str, college_name: str) -> str | None:
    # 이 서버는 정상 데이터를 주면서도 HTTP 상태코드를 404로 보내는 경우가 있어
    # raise_for_status()를 쓰지 않고 본문을 바로 파싱한다.
    resp = requests.post(f"https://{site_id}.pusan.ac.kr/ais/getDeptInfoDeptList", timeout=15)
    for row in resp.json():
        if row["deptNm"] == college_name:
            return row["deptCd"]
    return None


def get_dept_code(site_id: str, college_code: str, dept_name: str) -> str | None:
    resp = requests.post(
        f"https://{site_id}.pusan.ac.kr/ais/UNIV/{college_code}/getDeptInfoMajorList", timeout=15
    )
    for row in resp.json():
        if "(폐지)" in row["deptNm"]:
            continue
        if row["deptNm"] == f"{dept_name}({row['deptCd']})":
            return row["deptCd"]
    return None


def fetch_curriculum(site_id: str, fnct_no: str, college_code: str, dept_code: str) -> str | None:
    url = f"https://{site_id}.pusan.ac.kr/curriculum/{site_id}/{fnct_no}/view"
    data = {
        "findYear": "2026",
        "findUnivType": "UNIV",  # 학부만. 대학원(GRAD)은 이 프로젝트 범위 밖.
        "findUnivCd": college_code,
        "findDeptCd": dept_code,
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(url, data=data, timeout=15)
            if "등록된 데이터가 없습니다" not in resp.text and "교과목번호" in resp.text:
                return resp.text
        except requests.RequestException as exc:
            print(f"    시도 {attempt}: 요청 오류 {exc}")
        time.sleep(SLEEP_SECONDS)
    return None


def main() -> None:
    catalog_only = find_catalog_only_programs()
    print(f"카탈로그 추정 전용 학과 {len(catalog_only)}개 중 복구 가능한 패턴 탐색...")

    results: list[tuple[str, str]] = []
    for program_name in catalog_only:
        source_html = find_source_html(program_name)
        if not source_html:
            continue  # 이 패턴이 아니면 조용히 건너뜀 (대상이 아님)

        print(f"=== {program_name} ===")
        text = source_html.read_text(encoding="utf-8", errors="replace")
        site_id = extract_site_id(text)
        fnct_no = extract_fnct_no(text)
        college_name = find_college_name(program_name)
        if not site_id or not fnct_no or not college_name:
            print(f"  site_id/fnctNo/단과대학명 중 하나를 못 찾음, 건너뜀")
            results.append((program_name, "missing_metadata"))
            continue

        try:
            college_code = get_college_code(site_id, college_name)
            dept_code = get_dept_code(site_id, college_code, program_name) if college_code else None
        except Exception as exc:
            print(f"  코드 조회 실패: {exc}")
            results.append((program_name, f"lookup_error:{exc}"))
            continue
        if not college_code or not dept_code:
            print(f"  AIS 코드를 못 찾음 (college_code={college_code}, dept_code={dept_code})")
            results.append((program_name, "no_ais_code"))
            continue

        print(f"  site_id={site_id} fnct_no={fnct_no} college_code={college_code} dept_code={dept_code}, 재시도 중...")
        html = fetch_curriculum(site_id, fnct_no, college_code, dept_code)
        if html:
            out_path = source_html.parent / f"AIS_교육과정_2026_{program_name}.html"
            out_path.write_text(html, encoding="utf-8")
            print(f"  ✅ 복구 성공 -> {out_path}")
            results.append((program_name, "recovered"))
        else:
            print(f"  ❌ {MAX_RETRIES}번 재시도했지만 계속 빈 응답")
            results.append((program_name, "still_empty"))

    print("\n=== 요약 ===")
    if not results:
        print("  복구 가능한 패턴을 가진 학과가 없음")
    for name, status in results:
        print(f"  {name}: {status}")
    print(
        "\n복구된 게 있으면 이어서 실행:\n"
        "  python scripts/build_department_curriculum_structured_candidates.py\n"
        "  python scripts/build_graduation_requirement_seed_tables.py\n"
        "  python -m scripts.seed_graduation_requirements"
    )


if __name__ == "__main__":
    main()
