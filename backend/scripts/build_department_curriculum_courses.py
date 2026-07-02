from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.ingestion.normalizers.graduation_requirement_normalizer import (
    GraduationRequirementNormalizer,
    RequirementNormalizerContext,
)


SUPPORTED_SOURCE_SUFFIXES = {".html", ".txt"}
CATALOG_COLUMNS = [
    "year",
    "semester",
    "course_code",
    "course_name",
    "category",
    "credits",
    "offering_department",
    "display_department_name",
]

COURSE_OUTPUT_COLUMNS = [
    "college",
    "department_code",
    "department_name",
    "document_title",
    "curriculum_year",
    "admission_type",
    "section_title",
    "recommended_year",
    "recommended_semester",
    "category",
    "raw_course_name",
    "raw_credit",
    "source_file",
    "source_kind",
    "source_course_code",
    "matched_course_code",
    "matched_course_name",
    "match_status",
    "match_method",
    "matched_terms",
    "matched_departments",
    "choice_rule_types",
    "choice_rule_raw",
    "needs_review",
    "review_reason",
]

SUMMARY_COLUMNS = [
    "college",
    "department_code",
    "department_name",
    "source_dirs_with_files",
    "course_rows",
    "matched",
    "ambiguous",
    "unmatched",
    "needs_review",
]

UNSUPPORTED_COLUMNS = [
    "college",
    "department_code",
    "department_name",
    "source_file",
    "suffix",
    "reason",
]


@dataclass(frozen=True)
class DepartmentTarget:
    college: str
    department_code: str
    department_name: str
    folder_path: Path


@dataclass(frozen=True)
class CourseCatalogIndex:
    by_name: dict[str, list[dict[str, str]]]
    by_code: dict[str, list[dict[str, str]]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build department-level curriculum course rows from staged requirement sources."
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path(
            "../raw_data/manual_staging/01_graduation_requirements/by_department/_collection_targets_index.csv"
        ),
    )
    parser.add_argument(
        "--course-catalog",
        type=Path,
        default=Path(
            "../raw_data/parsed_experiments/course_catalog_multi_term/2023_2026_course_catalog_combined_cleaned_dedup.csv"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../raw_data/parsed_experiments/department_curriculum_courses"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    targets = read_targets(args.targets)
    catalog_index = read_course_catalog(args.course_catalog)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    course_rows: list[dict[str, Any]] = []
    unsupported_rows: list[dict[str, Any]] = []
    summary = defaultdict(lambda: {"course_rows": 0, "matched": 0, "ambiguous": 0, "unmatched": 0, "needs_review": 0, "source_dirs_with_files": 0})

    for target in targets:
        source_dir = target.folder_path / "00_sources"
        source_files = [
            path for path in source_dir.iterdir()
            if source_dir.exists() and path.is_file() and not path.name.startswith(".")
        ] if source_dir.exists() else []
        if source_files:
            summary[target.department_code]["source_dirs_with_files"] = 1

        for source in source_files:
            if source.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
                unsupported_rows.append(
                    {
                        "college": target.college,
                        "department_code": target.department_code,
                        "department_name": target.department_name,
                        "source_file": str(source),
                        "suffix": source.suffix.lower(),
                        "reason": "automatic extraction for this source type is not implemented yet",
                    }
                )

        if any(path.suffix.lower() == ".html" for path in source_files):
            normalized = normalize_html_sources(source_dir, target)
            course_rows.extend(rows_from_normalized_html(normalized, target, catalog_index))

        for txt_path in sorted(path for path in source_files if path.suffix.lower() == ".txt"):
            course_rows.extend(rows_from_txt_source(txt_path, target, catalog_index))

    for row in course_rows:
        dept_summary = summary[row["department_code"]]
        dept_summary["course_rows"] += 1
        dept_summary[row["match_status"]] += 1
        if row["needs_review"] == "Y":
            dept_summary["needs_review"] += 1

    write_csv(output_dir / "department_curriculum_courses.csv", COURSE_OUTPUT_COLUMNS, course_rows)
    write_csv(output_dir / "unsupported_sources.csv", UNSUPPORTED_COLUMNS, unsupported_rows)
    write_csv(
        output_dir / "department_curriculum_match_summary.csv",
        SUMMARY_COLUMNS,
        build_summary_rows(targets, summary),
    )
    write_json(
        output_dir / "summary.json",
        {
            "targets": len(targets),
            "course_rows": len(course_rows),
            "unsupported_sources": len(unsupported_rows),
            "output_files": {
                "courses": str(output_dir / "department_curriculum_courses.csv"),
                "summary": str(output_dir / "department_curriculum_match_summary.csv"),
                "unsupported": str(output_dir / "unsupported_sources.csv"),
            },
        },
    )
    print(output_dir)


def read_targets(path: Path) -> list[DepartmentTarget]:
    with path.resolve().open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return [
            DepartmentTarget(
                college=row["college_name"],
                department_code=row["academic_program_code"],
                department_name=row["program_name"],
                folder_path=Path("..") / row["folder_path"],
            )
            for row in reader
        ]


def read_course_catalog(path: Path) -> CourseCatalogIndex:
    by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_code: dict[str, list[dict[str, str]]] = defaultdict(list)
    with path.resolve().open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            if not row.get("course_name"):
                continue
            item = {column: row.get(column, "") for column in CATALOG_COLUMNS}
            item["normalized_course_name"] = normalize_course_name(row["course_name"])
            by_name[item["normalized_course_name"]].append(item)
            if item["course_code"]:
                by_code[item["course_code"]].append(item)
    return CourseCatalogIndex(by_name=by_name, by_code=by_code)


def normalize_html_sources(source_dir: Path, target: DepartmentTarget) -> dict[str, Any]:
    normalizer = GraduationRequirementNormalizer()
    context = RequirementNormalizerContext(
        college=target.college,
        department_code=target.department_code,
        department_name=target.department_name,
    )
    normalized = normalizer.normalize_directory(source_dir, context)
    normalized_dir = source_dir.parent / "01_normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    (normalized_dir / "graduation_requirements.normalized.json").write_text(
        normalizer.dumps(normalized),
        encoding="utf-8",
    )
    return normalized


def rows_from_normalized_html(
    normalized: dict[str, Any],
    target: DepartmentTarget,
    catalog_index: CourseCatalogIndex,
) -> list[dict[str, Any]]:
    rows = []
    for document in normalized.get("documents", []):
        track = document.get("track", {})
        for plan in document.get("course_plans", []):
            section_title = plan.get("section_title") or ""
            for table_row in plan.get("rows", []):
                if table_row.get("row_type") != "courses":
                    continue
                category = table_row.get("category") or ""
                for semester in table_row.get("semesters", []):
                    year_level, term = parse_recommended_period(semester.get("semester") or section_title)
                    choice_rules = semester.get("choice_rules") or []
                    for course in semester.get("course_items", []):
                        raw_name = course.get("name")
                        if not raw_name or is_placeholder_course_name(raw_name):
                            continue
                        matched = match_course(raw_name, course.get("credit"), target.department_name, catalog_index)
                        rows.append(
                            build_course_row(
                                target=target,
                                document_title=document.get("document_title", ""),
                                curriculum_year=track.get("curriculum_year"),
                                admission_type=track.get("admission_type"),
                                section_title=section_title,
                                recommended_year=year_level,
                                recommended_semester=term,
                                category=category,
                                raw_course_name=raw_name,
                                raw_credit=course.get("credit"),
                                source_file=document.get("source_file", ""),
                                source_kind="html",
                                source_course_code="",
                                matched=matched,
                                choice_rules=choice_rules,
                            )
                        )
    return rows


def rows_from_txt_source(
    txt_path: Path,
    target: DepartmentTarget,
    catalog_index: CourseCatalogIndex,
) -> list[dict[str, Any]]:
    text = txt_path.read_text(encoding="utf-8")
    if not re.search(r"^NO\t", text, flags=re.MULTILINE):
        return rows_from_code_list_txt_source(txt_path, text, target, catalog_index)

    rows = []
    document_title = txt_path.stem
    curriculum_year = infer_year(document_title)
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.split("\t")]
        if len(cells) < 7 or not cells[0].isdigit():
            continue
        raw_name = cells[-3]
        source_course_code = cells[-2]
        raw_credit = cells[-1]
        if not raw_name or is_placeholder_course_name(raw_name):
            continue
        matched = match_course(raw_name, raw_credit, target.department_name, catalog_index, source_course_code)
        rows.append(
            build_course_row(
                target=target,
                document_title=document_title,
                curriculum_year=curriculum_year,
                admission_type="unknown",
                section_title="교과목소개",
                recommended_year=cells[1],
                recommended_semester=cells[2],
                category=cells[3],
                raw_course_name=raw_name,
                raw_credit=raw_credit,
                source_file=txt_path.name,
                source_kind="txt",
                source_course_code=source_course_code,
                matched=matched,
                choice_rules=[],
            )
        )
    return rows


def rows_from_code_list_txt_source(
    txt_path: Path,
    text: str,
    target: DepartmentTarget,
    catalog_index: CourseCatalogIndex,
) -> list[dict[str, Any]]:
    rows = []
    document_title = txt_path.stem
    curriculum_year = infer_year(document_title)
    seen_codes = set()
    for match in re.finditer(r"\b(?:[A-Z]{2}\d{7}|Z[A-Z]z?\d{6}|Z[A-Z]\d{7})\b", text):
        course_code = match.group(0)
        if course_code in seen_codes:
            continue
        seen_codes.add(course_code)
        candidates = catalog_index.by_code.get(course_code, [])
        matched = summarize_match(candidates, "matched", "course_code") if candidates else empty_match("unmatched", "course_code")
        course_name = matched["course_name"].split("|", 1)[0] if matched["course_name"] else ""
        category = infer_category_from_context(text[max(0, match.start() - 120):match.start()])
        rows.append(
            build_course_row(
                target=target,
                document_title=document_title,
                curriculum_year=curriculum_year,
                admission_type="unknown",
                section_title="교육과정",
                recommended_year="",
                recommended_semester="",
                category=category,
                raw_course_name=course_name or course_code,
                raw_credit="",
                source_file=txt_path.name,
                source_kind="txt_code_list",
                source_course_code=course_code,
                matched=matched,
                choice_rules=[],
            )
        )
    return rows


def build_course_row(
    target: DepartmentTarget,
    document_title: str,
    curriculum_year: str | None,
    admission_type: str | None,
    section_title: str,
    recommended_year: str | None,
    recommended_semester: str | None,
    category: str,
    raw_course_name: str,
    raw_credit: str | None,
    source_file: str,
    source_kind: str,
    source_course_code: str,
    matched: dict[str, str],
    choice_rules: list[dict[str, Any]],
) -> dict[str, Any]:
    review_reasons = []
    if matched["match_status"] != "matched":
        review_reasons.append(f"course catalog match status is {matched['match_status']}")
    if choice_rules:
        review_reasons.append("choice rule is attached to this semester cell")
    return {
        "college": target.college,
        "department_code": target.department_code,
        "department_name": target.department_name,
        "document_title": document_title,
        "curriculum_year": curriculum_year or "",
        "admission_type": admission_type or "",
        "section_title": section_title,
        "recommended_year": recommended_year or "",
        "recommended_semester": recommended_semester or "",
        "category": category,
        "raw_course_name": raw_course_name,
        "raw_credit": raw_credit or "",
        "source_file": source_file,
        "source_kind": source_kind,
        "source_course_code": source_course_code,
        "matched_course_code": matched["course_code"],
        "matched_course_name": matched["course_name"],
        "match_status": matched["match_status"],
        "match_method": matched["match_method"],
        "matched_terms": matched["terms"],
        "matched_departments": matched["departments"],
        "choice_rule_types": "|".join(rule.get("rule_type", "") for rule in choice_rules),
        "choice_rule_raw": " || ".join(compact_text(rule.get("raw_text", "")) for rule in choice_rules),
        "needs_review": "Y" if review_reasons else "N",
        "review_reason": " | ".join(review_reasons),
    }


def match_course(
    raw_name: str,
    raw_credit: str | None,
    department_name: str,
    catalog_index: CourseCatalogIndex,
    source_course_code: str = "",
) -> dict[str, str]:
    if source_course_code:
        code_matches = catalog_index.by_code.get(source_course_code, [])
        if code_matches:
            return summarize_match(code_matches, "matched", "course_code")

    normalized_name = normalize_course_name(raw_name)
    candidates = catalog_index.by_name.get(normalized_name, [])

    if not candidates:
        return empty_match("unmatched", "normalized_name")

    credit = normalize_credit(raw_credit)
    if credit:
        credit_matches = [item for item in candidates if normalize_credit(item.get("credits")) == credit]
        if credit_matches:
            candidates = credit_matches

    dept_matches = [
        item for item in candidates
        if department_name and department_name in {item.get("offering_department"), item.get("display_department_name")}
    ]
    if dept_matches:
        return summarize_match(dept_matches, "matched", "name_credit_department")

    unique_codes = sorted({item["course_code"] for item in candidates if item["course_code"]})
    if len(unique_codes) == 1:
        return summarize_match(candidates, "matched", "name_credit_unique_code")
    return summarize_match(candidates, "ambiguous", "normalized_name")


def summarize_match(candidates: list[dict[str, str]], status: str, method: str) -> dict[str, str]:
    codes = sorted({item["course_code"] for item in candidates if item["course_code"]})
    names = sorted({item["course_name"] for item in candidates if item["course_name"]})
    terms = sorted({f"{item['year']}_{item['semester']}" for item in candidates if item["year"] and item["semester"]})
    departments = sorted({
        item["offering_department"] or item["display_department_name"]
        for item in candidates
        if item["offering_department"] or item["display_department_name"]
    })
    return {
        "match_status": status,
        "match_method": method,
        "course_code": "|".join(codes),
        "course_name": "|".join(names),
        "terms": "|".join(terms),
        "departments": "|".join(departments),
    }


def empty_match(status: str, method: str) -> dict[str, str]:
    return {
        "match_status": status,
        "match_method": method,
        "course_code": "",
        "course_name": "",
        "terms": "",
        "departments": "",
    }


def normalize_course_name(value: str) -> str:
    value = value.strip()
    value = value.replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III").replace("Ⅳ", "IV")
    value = value.replace("(Ⅰ)", "(I)").replace("(Ⅱ)", "(II)").replace("(Ⅲ)", "(III)")
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[ㆍ·]", "", value)
    return value.lower()


def normalize_credit(value: str | None) -> str:
    if not value:
        return ""
    value = str(value).strip()
    if "-" in value:
        return value.split("-", 1)[0]
    if value.endswith(".0"):
        return value[:-2]
    return value


def parse_recommended_period(value: str) -> tuple[str | None, str | None]:
    year_match = re.search(r"(\d+)학년", value)
    semester_match = re.search(r"(\d+)학기", value)
    return (
        f"{year_match.group(1)}학년" if year_match else None,
        f"{semester_match.group(1)}학기" if semester_match else None,
    )


def infer_year(value: str) -> str:
    match = re.search(r"(20\d{2})", value)
    return match.group(1) if match else ""


def infer_category_from_context(value: str) -> str:
    compact = compact_text(value)
    for category in ("전공필수", "전공선택", "전공기초", "효원핵심교양", "효원균형교양", "효원창의교양", "교양필수", "교양선택"):
        if category in compact:
            return category
    return ""


def is_placeholder_course_name(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    return (
        not compact
        or compact in {"1)", "2)", "3)", "1과목수강", "미수강과목중"}
        or "미수강과목중" in compact
    )


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def build_summary_rows(
    targets: list[DepartmentTarget],
    summary: dict[str, dict[str, int]],
) -> list[dict[str, Any]]:
    rows = []
    for target in targets:
        item = summary[target.department_code]
        rows.append(
            {
                "college": target.college,
                "department_code": target.department_code,
                "department_name": target.department_name,
                "source_dirs_with_files": item["source_dirs_with_files"],
                "course_rows": item["course_rows"],
                "matched": item["matched"],
                "ambiguous": item["ambiguous"],
                "unmatched": item["unmatched"],
                "needs_review": item["needs_review"],
            }
        )
    return rows


def write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
