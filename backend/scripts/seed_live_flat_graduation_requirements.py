"""Seed the current live flat graduation_requirements table from Annex 2.

This script targets the live Supabase schema at revision e5f6a7b8c9d0, where
graduation_requirements is still the flat table:

    department_id, major_id, program_type, curriculum_year,
    required_total_credits, required_major_required, required_major_elective,
    required_general_required, required_general_elective, required_free_elective

The newer requirement_sets/categories schema is intentionally not used here.

Source CSV:
    backend/seeds/graduation_credit_requirements_annex2_2026.csv

Mapping from the regulation table to the live flat columns:
    required_general_required = 효원핵심교양
    required_general_elective = 효원균형교양 + 효원창의교양
    required_major_required = 전공필수
    required_major_elective = 전공선택 + 심화전공
    required_free_elective = 일반선택
    required_total_credits = 총계

Rows from 별표2-2("융합전공") are excluded by default because the user asked for
PDF pages 31-36, which are 별표2 rows.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import unicodedata
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from app.core.config import settings


CSV_PATH = Path(__file__).resolve().parent.parent / "seeds" / "graduation_credit_requirements_annex2_2026.csv"
CURRICULUM_YEAR = "2026"
PROGRAM_TYPE = "primary"

ANNEX2_2_LIVE_COLLEGE_BY_PROGRAM = {
    "지능형헬스사이언스융합전공": "자연과학대학",
    "핀테크융합전공": "경영대학",
}


def _norm(value: str | None) -> str:
    text_value = unicodedata.normalize("NFC", value or "")
    text_value = re.sub(r"\(통합6년제\)", "", text_value)
    text_value = text_value.replace("・", "·").replace("ㆍ", "·").replace(".", "·")
    return " ".join(text_value.split())


def _key(value: str | None) -> str:
    return _norm(value).replace(" ", "").replace("·", "")


def _to_int(value: str | None) -> int | None:
    stripped = (value or "").strip()
    return int(stripped) if stripped.isdigit() else None


def _credits(row: dict[str, str], *columns: str) -> int | None:
    values = [_to_int(row.get(column)) for column in columns]
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present)


def _load_csv(include_annex2_2: bool, only_annex2_2: bool) -> list[dict[str, str]]:
    with CSV_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if only_annex2_2:
        return [row for row in rows if row["college"] == "융합전공"]
    if include_annex2_2:
        return rows
    return [row for row in rows if row["college"] != "융합전공"]


def _load_hierarchy_lookup(conn) -> dict[tuple[str, str], tuple[int, int | None, str]]:
    lookup: dict[tuple[str, str], tuple[int, int | None, str]] = {}
    department_rows = conn.execute(
        text(
            """
            select d.id as department_id, c.name as college_name, d.name as department_name
            from departments d
            join colleges c on c.id = d.college_id
            """
        )
    ).mappings()
    for row in department_rows:
        lookup[(_key(row["college_name"]), _key(row["department_name"]))] = (
            row["department_id"],
            None,
            f'{row["college_name"]} {row["department_name"]}',
        )

    major_rows = conn.execute(
        text(
            """
            select
              d.id as department_id,
              m.id as major_id,
              c.name as college_name,
              d.name as department_name,
              m.name as major_name
            from majors m
            join departments d on d.id = m.department_id
            join colleges c on c.id = d.college_id
            """
        )
    ).mappings()
    for row in major_rows:
        value = (
            row["department_id"],
            row["major_id"],
            f'{row["college_name"]} {row["department_name"]} {row["major_name"]}',
        )
        lookup[(_key(row["college_name"]), _key(row["major_name"]))] = value
        lookup[(_key(row["college_name"]), _key(f'{row["department_name"]} {row["major_name"]}'))] = value
    return lookup


def _resolve_row(
    row: dict[str, str], lookup: dict[tuple[str, str], tuple[int, int | None, str]]
) -> tuple[int, int | None, str] | None:
    name = row["program_name"]
    parent = row.get("parent_name") or ""
    college_name = ANNEX2_2_LIVE_COLLEGE_BY_PROGRAM.get(name, row["college"])
    college_key = _key(college_name)
    candidates = []
    if parent:
        candidates.append(f"{parent} {name}")
    candidates.append(name)
    for candidate in candidates:
        resolved = lookup.get((college_key, _key(candidate)))
        if resolved:
            return resolved
    return None


def _build_insert_values(row: dict[str, str], department_id: int, major_id: int | None) -> dict[str, Any]:
    return {
        "program_type": PROGRAM_TYPE,
        "curriculum_year": CURRICULUM_YEAR,
        "required_total_credits": _to_int(row.get("total")),
        "required_major_required": _to_int(row.get("major_required")),
        "required_major_elective": _credits(row, "major_elective", "deep_total"),
        "required_general_required": _to_int(row.get("hy_core")),
        "required_general_elective": _credits(row, "hy_balanced", "hy_creative"),
        "required_free_elective": _to_int(row.get("free_elective")),
        "department_id": department_id,
        "major_id": major_id,
        "created_at": dt.datetime.now(dt.UTC).replace(tzinfo=None),
        "updated_at": dt.datetime.now(dt.UTC).replace(tzinfo=None),
    }


def seed_live_flat_graduation_requirements(
    *,
    dry_run: bool = True,
    replace: bool = False,
    include_annex2_2: bool = False,
    only_annex2_2: bool = False,
) -> dict[str, Any]:
    rows = _load_csv(include_annex2_2, only_annex2_2)
    engine = create_engine(settings.DATABASE_URL)
    unmatched: list[str] = []
    values: list[dict[str, Any]] = []

    with engine.begin() as conn:
        lookup = _load_hierarchy_lookup(conn)
        for row in rows:
            resolved = _resolve_row(row, lookup)
            display = f"{row['college']} {row.get('parent_name') or ''} {row['program_name']}".strip()
            if not resolved:
                unmatched.append(display)
                continue
            department_id, major_id, _matched_name = resolved
            values.append(_build_insert_values(row, department_id, major_id))

        if not dry_run:
            if replace:
                conn.execute(
                    text(
                        """
                        delete from graduation_requirements
                        where program_type = :program_type
                          and curriculum_year = :curriculum_year
                        """
                    ),
                    {"program_type": PROGRAM_TYPE, "curriculum_year": CURRICULUM_YEAR},
                )
            elif values:
                conn.execute(
                    text(
                        """
                        delete from graduation_requirements
                        where program_type = :program_type
                          and curriculum_year = :curriculum_year
                          and department_id = :department_id
                          and (
                            (major_id is null and :major_id is null)
                            or major_id = :major_id
                          )
                        """
                    ),
                    [
                        {
                            "program_type": value["program_type"],
                            "curriculum_year": value["curriculum_year"],
                            "department_id": value["department_id"],
                            "major_id": value["major_id"],
                        }
                        for value in values
                    ],
                )
            conn.execute(
                text(
                    """
                    insert into graduation_requirements (
                      program_type,
                      curriculum_year,
                      required_total_credits,
                      required_major_required,
                      required_major_elective,
                      required_general_required,
                      required_general_elective,
                      required_free_elective,
                      created_at,
                      updated_at,
                      department_id,
                      major_id
                    )
                    values (
                      :program_type,
                      :curriculum_year,
                      :required_total_credits,
                      :required_major_required,
                      :required_major_elective,
                      :required_general_required,
                      :required_general_elective,
                      :required_free_elective,
                      :created_at,
                      :updated_at,
                      :department_id,
                      :major_id
                    )
                    """
                ),
                values,
            )

    return {
        "csv_rows": len(rows),
        "matched_rows": len(values),
        "unmatched_rows": len(unmatched),
        "unmatched": unmatched,
        "dry_run": dry_run,
        "replace": replace,
        "include_annex2_2": include_annex2_2,
        "only_annex2_2": only_annex2_2,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually insert rows into the live flat table.")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing primary/2026 graduation_requirements before inserting.",
    )
    parser.add_argument(
        "--include-annex2-2",
        action="store_true",
        help="Also include the three 별표2-2 융합전공 rows in the CSV.",
    )
    parser.add_argument(
        "--only-annex2-2",
        action="store_true",
        help="Only process the 별표2-2 융합전공 rows.",
    )
    args = parser.parse_args()
    result = seed_live_flat_graduation_requirements(
        dry_run=not args.apply,
        replace=args.replace,
        include_annex2_2=args.include_annex2_2,
        only_annex2_2=args.only_annex2_2,
    )
    print(result)


if __name__ == "__main__":
    main()
