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
- 적재 전 검사 2: 같은 교양 course_code에 이수구분이 두 가지 이상이면 **중단**한다.
  교양 행은 코드 기준 한 행으로 접히므로 그냥 두면 CSV에서 먼저 나온 행이 조용히 이긴다.
  2026-08-20에 `ZFz000098 효원브릿지`가 그렇게 `효원핵심교양`으로 들어갔다
  (find_general_education_category_conflicts). 원본이 실제로 갈려 있으면
  --general-education-majority-category 로 다수값을 써서 진행할 수 있다.

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
# 규정 제11조⑪ — 기초교양은 과목의 성질이 아니라 학과가 효원균형/창의 과목에 덧씌우는 지정.
# 같은 과목이 학과에 따라 기초교양이기도 효원균형교양이기도 한 것은 원본이 맞다.
BASE_LIBERAL_ARTS_CATEGORY = "기초교양"


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


def find_general_education_category_conflicts(rows: list[dict]) -> list[dict]:
    """교양 과목 하나(course_code)에 이수구분이 두 가지 이상이면 찾아낸다.

    왜 이 검사가 있는지: 교양 행은 아래 적재 루프에서 `seen_ge`로 **course_code 기준 한 행만
    남기고** 나머지를 버린다(전학교 공통이므로 department_id=NULL 한 행). 그래서 같은 코드에
    이수구분이 갈려 있으면 **CSV에서 먼저 나온 행이 조용히 이긴다** — 어느 학과 행이 먼저
    나오느냐라는 정렬 순서가 DB 값을 정하는 셈이다.

    2026-08-20에 실제로 그렇게 됐다. `seeds/ais_courses_2026.csv`(AIS 스냅샷 그대로)에서
    교양 세부영역 placeholder 3개가 학과별로 1행씩 어긋나 있었다:

        ZFz000098 효원브릿지        효원균형교양 58행 / 효원핵심교양 1행(국어국문학과)
        ZFz000092 사회와문화        효원균형교양 98행 / 효원핵심교양 1행(원예생명과학과)
        ZFz000110 인성과 사회봉사   효원창의교양 95행 / 효원균형교양 1행(한국음악학과)

    이 중 `ZFz000098`은 소수값 행이 CSV에서 먼저 나오는 바람에(국어국문학과가 앞쪽) DB에
    `효원핵심교양`으로 들어갔다. 나머지 둘이 다수값으로 들어간 건 순전히 행 순서 운이다.
    교양 영역 판정이 이수구분으로 갈라지므로(`효원균형교양` 6영역 / `효원창의교양` 3영역),
    한 행이 어긋나면 그 영역이 통째로 엉뚱한 그룹에서 집계된다.

    되돌아보면 규정이 답을 이미 갖고 있다 — 교육과정 편성·운영규정 제9조는
    ①에서 효원핵심교양을 **과목명으로 열거**하고(열린사고와 표현/대학영어/인공지능과
    디지털사고/고전읽기와 토론/공학작문 및 발표), ②③에서 효원균형교양 6개·효원창의교양
    3개 소영역을 **전교 공통으로** 정한다. 학과가 고르는 것은 "어느 영역을 요건에 넣을까"지
    "그 영역이 어느 그룹인가"가 아니다. 그래도 이 검사는 규정을 코드에 박지 않는다 —
    다수결/소수결을 사람에게 보여주고 판단을 받는다.

    **`기초교양`은 예외다.** 같은 규정 제11조⑪이 "기초교양 교과목은 … 다른 학과에서 편성한
    효원균형교양 및 효원창의교양 교과목 중 전공과 연계하여 6학점 범위 안에서 편성할 수 있다"
    라고 정한다 — 즉 `기초교양`은 과목의 성질이 아니라 **학과가 특정 과목에 덧씌우는 지정**
    이다. 그래서 `ZF1200703 브릿지기초물리(I)`가 어느 학과에는 `기초교양`, 어느 학과에는
    `효원균형교양`으로 나오는 건 원본이 맞다. 이건 `kind="기초교양_overlay"`로 분류해서
    **중단시키지 않고 경고만** 한다 (전학교 공통 한 행 모델로는 학과별 지정을 표현할 수
    없다는 한계는 그대로 남는다).
    """
    from collections import Counter, defaultdict

    by_code: dict[str, Counter] = defaultdict(Counter)
    names: dict[str, str] = {}
    units: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in rows:
        category = (r.get("category") or "").strip()
        code = (r.get("course_code") or "").strip()
        if not code or GENERAL_ED_KEYWORD not in category:
            continue
        by_code[code][category] += 1
        names.setdefault(code, norm_name(r.get("course_name") or ""))
        units[(code, category)].append(norm_name(r.get("unit_name") or r.get("ais_dept_code") or ""))

    conflicts = []
    for code, counter in sorted(by_code.items()):
        if len(counter) < 2:
            continue
        ranked = counter.most_common()
        # 기초교양을 빼고도 이수구분이 갈리면 그건 과목 자체의 그룹이 어긋난 것 = 사고.
        intrinsic = {c for c in counter if c != BASE_LIBERAL_ARTS_CATEGORY}
        kind = "group_conflict" if len(intrinsic) > 1 else "기초교양_overlay"
        conflicts.append(
            {
                "course_code": code,
                "course_name": names[code],
                "counts": dict(ranked),
                "kind": kind,
                "majority": ranked[0][0],
                # 다수값이 동점이면 majority를 믿을 수 없다 — 표시만 하고 사람이 정한다.
                "tied": len(ranked) > 1 and ranked[0][1] == ranked[1][1],
                "minority_units": {
                    category: units[(code, category)] for category, _ in ranked[1:]
                },
            }
        )
    return conflicts


def format_general_education_category_conflicts(conflicts: list[dict]) -> list[str]:
    lines = []
    for c in conflicts:
        counts = " / ".join(f"{k} {v}행" for k, v in c["counts"].items())
        lines.append(f"{c['course_code']} {c['course_name']}: {counts}")
        for category, unit_names in c["minority_units"].items():
            shown = ", ".join(unit_names[:5]) + ("…" if len(unit_names) > 5 else "")
            lines.append(f"      소수 '{category}' 행의 학과: {shown}")
        if c["tied"]:
            lines.append("      ⚠️ 최다값이 동점이다 — 다수결로 정할 수 없다.")
    return lines


def load_unit_index(mapping_path: Path) -> dict[str, dict]:
    """ais_dept_code -> 매핑 행."""
    with mapping_path.open(encoding="utf-8-sig") as f:
        return {r["ais_dept_code"]: r for r in csv.DictReader(f) if r["ais_dept_code"]}


def import_courses(
    courses_csv: Path,
    mapping_path: Path,
    dry_run: bool = False,
    allow_name_collisions: bool = False,
    use_majority_category: bool = False,
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

    # 교양 행은 course_code 기준 한 행으로 접히므로 이수구분이 갈리면 CSV 행 순서가 DB 값을
    # 정해버린다. 조용히 이기게 두지 않는다 — 기본은 중단, --general-education-majority-category
    # 를 주면 다수값으로 통일하고 무엇을 골랐는지 찍는다.
    all_ge_conflicts = find_general_education_category_conflicts(rows)
    ge_conflicts = [c for c in all_ge_conflicts if c["kind"] == "group_conflict"]
    ge_overlays = [c for c in all_ge_conflicts if c["kind"] != "group_conflict"]
    ge_category_override: dict[str, str] = {}
    if ge_overlays:
        # 원본이 맞는 경우다(규정 제11조⑪). 중단시키지 않되 조용히 넘어가지도 않는다 —
        # 지금 모델은 학과별 기초교양 지정을 표현하지 못하고 한 행만 남긴다.
        print(f"⚠️  학과가 기초교양으로 지정한 교양 과목 {len(ge_overlays)}건 — 원본이 맞다(규정 제11조⑪).")
        for line in format_general_education_category_conflicts(ge_overlays):
            print("   -", line)
        print("   → courses는 교양을 course_code당 한 행만 두므로 학과별 기초교양 지정은")
        print("     표현되지 않는다. CSV에서 먼저 나온 행의 이수구분이 남는다.")
    if ge_conflicts:
        tied = [c for c in ge_conflicts if c["tied"]]
        print("❌ 같은 교양 course_code에 이수구분이 두 가지 이상이다 — 먼저 나온 행이 조용히 이긴다:")
        for line in format_general_education_category_conflicts(ge_conflicts):
            print("   -", line)
        if not use_majority_category or tied:
            print("   → AIS 원문/학과 교육과정표에서 어느 쪽이 맞는지 확인해 CSV를 고쳐라.")
            print("     (교육과정 편성·운영규정 제9조: 효원핵심교양은 과목명 열거,")
            print("      효원균형교양 6개·효원창의교양 3개 소영역은 전교 공통이다)")
            if not tied:
                print("     원본이 실제로 그렇다면 --general-education-majority-category 로")
                print("     다수값을 써서 진행할 수 있다.")
            raise SystemExit(1)
        ge_category_override = {c["course_code"]: c["majority"] for c in ge_conflicts}
        print("   → --general-education-majority-category: 위 코드는 다수값으로 적재한다.")

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
                category=(
                    ge_category_override.get(r["course_code"], r["category"].strip())
                    if is_ge
                    else r["category"].strip()
                ),
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
    parser.add_argument(
        "--general-education-majority-category",
        action="store_true",
        help=(
            "같은 교양 course_code에 이수구분이 갈려도 다수값으로 통일해서 진행 "
            "(기본은 중단). 동점이면 이 옵션을 줘도 중단한다."
        ),
    )
    args = parser.parse_args()
    import_courses(
        args.courses,
        args.mapping,
        dry_run=args.dry_run,
        allow_name_collisions=args.allow_name_collisions,
        use_majority_category=args.general_education_majority_category,
    )
