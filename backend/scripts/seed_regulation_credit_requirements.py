"""「부산대학교 교육과정 편성 및 운영규정」 별표2/2-2의 졸업이수학점 편성표를 정본으로 적재한다.

원문: 규칙 제3099호(2026-02-27) 별표2(대학별 학과(부)·전공), 별표2-2(융합전공 주전공형).
전사본: backend/seeds/graduation_credit_requirements_annex2_2026.csv — 행별 산술 검증
(교양소계=핵심+균형+창의, 최소전공소계=기초+필수+선택, 합계=소계+심화,
총계=교양+합계+일선+교직)을 통과한 상태로 커밋한다.

동작:
1. program_name(+parent)을 계층 브리지/별칭으로 academic_program_code에 매칭
2. (code, 'primary', '2026') requirement_set의 required_total_credits를 총계로 갱신
3. 카테고리별 학점을 needs_review=false, source_kind='university_regulation'으로 upsert
4. 같은 (세트, category_code)의 타 소스 검토완료(minimum_credits) 행은 needs_review=true로
   강등(정본 우선 — 값 불일치는 리포트로 출력). 재실행해도 안전(idempotent).

실행: python -m scripts.seed_regulation_credit_requirements [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import unicodedata
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.db import SessionLocal
from app.domains.academics.models import (
    AcademicProgramAlias,
    Department,
    Major,
    RequirementCategory,
    RequirementSet,
)

CSV_PATH = Path(__file__).resolve().parent.parent / "seeds" / "graduation_credit_requirements_annex2_2026.csv"
SOURCE_KIND = "university_regulation"
SOURCE_FILE = "부산대학교 교육과정 편성 및 운영규정(제3099호, 2026-02-27) 별표2·별표2-2"
CURRICULUM_YEAR = "2026"

# CSV 컬럼 -> (category_code, 표시명). 순서는 별표2 열 순서.
CATEGORY_MAP: list[tuple[str, str, str]] = [
    ("hy_core", "general_core", "효원핵심교양"),
    ("hy_balanced", "general_balanced", "효원균형교양"),
    ("hy_creative", "general_creative", "효원창의교양"),
    ("general_subtotal", "general_total", "교양 소계"),
    ("major_foundation", "major_foundation", "전공기초"),
    ("major_required", "major_required", "전공필수"),
    ("major_elective", "major_elective", "전공선택"),
    ("minor_subtotal", "minimum_major_total", "최소전공 소계"),
    ("deep_total", "deep_major", "심화전공"),
    ("major_total", "major_total", "전공 합계"),
    ("free_elective", "free_elective", "일반선택"),
    ("teaching", "teacher_training_total", "교직과목"),
]


def _norm(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value or "").split()).replace("・", "·").replace("ㆍ", "·")


def _norm_key(value: str) -> str:
    """공백/중점(·)/마침표 표기 차이를 무시하는 매칭 키(예: 화공생명·환경공학부 vs 화공생명.환경공학부)."""
    return _norm(value).replace(" ", "").replace("·", "").replace(".", "")


def _build_code_lookup(db) -> dict[str, str]:
    lookup: dict[str, str] = {}
    # 별칭(구명칭 포함)이 가장 낮은 우선순위 — 먼저 넣고 계층 브리지로 덮어쓴다.
    for code, alias in db.execute(
        select(AcademicProgramAlias.academic_program_code, AcademicProgramAlias.alias_name)
    ):
        lookup.setdefault(_norm_key(alias), code)
    for name, code in db.execute(
        select(Department.name, Department.academic_program_code).where(
            Department.academic_program_code.is_not(None)
        )
    ):
        lookup[_norm_key(name)] = code
    for name, dept_name, code in db.execute(
        select(Major.name, Department.name, Major.academic_program_code)
        .join(Department, Major.department_id == Department.id)
        .where(Major.academic_program_code.is_not(None))
    ):
        lookup[_norm_key(name)] = code
        lookup[_norm_key(f"{dept_name} {name}")] = code
    # 프로그램 마스터 정식명("화공생명·환경공학부 환경공학전공" 같은 학부+전공 결합 표기)도
    # 매칭 키로 — 단, 계층 브리지가 이미 잡은 키는 덮어쓰지 않는다.
    from app.domains.academics.models import AcademicProgram

    for code, program_name in db.execute(
        select(AcademicProgram.academic_program_code, AcademicProgram.program_name)
    ):
        lookup.setdefault(_norm_key(program_name), code)
    return lookup


def _resolve_code(row: dict[str, str], lookup: dict[str, str]) -> str | None:
    name = row["program_name"]
    parent = row.get("parent_name") or ""
    for candidate in (f"{parent} {name}".strip(), name):
        code = lookup.get(_norm_key(candidate))
        if code:
            return code
    return None


def seed_regulation_credit_requirements(dry_run: bool = False) -> dict[str, int]:
    with CSV_PATH.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    db = SessionLocal()
    matched = 0
    unmatched: list[str] = []
    no_set: list[str] = []
    conflicts: list[str] = []
    demoted = 0
    upserted = 0
    try:
        lookup = _build_code_lookup(db)
        for row in rows:
            code = _resolve_code(row, lookup)
            display = f"{row.get('parent_name') or row['college']} {row['program_name']}".strip()
            if not code:
                unmatched.append(display)
                continue
            reqset = db.execute(
                select(RequirementSet).where(
                    RequirementSet.academic_program_code == code,
                    RequirementSet.program_type == "primary",
                    RequirementSet.curriculum_year == CURRICULUM_YEAR,
                )
            ).scalar_one_or_none()
            if reqset is None:
                no_set.append(f"{display} ({code})")
                continue
            matched += 1
            counts = _apply_row(db, reqset, row, conflicts)
            demoted += counts["demoted"]
            upserted += counts["upserted"]

        if dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    if unmatched:
        print(f"[매칭 실패 {len(unmatched)}건] " + " / ".join(unmatched))
    if no_set:
        print(f"[요건세트 없음 {len(no_set)}건] " + " / ".join(no_set))
    if conflicts:
        print(f"[정본과 기존 검토값 불일치 {len(conflicts)}건 — 정본으로 대체]")
        for c in conflicts:
            print("  " + c)
    return {
        "rows": len(rows),
        "matched_sets": matched,
        "categories_upserted": upserted,
        "demoted_rows": demoted,
        "unmatched": len(unmatched),
        "no_requirement_set": len(no_set),
    }


def _apply_row(db, reqset: RequirementSet, row: dict[str, str], conflicts: list[str]) -> dict[str, int]:
    display = row["program_name"]
    note = (row.get("notes") or "").strip()
    # 자유전공학부처럼 표의 총계가 실제 졸업요건 전체가 아닌 특수 행은 판정에 쓰지 않는다.
    special_review = "주전공의 최소전공 기준" in note

    total = _to_int(row.get("total"))
    metadata = dict(reqset.rule_metadata or {})
    metadata["annex2_source"] = SOURCE_FILE
    if note:
        metadata["annex2_note"] = note
    reqset.required_total_credits = total if not special_review else reqset.required_total_credits
    reqset.rule_metadata = metadata

    values: list[dict[str, Any]] = []
    for csv_col, category_code, category_name in CATEGORY_MAP:
        credits = _to_int(row.get(csv_col))
        if credits is None:
            continue
        notes_parts = []
        if category_code == "general_balanced" and _to_int(row.get("basic_included")):
            notes_parts.append(f"기초교양 {row['basic_included']}학점 포함")
        if category_code == "deep_major" and (row.get("deep_required") or "").strip():
            notes_parts.append(
                f"심화전공필수 {row['deep_required']} / 심화전공선택 {row['deep_elective']} (별표2 표기)"
            )
        if note:
            notes_parts.append(note)
        values.append(
            {
                "external_id": f"annex2_{reqset.academic_program_code}_{category_code}",
                "requirement_set_id": reqset.id,
                "category_code": category_code,
                "category_name": category_name,
                "minimum_credits": str(credits),
                "rule_type": "minimum_credits",
                "source_kind": SOURCE_KIND,
                "source_file": SOURCE_FILE,
                "needs_review": special_review,
                "review_reason": note if special_review else None,
                "notes": " | ".join(notes_parts) or None,
            }
        )

    if values:
        stmt = insert(RequirementCategory).values(values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_requirement_categories_external_id",
            set_={
                col: getattr(stmt.excluded, col)
                for col in (
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
                )
            },
        )
        db.execute(stmt)

    # 같은 (세트, category_code)의 타 소스 검토완료 학점 규칙은 강등한다 — 정본 우선.
    demoted = 0
    reg_codes = {v["category_code"] for v in values}
    if reg_codes:
        # 구 규정집 파싱 후보(catreq_*)도 source_kind가 같으므로, 이번 정본 행(annex2_*)
        # 외의 모든 검토완료 학점 규칙을 강등 대상으로 본다.
        existing = db.execute(
            select(RequirementCategory).where(
                RequirementCategory.requirement_set_id == reqset.id,
                RequirementCategory.category_code.in_(reg_codes),
                RequirementCategory.rule_type == "minimum_credits",
                RequirementCategory.external_id.not_like("annex2\\_%"),
                RequirementCategory.needs_review.is_(False),
            )
        ).scalars().all()
        reg_value_by_code = {v["category_code"]: v["minimum_credits"] for v in values}
        for cat in existing:
            reg_value = reg_value_by_code[cat.category_code]
            if (cat.minimum_credits or "").strip() != reg_value:
                conflicts.append(
                    f"{display} {cat.category_code}: 기존 {cat.minimum_credits} → 정본 {reg_value}"
                    f" (기존 출처: {cat.source_kind})"
                )
            cat.needs_review = True
            cat.review_reason = (
                f"별표2 정본(annex2_{reqset.academic_program_code}_{cat.category_code})으로 대체"
            )
            demoted += 1

    return {"upserted": len(values), "demoted": demoted}


def _to_int(value: str | None) -> int | None:
    stripped = (value or "").strip()
    return int(stripped) if stripped.isdigit() else None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = seed_regulation_credit_requirements(dry_run=args.dry_run)
    print(f"별표2 정본 적재 {'(dry-run) ' if args.dry_run else ''}완료: {result}")
