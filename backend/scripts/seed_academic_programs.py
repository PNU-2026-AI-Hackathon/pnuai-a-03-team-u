"""졸업요건용 학사 프로그램 마스터를 DB에 upsert하고 계층 브리지를 채운다.

schools~majors 계층은 회원가입/조회용 이름 계층이고, 이 스크립트가 넣는
`academic_programs`는 학과코드가 필요한 졸업요건/교육과정 연결 기준이다.
두 축의 연결은 별도 매핑 테이블이 아니라 departments/majors의
`academic_program_code` 브리지 컬럼이 담당하며, 이 스크립트가
`school_hierarchy_mapping.csv`(계층 시드와 같은 원본)로 backfill한다.

재실행해도 안전(idempotent): programs/aliases는 upsert, 브리지는 같은 값 재기록.

실행: python -m scripts.seed_academic_programs [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.db import SessionLocal
from app.domains.academics.models import (
    AcademicProgram,
    AcademicProgramAlias,
    College,
    Department,
    Major,
)

SEED_DIR = Path(__file__).resolve().parent.parent / "seeds"
PROGRAMS_PATH = SEED_DIR / "academic_programs_2026_active_bachelor.csv"
ALIASES_PATH = SEED_DIR / "academic_program_aliases_2026.csv"
HIERARCHY_MAPPING_PATH = SEED_DIR / "school_hierarchy_mapping.csv"

# seed_school_hierarchy.py와 동일 — 계층에 적재된 행만 브리지 대상이 된다.
LOADABLE_RULES = {"ais", "direct", "direct_special", "space_split", "paren_split", "manual_parent"}

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


def seed_academic_programs(dry_run: bool = False) -> dict[str, int]:
    program_rows = _read_csv(PROGRAMS_PATH)
    alias_rows = _read_csv(ALIASES_PATH)
    active_program_codes = {row["academic_program_code"] for row in program_rows}

    db = SessionLocal()
    try:
        _upsert_programs(db, program_rows)
        alias_count = _upsert_aliases(db, alias_rows, active_program_codes)
        bridge_counts = _backfill_hierarchy_bridge(db, active_program_codes)
        if dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    return {
        "academic_programs": len(program_rows),
        "academic_program_aliases": alias_count,
        **bridge_counts,
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


def _upsert_aliases(db, rows: list[dict[str, str]], allowed_program_codes: set[str]) -> int:
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
                "normalized_alias_name": row["normalized_alias_name"] or _normalize_alias(row["alias_name"]),
                "source": _blank_to_none(row.get("source", "")),
            }
        )
    if not values:
        return 0

    stmt = insert(AcademicProgramAlias).values(values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_academic_program_alias",
        set_={
            "normalized_alias_name": stmt.excluded.normalized_alias_name,
            "source": stmt.excluded.source,
        },
    )
    db.execute(stmt)
    return len(values)


def _pick_bridge_code(raw_code: str, allowed: set[str], feature_by_code: dict[str, str]) -> str | None:
    """매핑 CSV의 코드 필드에서 브리지에 걸 코드 하나를 고른다.

    조선·해양공학과처럼 'U...075;U...133'(일반과정;계약학과) 두 코드가 세미콜론으로
    묶인 행이 있다 — 브리지 컬럼은 하나뿐이므로 일반과정 코드를 우선한다.
    (계약학과 프로그램은 academic_programs에는 존재하되 계층 브리지 없이 남는다.)
    """
    candidates = [c.strip() for c in (raw_code or "").split(";") if c.strip() in allowed]
    if not candidates:
        return None
    for code in candidates:
        if feature_by_code.get(code) == "일반과정":
            return code
    return candidates[0]


def _backfill_hierarchy_bridge(db, allowed_program_codes: set[str]) -> dict[str, int]:
    """school_hierarchy_mapping.csv 기준으로 departments/majors.academic_program_code를 채운다.

    major_name이 있으면 코드는 세부 전공(majors) 쪽에, 없으면 학과(departments) 쪽에
    붙는다 — 참조하는 쪽(요건세트/사용자)은 브리지가 있는 계층 행을 통해 코드를 얻는다.
    """
    college_ids = {
        _normalize_name(name): college_id
        for college_id, name in db.execute(select(College.id, College.name))
    }
    departments = db.execute(
        select(Department.id, Department.college_id, Department.name)
    ).all()
    dept_ids = {
        (dept.college_id, _normalize_name(dept.name)): dept.id for dept in departments
    }
    majors = db.execute(select(Major.id, Major.department_id, Major.name)).all()
    major_ids = {
        (major.department_id, _normalize_name(major.name)): major.id for major in majors
    }

    feature_by_code = {
        code: feature
        for code, feature in db.execute(
            select(AcademicProgram.academic_program_code, AcademicProgram.program_feature_name)
        )
    }
    rows = []
    for row in _read_csv(HIERARCHY_MAPPING_PATH):
        if (row.get("split_rule") or "").strip() not in LOADABLE_RULES:
            continue
        code = _pick_bridge_code(
            row.get("academic_program_code") or "", allowed_program_codes, feature_by_code
        )
        if code:
            rows.append((code, row))
    # 같은 코드가 여러 계층 행에 걸치면(예: 기계공학부 — 학부 공통 + AIS 조회용
    # 세부전공 5행이 코드 하나를 공유) 학과 레벨 행에만 브리지를 건다.
    # 세부전공 행은 AIS 커리큘럼 조회용 참고 구분일 뿐 요건 단위가 아니다.
    dept_level_codes = {
        code for code, row in rows if not _normalize_name(row.get("major_name") or "")
    }

    dept_updates = 0
    major_updates = 0
    unmatched: list[str] = []
    for code, row in rows:
        if _normalize_name(row.get("major_name") or "") and code in dept_level_codes:
            continue
        college_id = college_ids.get(_normalize_name(row.get("college_name") or ""))
        dept_id = dept_ids.get((college_id, _normalize_name(row.get("department_name") or "")))
        if not dept_id:
            unmatched.append(f"{code} {row.get('department_name')}")
            continue
        major_name = _normalize_name(row.get("major_name") or "")
        if major_name:
            major_id = major_ids.get((dept_id, major_name))
            if not major_id:
                unmatched.append(f"{code} {row.get('department_name')}/{row.get('major_name')}")
                continue
            db.execute(
                Major.__table__.update().where(Major.id == major_id).values(academic_program_code=code)
            )
            major_updates += 1
        else:
            db.execute(
                Department.__table__.update()
                .where(Department.id == dept_id)
                .values(academic_program_code=code)
            )
            dept_updates += 1

    if unmatched:
        print(f"  [bridge] 계층에서 못 찾은 매핑 {len(unmatched)}건: {', '.join(unmatched[:5])} ...")
    return {
        "bridge_departments": dept_updates,
        "bridge_majors": major_updates,
        "bridge_unmatched": len(unmatched),
    }


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


def _normalize_alias(value: str) -> str:
    return re.sub(r"[\s:()（）·ㆍ・.]", "", value or "").lower()


def _normalize_name(value: str) -> str:
    """seed_school_hierarchy.py의 normalize와 동일 (NFC + 공백 정리)."""
    return " ".join(unicodedata.normalize("NFC", value or "").split())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = seed_academic_programs(dry_run=args.dry_run)
    print(f"학사 프로그램 시드 {'(dry-run) ' if args.dry_run else ''}완료: {result}")
