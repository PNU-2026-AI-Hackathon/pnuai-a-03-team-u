from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


OUTPUT_COLUMNS = [
    "college_name",
    "academic_program_code",
    "program_name",
    "old_source_status",
    "reclassified_status",
    "evidence_level",
    "parent_academic_program_code",
    "parent_program_name",
    "parent_homepage_url",
    "parent_source_status",
    "parent_candidate_count",
    "parent_course_candidate_count",
    "parent_rule_candidate_count",
    "reason",
    "next_action",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reclassify homepage-unmatched departments when parent/umbrella curriculum sources exist."
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path(
            "../raw_data/manual_staging/01_graduation_requirements/by_department/_collection_targets_index.csv"
        ),
    )
    parser.add_argument(
        "--review-status",
        type=Path,
        default=Path("../raw_data/parsed_experiments/department_curriculum_review_pack/department_parse_status.csv"),
    )
    parser.add_argument(
        "--course-candidates",
        type=Path,
        default=Path(
            "../raw_data/parsed_experiments/department_curriculum_structured_candidates/curriculum_course_candidates.csv"
        ),
    )
    parser.add_argument(
        "--rule-candidates",
        type=Path,
        default=Path(
            "../raw_data/parsed_experiments/department_curriculum_structured_candidates/curriculum_text_rule_candidates.csv"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../raw_data/parsed_experiments/department_curriculum_reclassification"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    targets = read_csv(args.targets.resolve())
    status_rows = read_csv(args.review_status.resolve())
    course_rows = read_csv(args.course_candidates.resolve())
    rule_rows = read_csv(args.rule_candidates.resolve())

    targets_by_code = {row["academic_program_code"]: row for row in targets}
    status_by_code = {row["academic_program_code"]: row for row in status_rows}
    course_counts = Counter(row["department_code"] for row in course_rows)
    rule_counts = Counter(row["department_code"] for row in rule_rows)
    children_by_parent = build_parent_index(targets, status_by_code, course_counts, rule_counts)

    output_rows: list[dict[str, str]] = []
    for row in status_rows:
        if row.get("source_status") != "homepage_unmatched":
            continue
        target = targets_by_code[row["academic_program_code"]]
        parent = infer_parent(target, targets, status_by_code, course_counts, rule_counts, children_by_parent)
        output_rows.append(build_output_row(target, row, parent, status_by_code, course_counts, rule_counts))

    output_rows.sort(key=lambda item: (status_order(item["reclassified_status"]), item["college_name"], item["program_name"]))
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "homepage_unmatched_reclassified.csv", OUTPUT_COLUMNS, output_rows)
    unresolved_rows = [
        row
        for row in output_rows
        if row["reclassified_status"]
        in {
            "needs_manual_search",
            "parent_unit_needs_source",
            "stage_program_needs_parent_source",
            "contract_department_needs_source",
        }
    ]
    write_csv(output_dir / "curriculum_source_truly_missing_candidates.csv", OUTPUT_COLUMNS, unresolved_rows)
    summary = {
        "homepage_unmatched_input": len(output_rows),
        "status_counts": dict(Counter(row["reclassified_status"] for row in output_rows)),
        "evidence_counts": dict(Counter(row["evidence_level"] for row in output_rows)),
        "truly_missing_candidate_count": len(unresolved_rows),
        "outputs": {
            "homepage_unmatched_reclassified": str(output_dir / "homepage_unmatched_reclassified.csv"),
            "curriculum_source_truly_missing_candidates": str(
                output_dir / "curriculum_source_truly_missing_candidates.csv"
            ),
            "readme": str(output_dir / "README.md"),
        },
        "notes": [
            "parent_curriculum_source_found means an umbrella department in the local target list already has homepage/curriculum candidates.",
            "child_curriculum_source_found means a child specialization has sources that can be used to validate the umbrella row.",
            "non_graduating_unit means the row is not a graduation department/program by itself.",
            "contract_department_needs_source means the row should be checked in contract-department curriculum tables, not only normal department homepages.",
            "needs_manual_search is not a confirmed absence; it is the remaining official-source search queue.",
        ],
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "README.md").write_text(build_readme(summary), encoding="utf-8")
    print(output_dir)


def build_parent_index(
    targets: list[dict[str, str]],
    status_by_code: dict[str, dict[str, str]],
    course_counts: Counter[str],
    rule_counts: Counter[str],
) -> dict[str, list[dict[str, str]]]:
    children: dict[str, list[dict[str, str]]] = defaultdict(list)
    for target in targets:
        parent_name = parent_name_from_program(target["program_name"])
        if not parent_name or parent_name == target["program_name"]:
            continue
        children[parent_name].append(target)
    return {
        parent: [
            child
            for child in child_rows
            if has_source_evidence(child["academic_program_code"], status_by_code, course_counts, rule_counts)
        ]
        for parent, child_rows in children.items()
    }


def infer_parent(
    target: dict[str, str],
    targets: list[dict[str, str]],
    status_by_code: dict[str, dict[str, str]],
    course_counts: Counter[str],
    rule_counts: Counter[str],
    children_by_parent: dict[str, list[dict[str, str]]],
) -> dict[str, Any] | None:
    special = special_academic_structure(target, targets, status_by_code, course_counts, rule_counts)
    if special:
        return special

    parent_name = parent_name_from_program(target["program_name"])
    if parent_name:
        parent = find_target_by_name(targets, target["college_name"], parent_name)
        if parent and has_source_evidence(parent["academic_program_code"], status_by_code, course_counts, rule_counts):
            return {"kind": "parent", "target": parent, "reason": f"상위 단위 `{parent_name}`에 공식 홈페이지/원문 후보가 있음"}

    # Umbrella rows can be validated from child specializations when at least one child has sources.
    child_sources = children_by_parent.get(target["program_name"], [])
    if child_sources:
        best = sorted(
            child_sources,
            key=lambda item: (
                -course_counts[item["academic_program_code"]],
                -rule_counts[item["academic_program_code"]],
                item["program_name"],
            ),
        )[0]
        return {
            "kind": "child",
            "target": best,
            "reason": f"하위 세부전공 `{best['program_name']}`에 원문 후보가 있어 상위 학부 검증에 재사용 가능",
        }

    manual_parent_name = manual_parent_name_for(target["program_name"])
    if manual_parent_name:
        parent = find_target_by_name(targets, target["college_name"], manual_parent_name)
        if parent and has_source_evidence(parent["academic_program_code"], status_by_code, course_counts, rule_counts):
            return {"kind": "parent", "target": parent, "reason": f"수동 규칙상 상위 단위 `{manual_parent_name}`에 묶임"}

    return None


def build_output_row(
    target: dict[str, str],
    old_status: dict[str, str],
    parent: dict[str, Any] | None,
    status_by_code: dict[str, dict[str, str]],
    course_counts: Counter[str],
    rule_counts: Counter[str],
) -> dict[str, str]:
    if parent:
        parent_target = parent["target"]
        parent_status = status_by_code.get(parent_target["academic_program_code"], {})
        parent_code = parent_target["academic_program_code"]
        if parent["kind"] == "contract_department":
            reclassified = "contract_department_needs_source"
            evidence = "structure"
            action = "계약학과 교육과정표, 수강편람 계약학과 별표, 운영부서 공지에서 졸업이수학점과 전공과목을 확인한다."
        elif parent["kind"] == "non_graduating":
            reclassified = "non_graduating_unit"
            evidence = "structure"
            action = "졸업요건 수집 대상에서 제외하거나 공통 교양/모집단위 메타데이터로만 관리한다."
        elif parent["kind"] == "parent_unit":
            reclassified = "parent_unit_needs_source"
            evidence = "structure"
            action = "상위 학부 원문을 찾은 뒤 하위 전공별 표를 분리한다."
        elif parent["kind"] == "stage_program":
            reclassified = "stage_program_needs_parent_source"
            evidence = "structure"
            action = "의학과/치의학과 전체 교육과정 안에서 예과/본과 단계를 분리한다."
        elif parent["kind"] == "child":
            reclassified = "child_curriculum_source_found"
            evidence = "medium"
            action = "하위 세부전공 원문을 상위 학부 행과 연결할지 확인한다."
        else:
            reclassified = "parent_curriculum_source_found"
            evidence = "high"
            action = "상위 학부/학과 원문 안에서 해당 세부전공 표/행을 분리해 매핑한다."
        return {
            "college_name": target["college_name"],
            "academic_program_code": target["academic_program_code"],
            "program_name": target["program_name"],
            "old_source_status": old_status.get("source_status", ""),
            "reclassified_status": reclassified,
            "evidence_level": evidence,
            "parent_academic_program_code": parent_code,
            "parent_program_name": parent_target["program_name"],
            "parent_homepage_url": parent_status.get("homepage_url", ""),
            "parent_source_status": parent_status.get("source_status", ""),
            "parent_candidate_count": parent_status.get("candidate_count", "0"),
            "parent_course_candidate_count": str(course_counts[parent_code]),
            "parent_rule_candidate_count": str(rule_counts[parent_code]),
            "reason": parent["reason"],
            "next_action": action,
        }

    return {
        "college_name": target["college_name"],
        "academic_program_code": target["academic_program_code"],
        "program_name": target["program_name"],
        "old_source_status": old_status.get("source_status", ""),
        "reclassified_status": "needs_manual_search",
        "evidence_level": "none",
        "parent_academic_program_code": "",
        "parent_program_name": "",
        "parent_homepage_url": "",
        "parent_source_status": "",
        "parent_candidate_count": "0",
        "parent_course_candidate_count": "0",
        "parent_rule_candidate_count": "0",
        "reason": "로컬 수집 결과와 상위/하위 학과 규칙에서 원문 후보를 확정하지 못함",
        "next_action": "공식 웹에서 학과/상위 학부 홈페이지와 교육과정 원문을 직접 검색한다.",
    }


def parent_name_from_program(program_name: str) -> str:
    name = normalize_spaces(program_name)
    if "(" in name:
        return normalize_spaces(re.sub(r"\([^)]*\)", "", name))
    for marker in (" ",):
        if marker in name and name.endswith("전공"):
            return name.split(marker, 1)[0]
    for suffix in ("시각디자인전공", "애니메이션전공"):
        if name.startswith("디자인학과") and suffix in name:
            return "디자인학과"
    if name.startswith("무용학과") and name.endswith("전공"):
        return "무용학과"
    if name.startswith("음악학과") and name.endswith("전공"):
        return "음악학과"
    if name.startswith("조형학과") and name.endswith("전공"):
        return "조형학과"
    if name in {"서양화전공", "한국화전공", "조소전공"}:
        return "미술학과"
    return ""


def special_academic_structure(
    target: dict[str, str],
    targets: list[dict[str, str]],
    status_by_code: dict[str, dict[str, str]],
    course_counts: Counter[str],
    rule_counts: Counter[str],
) -> dict[str, Any] | None:
    name = target["program_name"]
    if target.get("program_feature_name") == "계약학과":
        return {
            "kind": "contract_department",
            "target": empty_parent_target(),
            "reason": "계약학과는 일반 학과 홈페이지가 아니라 계약학과 교육과정/수강편람 별표/운영자료에서 원문을 찾아야 함",
        }
    if name.startswith("교양학부") or name == "기타모집단위":
        return {
            "kind": "non_graduating",
            "target": empty_parent_target(),
            "reason": "교양학부/기타모집단위는 학생이 졸업하는 학과별 교육과정 원문 대상이 아니라 공통 교양/모집단위 메타데이터로 처리",
        }
    if name == "국제학부":
        child = find_target_by_name(targets, target["college_name"], "한국·동아시아학전공")
        if child and has_source_evidence(child["academic_program_code"], status_by_code, course_counts, rule_counts):
            return {
                "kind": "child",
                "target": child,
                "reason": "국제학부는 상위 학부이며 하위 전공 원문을 함께 확인해야 함",
            }
        return {
            "kind": "parent_unit",
            "target": empty_parent_target(),
            "reason": "국제학부는 상위 학부이므로 별도 세부전공 원문 또는 학부 공통 원문을 찾아야 함",
        }
    if name == "한국·동아시아학전공":
        parent = find_target_by_name(targets, target["college_name"], "국제학부")
        return {
            "kind": "parent_unit",
            "target": parent or empty_parent_target(),
            "reason": "한국·동아시아학전공은 국제학부 하위 전공으로 학부 원문 안에서 분리해야 함",
        }
    if name == "의예과":
        parent = find_target_by_name(targets, "의과대학", "의학과")
        return {
            "kind": "stage_program",
            "target": parent or empty_parent_target(),
            "reason": "의예과는 의학과 6년 과정 중 예과 2년 단계로 독립 졸업학과가 아니라 의학과 교육과정 안에서 분리",
        }
    return None


def empty_parent_target() -> dict[str, str]:
    return {
        "college_name": "",
        "academic_program_code": "",
        "program_name": "",
    }


def manual_parent_name_for(program_name: str) -> str:
    mapping = {
        "의생명공학전공": "의생명융합공학부",
        "화공생명.환경공학부": "화공생명공학과",
    }
    return mapping.get(program_name, "")


def find_target_by_name(targets: list[dict[str, str]], college_name: str, program_name: str) -> dict[str, str] | None:
    normalized = normalize_name(program_name)
    same_college = [row for row in targets if row["college_name"] == college_name]
    for row in same_college:
        if normalize_name(row["program_name"]) == normalized:
            return row
    for row in targets:
        if normalize_name(row["program_name"]) == normalized:
            return row
    return None


def has_source_evidence(
    code: str,
    status_by_code: dict[str, dict[str, str]],
    course_counts: Counter[str],
    rule_counts: Counter[str],
) -> bool:
    status = status_by_code.get(code, {})
    if status.get("homepage_url") and status.get("source_status") != "homepage_unmatched":
        return True
    if as_int(status.get("candidate_count")) > 0:
        return True
    return course_counts[code] > 0 or rule_counts[code] > 0


def status_order(value: str) -> int:
    return {
        "needs_manual_search": 0,
        "parent_unit_needs_source": 1,
        "stage_program_needs_parent_source": 2,
        "contract_department_needs_source": 3,
        "non_graduating_unit": 4,
        "child_curriculum_source_found": 5,
        "parent_curriculum_source_found": 6,
    }.get(value, 9)


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_name(value: str) -> str:
    return re.sub(r"[\s:()（）·ㆍ・.,/\-_\[\]{}<>|\"'“”‘’]", "", value or "").lower()


def as_int(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


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
    return f"""# 홈페이지 미매칭 재분류 리포트

이 폴더는 기존 `homepage_unmatched` 학과/전공을 다시 분류한 결과다.

## 현재 요약

- 입력 `homepage_unmatched`: {summary["homepage_unmatched_input"]}개
- 진짜 수동 검색 후보: {summary["truly_missing_candidate_count"]}개

## 상태값

- `parent_curriculum_source_found`: 세부 전공 홈페이지는 없지만 상위 학부/학과 홈페이지와 원문 후보가 있다.
- `child_curriculum_source_found`: 상위 학부 행은 직접 원문이 없지만 하위 세부전공 원문이 있다.
- `non_graduating_unit`: 졸업하는 학과/전공이 아니므로 학과별 졸업요건 수집 대상에서 제외한다.
- `parent_unit_needs_source`: 상위 학부라서 하위 전공/학부 공통 원문을 찾아야 한다.
- `stage_program_needs_parent_source`: 예과처럼 상위 학과 과정 안의 단계라서 부모 학과 교육과정 안에서 분리해야 한다.
- `contract_department_needs_source`: 계약학과라서 일반 학과 홈페이지가 아니라 계약학과 교육과정표/수강편람 별표/운영자료에서 찾아야 한다.
- `needs_manual_search`: 로컬 수집 결과와 상위/하위 규칙으로도 공식 원문 후보를 확정하지 못했다.
- `curriculum_source_missing`: 사람이 공식 웹까지 확인한 뒤에만 사용할 최종 상태다. 이 스크립트는 자동으로 이 값을 확정하지 않는다.

## 파일

- `homepage_unmatched_reclassified.csv`: 41개 전체 재분류 결과.
- `curriculum_source_truly_missing_candidates.csv`: 아직 공식 웹 검색이 필요한 후보만 모은 파일.
- `summary.json`: 집계 통계.

## 주의

`needs_manual_search`는 “없음”이 아니다. 공식 웹에서 상위 학부, 학과 홈페이지, 학사공지, 학사요람을 확인한 뒤에만 `curriculum_source_missing`으로 확정한다.
"""


if __name__ == "__main__":
    main()
