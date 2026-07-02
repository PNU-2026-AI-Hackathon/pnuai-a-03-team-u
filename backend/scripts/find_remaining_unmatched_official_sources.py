from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.ingestion.crawlers.department_curriculum_source_crawler import (  # noqa: E402
    TargetProgram,
    create_session,
    discover_pnu_homepages,
    discover_source_candidates,
)


OUTPUT_COLUMNS = [
    "college_name",
    "academic_program_code",
    "program_name",
    "search_status",
    "official_homepage_url",
    "official_listed_program_name",
    "homepage_match_method",
    "curriculum_candidate_count",
    "undergraduate_candidate_count",
    "minor_candidate_count",
    "dual_major_candidate_count",
    "top_candidate_title",
    "top_candidate_url",
    "top_candidate_score",
    "next_action",
]


MANUAL_HOMEPAGE_BY_PROGRAM = {
    "약학부(통합6년제)": ("약학전공", "약학부는 대표 학과 링크에서 약학전공/제약학전공 공용 홈페이지로 운영됨"),
}

CONTRACT_DEPARTMENT_NAMES = {
    "발전공학과",
    "스마트가전공학과",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search official PNU homepage links for reclassified unmatched departments."
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path(
            "../raw_data/manual_staging/01_graduation_requirements/by_department/_collection_targets_index.csv"
        ),
    )
    parser.add_argument(
        "--reclassified",
        type=Path,
        default=Path(
            "../raw_data/parsed_experiments/department_curriculum_reclassification/curriculum_source_truly_missing_candidates.csv"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../raw_data/parsed_experiments/department_curriculum_official_search"),
    )
    parser.add_argument("--max-pages-per-site", type=int, default=8)
    parser.add_argument("--delay-seconds", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    remaining_rows = read_csv(args.reclassified.resolve())
    session = create_session()
    official_links = discover_pnu_homepages(session, delay_seconds=args.delay_seconds)
    links_by_name = {normalize_name(link.listed_program_name): link for link in official_links}

    output_rows: list[dict[str, str]] = []
    for row in remaining_rows:
        link, method = find_official_link(row["program_name"], links_by_name)
        if not link:
            output_rows.append(not_found_row(row))
            continue

        target = TargetProgram(
            college_name=row["college_name"],
            academic_program_code=row["academic_program_code"],
            program_name=row["program_name"],
            folder_path="",
        )
        candidates = discover_source_candidates(
            session,
            target,
            link.homepage_url,
            max_pages=args.max_pages_per_site,
            delay_seconds=args.delay_seconds,
        )
        top = candidates[0] if candidates else None
        status = "official_curriculum_source_found" if candidates else "official_homepage_found_no_curriculum_candidate"
        output_rows.append(
            {
                "college_name": row["college_name"],
                "academic_program_code": row["academic_program_code"],
                "program_name": row["program_name"],
                "search_status": status,
                "official_homepage_url": link.homepage_url,
                "official_listed_program_name": link.listed_program_name,
                "homepage_match_method": method,
                "curriculum_candidate_count": str(len(candidates)),
                "undergraduate_candidate_count": str(sum(1 for item in candidates if item.has_undergraduate_keyword)),
                "minor_candidate_count": str(sum(1 for item in candidates if item.has_minor_keyword)),
                "dual_major_candidate_count": str(sum(1 for item in candidates if item.has_dual_major_keyword)),
                "top_candidate_title": top.candidate_title if top else "",
                "top_candidate_url": top.candidate_url if top else "",
                "top_candidate_score": str(top.score) if top else "",
                "next_action": next_action(status),
            }
        )

    output_rows.sort(key=lambda item: (status_order(item["search_status"]), item["college_name"], item["program_name"]))
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "official_source_search_results.csv", OUTPUT_COLUMNS, output_rows)
    still_missing = [row for row in output_rows if row["search_status"] == "still_not_found"]
    write_csv(output_dir / "still_not_found_after_official_search.csv", OUTPUT_COLUMNS, still_missing)
    final_source_targets = final_source_search_targets(still_missing)
    write_csv(
        output_dir / "final_source_search_targets.csv",
        [
            "college_name",
            "academic_program_code",
            "program_name",
            "search_target_type",
            "reason",
            "next_action",
        ],
        final_source_targets,
    )
    summary = {
        "input_remaining_rows": len(remaining_rows),
        "status_counts": dict(Counter(row["search_status"] for row in output_rows)),
        "still_not_found_count": len(still_missing),
        "final_source_search_target_count": len(final_source_targets),
        "outputs": {
            "official_source_search_results": str(output_dir / "official_source_search_results.csv"),
            "still_not_found_after_official_search": str(output_dir / "still_not_found_after_official_search.csv"),
            "final_source_search_targets": str(output_dir / "final_source_search_targets.csv"),
            "readme": str(output_dir / "README.md"),
        },
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "README.md").write_text(build_readme(summary), encoding="utf-8")
    print(output_dir)


def find_official_link(program_name: str, links_by_name: dict[str, Any]) -> tuple[Any | None, str]:
    variants = name_variants(program_name)
    for variant in variants:
        link = links_by_name.get(variant)
        if link:
            return link, "pnu_listed_name_variant"

    manual = MANUAL_HOMEPAGE_BY_PROGRAM.get(program_name)
    if manual:
        listed_name, reason = manual
        link = links_by_name.get(normalize_name(listed_name))
        if link:
            return link, f"manual_parent_link: {reason}"
    return None, ""


def name_variants(program_name: str) -> list[str]:
    variants = [program_name]
    without_parentheses = re.sub(r"\([^)]*\)", "", program_name).strip()
    variants.append(without_parentheses)
    if program_name.endswith("(통합6년제)"):
        variants.append(program_name.replace("(통합6년제)", "").strip())
    if "·" in program_name:
        variants.append(program_name.replace("·", ""))
    if "." in program_name:
        variants.append(program_name.replace(".", ""))
    normalized = []
    seen = set()
    for variant in variants:
        key = normalize_name(variant)
        if key and key not in seen:
            seen.add(key)
            normalized.append(key)
    return normalized


def not_found_row(row: dict[str, str]) -> dict[str, str]:
    return {
        "college_name": row["college_name"],
        "academic_program_code": row["academic_program_code"],
        "program_name": row["program_name"],
        "search_status": "still_not_found",
        "official_homepage_url": "",
        "official_listed_program_name": "",
        "homepage_match_method": "",
        "curriculum_candidate_count": "0",
        "undergraduate_candidate_count": "0",
        "minor_candidate_count": "0",
        "dual_major_candidate_count": "0",
        "top_candidate_title": "",
        "top_candidate_url": "",
        "top_candidate_score": "",
        "next_action": "부산대 대표 학과 링크에 없으므로 학사요람/학부대학/단과대학 공지에서 수동 확인한다.",
    }


def next_action(status: str) -> str:
    if status == "official_curriculum_source_found":
        return "공식 홈페이지 후보 URL을 다운로드/파싱 대상에 추가한다."
    if status == "official_homepage_found_no_curriculum_candidate":
        return "공식 홈페이지는 찾았으나 제한 탐색에서 교육과정 후보가 없으므로 메뉴를 수동 확인한다."
    return "부산대 대표 학과 링크에 없으므로 학사요람/학부대학/단과대학 공지에서 수동 확인한다."


def status_order(status: str) -> int:
    return {
        "still_not_found": 0,
        "official_homepage_found_no_curriculum_candidate": 1,
        "official_curriculum_source_found": 2,
    }.get(status, 9)


def final_source_search_targets(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    skip = {
        "한국·동아시아학전공": "국제학부 원문 안에서 분리",
        "의예과": "의학과 교육과정 안에서 예과 2년 단계로 분리",
    }
    output = []
    seen = set()
    for row in rows:
        name = row["program_name"]
        if name in skip:
            continue
        key = (row["college_name"], name)
        if key in seen:
            continue
        seen.add(key)
        reason = "부산대 대표 학과 링크 기준으로도 공식 교육과정 후보 미확인"
        search_target_type = "parent_or_direct_source"
        next_action = "학사요람/단과대학/학부대학/융합전공 별도 페이지에서 공식 교육과정 원문을 확인한다."
        if name in CONTRACT_DEPARTMENT_NAMES:
            search_target_type = "contract_department_source"
            reason = "계약학과로 분류됨; 일반 학과 홈페이지보다 계약학과 교육과정표/수강편람 계약학과 별표/운영자료 확인 필요"
            next_action = "수강편람 계약학과 졸업이수학점 편성표, 계약학과 운영부서 공지, 산업체 계약학과 안내에서 원문을 확인한다."
        if name == "국제학부":
            reason = "상위 학부 원문 필요; 한국·동아시아학전공은 이 원문 안에서 분리"
        if name == "의학과":
            reason = "의학과 전체 교육과정 원문 필요; 의예과 2년 단계는 이 원문 안에서 분리"
        output.append(
            {
                "college_name": row["college_name"],
                "academic_program_code": row["academic_program_code"],
                "program_name": name,
                "search_target_type": search_target_type,
                "reason": reason,
                "next_action": next_action,
            }
        )
    return output


def normalize_name(value: str) -> str:
    return re.sub(r"[\s:()（）·ㆍ・.,/\-_\[\]{}<>|\"'“”‘’]", "", value or "").lower()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_readme(summary: dict[str, Any]) -> str:
    return f"""# 공식 홈페이지 재검색 결과

`department_curriculum_reclassification/curriculum_source_truly_missing_candidates.csv`에 남은 후보를 부산대 대표 학과 링크에서 다시 검색한 결과다.

## 현재 요약

- 재검색 입력: {summary["input_remaining_rows"]}개
- 대표 링크/교육과정 후보까지 찾음: {summary["status_counts"].get("official_curriculum_source_found", 0)}개
- 대표 링크는 찾았으나 교육과정 후보 미확인: {summary["status_counts"].get("official_homepage_found_no_curriculum_candidate", 0)}개
- 대표 링크에서도 못 찾음: {summary["still_not_found_count"]}개
- 구조를 접은 최종 원문 검색 타깃: {summary["final_source_search_target_count"]}개

## 파일

- `official_source_search_results.csv`: 재검색 전체 결과.
- `still_not_found_after_official_search.csv`: 공식 대표 링크 기준으로도 남은 수동 확인 대상.
- `final_source_search_targets.csv`: 교양학부 제외, 예과/하위전공을 부모 원문으로 접은 최종 원문 검색 타깃.
- `summary.json`: 집계 통계.

`still_not_found`는 최종 부재 확정이 아니다. 학사요람, 단과대학 공지, 학부대학/융합전공 별도 페이지까지 확인한 뒤에만 원문 없음으로 확정한다.
"""


if __name__ == "__main__":
    main()
