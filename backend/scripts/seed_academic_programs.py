"""졸업요건용 학사 프로그램 마스터를 DB에 upsert한다.

`departments`는 회원가입 입력값 검증용 이름 목록이고, 이 스크립트가 넣는
`academic_programs`는 학과코드가 필요한 졸업요건/교육과정 연결 기준이다.

실행: python -m scripts.seed_academic_programs
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.db import SessionLocal
from app.domains.academics.models import (
    AcademicProgram,
    AcademicProgramAlias,
    Department,
    DepartmentAcademicProgramMapping,
)

SEED_DIR = Path(__file__).resolve().parent.parent / "seeds"
PROGRAMS_PATH = SEED_DIR / "academic_programs_2026_active_bachelor.csv"
ALIASES_PATH = SEED_DIR / "academic_program_aliases_2026.csv"

PROGRAM_COLUMNS = [
    "academic_program_code",
    "survey_year",
    "survey_round",
    "school_code",
    "school_name",
    "campus_code",
    "campus_name",
    "college_code",
    "college_name",
    "program_name",
    "display_name",
    "normalized_program_name",
    "parent_department_name",
    "major_name",
    "day_night_code",
    "day_night_name",
    "program_feature_code",
    "program_feature_name",
    "duration_code",
    "duration_name",
    "status_code",
    "status_name",
    "education_ministry_5_category",
    "degree_level",
    "quota_adjustment_type",
    "first_admission_year",
    "free_major_type_code",
    "free_major_type_name",
    "kedi_7_category",
    "source_updated_at",
    "source_file",
    "is_active",
    "is_bachelor",
]


def seed_academic_programs() -> dict[str, int]:
    program_rows = _read_csv(PROGRAMS_PATH)
    alias_rows = _read_csv(ALIASES_PATH)
    active_program_codes = {row["academic_program_code"] for row in program_rows}

    db = SessionLocal()
    try:
        _upsert_programs(db, program_rows)
        _upsert_aliases(db, alias_rows, active_program_codes)
        mapping_count = _upsert_department_mappings(db)
        db.commit()
    finally:
        db.close()

    return {
        "academic_programs": len(program_rows),
        "academic_program_aliases": len(alias_rows),
        "department_academic_program_mappings": mapping_count,
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _upsert_programs(db, rows: list[dict[str, str]]) -> None:
    values = [_program_value(row) for row in rows]
    if not values:
        return

    stmt = insert(AcademicProgram).values(values)
    update_columns = {
        column: getattr(stmt.excluded, column)
        for column in PROGRAM_COLUMNS
        if column != "academic_program_code"
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=["academic_program_code"],
        set_=update_columns,
    )
    db.execute(stmt)


def _program_value(row: dict[str, str]) -> dict[str, Any]:
    value = {column: _blank_to_none(row.get(column, "")) for column in PROGRAM_COLUMNS}
    value["survey_year"] = _to_int(value["survey_year"])
    value["survey_round"] = _to_int(value["survey_round"])
    value["is_active"] = _to_bool(value["is_active"])
    value["is_bachelor"] = _to_bool(value["is_bachelor"])
    return value


def _upsert_aliases(db, rows: list[dict[str, str]], allowed_program_codes: set[str]) -> None:
    values = []
    seen = set()
    for row in rows:
        if not row.get("academic_program_code") or not row.get("alias_name"):
            continue
        if row["academic_program_code"] not in allowed_program_codes:
            continue
        key = (row["academic_program_code"], row["alias_type"], row["alias_name"])
        if key in seen:
            continue
        seen.add(key)
        values.append(
            {
            "academic_program_code": row["academic_program_code"],
            "alias_type": row["alias_type"],
            "alias_name": row["alias_name"],
            "normalized_alias_name": row["normalized_alias_name"] or _normalize(row["alias_name"]),
            "source": _blank_to_none(row.get("source", "")),
            }
        )
    if not values:
        return

    stmt = insert(AcademicProgramAlias).values(values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_academic_program_alias",
        set_={
            "normalized_alias_name": stmt.excluded.normalized_alias_name,
            "source": stmt.excluded.source,
        },
    )
    db.execute(stmt)


def _upsert_department_mappings(db) -> int:
    departments = db.scalars(select(Department)).all()
    if not departments:
        return 0

    aliases = db.execute(
        select(
            AcademicProgramAlias.academic_program_code,
            AcademicProgramAlias.alias_type,
            AcademicProgramAlias.alias_name,
            AcademicProgramAlias.normalized_alias_name,
        )
    ).all()
    programs = {
        program.academic_program_code: program
        for program in db.scalars(select(AcademicProgram)).all()
    }

    aliases_by_normalized: dict[str, list[Any]] = {}
    for alias in aliases:
        aliases_by_normalized.setdefault(alias.normalized_alias_name, []).append(alias)

    values = []
    seen = set()
    for department in departments:
        normalized_name = _normalize(department.name)
        for alias in aliases_by_normalized.get(normalized_name, []):
            program = programs.get(alias.academic_program_code)
            if program is None:
                continue
            relation_type = _relation_type(department.name, alias.alias_type, program)
            key = (department.id, alias.academic_program_code, relation_type)
            if key in seen:
                continue
            seen.add(key)
            values.append(
                {
                    "department_id": department.id,
                    "academic_program_code": alias.academic_program_code,
                    "relation_type": relation_type,
                    "source": f"academic_program_alias:{alias.alias_type}",
                    "confidence": 1.0,
                }
            )

    if not values:
        return 0

    stmt = insert(DepartmentAcademicProgramMapping).values(values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_department_academic_program_mapping",
        set_={
            "source": stmt.excluded.source,
            "confidence": stmt.excluded.confidence,
        },
    )
    db.execute(stmt)
    return len(values)


def _relation_type(department_name: str, alias_type: str, program: AcademicProgram) -> str:
    if department_name == program.program_name:
        return "same"
    if department_name == program.parent_department_name:
        return "parent"
    if department_name == program.major_name:
        return "major_track"
    if alias_type == "display_name":
        return "display_name"
    return "alias"


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _to_int(value: str | None) -> int | None:
    return int(value) if value else None


def _to_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _normalize(value: str) -> str:
    return re.sub(r"[\s:()（）·ㆍ・.]", "", value or "").lower()


if __name__ == "__main__":
    result = seed_academic_programs()
    print(
        "학사 프로그램 시드 완료: "
        f"{result['academic_programs']} programs, "
        f"{result['academic_program_aliases']} aliases, "
        f"{result['department_academic_program_mappings']} mappings"
    )
