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
- 적재 전 검사: 같은 단위·같은 개설 주체(교과목코드 앞 2글자)에 동명 과목이 있으면
  과목명 접미사(I/II 등) 유실로 보고 **중단**한다. 2026-07-23에 시드 CSV를 손으로
  고치다 `이산수학(I)/(II)`가 둘 다 `이산수학`이 된 사고 재발 방지
  (find_suffix_dropped_collisions). 원본이 실제 동명이면 --allow-name-collisions.

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


# 교과목코드 앞 2글자 = 개설 주체(학과/교양) 접두사. ZE/CB/DM처럼 주체가 다르면 같은
# 과목명에 다른 코드가 붙는 게 정상이다(부산대 원본 데이터의 성질).
_OWNER_PREFIX_LEN = 2


def find_suffix_dropped_collisions(rows: list[dict]) -> list[str]:
    """같은 단위·같은 개설 주체인데 과목명이 겹치는 행을 찾는다 = 접미사 유실 의심.

    왜 이 검사가 있는지: 2026-07-23 PR #92에서 컴퓨터공학전공 커리큘럼 58행을
    `seeds/ais_courses_2026.csv`에 **손으로 append**하면서 로마숫자 접미사가 4행 빠졌다
    (`이산수학(I)`/`이산수학(II)` → 둘 다 `이산수학`, `일반물리학(I)`/`(II)` → 둘 다
    `일반물리학`). 서로 다른 과목이 DB에서 같은 이름이 되면서
    `timetable_chat._sibling_course_ids`가 (과목명·학과·전공·이수구분·학점)이 같은
    일반물리학 두 행을 "같은 과목의 형제"로 묶어 (I)의 분반과 (II)의 분반을 합쳐버렸다.

    구분 기준: 같은 `ais_dept_code` 안에서 같은 과목명에 코드가 갈리는데 **개설 주체
    접두사까지 같으면** 접미사 유실이다. 접두사가 다르면(예: 약학과 401300의
    `약리학(I)` DS2002822/PD2002822) 원본 데이터의 정상 중복이므로 통과시킨다.
    """
    from collections import defaultdict

    groups: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for r in rows:
        code = (r.get("course_code") or "").strip()
        name = norm_name(r.get("course_name") or "")
        dept = (r.get("ais_dept_code") or "").strip()
        if not code or not name:
            continue
        groups[(dept, name, code[:_OWNER_PREFIX_LEN])].add(code)
    return [
        f"ais_dept_code={dept} '{name}' → {sorted(codes)} (개설 주체 {prefix} 동일)"
        for (dept, name, prefix), codes in sorted(groups.items())
        if len(codes) > 1
    ]


def load_unit_index(mapping_path: Path) -> dict[str, dict]:
    """ais_dept_code -> 매핑 행."""
    with mapping_path.open(encoding="utf-8-sig") as f:
        return {r["ais_dept_code"]: r for r in csv.DictReader(f) if r["ais_dept_code"]}


def import_courses(
    courses_csv: Path,
    mapping_path: Path,
    dry_run: bool = False,
    allow_name_collisions: bool = False,
) -> None:
    units = load_unit_index(mapping_path)
    with courses_csv.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    collisions = find_suffix_dropped_collisions(rows)
    if collisions and not allow_name_collisions:
        print("❌ 같은 단위·같은 개설 주체인데 과목명이 겹친다 — 접미사(I/II 등) 유실 의심:")
        for line in collisions:
            print("   -", line)
        print("   → AIS 원문에서 과목명을 다시 확인해 CSV를 고쳐라. 원본이 실제로 동명이면")
        print("     --allow-name-collisions 로 통과시킬 수 있다.")
        raise SystemExit(1)

    db = SessionLocal()
    created = updated = skipped_unit = dup_in_run = 0
    seen_ge: set[str] = set()
    # SessionLocal이 autoflush=False라 같은 실행 안의 add가 이후 조회에 안 보인다.
    # 같은 단위에 같은 과목코드가 두 번 나오는 경우(교직과목 권장시점 2개 등)를 여기서 걸러낸다.
    seen_unit_course: set[tuple] = set()
    # 같은 과목명·학과인데 course_code가 갈리는 케이스 (합치면 안 되지만 조회 시 주의 필요).
    alias_groups: list[str] = []
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
                # 같은 (과목명, 학과, 전공)인데 course_code만 다른 행이 이미 있으면 기록해둔다.
                # 이걸 합치면 안 된다 — 부산대가 같은 교양 과목명에 개설 주체별로 다른
                # 교과목코드를 발급하기 때문이고, 코드는 수강신청에 필요하다. 문제는 **개설
                # (course_offerings)이 이 형제 행들에 흩어져 붙는다**는 점이다. 조회가 한 행만
                # 보면 분반이 0인 행을 집어 "이번 학기 미개설"이라고 오답한다(2026-08-13 실제
                # 사고: 공학작문및발표 28개 분반이 안 보였다). 조회 측 대응은
                # timetable_chat._sibling_course_ids에 있고, 여기서는 그룹이 새로 생기는 걸
                # 적재 시점에 드러내 검토 대상으로 남긴다.
                sibling = (
                    db.query(Course)
                    .filter_by(department_id=dept_id, major_id=major_id,
                               course_name=values["course_name"])
                    .first()
                )
                if sibling is not None:
                    alias_groups.append(
                        f"{values['course_name']} (dept={dept_id}, major={major_id}): "
                        f"기존 {sibling.course_code} + 신규 {r['course_code']}"
                    )
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

    if alias_groups:
        print(f"\n⚠️  같은 과목명·학과인데 course_code가 갈린 행 {len(alias_groups)}건이 새로 생겼다.")
        for line in alias_groups[:20]:
            print("   -", line)
        if len(alias_groups) > 20:
            print(f"   ... 외 {len(alias_groups) - 20}건")
        print("   → 행을 합치지 마라 (교과목코드는 수강신청에 필요). 대신 개설이 형제 행에")
        print("     흩어지므로 적재 후 아래로 전체 현황을 확인할 것:")
        print("     python scripts/report_course_alias_groups.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--courses", type=Path, default=DEFAULT_COURSES)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--allow-name-collisions",
        action="store_true",
        help="같은 단위·같은 개설 주체에 동명 과목이 있어도 진행 (기본은 접미사 유실로 보고 중단).",
    )
    args = parser.parse_args()
    import_courses(
        args.courses,
        args.mapping,
        dry_run=args.dry_run,
        allow_name_collisions=args.allow_name_collisions,
    )
