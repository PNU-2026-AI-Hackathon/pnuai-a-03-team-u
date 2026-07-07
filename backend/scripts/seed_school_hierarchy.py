"""계층 매핑표(_hierarchy_mapping.csv)를 schools/colleges/departments/majors에 적재한다.

매핑표는 수집 대상 151건(_collection_targets_index.csv)을 학교/단과대/학과/전공
계층으로 분류한 것으로, raw_data(로컬 전용, gitignore) 작업 공간에서 생성된다.
분류 규칙과 팀 확인 근거는 raw_data/WORKLOG_department_curriculum_collection.md
"2026-07-08 계층 매핑표" 항목 참고.

- split_rule=exclude(교양학부 계열/기타모집단위)와 needs_confirm은 건너뛴다.
- domains/academics/hierarchy.py의 get-or-create를 그대로 사용하므로 재실행해도
  중복이 생기지 않는다(idempotent).
- 이름은 NFC 정규화 + 공백 정리만 하고 그 외 표기는 매핑표를 그대로 따른다.

실행: python -m scripts.seed_school_hierarchy [--mapping <csv>] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import unicodedata
from pathlib import Path

from app.core.db import SessionLocal
from app.domains.academics.hierarchy import resolve_hierarchy
from app.domains.academics.models import College, Department, Major, School

DEFAULT_MAPPING = Path(__file__).resolve().parent.parent / "seeds" / "school_hierarchy_mapping.csv"

LOADABLE_RULES = {"ais", "direct", "direct_special", "space_split", "paren_split", "manual_parent"}


def normalize(name: str) -> str:
    return " ".join(unicodedata.normalize("NFC", name).split())


def load_mapping(path: Path) -> tuple[list[dict], list[dict]]:
    """매핑 CSV를 (적재 대상, 건너뛴 행) 튜플로 반환한다."""
    loadable, skipped = [], []
    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["split_rule"] in LOADABLE_RULES:
                loadable.append(row)
            else:
                skipped.append(row)
    return loadable, skipped


def seed_hierarchy(mapping_path: Path, dry_run: bool = False) -> None:
    loadable, skipped = load_mapping(mapping_path)
    db = SessionLocal()
    try:
        before = {
            m.__tablename__: db.query(m).count() for m in (School, College, Department, Major)
        }
        for row in loadable:
            resolve_hierarchy(
                db,
                school_name=normalize(row["school_name"]),
                college_name=normalize(row["college_name"]),
                department_name=normalize(row["department_name"]),
                major_name=normalize(row["major_name"]) or None,
            )
        after = {
            m.__tablename__: db.query(m).count() for m in (School, College, Department, Major)
        }
        if dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    print(f"매핑 {len(loadable) + len(skipped)}행 중 적재 {len(loadable)} / 건너뜀 {len(skipped)}")
    for row in skipped:
        print(f"  skip [{row['split_rule']}] {row['program_name_src']}")
    for table in before:
        print(f"{table}: {before[table]} -> {after[table]} (+{after[table] - before[table]})"
              + (" [dry-run, 롤백됨]" if dry_run else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    seed_hierarchy(args.mapping, dry_run=args.dry_run)
