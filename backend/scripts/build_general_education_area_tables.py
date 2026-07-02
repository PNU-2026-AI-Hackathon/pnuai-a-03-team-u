from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


AREA_MASTER_ROWS = [
    {
        "area_key": "area_1",
        "area_no": "1",
        "area_name": "사상과 역사",
        "area_group": "general_education_area",
        "aliases": "사상과역사|Philosophy and History",
        "representative_course_code": "ZFz000091",
    },
    {
        "area_key": "area_2",
        "area_no": "2",
        "area_name": "사회와 문화",
        "area_group": "general_education_area",
        "aliases": "사회와문화|Society and Culture",
        "representative_course_code": "ZFz000092",
    },
    {
        "area_key": "area_3",
        "area_no": "3",
        "area_name": "문학과 예술",
        "area_group": "general_education_area",
        "aliases": "문학과예술|Literature and Arts",
        "representative_course_code": "ZFz000093",
    },
    {
        "area_key": "area_4",
        "area_no": "4",
        "area_name": "과학과 기술",
        "area_group": "general_education_area",
        "aliases": "과학과기술|Science and Technology",
        "representative_course_code": "ZFz000094",
    },
    {
        "area_key": "area_5",
        "area_no": "5",
        "area_name": "건강과 레포츠",
        "area_group": "general_education_area",
        "aliases": "건강과레포츠|Health and Recreation/Sports",
        "representative_course_code": "ZFz000095",
    },
    {
        "area_key": "area_6",
        "area_no": "6",
        "area_name": "외국어",
        "area_group": "general_education_area",
        "aliases": "외국어|세계와 소통|세계와소통|Global Communication",
        "representative_course_code": "ZFz000096",
    },
    {
        "area_key": "area_7",
        "area_no": "7",
        "area_name": "생명의료윤리",
        "area_group": "general_education_area",
        "aliases": "생명의료윤리",
        "representative_course_code": "",
    },
    {
        "area_key": "hyowon_creative_convergence",
        "area_no": "",
        "area_name": "융합과 창의",
        "area_group": "hyowon_creative",
        "aliases": "융합과창의|Convergence and Creativity",
        "representative_course_code": "ZFz000097",
    },
    {
        "area_key": "hyowon_creative_character",
        "area_no": "",
        "area_name": "인성과 사회봉사",
        "area_group": "hyowon_creative",
        "aliases": "인성과사회봉사|Character and Community Service",
        "representative_course_code": "ZFz000110",
    },
]

AREA_COLUMNS = [
    "area_key",
    "area_no",
    "area_name",
    "area_group",
    "aliases",
    "representative_course_code",
]
RULE_COLUMNS = [
    "rule_id",
    "college",
    "department_code",
    "department_name",
    "document_title",
    "curriculum_year",
    "admission_type",
    "category",
    "rule_type",
    "required_distinct_area_count",
    "min_courses_per_area",
    "required_credits",
    "raw_text",
    "source_file",
    "needs_review",
    "review_reason",
]
RULE_AREA_COLUMNS = [
    "rule_id",
    "area_key",
    "area_no",
    "area_name",
    "required",
    "source_text",
]
COURSE_AREA_COLUMNS = [
    "course_code",
    "course_name",
    "area_key",
    "area_no",
    "area_name",
    "area_group",
    "source",
    "confidence",
    "needs_review",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build general education area rule tables.")
    parser.add_argument(
        "--department-curriculum-courses",
        type=Path,
        default=Path("../raw_data/parsed_experiments/department_curriculum_courses/department_curriculum_courses.csv"),
    )
    parser.add_argument(
        "--normalized-root",
        type=Path,
        default=Path("../raw_data/manual_staging/01_graduation_requirements/by_department"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../raw_data/parsed_experiments/general_education_area_tables"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    curriculum_rows = read_csv(args.department_curriculum_courses)
    normalized_documents = read_normalized_documents(args.normalized_root)
    rule_rows, rule_area_rows = build_department_area_rules(curriculum_rows, normalized_documents)
    course_area_rows = build_course_area_map(curriculum_rows)

    write_csv(output_dir / "general_education_areas.csv", AREA_COLUMNS, AREA_MASTER_ROWS)
    write_csv(output_dir / "department_general_education_area_rules.csv", RULE_COLUMNS, rule_rows)
    write_csv(output_dir / "department_general_education_area_rule_areas.csv", RULE_AREA_COLUMNS, rule_area_rows)
    write_csv(output_dir / "course_general_education_area_map.csv", COURSE_AREA_COLUMNS, course_area_rows)
    write_json(
        output_dir / "summary.json",
        {
            "area_count": len(AREA_MASTER_ROWS),
            "department_area_rules": len(rule_rows),
            "rule_area_links": len(rule_area_rows),
            "course_area_mappings": len(course_area_rows),
            "output_files": {
                "areas": str(output_dir / "general_education_areas.csv"),
                "rules": str(output_dir / "department_general_education_area_rules.csv"),
                "rule_areas": str(output_dir / "department_general_education_area_rule_areas.csv"),
                "course_area_map": str(output_dir / "course_general_education_area_map.csv"),
            },
        },
    )
    print(output_dir)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.resolve().open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def read_normalized_documents(root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    documents = {}
    for path in root.resolve().glob("*/*/01_normalized/graduation_requirements.normalized.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for document in data.get("documents", []):
            documents[(data.get("department_code", ""), document.get("document_title", ""))] = document
    return documents


def build_department_area_rules(
    curriculum_rows: list[dict[str, str]],
    normalized_documents: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    grouped = defaultdict(list)
    for row in curriculum_rows:
        area = infer_area(row["raw_course_name"])
        if not area:
            continue
        key = (
            row["college"],
            row["department_code"],
            row["department_name"],
            row["document_title"],
            row["curriculum_year"],
            row["admission_type"],
            clean_category(row["category"]),
        )
        grouped[key].append((row, area))

    rule_rows = []
    rule_area_rows = []
    for index, (key, values) in enumerate(sorted(grouped.items()), start=1):
        college, department_code, department_name, document_title, curriculum_year, admission_type, category = key
        rule_id = f"gerule_{index:05d}"
        source_text = source_text_for_rule(department_code, document_title, category, normalized_documents)
        area_keys = sorted({area["area_key"] for _row, area in values})
        fallback_text = fallback_source_text(values, area_keys)
        rule_text = source_text or fallback_text
        distinct_count = infer_required_distinct_area_count(rule_text, category, len(area_keys))
        min_courses = infer_min_courses_per_area(rule_text, category, len(area_keys))
        required_credits = infer_required_credits(values)
        review_reasons = ["area options were extracted from curriculum source"]
        if not source_text:
            review_reasons.append("rule text was reconstructed from area rows")
        if distinct_count and not source_text:
            review_reasons.append("minimum area count is inferred")
        rule_rows.append(
            {
                "rule_id": rule_id,
                "college": college,
                "department_code": department_code,
                "department_name": department_name,
                "document_title": document_title,
                "curriculum_year": curriculum_year,
                "admission_type": admission_type,
                "category": category,
                "rule_type": "area_distribution",
                "required_distinct_area_count": distinct_count,
                "min_courses_per_area": min_courses,
                "required_credits": required_credits,
                "raw_text": compact_text(rule_text),
                "source_file": "|".join(sorted({row["source_file"] for row, _area in values})),
                "needs_review": "Y",
                "review_reason": "; ".join(review_reasons) + "; exact graduation rule should be reviewed",
            }
        )
        for area_key in area_keys:
            area = area_by_key(area_key)
            source_values = sorted({row["raw_course_name"] for row, item_area in values if item_area["area_key"] == area_key})
            rule_area_rows.append(
                {
                    "rule_id": rule_id,
                    "area_key": area["area_key"],
                    "area_no": area["area_no"],
                    "area_name": area["area_name"],
                    "required": infer_required_area_flag(area, category, rule_text),
                    "source_text": "|".join(source_values),
                }
            )
    return rule_rows, rule_area_rows


def build_course_area_map(curriculum_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    mappings = {}
    for row in curriculum_rows:
        area = infer_area(row["raw_course_name"]) or infer_area(row["category"])
        course_code = row["source_course_code"] or row["matched_course_code"]
        if not area or not course_code:
            continue
        key = (course_code, area["area_key"])
        mappings[key] = {
            "course_code": course_code,
            "course_name": normalized_course_area_name(row["raw_course_name"], area),
            "area_key": area["area_key"],
            "area_no": area["area_no"],
            "area_name": area["area_name"],
            "area_group": area["area_group"],
            "source": row["source_kind"],
            "confidence": "0.90" if row["source_course_code"] else "0.70",
            "needs_review": "Y" if not row["source_course_code"] else "N",
        }
    for area in AREA_MASTER_ROWS:
        if area["representative_course_code"]:
            key = (area["representative_course_code"], area["area_key"])
            mappings.setdefault(
                key,
                {
                    "course_code": area["representative_course_code"],
                    "course_name": area["area_name"],
                    "area_key": area["area_key"],
                    "area_no": area["area_no"],
                    "area_name": area["area_name"],
                    "area_group": area["area_group"],
                    "source": "area_master",
                    "confidence": "0.80",
                    "needs_review": "Y",
                },
            )
    return [mappings[key] for key in sorted(mappings)]


def source_text_for_rule(
    department_code: str,
    document_title: str,
    category: str,
    normalized_documents: dict[tuple[str, str], dict[str, Any]],
) -> str:
    document = normalized_documents.get((department_code, document_title), {})
    note_texts = [note.get("text", "") for note in document.get("notes", [])]
    if category.startswith("교양 선택"):
        return "\n".join(text for text in note_texts if "교양선택" in text or "영역" in text)
    return "\n".join(text for text in note_texts if "영역" in text)


def fallback_source_text(values: list[tuple[dict[str, str], dict[str, str]]], area_keys: list[str]) -> str:
    area_parts = []
    for area_key in area_keys:
        area = area_by_key(area_key)
        label = f"{area['area_no']}영역: {area['area_name']}" if area["area_no"] else area["area_name"]
        area_parts.append(label)

    course_parts = []
    for row, _area in values:
        raw_name = compact_text(row.get("raw_course_name", ""))
        if raw_name and raw_name not in course_parts:
            course_parts.append(raw_name)

    text_parts = []
    if area_parts:
        text_parts.append("허용 영역: " + ", ".join(area_parts))
    if course_parts:
        text_parts.append("원문 항목: " + " | ".join(course_parts))
    return " / ".join(text_parts)


def infer_required_distinct_area_count(source_text: str, category: str, area_count: int) -> str:
    text = compact_text(source_text)
    match = re.search(r"(\d+)개\s*영역\s*중\s*(\d+)개\s*영역", text)
    if match:
        return match.group(2)
    match = re.search(r"([1-7])\s*개\s*영역.*?([1-7])\s*개\s*영역", text)
    if match:
        return match.group(2)
    if "교양 선택" in category or "교양선택" in category:
        return "5" if area_count >= 5 else ""
    return ""


def infer_min_courses_per_area(source_text: str, category: str, area_count: int) -> str:
    text = compact_text(source_text)
    if re.search(r"1과목\s*이상", text):
        return "1"
    if ("교양 선택" in category or "교양선택" in category) and area_count >= 5:
        return "1"
    return ""


def infer_required_area_flag(area: dict[str, str], category: str, source_text: str) -> str:
    if area["area_key"] == "area_7" and ("반드시" in source_text or "기초 교양" in category):
        return "Y"
    return ""


def infer_required_credits(values: list[tuple[dict[str, str], dict[str, str]]]) -> str:
    totals = []
    for row, _area in values:
        credit = row.get("raw_credit", "")
        if credit and "-" in credit:
            totals.append(credit.split("-", 1)[0])
        elif credit:
            totals.append(credit)
    return ""


def infer_area(value: str) -> dict[str, str] | None:
    text = compact_text(value)
    number_match = re.search(r"([1-7])\s*영역", text)
    if number_match:
        return area_by_no(number_match.group(1))

    normalized = normalize_text(text)
    for area in AREA_MASTER_ROWS:
        names = [area["area_name"], *area["aliases"].split("|")]
        if any(normalize_text(name) and normalize_text(name) in normalized for name in names):
            return area
    return None


def area_by_no(area_no: str) -> dict[str, str]:
    for area in AREA_MASTER_ROWS:
        if area["area_no"] == area_no:
            return area
    raise KeyError(area_no)


def area_by_key(area_key: str) -> dict[str, str]:
    for area in AREA_MASTER_ROWS:
        if area["area_key"] == area_key:
            return area
    raise KeyError(area_key)


def clean_category(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\d+\)", "", value)).strip()


def normalized_course_area_name(raw_name: str, area: dict[str, str]) -> str:
    if raw_name.startswith("ZF") or raw_name.startswith("ZE"):
        return area["area_name"]
    return compact_text(raw_name)


def normalize_text(value: str) -> str:
    return re.sub(r"[\s:()（）·ㆍ・]", "", value).lower()


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
