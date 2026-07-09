"""파싱된 졸업요건 후보를 requirement_sets/categories/courses에 적재한다.

전제: 마이그레이션 적용 + scripts.seed_academic_programs 실행(프로그램 마스터/브리지).
멱등성: requirement_sets는 (academic_program_code, program_type, curriculum_year)로,
카테고리/과목은 파싱 산출물에서 만든 안정 external_id로 upsert한다.

사람 검토 결과(`backend/seeds/requirement_course_corrections.csv`)가 있으면 자동 파싱
결과 위에 덮어써서 적용한다. raw_data/ 파이프라인을 몇 번을 다시 돌려도(재크롤링,
재파싱, 재시딩) 검토 결과가 유실되지 않는 이유가 이것이다 — corrections 파일은
`backend/seeds/`에 있어 git으로 버전관리되고, raw_data/의 자동 생성 파일과 분리돼 있다.

현재 범위(2026-07-09 결정): 기본은 주전공(primary)만 적재한다. 부전공/복수전공은
같은 테이블의 program_type 행으로 나중에 --program-types로 확장하고, 교직
(teacher_training)은 카테고리 어휘 재정리(teacher_training_basic/pedagogy) 후
별도 세션에서 적재한다 — 그때까지 이 스크립트는 교직 행을 건너뛴다.

실행:
    python -m scripts.seed_graduation_requirements [--program-types primary,dual,minor] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.core.db import SessionLocal
from app.domains.academics.models import (
    Department,
    Major,
    RequirementCategory,
    RequirementCourse,
    RequirementSet,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = REPO_ROOT / "raw_data/parsed_experiments/graduation_requirement_seed_tables"

REQSETS_PATH = SEED_DIR / "requirement_sets_seed_candidates.csv"
CATEGORIES_PATH = SEED_DIR / "requirement_category_seed_candidates.csv"
COURSES_PATH = SEED_DIR / "requirement_course_seed_candidates.csv"
CORRECTIONS_PATH = REPO_ROOT / "backend/seeds/requirement_course_corrections.csv"
# 자동 파이프라인이 처리 못하는 원문(짧은 과목코드, 영문 rowspan 표 등)에서 사람이
# 직접 확인해 채워 넣은 과목. requirement_course_seed_candidates.csv를 재생성해도
# 유실되지 않도록 raw_data/가 아니라 backend/seeds/에 둔다.
SUPPLEMENTAL_COURSES_PATH = REPO_ROOT / "backend/seeds/requirement_course_supplemental.csv"
# 사람이 requirement_text_rules 원문(현재는 raw_data CSV 아카이브)을 읽고 구조화한
# 카테고리 규칙 — 주로 복수전공/부전공 최소전공 총학점. 재파싱/재시딩해도 유실되지 않는다.
SUPPLEMENTAL_CATEGORIES_PATH = REPO_ROOT / "backend/seeds/requirement_category_supplemental.csv"

# 사람 검토 CSV에서 이 값이면 requirement_courses에서 아예 제외한다 (실제 과목이 아니었던
# 경우, 예: 표 서식 부스러기나 영역 라벨을 과목으로 잘못 뽑은 경우).
DROP_RESOLUTION = "drop"

DEFAULT_PROGRAM_TYPES = "primary"
# 구 어휘 'teacher_training'은 새 스키마의 teacher_training_basic(△)/
# teacher_training_pedagogy(□)로 재정리 예정이라 그때까지 적재하지 않는다.
EXCLUDED_CATEGORY_CODES = {"teacher_training"}


REQSET_COLUMNS = [
    "department_id",
    "major_id",
    "academic_program_code",
    "program_type",
    "curriculum_year",
    "required_total_credits",
    "rule_metadata",
    "is_active",
]

CATEGORY_COLUMNS = [
    "external_id",
    "requirement_set_id",
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


def seed_graduation_requirements(
    program_types: set[str], dry_run: bool = False
) -> dict[str, int]:
    reqset_rows = [
        row for row in _read_csv(REQSETS_PATH) if (row.get("program_type") or "") in program_types
    ]
    category_rows = _read_csv(CATEGORIES_PATH)
    course_rows = _read_csv(COURSES_PATH)
    corrections = _load_corrections()

    db = SessionLocal()
    try:
        reqset_external_to_db_id = _upsert_requirement_sets(db, reqset_rows)
        seeded_set_ids = set(reqset_external_to_db_id.values())
        category_count, cat_skipped = _upsert_categories(
            db, category_rows, reqset_external_to_db_id, seeded_set_ids, program_types
        )
        course_count, dropped_count, course_skipped = _upsert_courses(
            db, course_rows, reqset_external_to_db_id, seeded_set_ids, corrections, program_types
        )
        if dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    return {
        "requirement_sets": len(reqset_rows),
        "requirement_categories": category_count,
        "requirement_courses": course_count,
        "requirement_courses_dropped_by_review": dropped_count,
        "teacher_training_rows_skipped": cat_skipped + course_skipped,
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


def _hierarchy_by_code(db) -> dict[str, tuple[int | None, int | None]]:
    """브리지 컬럼 기준 code -> (department_id, major_id).

    코드가 세부 전공(majors)에 붙어 있으면 소속 department_id도 함께 채운다 —
    엔진의 타학과 과목 필터가 requirement_sets.department_id와 비교하기 때문.
    """
    mapping: dict[str, tuple[int | None, int | None]] = {}
    for dept_id, code in db.execute(
        select(Department.id, Department.academic_program_code).where(
            Department.academic_program_code.is_not(None)
        )
    ):
        mapping[code] = (dept_id, None)
    for major_id, dept_id, code in db.execute(
        select(Major.id, Major.department_id, Major.academic_program_code).where(
            Major.academic_program_code.is_not(None)
        )
    ):
        mapping[code] = (dept_id, major_id)
    return mapping


def _upsert_requirement_sets(db, rows: list[dict[str, str]]) -> dict[str, int]:
    hierarchy_by_code = _hierarchy_by_code(db)
    unmatched = 0
    values = []
    for row in rows:
        value = _requirement_set_value(row, hierarchy_by_code)
        if value["department_id"] is None:
            unmatched += 1
        values.append(value)
    if unmatched:
        print(f"  [requirement_sets] 브리지에서 계층을 못 찾은 세트 {unmatched}건 (department_id=NULL로 적재)")
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


def _requirement_set_value(
    row: dict[str, str], hierarchy_by_code: dict[str, tuple[int | None, int | None]]
) -> dict[str, Any]:
    code = _blank_to_none(row.get("academic_program_code"))
    department_id, major_id = hierarchy_by_code.get(code or "", (None, None))
    return {
        "department_id": department_id,
        "major_id": major_id,
        "academic_program_code": code,
        "program_type": _blank_to_none(row.get("program_type")),
        "curriculum_year": _blank_to_none(row.get("curriculum_year")),
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
    seeded_set_ids: set[int],
    program_types: set[str],
) -> tuple[int, int]:
    values = []
    skipped_teacher_training = 0
    for row in rows:
        # parsed_course_presence는 과목 행을 (세트, 카테고리)로 group by 한 파생 placeholder라
        # DB에 저장하지 않는다 — 필요하면 requirement_courses에서 언제든 재계산 가능.
        if (row.get("rule_type") or "").strip() == "parsed_course_presence":
            continue
        db_reqset_id = reqset_external_to_db_id.get(row.get("requirement_set_id", ""))
        if not db_reqset_id:
            continue
        if (row.get("category_code") or "").strip() in EXCLUDED_CATEGORY_CODES:
            skipped_teacher_training += 1
            continue
        values.append(
            {
                "external_id": row["category_requirement_id"],
                "requirement_set_id": db_reqset_id,
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
    values.extend(_supplemental_category_values(db, program_types))
    _bulk_upsert(db, RequirementCategory, values, CATEGORY_COLUMNS, "uq_requirement_categories_external_id")
    _prune_stale(db, RequirementCategory, {value["external_id"] for value in values}, seeded_set_ids)
    return len(values), skipped_teacher_training


def _supplemental_category_values(db, program_types: set[str]) -> list[dict[str, Any]]:
    """사람이 텍스트 규칙 원문을 검토해 구조화한 카테고리 규칙(주로 복수전공/부전공
    최소전공 총학점). 이번 실행 범위(program_types) 밖이거나 대상 세트가 없으면 건너뛴다."""
    if not SUPPLEMENTAL_CATEGORIES_PATH.exists():
        return []
    values = []
    for row in _read_csv(SUPPLEMENTAL_CATEGORIES_PATH):
        if row["program_type"] not in program_types:
            continue
        reqset_id = db.execute(
            select(RequirementSet.id).where(
                RequirementSet.academic_program_code == row["academic_program_code"],
                RequirementSet.program_type == row["program_type"],
                RequirementSet.curriculum_year == row["curriculum_year"],
            )
        ).scalar()
        if not reqset_id:
            print(f"  [supplemental category] 대상 세트 없음, 건너뜀: {row['external_id']}")
            continue
        values.append(
            {
                "external_id": row["external_id"],
                "requirement_set_id": reqset_id,
                "category_code": row["category_code"],
                "category_name": _blank_to_none(row.get("category_name")),
                "minimum_credits": _blank_to_none(row.get("minimum_credits")),
                "rule_type": "minimum_credits",
                "source_kind": "manual_text_rule_review",
                "source_file": None,
                "needs_review": _to_bool(row.get("needs_review")),
                "review_reason": _blank_to_none(row.get("review_reason")),
                "notes": _blank_to_none(row.get("notes")),
            }
        )
    return values


def _supplemental_course_values(
    db, corrections: dict[str, dict[str, str]], program_types: set[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    if not SUPPLEMENTAL_COURSES_PATH.exists():
        return [], []
    values = []
    dropped_ids: list[str] = []
    for row in _read_csv(SUPPLEMENTAL_COURSES_PATH):
        if row.get("program_type") and row["program_type"] not in program_types:
            continue
        reqset_id = db.execute(
            select(RequirementSet.id).where(
                RequirementSet.academic_program_code == row["academic_program_code"],
                RequirementSet.program_type == row["program_type"],
                RequirementSet.curriculum_year == row["curriculum_year"],
            )
        ).scalar()
        if not reqset_id:
            continue
        req_id = row["requirement_course_id"]
        correction = corrections.get(req_id)
        if correction and correction["resolution"].strip().lower() == DROP_RESOLUTION:
            dropped_ids.append(req_id)
            continue
        value = {
            "external_id": req_id,
            "requirement_set_id": reqset_id,
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
        if correction:
            value = _apply_correction(value, correction)
        values.append(value)
    return values, dropped_ids


def _upsert_courses(
    db,
    rows: list[dict[str, str]],
    reqset_external_to_db_id: dict[str, int],
    seeded_set_ids: set[int],
    corrections: dict[str, dict[str, str]],
    program_types: set[str],
) -> tuple[int, int, int]:
    values = []
    dropped_ids: list[str] = []
    skipped_teacher_training = 0
    for row in rows:
        db_reqset_id = reqset_external_to_db_id.get(row.get("requirement_set_id", ""))
        if not db_reqset_id:
            continue
        if (row.get("category_code") or "").strip() in EXCLUDED_CATEGORY_CODES:
            skipped_teacher_training += 1
            continue
        req_id = row["requirement_course_id"]
        correction = corrections.get(req_id)
        if correction and correction["resolution"].strip().lower() == DROP_RESOLUTION:
            dropped_ids.append(req_id)
            continue
        value = {
            "external_id": req_id,
            "requirement_set_id": db_reqset_id,
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

    supplemental_values, supplemental_dropped_ids = _supplemental_course_values(
        db, corrections, program_types
    )
    values.extend(supplemental_values)
    dropped_ids.extend(supplemental_dropped_ids)
    _bulk_upsert(db, RequirementCourse, values, COURSE_COLUMNS, "uq_requirement_courses_external_id")

    deleted = 0
    if dropped_ids:
        result = db.execute(delete(RequirementCourse).where(RequirementCourse.external_id.in_(dropped_ids)))
        deleted = result.rowcount or 0

    deleted += _prune_stale(db, RequirementCourse, {value["external_id"] for value in values}, seeded_set_ids)

    return len(values), deleted, skipped_teacher_training


def _prune_stale(db, model, current_ids: set[str], seeded_set_ids: set[int]) -> int:
    """requirement_course_id 등 external_id는 매칭 결과를 포함한 내용 해시라, 매칭
    로직이 개선되면 같은 행이라도 해시가 바뀐다. upsert만으로는 옛 해시로 남은 행이
    DB에 그대로 남으므로 이번 실행 결과와 동기화한다.

    단, 이번 실행이 적재한 요건세트(program_type 범위) 소속 행만 지운다 — primary만
    재시딩할 때 나중에 적재된 부전공/복수전공 행을 지우면 안 되기 때문."""
    if not current_ids or not seeded_set_ids:
        return 0
    stale = db.execute(
        select(model.external_id).where(
            model.requirement_set_id.in_(seeded_set_ids),
            model.external_id.not_in(current_ids),
        )
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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--program-types",
        default=DEFAULT_PROGRAM_TYPES,
        help="쉼표 구분 program_type 목록 (기본: primary)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    types = {t.strip() for t in args.program_types.split(",") if t.strip()}
    result = seed_graduation_requirements(types, dry_run=args.dry_run)
    print(f"졸업요건 시드 {'(dry-run) ' if args.dry_run else ''}완료 ({','.join(sorted(types))}): {result}")
