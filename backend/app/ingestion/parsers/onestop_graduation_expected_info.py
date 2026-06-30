"""Normalize PNU One-Stop graduation expected information tables.

Input is the raw JSON extracted by
`app.ingestion.crawlers.graduation_expected_info`. Output is a user-scoped
candidate structure ready to map into graduation audit tables.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


TABLE_NAMES = {
    0: "major_application_info",
    1: "subject_category_completion",
    2: "required_course_completion",
    3: "general_education_area_completion",
    4: "general_required_course_completion",
    5: "major_course_completion",
    6: "graduation_requirement_completion",
}

CATEGORY_STATUS_TABLE = "subject_category_completion"
REQUIREMENT_ITEM_TABLES = {
    "required_course_completion",
    "general_education_area_completion",
    "general_required_course_completion",
    "major_course_completion",
    "graduation_requirement_completion",
}


def _slug(value: str) -> str:
    value = value.strip().replace(" ", "_")
    value = re.sub(r"[^0-9A-Za-z가-힣_()]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "blank"


def _expand_table_grid(table: dict[str, Any]) -> list[list[str]]:
    grid: list[list[str]] = []
    occupied: dict[tuple[int, int], str] = {}
    for row in table.get("rows", []):
        row_index = int(row.get("rowIndex", len(grid)))
        grid_row: list[str] = []
        col_index = 0
        for cell in row.get("cells", []):
            while (row_index, col_index) in occupied:
                grid_row.append(occupied[(row_index, col_index)])
                col_index += 1

            value = str(cell.get("text") or "")
            row_span = int(cell.get("rowSpan") or 1)
            col_span = int(cell.get("colSpan") or 1)
            for delta_col in range(col_span):
                grid_row.append(value)
                if row_span > 1:
                    for delta_row in range(1, row_span):
                        occupied[(row_index + delta_row, col_index + delta_col)] = value
            col_index += col_span

        while (row_index, col_index) in occupied:
            grid_row.append(occupied[(row_index, col_index)])
            col_index += 1

        grid.append(grid_row)

    width = max((len(row) for row in grid), default=0)
    return [row + [""] * (width - len(row)) for row in grid]


def _header_names(parent_row: list[str], child_row: list[str]) -> list[str]:
    names: list[str] = []
    seen: dict[str, int] = {}
    for parent, child in zip(parent_row, child_row):
        if parent and parent != child and parent != "No":
            name = f"{parent}_{child}" if child else parent
        else:
            name = child or parent or "blank"
        name = _slug(name)
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = f"{name}_{seen[name]}"
        names.append(name)
    return names


def _records_from_grid(table_index: int, grid: list[list[str]]) -> list[dict[str, str]]:
    if not grid:
        return []
    if table_index == 0:
        headers = [_slug(value) for value in grid[0]]
        data_rows = grid[1:]
    else:
        if len(grid) < 3:
            return []
        headers = _header_names(grid[0], grid[1])
        data_rows = grid[2:]

    records: list[dict[str, str]] = []
    for row in data_rows:
        if not any(cell.strip() for cell in row):
            continue
        non_empty_values = {cell.strip() for cell in row if cell.strip()}
        if non_empty_values == {"조회내역이 없습니다."}:
            records.append({"no_records": "Y", "message": "조회내역이 없습니다."})
            continue
        records.append(
            {headers[index]: row[index] if index < len(row) else "" for index in range(len(headers))}
        )
    return records


def _to_float(value: str) -> float | None:
    value = str(value).strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def normalize_graduation_expected_info(payload: dict[str, Any]) -> dict[str, Any]:
    tables: list[dict[str, Any]] = []
    category_statuses: list[dict[str, Any]] = []
    requirement_items: list[dict[str, Any]] = []

    for table in payload.get("tables", []):
        table_index = int(table.get("tableIndex", len(tables)))
        table_name = TABLE_NAMES.get(table_index, f"table_{table_index:02d}")
        grid = _expand_table_grid(table)
        records = _records_from_grid(table_index, grid)

        tables.append(
            {
                "table_index": table_index,
                "table_name": table_name,
                "caption": table.get("caption", ""),
                "visible_at_extract": table.get("visible", False),
                "row_count": table.get("rowCount", len(grid)),
                "grid": grid,
                "records": records,
            }
        )

        if table_name == CATEGORY_STATUS_TABLE:
            for record in records:
                if record.get("no_records") == "Y":
                    continue
                category_statuses.append(
                    {
                        "program_type": record.get("졸업기준_학적신청구분", ""),
                        "category": record.get("졸업기준_사정구분", ""),
                        "required_credits": _to_float(record.get("졸업기준_기준학점", "")),
                        "earned_credits": _to_float(record.get("학생이수정보_취득학점", "")),
                        "registered_credits": _to_float(record.get("학생이수정보_수강신청학점", "")),
                        "expected_credits": _to_float(record.get("학생이수정보_취득예정학점", "")),
                        "completed_status": record.get("학생이수정보_이수여부", ""),
                        "failure_reason": record.get("학생이수정보_졸업불가사유", ""),
                        "source_table_name": table_name,
                        "raw_record": record,
                    }
                )

        if table_name in REQUIREMENT_ITEM_TABLES:
            for record in records:
                if record.get("no_records") == "Y":
                    requirement_items.append(
                        {
                            "requirement_area": table_name,
                            "completed_status": "no_records",
                            "note": record.get("message", ""),
                            "source_table_name": table_name,
                            "raw_record": record,
                        }
                    )
                    continue
                requirement_items.append(
                    {
                        "requirement_area": table_name,
                        "required_category": record.get("졸업기준(교육과정정보)_교과목구분")
                        or record.get("졸업기준(이수모형정보)_교양영역명")
                        or record.get("졸업기준_졸업요건명")
                        or "",
                        "required_course_name": record.get("졸업기준(교육과정정보)_교과목명")
                        or record.get("졸업기준(이수모형정보)_교과목명")
                        or record.get("졸업기준_상세졸업요건명")
                        or "",
                        "required_credits": _to_float(
                            record.get("졸업기준(교육과정정보)_학점", "")
                            or record.get("졸업기준(이수모형정보)_학점", "")
                        ),
                        "completed_course_name": record.get("학생이수정보_교과목명", ""),
                        "completed_grade": record.get("학생이수정보_등급", ""),
                        "completed_credits": _to_float(record.get("학생이수정보_학점", "")),
                        "completed_status": record.get("학생이수정보_이수여부", ""),
                        "note": record.get("학생이수정보_비고", "")
                        or record.get("학생이수정보_비고_예외사항_상세내역_점수", "")
                        or "",
                        "source_table_name": table_name,
                        "raw_record": record,
                    }
                )

    return {
        "source_system": payload.get("sourceSystem", "pnu_onestop"),
        "source_menu_code": payload.get("sourceMenuCode", "000000000000089"),
        "source_url": payload.get("sourceUrl", ""),
        "page_title": payload.get("pageTitle", ""),
        "extracted_at": payload.get("extractedAt", ""),
        "normalized_at": datetime.now(UTC).isoformat(),
        "tables": tables,
        "category_statuses": category_statuses,
        "requirement_items": requirement_items,
        "privacy_note": "user-scoped personal academic data",
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key == "raw_record":
                continue
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_normalized_outputs(output_dir: Path, normalized: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "graduation_expected_info_normalized.json").write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_csv(output_dir / "category_statuses.csv", normalized["category_statuses"])
    _write_csv(output_dir / "requirement_items.csv", normalized["requirement_items"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize PNU One-Stop graduation expected information raw JSON"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    normalized = normalize_graduation_expected_info(payload)
    write_normalized_outputs(args.output_dir, normalized)
    print(
        json.dumps(
            {
                "source_menu_code": normalized["source_menu_code"],
                "table_count": len(normalized["tables"]),
                "category_status_count": len(normalized["category_statuses"]),
                "requirement_item_count": len(normalized["requirement_items"]),
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
