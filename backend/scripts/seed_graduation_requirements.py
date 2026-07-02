"""Seed parsed graduation requirement candidates into the DB.

This script expects migrations to be applied and academic_programs to be seeded.
It is idempotent: requirement_sets are upserted by
(academic_program_code, program_type, curriculum_year), and detail tables are
upserted by stable external_id generated from raw parsing outputs.

실행:
    python -m scripts.seed_graduation_requirements
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.db import SessionLocal
from app.domains.academics.models import (
    RequirementCategory,
    RequirementCourse,
    RequirementSet,
    RequirementTextRule,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = REPO_ROOT / "raw_data/parsed_experiments/graduation_requirement_seed_tables"

REQSETS_PATH = SEED_DIR / "requirement_sets_seed_candidates.csv"
CATEGORIES_PATH = SEED_DIR / "requirement_category_seed_candidates.csv"
COURSES_PATH = SEED_DIR / "requirement_course_seed_candidates.csv"
TEXT_RULES_PATH = SEED_DIR / "requirement_text_rule_seed_candidates.csv"


REQSET_COLUMNS = [
    "school",
    "department",
    "academic_program_code",
    "major",
    "program_type",
    "curriculum_year",
    "name",
    "required_total_credits",
    "rule_metadata",
    "is_active",
]

CATEGORY_COLUMNS = [
    "external_id",
    "requirement_set_id",
    "academic_program_code",
    "program_name",
    "program_type",
    "category_code",
    "category_name",
    "minimum_credits",
    "rule_type",
    "source_kind",
    "source_file",
    "needs_review",
    "review_reason",
    "notes",
]

COURSE_COLUMNS = [
    "external_id",
    "requirement_set_id",
    "academic_program_code",
    "college_name",
    "program_name",
    "program_type",
    "curriculum_year",
    "category_code",
    "recommended_year",
    "recommended_semester",
    "raw_course_code",
    "raw_course_name",
    "raw_credit",
    "matched_course_code",
    "matched_course_name",
    "match_status",
    "match_method",
    "matched_terms",
    "matched_departments",
    "choice_rule_types",
    "choice_rule_raw",
    "source_table",
    "source_file",
    "needs_review",
    "review_reason",
]

TEXT_RULE_COLUMNS = [
    "external_id",
    "requirement_set_id",
    "academic_program_code",
    "program_name",
    "program_type",
    "category_code",
    "rule_text",
    "rule_field",
    "rule_value",
    "source_kind",
    "source_file",
    "source_title",
    "needs_review",
    "review_reason",
]


def seed_graduation_requirements() -> dict[str, int]:
    reqset_rows = _read_csv(REQSETS_PATH)
    category_rows = _read_csv(CATEGORIES_PATH)
    course_rows = _read_csv(COURSES_PATH)
    text_rule_rows = _read_csv(TEXT_RULES_PATH)

    db = SessionLocal()
    try:
        reqset_external_to_db_id = _upsert_requirement_sets(db, reqset_rows)
        category_count = _upsert_categories(db, category_rows, reqset_external_to_db_id)
        course_count = _upsert_courses(db, course_rows, reqset_external_to_db_id)
        text_rule_count = _upsert_text_rules(db, text_rule_rows, reqset_external_to_db_id)
        db.commit()
    finally:
        db.close()

    return {
        "requirement_sets": len(reqset_rows),
        "requirement_categories": category_count,
        "requirement_courses": course_count,
        "requirement_text_rules": text_rule_count,
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _upsert_requirement_sets(db, rows: list[dict[str, str]]) -> dict[str, int]:
    values = [_requirement_set_value(row) for row in rows]
    if values:
        stmt = insert(RequirementSet).values(values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_requirement_sets_program_type_year",
            set_={
                column: getattr(stmt.excluded, column)
                for column in REQSET_COLUMNS
                if column not in {"academic_program_code", "program_type", "curriculum_year"}
            },
        )
        db.execute(stmt)
        db.flush()

    db_rows = db.execute(
        select(
            RequirementSet.id,
            RequirementSet.academic_program_code,
            RequirementSet.program_type,
            RequirementSet.curriculum_year,
        )
    ).all()
    by_key = {
        (row.academic_program_code, row.program_type, row.curriculum_year): row.id
        for row in db_rows
    }
    external_to_db_id: dict[str, int] = {}
    for row in rows:
        key = (row["academic_program_code"], row["program_type"], row["curriculum_year"])
        db_id = by_key.get(key)
        if db_id:
            external_to_db_id[row["requirement_set_id"]] = db_id
    return external_to_db_id


def _requirement_set_value(row: dict[str, str]) -> dict[str, Any]:
    return {
        "school": "부산대학교",
        "department": _blank_to_none(row.get("program_name")),
        "academic_program_code": _blank_to_none(row.get("academic_program_code")),
        "major": _blank_to_none(row.get("program_name")),
        "program_type": _blank_to_none(row.get("program_type")),
        "curriculum_year": _blank_to_none(row.get("curriculum_year")),
        "name": _blank_to_none(row.get("name")),
        "required_total_credits": _to_int(row.get("required_total_credits")),
        "rule_metadata": {
            "seed_source": "graduation_requirement_seed_tables",
            "source_priority": row.get("source_priority"),
            "coverage_status": row.get("coverage_status"),
            "source_file": row.get("source_file"),
            "notes": row.get("notes"),
            "display_name": row.get("display_name"),
            "college_name": row.get("college_name"),
        },
        "is_active": True,
    }


def _upsert_categories(
    db,
    rows: list[dict[str, str]],
    reqset_external_to_db_id: dict[str, int],
) -> int:
    values = []
    for row in rows:
        db_reqset_id = reqset_external_to_db_id.get(row.get("requirement_set_id", ""))
        if not db_reqset_id:
            continue
        values.append(
            {
                "external_id": row["category_requirement_id"],
                "requirement_set_id": db_reqset_id,
                "academic_program_code": _blank_to_none(row.get("academic_program_code")),
                "program_name": _blank_to_none(row.get("program_name")),
                "program_type": _blank_to_none(row.get("program_type")),
                "category_code": row["category_code"],
                "category_name": _blank_to_none(row.get("category_name")),
                "minimum_credits": _blank_to_none(row.get("minimum_credits")),
                "rule_type": _blank_to_none(row.get("rule_type")),
                "source_kind": _blank_to_none(row.get("source_kind")),
                "source_file": _blank_to_none(row.get("source_file")),
                "needs_review": _to_bool(row.get("needs_review")),
                "review_reason": _blank_to_none(row.get("review_reason")),
                "notes": _blank_to_none(row.get("notes")),
            }
        )
    _bulk_upsert(db, RequirementCategory, values, CATEGORY_COLUMNS, "uq_requirement_categories_external_id")
    return len(values)


def _upsert_courses(
    db,
    rows: list[dict[str, str]],
    reqset_external_to_db_id: dict[str, int],
) -> int:
    values = []
    for row in rows:
        db_reqset_id = reqset_external_to_db_id.get(row.get("requirement_set_id", ""))
        if not db_reqset_id:
            continue
        values.append(
            {
                "external_id": row["requirement_course_id"],
                "requirement_set_id": db_reqset_id,
                "academic_program_code": _blank_to_none(row.get("academic_program_code")),
                "college_name": _blank_to_none(row.get("college_name")),
                "program_name": _blank_to_none(row.get("program_name")),
                "program_type": _blank_to_none(row.get("program_type")),
                "curriculum_year": _blank_to_none(row.get("curriculum_year")),
                "category_code": _blank_to_none(row.get("category_code")),
                "recommended_year": _blank_to_none(row.get("recommended_year")),
                "recommended_semester": _blank_to_none(row.get("recommended_semester")),
                "raw_course_code": _blank_to_none(row.get("raw_course_code")),
                "raw_course_name": _blank_to_none(row.get("raw_course_name")),
                "raw_credit": _blank_to_none(row.get("raw_credit")),
                "matched_course_code": _blank_to_none(row.get("matched_course_code")),
                "matched_course_name": _blank_to_none(row.get("matched_course_name")),
                "match_status": _blank_to_none(row.get("match_status")),
                "match_method": _blank_to_none(row.get("match_method")),
                "matched_terms": _blank_to_none(row.get("matched_terms")),
                "matched_departments": _blank_to_none(row.get("matched_departments")),
                "choice_rule_types": _blank_to_none(row.get("choice_rule_types")),
                "choice_rule_raw": _blank_to_none(row.get("choice_rule_raw")),
                "source_table": _blank_to_none(row.get("source_table")),
                "source_file": _blank_to_none(row.get("source_file")),
                "needs_review": _to_bool(row.get("needs_review")),
                "review_reason": _blank_to_none(row.get("review_reason")),
            }
        )
    _bulk_upsert(db, RequirementCourse, values, COURSE_COLUMNS, "uq_requirement_courses_external_id")
    return len(values)


def _upsert_text_rules(
    db,
    rows: list[dict[str, str]],
    reqset_external_to_db_id: dict[str, int],
) -> int:
    values = []
    for row in rows:
        db_reqset_id = reqset_external_to_db_id.get(row.get("requirement_set_id", ""))
        values.append(
            {
                "external_id": row["text_rule_id"],
                "requirement_set_id": db_reqset_id,
                "academic_program_code": _blank_to_none(row.get("academic_program_code")),
                "program_name": _blank_to_none(row.get("program_name")),
                "program_type": _blank_to_none(row.get("program_type")),
                "category_code": _blank_to_none(row.get("category_code")),
                "rule_text": _blank_to_none(row.get("rule_text")),
                "rule_field": _blank_to_none(row.get("rule_field")),
                "rule_value": _blank_to_none(row.get("rule_value")),
                "source_kind": _blank_to_none(row.get("source_kind")),
                "source_file": _blank_to_none(row.get("source_file")),
                "source_title": _blank_to_none(row.get("source_title")),
                "needs_review": _to_bool(row.get("needs_review")),
                "review_reason": _blank_to_none(row.get("review_reason")),
            }
        )
    _bulk_upsert(db, RequirementTextRule, values, TEXT_RULE_COLUMNS, "uq_requirement_text_rules_external_id")
    return len(values)


def _bulk_upsert(db, model, values: list[dict[str, Any]], columns: list[str], constraint: str) -> None:
    if not values:
        return
    chunk_size = 1000
    for start in range(0, len(values), chunk_size):
        chunk = values[start : start + chunk_size]
        stmt = insert(model).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint=constraint,
            set_={
                column: getattr(stmt.excluded, column)
                for column in columns
                if column != "external_id"
            },
        )
        db.execute(stmt)


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    stripped = value.strip()
    if not stripped or not stripped.isdigit():
        return None
    return int(stripped)


def _to_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "t", "y", "yes"}


if __name__ == "__main__":
    result = seed_graduation_requirements()
    print(result)
