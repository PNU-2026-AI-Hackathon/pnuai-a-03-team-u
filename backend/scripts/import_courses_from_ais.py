"""AIS 교육과정 CSV를 courses 테이블에 적재한다.

입력 CSV 컬럼: ais_dept_code, curriculum_year, grade(학년), semester(학기),
category(교과목구분), course_name, course_code, credits.
계층 매핑 CSV(_hierarchy_mapping.csv)의 ais_dept_code로 department_id/major_id를 결정한다.

컨벤션:
- courses 행 = "해당 학과/전공 교육과정의 과목 항목". 같은 course_code가 여러 단위의
  교육과정에 있으면 행이 여러 개 생긴다(ix_courses_course_code가 비유니크인 이유).
- 전공기초/전공필수/전공선택/교직과목 → 단위별 행 (department_id, 전공 단위면 major_id까지).
- 교양(효원핵심/균형/창의 등 '교양' 포함 구분) → 전학교 공통이므로 course_code 기준
  중복 제거 후 department_id=NULL 한 행만 둔다 (성적 매칭용).
- year = 학년("1학년"→"1"), semester = 학기("1학기"→"1", "1,2학기"→"1,2") — Course 모델
  docstring대로 "참고값".
- 멱등: (department_id, major_id, course_code) 기준 get-or-create, 재실행 시 갱신.

실행: python -m scripts.import_courses_from_ais --courses <csv> [--mapping <csv>] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from pathlib import Path

from app.core.db import SessionLocal
from app.domains.academics.hierarchy import resolve_hierarchy
from app.domains.courses.models import Course

SEEDS = Path(__file__).resolve().parent.parent / "seeds"
DEFAULT_MAPPING = SEEDS / "school_hierarchy_mapping.csv"
DEFAULT_COURSES = SEEDS / "ais_courses_2026.csv"

GENERAL_ED_KEYWORD = "교양"


def norm_name(s: str) -> str:
    return " ".join(unicodedata.normalize("NFC", s).split())


def norm_grade(s: str) -> str | None:
    """'1학년'→'1'. '전학년' 같은 비숫자 값은 원문 유지."""
    stripped = s.replace("학년", "").strip()
    return stripped if stripped.isdigit() else (s.strip() or None)


def norm_semester(s: str) -> str | None:
    """'1학기'→'1', '1,2학기'→'1,2'. '전학기'/계절·도약수업은 원문 유지."""
    stripped = s.replace("학기", "").replace(" ", "")
    return stripped if re.fullmatch(r"[12](,[12])?", stripped) else (s.strip() or None)


def load_unit_index(mapping_path: Path) -> dict[str, dict]:
    """ais_dept_code -> 매핑 행."""
    with mapping_path.open(encoding="utf-8-sig") as f:
        return {r["ais_dept_code"]: r for r in csv.DictReader(f) if r["ais_dept_code"]}


def import_courses(courses_csv: Path, mapping_path: Path, dry_run: bool = False) -> None:
    units = load_unit_index(mapping_path)
    with courses_csv.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    db = SessionLocal()
    created = updated = skipped_unit = dup_in_run = 0
    seen_ge: set[str] = set()
    # SessionLocal이 autoflush=False라 같은 실행 안의 add가 이후 조회에 안 보인다.
    # 같은 단위에 같은 과목코드가 두 번 나오는 경우(교직과목 권장시점 2개 등)를 여기서 걸러낸다.
    seen_unit_course: set[tuple] = set()
    try:
        for r in rows:
            unit = units.get(r["ais_dept_code"])
            if unit is None:
                skipped_unit += 1
                continue
            is_ge = GENERAL_ED_KEYWORD in r["category"]
            if is_ge:
                if r["course_code"] in seen_ge:
                    continue
                seen_ge.add(r["course_code"])
                dept_id = major_id = None
            else:
                dept_id, major_id = resolve_hierarchy(
                    db,
                    school_name=norm_name(unit["school_name"]),
                    college_name=norm_name(unit["college_name"]),
                    department_name=norm_name(unit["department_name"]),
                    major_name=norm_name(unit["major_name"]) or None,
                )
            values = dict(
                # AIS 원본에 교과목명이 빈 과목이 실존한다(행정학과 PA2700143, 2024~2026 모두 공란).
                # 실존 과목이므로 버리지 않고 표시용 이름으로 대체한다.
                course_name=norm_name(r["course_name"]) or f"(교과목명 미상: {r['course_code']})",
                category=r["category"].strip(),
                credits=float(r["credits"]) if r["credits"] else None,
                year=norm_grade(r["grade"]),
                semester=norm_semester(r["semester"]),
            )
            unit_key = (dept_id, major_id, r["course_code"])
            if unit_key in seen_unit_course:
                dup_in_run += 1
                continue
            seen_unit_course.add(unit_key)
            course = (
                db.query(Course)
                .filter_by(department_id=dept_id, major_id=major_id, course_code=r["course_code"])
                .one_or_none()
            )
            if course is None:
                db.add(Course(course_code=r["course_code"], department_id=dept_id,
                              major_id=major_id, **values))
                created += 1
            else:
                changed = False
                for k, v in values.items():
                    if getattr(course, k) != v:
                        setattr(course, k, v)
                        changed = True
                updated += int(changed)
        if dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    print(f"입력 {len(rows)}행 → 신규 {created} / 갱신 {updated} / 교양 중복 제거 "
          f"{len([r for r in rows if GENERAL_ED_KEYWORD in r['category']]) - len(seen_ge)} / "
          f"매핑 없는 단위 스킵 {skipped_unit} / 실행 내 중복 스킵 {dup_in_run}" + (" [dry-run, 롤백됨]" if dry_run else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--courses", type=Path, default=DEFAULT_COURSES)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    import_courses(args.courses, args.mapping, dry_run=args.dry_run)
