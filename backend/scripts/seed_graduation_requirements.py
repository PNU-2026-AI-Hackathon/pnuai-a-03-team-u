"""Seed parsed graduation requirement candidates into the DB.

This script expects migrations to be applied and academic_programs to be seeded.
It is idempotent: requirement_sets are upserted by
(academic_program_code, program_type, curriculum_year), and detail tables are
upserted by stable external_id generated from raw parsing outputs.

사람 검토 결과(`backend/seeds/requirement_course_corrections.csv`)가 있으면 자동 파싱
결과 위에 덮어써서 적용한다. raw_data/ 파이프라인을 몇 번을 다시 돌려도(재크롤링,
재파싱, 재시딩) 검토 결과가 유실되지 않는 이유가 이것이다 — corrections 파일은
`backend/seeds/`에 있어 git으로 버전관리되고, raw_data/의 자동 생성 파일과 분리돼 있다.

실행:
    python scripts/export_requirement_course_review_queue.py  # 검토 대상 뽑기
    (검토 후 backend/seeds/requirement_course_corrections.csv에 결과 기록)
    python -m scripts.seed_graduation_requirements               # 자동 파싱 + 검토 결과 함께 반영
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
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
CORRECTIONS_PATH = REPO_ROOT / "backend/seeds/requirement_course_corrections.csv"
# 자동 파이프라인이 처리 못하는 원문(짧은 과목코드, 영문 rowspan 표 등)에서 사람이
# 직접 확인해 채워 넣은 과목. requirement_course_seed_candidates.csv를 재생성해도
# 유실되지 않도록 raw_data/가 아니라 backend/seeds/에 둔다.
SUPPLEMENTAL_COURSES_PATH = REPO_ROOT / "backend/seeds/requirement_course_supplemental.csv"

# 사람 검토 CSV에서 이 값이면 requirement_courses에서 아예 제외한다 (실제 과목이 아니었던
# 경우, 예: 표 서식 부스러기나 영역 라벨을 과목으로 잘못 뽑은 경우).
DROP_RESOLUTION = "drop"


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
    corrections = _load_corrections()

    db = SessionLocal()
    try:
        reqset_external_to_db_id = _upsert_requirement_sets(db, reqset_rows)
        category_count = _upsert_categories(db, category_rows, reqset_external_to_db_id)
        course_count, dropped_count = _upsert_courses(db, course_rows, reqset_external_to_db_id, corrections)
        text_rule_count = _upsert_text_rules(db, text_rule_rows, reqset_external_to_db_id)
        db.commit()
    finally:
        db.close()

    return {
        "requirement_sets": len(reqset_rows),
        "requirement_categories": category_count,
        "requirement_courses": course_count,
        "requirement_courses_dropped_by_review": dropped_count,
        "requirement_text_rules": text_rule_count,
        "corrections_applied": len(corrections),
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _load_corrections() -> dict[str, dict[str, str]]:
    """requirement_course_id -> 사람이 검토한 결과. resolution이 빈칸인 행은 아직
    검토 전이므로 무시한다."""
    if not CORRECTIONS_PATH.exists():
        return {}
    corrections: dict[str, dict[str, str]] = {}
    for row in _read_csv(CORRECTIONS_PATH):
        req_id = (row.get("requirement_course_id") or "").strip()
        resolution = (row.get("resolution") or "").strip().lower()
        if not req_id or not resolution:
            continue
        corrections[req_id] = row
    return corrections


def _apply_correction(value: dict[str, Any], correction: dict[str, str]) -> dict[str, Any]:
    resolution = correction["resolution"].strip().lower()
    reviewer_note = " | ".join(
        part
        for part in [
            f"manually verified by {correction.get('reviewed_by', '').strip() or 'unknown'}"
            f"{' on ' + correction['reviewed_at'].strip() if correction.get('reviewed_at', '').strip() else ''}",
            correction.get("note", "").strip(),
        ]
        if part
    )
    if resolution == "fix":
        for field, column in (
            ("corrected_matched_course_code", "matched_course_code"),
            ("corrected_matched_course_name", "matched_course_name"),
            ("corrected_match_status", "match_status"),
        ):
            corrected = (correction.get(field) or "").strip()
            if corrected:
                value[column] = corrected
        value["needs_review"] = False
        value["review_reason"] = reviewer_note
    elif resolution == "confirm":
        value["needs_review"] = False
        value["review_reason"] = reviewer_note
    elif resolution == "needs_source":
        value["review_reason"] = reviewer_note or value.get("review_reason")
    return value


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
    _prune_stale(db, RequirementCategory, {value["external_id"] for value in values})
    return len(values)


def _supplemental_course_values(db) -> list[dict[str, Any]]:
    if not SUPPLEMENTAL_COURSES_PATH.exists():
        return []
    values = []
    for row in _read_csv(SUPPLEMENTAL_COURSES_PATH):
        reqset_id = db.execute(
            select(RequirementSet.id).where(
                RequirementSet.academic_program_code == row["academic_program_code"],
                RequirementSet.program_type == row["program_type"],
                RequirementSet.curriculum_year == row["curriculum_year"],
            )
        ).scalar()
        if not reqset_id:
            continue
        values.append(
            {
                "external_id": row["requirement_course_id"],
                "requirement_set_id": reqset_id,
                "academic_program_code": _blank_to_none(row.get("academic_program_code")),
                "college_name": None,
                "program_name": None,
                "program_type": _blank_to_none(row.get("program_type")),
                "curriculum_year": _blank_to_none(row.get("curriculum_year")),
                "category_code": _blank_to_none(row.get("category_code")),
                "recommended_year": _blank_to_none(row.get("recommended_year")),
                "recommended_semester": _blank_to_none(row.get("recommended_semester")),
                "raw_course_code": _blank_to_none(row.get("raw_course_code")),
                "raw_course_name": _blank_to_none(row.get("raw_course_name")),
                "raw_credit": _blank_to_none(row.get("raw_credit")),
                "matched_course_code": None,
                "matched_course_name": None,
                "match_status": "unmatched",
                "match_method": "manual_supplemental",
                "matched_terms": None,
                "matched_departments": None,
                "choice_rule_types": None,
                "choice_rule_raw": None,
                "source_table": "requirement_course_supplemental",
                "source_file": _blank_to_none(row.get("source_file")),
                "needs_review": True,
                "review_reason": _blank_to_none(row.get("note")),
            }
        )
    return values


def _upsert_courses(
    db,
    rows: list[dict[str, str]],
    reqset_external_to_db_id: dict[str, int],
    corrections: dict[str, dict[str, str]],
) -> tuple[int, int]:
    values = []
    dropped_ids: list[str] = []
    for row in rows:
        db_reqset_id = reqset_external_to_db_id.get(row.get("requirement_set_id", ""))
        if not db_reqset_id:
            continue
        req_id = row["requirement_course_id"]
        correction = corrections.get(req_id)
        if correction and correction["resolution"].strip().lower() == DROP_RESOLUTION:
            dropped_ids.append(req_id)
            continue
        value = {
            "external_id": req_id,
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
        if correction:
            value = _apply_correction(value, correction)
        values.append(value)

    values.extend(_supplemental_course_values(db))
    _bulk_upsert(db, RequirementCourse, values, COURSE_COLUMNS, "uq_requirement_courses_external_id")

    deleted = 0
    if dropped_ids:
        result = db.execute(delete(RequirementCourse).where(RequirementCourse.external_id.in_(dropped_ids)))
        deleted = result.rowcount or 0

    deleted += _prune_stale(db, RequirementCourse, {value["external_id"] for value in values})

    return len(values), deleted


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
    _prune_stale(db, RequirementTextRule, {value["external_id"] for value in values})
    return len(values)


def _prune_stale(db, model, current_ids: set[str]) -> int:
    """requirement_course_id 등 external_id는 매칭 결과를 포함한 내용 해시라, 매칭
    로직이 개선되면 같은 행이라도 해시가 바뀐다. upsert만으로는 옛 해시로 남은 행이
    DB에 그대로 남으므로, 이번 실행에서 실제로 만들어진 external_id 집합과 동기화한다."""
    if not current_ids:
        return 0
    stale = db.execute(
        select(model.external_id).where(model.external_id.not_in(current_ids))
    ).scalars().all()
    if not stale:
        return 0
    result = db.execute(delete(model).where(model.external_id.in_(stale)))
    return result.rowcount or 0


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
