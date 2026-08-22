"""수강편람 CSV의 효원균형교양·효원창의교양 실제 강좌 → courses 시드.

## 배경

`courses`의 효원균형교양·효원창의교양은 두 종류가 섞여 있다:
1. `ZFz…` 코드의 "영역" placeholder 6+3개(균형 6영역/창의 3영역, 규정 제9조).
   대체과목 기능(`app/domains/academics/course_substitution.py`)이 "균형 6영역 중
   2영역"처럼 영역 단위 인정을 표현하려고 쓰는 자체 구성 값이다. 실제 PNU 과목이
   아니므로 건드리지 않는다.
2. 그 외 실제 개설 강좌(`ZF1…`/`KM1…`/`ST1…` 등 진짜 코드) 소수.

`scripts/import_course_offerings.py`는 수강편람 CSV의 `course_code`가 `courses`에
이미 있어야만 course_offerings를 적재하고, 없으면 조용히 스킵한다(교양은 학과 커리큘럼
문서 수집 대상이 아니라 courses에 애초에 안 들어가 있는 경우가 대부분). 그 결과 실제로는
2026-2학기에 효원균형교양 154개 강좌(304개 분반)·효원창의교양 48개 강좌(87개 분반)가
개설돼 있는데 courses에 없어서 온스톱 수강편람 → course_offerings 적재 시 대부분
스킵됐다(2026-08-22 확인, 균형 10/154·창의 1/48만 매칭).

이 스크립트는 그 갭을 메운다: CSV에서 이 두 카테고리의 고유 course_code를 모아
`courses`에 없는 것만 새로 만든다. `ZFz…` placeholder나 이미 있는 실제 코드는
건드리지 않는다(스킵). department_id/major_id는 NULL — 교양은 학과 무관하게
전교생에게 열려 있고, `/me/curriculum`이 `department_id IS NULL`인 과목을 학과와
무관하게 후보로 내려주는 기존 규칙과 맞춘다.

실행 후 `import_course_offerings.py`를 같은 CSV로 재실행해야 course_offerings가
실제로 채워진다(이 스크립트는 courses만 채운다).

사용:
    ./backend/.venv/bin/python -m scripts.seed_general_education_courses_from_offerings \
        --csv raw_data/crawled_data/onestop_course_catalog/2026_2/2026_2_course_catalog.csv
    # dry-run(기본). --commit으로 반영.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import select
from sqlalchemy.orm import Session

# Course.department_id/major_id의 ForeignKey("departments.id"/"majors.id")는 문자열 참조라,
# 이 모듈들을 import해서 테이블을 메타데이터에 등록해둬야 flush 시 FK를 못 찾는 에러가 안 난다.
from app.domains.academics.models import Department, Major  # noqa: F401
from app.core.db import SessionLocal
from app.domains.courses.models import Course

TARGET_CATEGORIES = {"효원균형교양", "효원창의교양"}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    s = value.strip()
    return s or None


def _to_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def import_csv(csv_path: Path, db: Session, *, commit: bool) -> dict:
    stats = Counter()
    created_samples: list[str] = []

    existing_codes: set[str] = set(
        db.scalars(select(Course.course_code).where(Course.course_code.is_not(None))).all()
    )

    # CSV 안에서도 같은 course_code가 분반 수만큼 반복되므로 먼저 course_code 단위로 합친다.
    seen_in_csv: dict[str, tuple[str, str, float | None]] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            stats["rows_total"] += 1
            category = _clean(row.get("category"))
            if category not in TARGET_CATEGORIES:
                continue
            course_code = _clean(row.get("course_code"))
            course_name = _clean(row.get("course_name"))
            if not course_code or not course_name:
                stats["skipped_missing_code_or_name"] += 1
                continue
            if course_code not in seen_in_csv:
                seen_in_csv[course_code] = (course_name, category, _to_float(row.get("credits")))

    for course_code, (course_name, category, credits) in sorted(seen_in_csv.items()):
        if course_code in existing_codes:
            stats["skipped_existing"] += 1
            continue
        db.add(
            Course(
                course_code=course_code,
                course_name=course_name,
                category=category,
                credits=credits,
                department_id=None,
                major_id=None,
                source_document=csv_path.name,
            )
        )
        existing_codes.add(course_code)
        stats["created"] += 1
        if len(created_samples) < 15:
            created_samples.append(f"{course_code}:{course_name}({category})")

    if commit:
        db.commit()
    else:
        db.rollback()

    return {
        "distinct_target_category_codes_in_csv": len(seen_in_csv),
        "stats": dict(stats),
        "created_samples": created_samples,
        "committed": commit,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--commit", action="store_true", help="실제 반영. 기본은 dry-run(rollback).")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        sys.exit(1)
    db = SessionLocal()
    try:
        result = import_csv(args.csv, db, commit=args.commit)
    finally:
        db.close()
    import json

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
