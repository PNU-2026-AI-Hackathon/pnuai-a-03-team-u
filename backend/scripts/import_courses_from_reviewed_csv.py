"""검토완료된 교육과정 CSV → courses 시드.

`raw_data/manual_staging/01_graduation_requirements/by_department/{college}/{code}__{학과}/03_reviewed_rules/AIS_교육과정_{연도}_{전공/학과}.csv`
형식의 검토 CSV를 읽어 courses에 upsert한다.

**CSV 스키마** (헤더):
academic_program_code, college_name, department_name, major_name, curriculum_year, grade,
semester, category_name, category_code, course_code, course_name, credits,
is_minor_required, choice_group, marker, marker_description, source_kind, source_file, source_note

**매칭·upsert**:
- course_code로 기존 courses 조회
- 있으면 skip (혹은 --update-existing 지정 시 category/credits/dept/major 갱신)
- 없으면 새로 생성. department_id는 department_name으로, major_id는 (department_id, major_name)으로 조회
- dept/major 조회 실패 시 그 row skip하고 로그

**멱등**: 재실행 안전. 기본 정책은 기존 course_code 발견 시 skip.

실행:
    python -m scripts.import_courses_from_reviewed_csv \
        --csv "../raw_data/.../03_reviewed_rules/AIS_교육과정_2026_컴퓨터공학전공.csv"
    # dry-run (기본). --commit으로 반영. --update-existing으로 기존 행 갱신 허용.
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

from app.core.db import SessionLocal
from app.domains.academics.models import Department, Major
from app.domains.courses.models import Course


def _clean(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def import_csv(csv_path: Path, db: Session, *, commit: bool, update_existing: bool) -> dict:
    stats = Counter()
    skipped_dept: list[str] = []
    skipped_major: list[str] = []
    created_samples: list[str] = []
    updated_samples: list[str] = []

    # 학과·전공 매핑을 한 번에 로드. departments 중복 시드가 있어 이름 하나가 여러 id로
    # 존재하는 경우가 있으므로(예: '정보컴퓨터공학부' id=108, id=110), major_name이 있을 때는
    # major 이름에서 dept_id를 역산하는 게 안전하다.
    dept_name_to_ids: dict[str, list[int]] = {}
    for name, did in db.execute(select(Department.name, Department.id)).all():
        dept_name_to_ids.setdefault(name, []).append(did)
    major_name_dept_to_id: dict[tuple[int, str], int] = {}
    major_by_name_only: dict[str, list[tuple[int, int]]] = {}  # major_name → [(dept_id, major_id), ...]
    for mid, mname, did in db.execute(select(Major.id, Major.name, Major.department_id)).all():
        major_name_dept_to_id[(did, mname)] = mid
        major_by_name_only.setdefault(mname, []).append((did, mid))
    # course_code로 기존 조회 (bulk)
    code_to_course: dict[str, Course] = {
        c.course_code: c
        for c in db.scalars(select(Course).where(Course.course_code.is_not(None))).all()
    }

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            stats["rows_total"] += 1
            course_code = _clean(row.get("course_code"))
            course_name = _clean(row.get("course_name"))
            if not course_code or not course_name:
                stats["skipped_missing_code_or_name"] += 1
                continue

            dept_name = _clean(row.get("department_name"))
            major_name = _clean(row.get("major_name"))
            dept_id = None
            major_id = None

            if major_name:
                # major_name이 있으면 이 이름의 major가 어느 dept에 속하는지 먼저 찾는다.
                # 같은 dept name이 여러 id로 중복 시드된 경우도 major 실제 부모를 우선한다.
                candidates = major_by_name_only.get(major_name, [])
                if dept_name and dept_name in dept_name_to_ids:
                    dept_ids_for_name = set(dept_name_to_ids[dept_name])
                    filtered = [(did, mid) for did, mid in candidates if did in dept_ids_for_name]
                    if filtered:
                        candidates = filtered
                if len(candidates) == 1:
                    dept_id, major_id = candidates[0]
                elif len(candidates) > 1:
                    # 여러 dept에 같은 major_name이 있으면 첫 번째 사용 (드묾)
                    dept_id, major_id = candidates[0]

            if dept_id is None:
                # major 매칭 실패했거나 major_name이 없는 row → dept_name으로 조회
                dept_ids = dept_name_to_ids.get(dept_name, []) if dept_name else []
                if dept_ids:
                    dept_id = dept_ids[0]

            if dept_id is None:
                stats["skipped_no_department"] += 1
                if len(skipped_dept) < 10:
                    skipped_dept.append(f"{course_code}({dept_name})")
                continue

            if major_name and major_id is None:
                stats["missing_major_fallback_to_dept"] += 1
                if len(skipped_major) < 10:
                    skipped_major.append(f"{course_code}({dept_name}/{major_name})")

            existing = code_to_course.get(course_code)
            if existing is not None:
                if update_existing:
                    existing.course_name = course_name
                    existing.category = _clean(row.get("category_name"))
                    existing.credits = _to_float(row.get("credits"))
                    existing.department_id = dept_id
                    existing.major_id = major_id
                    existing.year = _clean(row.get("grade"))
                    existing.semester = _clean(row.get("semester"))
                    stats["updated"] += 1
                    if len(updated_samples) < 10:
                        updated_samples.append(f"{course_code}:{course_name}")
                else:
                    stats["skipped_existing"] += 1
                continue

            new_course = Course(
                course_code=course_code,
                course_name=course_name,
                category=_clean(row.get("category_name")),
                credits=_to_float(row.get("credits")),
                department_id=dept_id,
                major_id=major_id,
                year=_clean(row.get("grade")),
                semester=_clean(row.get("semester")),
            )
            db.add(new_course)
            code_to_course[course_code] = new_course
            stats["created"] += 1
            if len(created_samples) < 10:
                created_samples.append(f"{course_code}:{course_name}")

    if commit:
        db.commit()
    else:
        db.rollback()

    return {
        "stats": dict(stats),
        "created_samples": created_samples,
        "updated_samples": updated_samples,
        "skipped_department_samples": skipped_dept,
        "missing_major_samples": skipped_major,
        "committed": commit,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--commit", action="store_true", help="실제 반영. 기본은 dry-run(rollback).")
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="course_code 이미 있는 경우 category/credits/dept/major/grade/semester 갱신 허용 (기본은 skip).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.csv.exists():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        sys.exit(1)
    db = SessionLocal()
    try:
        result = import_csv(args.csv, db, commit=args.commit, update_existing=args.update_existing)
    finally:
        db.close()
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
