from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[1]))


COURSE_COLUMNS = [
    "school",
    "college",
    "department_code",
    "department_name",
    "catalog_department_name",
    "course_code",
    "course_name",
    "category",
    "credits",
    "target_grades",
    "offered_terms",
    "regular_terms",
    "seasonal_terms",
    "sections_count",
    "professors",
    "class_types",
    "general_education_area",
    "latest_year",
    "latest_semester",
    "latest_timetable_raw",
    "latest_remark",
    "program_match_status",
    "needs_review",
    "review_reason",
]

SUMMARY_COLUMNS = [
    "catalog_department_name",
    "college",
    "department_code",
    "department_name",
    "program_match_status",
    "course_count",
    "전공필수",
    "전공선택",
    "전공기초",
    "교양필수",
    "교양선택",
    "일반선택",
    "교직과목",
    "기타",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build provisional department course tables from the multi-term course catalog."
    )
    parser.add_argument(
        "--course-catalog",
        type=Path,
        default=Path(
            "../raw_data/parsed_experiments/course_catalog_multi_term/2023_2026_course_catalog_combined_cleaned_dedup.csv"
        ),
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path(
            "../raw_data/manual_staging/01_graduation_requirements/by_department/_collection_targets_index.csv"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../raw_data/parsed_experiments/department_courses_from_catalog"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    program_index = read_program_index(args.targets)
    catalog_rows = read_catalog(args.course_catalog)
    grouped = group_catalog_courses(catalog_rows)
    course_rows = [
        build_course_row(key, rows, program_index)
        for key, rows in sorted(grouped.items(), key=lambda item: item[0])
    ]

    summary_rows = build_summary(course_rows)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    write_csv(output_dir / "department_courses_from_catalog.csv", COURSE_COLUMNS, course_rows)
    write_csv(output_dir / "department_courses_from_catalog_summary.csv", SUMMARY_COLUMNS, summary_rows)
    write_json(
        output_dir / "summary.json",
        {
            "source": str(args.course_catalog),
            "catalog_rows": len(catalog_rows),
            "department_course_rows": len(course_rows),
            "catalog_departments": len({row["catalog_department_name"] for row in course_rows}),
            "program_matched_rows": sum(1 for row in course_rows if row["program_match_status"] == "matched"),
            "program_unmatched_rows": sum(1 for row in course_rows if row["program_match_status"] != "matched"),
            "output_files": {
                "courses": str(output_dir / "department_courses_from_catalog.csv"),
                "summary": str(output_dir / "department_courses_from_catalog_summary.csv"),
            },
        },
    )
    print(output_dir)


def read_program_index(path: Path) -> dict[str, dict[str, str]]:
    index = {}
    with path.resolve().open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            name = row["program_name"]
            index[normalize_name(name)] = {
                "college": row["college_name"],
                "department_code": row["academic_program_code"],
                "department_name": name,
            }
    return index


def read_catalog(path: Path) -> list[dict[str, str]]:
    with path.resolve().open(encoding="utf-8-sig", newline="") as file:
        return [row for row in csv.DictReader(file) if row.get("course_code") and row.get("course_name")]


def group_catalog_courses(rows: list[dict[str, str]]) -> dict[tuple[str, str, str, str], list[dict[str, str]]]:
    grouped = defaultdict(list)
    for row in rows:
        department = row.get("offering_department") or row.get("display_department_name") or row.get("raw_department") or ""
        key = (
            normalize_name(department),
            row["course_code"],
            normalize_name(row["course_name"]),
            row.get("category", ""),
        )
        grouped[key].append(row)
    return grouped


def build_course_row(
    key: tuple[str, str, str, str],
    rows: list[dict[str, str]],
    program_index: dict[str, dict[str, str]],
) -> dict[str, str]:
    department_key, course_code, _course_name_key, category = key
    latest = max(rows, key=lambda row: term_sort_key(row.get("year", ""), row.get("semester", "")))
    department_name = latest.get("offering_department") or latest.get("display_department_name") or latest.get("raw_department") or ""
    program = program_index.get(department_key)
    program_match_status = "matched" if program else "unmatched"
    review_reasons = []
    if not program:
        review_reasons.append("catalog department did not match collection target program name")

    terms = sorted({term_label(row) for row in rows}, key=term_label_sort_key)
    regular_terms = [term for term in terms if term.endswith("_1") or term.endswith("_2")]
    seasonal_terms = [term for term in terms if term.endswith("_summer") or term.endswith("_winter")]

    return {
        "school": latest.get("school", ""),
        "college": program["college"] if program else latest.get("college", ""),
        "department_code": program["department_code"] if program else "",
        "department_name": program["department_name"] if program else "",
        "catalog_department_name": department_name,
        "course_code": course_code,
        "course_name": latest.get("course_name", ""),
        "category": category,
        "credits": most_common(row.get("credits", "") for row in rows),
        "target_grades": "|".join(sorted({row.get("target_grade", "") for row in rows if row.get("target_grade", "")})),
        "offered_terms": "|".join(terms),
        "regular_terms": "|".join(regular_terms),
        "seasonal_terms": "|".join(seasonal_terms),
        "sections_count": str(len(rows)),
        "professors": "|".join(sorted({row.get("professor", "") for row in rows if row.get("professor", "")})[:20]),
        "class_types": "|".join(sorted({row.get("class_type", "") for row in rows if row.get("class_type", "")})),
        "general_education_area": most_common(row.get("general_education_area", "") for row in rows),
        "latest_year": latest.get("year", ""),
        "latest_semester": latest.get("semester", ""),
        "latest_timetable_raw": latest.get("timetable_raw", ""),
        "latest_remark": latest.get("remark", ""),
        "program_match_status": program_match_status,
        "needs_review": "Y" if review_reasons else "N",
        "review_reason": " | ".join(review_reasons),
    }


def build_summary(course_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped = defaultdict(list)
    for row in course_rows:
        grouped[row["catalog_department_name"]].append(row)

    summary_rows = []
    for department_name, rows in sorted(grouped.items()):
        counts = Counter(row["category"] for row in rows)
        first = rows[0]
        other_count = sum(
            count
            for category, count in counts.items()
            if category not in {"전공필수", "전공선택", "전공기초", "교양필수", "교양선택", "일반선택", "교직과목"}
        )
        summary_rows.append(
            {
                "catalog_department_name": department_name,
                "college": first["college"],
                "department_code": first["department_code"],
                "department_name": first["department_name"],
                "program_match_status": first["program_match_status"],
                "course_count": len(rows),
                "전공필수": counts["전공필수"],
                "전공선택": counts["전공선택"],
                "전공기초": counts["전공기초"],
                "교양필수": counts["교양필수"],
                "교양선택": counts["교양선택"],
                "일반선택": counts["일반선택"],
                "교직과목": counts["교직과목"],
                "기타": other_count,
            }
        )
    return summary_rows


def normalize_name(value: str) -> str:
    value = value or ""
    value = value.replace("・", "·").replace(".", "·")
    value = re.sub(r"\s+", "", value)
    return value.lower()


def term_label(row: dict[str, str]) -> str:
    return f"{row.get('year', '')}_{row.get('semester', '')}"


def term_sort_key(year: str, semester: str) -> tuple[int, int]:
    semester_order = {"1": 1, "summer": 2, "2": 3, "winter": 4}
    return (int(year or 0), semester_order.get(semester, 0))


def term_label_sort_key(term: str) -> tuple[int, int]:
    year, _, semester = term.partition("_")
    return term_sort_key(year, semester)


def most_common(values: Any) -> str:
    cleaned = [value for value in values if value]
    if not cleaned:
        return ""
    return Counter(cleaned).most_common(1)[0][0]


def write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
