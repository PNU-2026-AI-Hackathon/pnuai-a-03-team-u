"""수강편람 CSV의 전공선택·전공필수·전공기초·일반선택 실제 강좌 → courses 시드.

## 배경

`scripts/seed_general_education_courses_from_offerings.py`가 효원균형/창의교양
갭을 메운 것과 같은 문제가 전공 계열 4개 카테고리에도 있다(2026-08-23 확인):
`import_course_offerings.py`는 `course_code`가 `courses`에 이미 있어야만
`course_offerings`를 적재하는데, 이 4개 카테고리도 최근 개설분 상당수가 `courses`에
없어서 조용히 스킵되고 있었다.

전공 계열은 교양과 달리 `department_id`가 항상 채워져 있어야 한다(현재 이 4개
카테고리 기존 행 중 `department_id IS NULL`은 0건 — 비워두면 `_major_scope_filter`가
모든 학과 검색에 이 과목을 섞어 넣는다). 그래서 CSV의 `offering_department` 값을
기존 `departments`/`majors` 이름과 **정확히 일치**하는 것만 채운다(교육과정
검토 CSV 임포터 `import_courses_from_reviewed_csv.py`와 같은 매칭 방식).

**정확 일치하지 않는 행은 넣지 않고 스킵 목록에 담는다** — 억지로 짐작해서 잘못된
department_id를 붙이면 그 과목이 엉뚱한 학과 검색 결과에 나타난다. 2026-08-23 1차
확인 결과 358건 중 106건만 정확 일치하고 나머지 252건은 세 부류였다:

1. **학사과/현장실습지원센터/창업교육센터 등 행정·지원부서 + 법학과 개설(133건,
   전부 일반선택).** 처음엔 department_id를 NULL로 둘지가 새 컨벤션 결정이라
   보류했는데, 재확인 결과 애초에 특정 학과 소속이 아니라 전교생 대상으로 열리는
   과목들이다(창의적문제해결력/진로탐색과생애설계/장기현장실습/고급한국어 등 —
   내용은 교양스러운데 PNU 원문 이수구분이 "교양선택"이 아니라 "일반선택"으로 돼
   있을 뿐, 재분류하지 않고 원문 그대로 둔다). 법학과도 포함되는 이유:
   `academic_programs_seed_2026_active_bachelor.csv`(152개 활성 학사과정 전체
   목록) 대조 결과 학부 자체가 없다(로스쿨 체제 전환, 대학원 과정만 존재) — 그런데
   이 18건이 전부 전공필수/선택이 아니라 일반선택이라, "법학과 전공생만 듣는 과목"이
   아니라 개방형 교양성 과목(생활과 법률류)으로 보고 같이 채운다. →
   **`INSTITUTION_WIDE_OFFERING_UNITS`로 department_id=NULL 채움 (2026-08-23 2차 반영).**
2. 미래모빌리티전공/클린에너지전공 등 2026 신설 융합전공 + 글로벌스터디즈
   프로그램(99건, 전공필수/선택/기초) — `departments`/`majors`는 물론
   `_collection_targets_index.csv`(151개 공식 수집 대상)와
   `academic_programs_2026_master`(2026 학과 마스터 전수)에도 이름 자체가 없다.
   정식 학사 프로그램 등록이 먼저 필요해 이번에도 스킵.
3. ~~한의학과·법학과(38건)~~ → **한의학과(20건)만 남음.** 법학과는 위 1번으로
   이동. 한의학과는 152개 활성 학사과정 목록에 없음(한의학전문대학원/일반대학원
   대학원 과정만 존재) — 확정된 공백, 액션 불필요.

2·3번은 `--skip-report`로 저장해서 다음에 이어갈 수 있게 한다.

실행:
    ./backend/.venv/bin/python -m scripts.seed_major_courses_from_offerings \
        --csv raw_data/crawled_data/onestop_course_catalog/2026_2/2026_2_course_catalog.csv \
        --skip-report raw_data/reports/major_course_gap_skipped_2026-08-23.csv
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

from app.core.db import SessionLocal
from app.domains.academics.models import Department, Major
from app.domains.courses.models import Course

TARGET_CATEGORIES = {"전공선택", "전공필수", "전공기초", "일반선택"}

# 특정 학과 소속이 아니라 전교생 대상으로 일반선택 과목을 개설하는 행정·지원부서(+ 학부
# 자체가 없는 법학과). 2026-08-23 확인: 이 17개 offering_department 값은 스킵 리포트에서
# 카테고리가 전부 "일반선택"뿐이었다(전공필수/선택 섞인 게 하나도 없음). department_id를
# NULL로 두면 균형/창의교양과 같은 방식으로 전교생 검색에 노출된다.
INSTITUTION_WIDE_OFFERING_UNITS = frozenset({
    "학사과", "현장실습지원센터", "언어교육원", "창업교육센터", "취업전략과",
    "국제협력실", "교육인증원", "지역사회기여센터", "사회과학대학", "홍보실",
    "학군단", "부산대언론사", "경제통상연구원", "AI융합교육원", "교수학습지원센터",
    "여성연구소", "법학과",
})


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
    skipped_rows: list[dict] = []

    existing_codes: set[str] = set(
        db.scalars(select(Course.course_code).where(Course.course_code.is_not(None))).all()
    )

    # 이름 → id 매핑. 같은 이름이 여러 부서/학과에 중복 시드된 경우 후보가 1개일 때만 채택한다
    # (import_courses_from_reviewed_csv.py와 달리 사람이 검토한 CSV가 아니라 원본 카탈로그를
    # 직접 읽으므로, 모호하면 첫 번째를 그냥 쓰지 않고 스킵한다 — 잘못된 학과 배정이 검토 없이
    # 들어가면 안 된다).
    dept_name_to_ids: dict[str, list[int]] = {}
    for name, did in db.execute(select(Department.name, Department.id)).all():
        dept_name_to_ids.setdefault(name, []).append(did)
    major_name_to_pairs: dict[str, list[tuple[int, int]]] = {}
    for mid, mname, did in db.execute(select(Major.id, Major.name, Major.department_id)).all():
        major_name_to_pairs.setdefault(mname, []).append((did, mid))

    def resolve(dept_field: str) -> tuple[int | None, int | None, str]:
        """(department_id, major_id, reason) — reason은 매칭 실패/모호 시 스킵 사유."""
        dept_ids = dept_name_to_ids.get(dept_field, [])
        major_pairs = major_name_to_pairs.get(dept_field, [])
        if dept_ids and major_pairs:
            return None, None, "ambiguous_dept_and_major_same_name"
        if dept_ids:
            if len(dept_ids) == 1:
                return dept_ids[0], None, ""
            return None, None, "ambiguous_department_name_duplicated"
        if major_pairs:
            if len(major_pairs) == 1:
                return major_pairs[0][0], major_pairs[0][1], ""
            return None, None, "ambiguous_major_name_duplicated"
        return None, None, "no_match"

    # CSV 안에서도 같은 course_code가 분반 수만큼 반복되므로 course_code 단위로 먼저 합친다.
    seen_in_csv: dict[str, tuple[str, str, float | None, str]] = {}
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
                dept_field = _clean(row.get("offering_department")) or ""
                seen_in_csv[course_code] = (
                    course_name, category, _to_float(row.get("credits")), dept_field,
                )

    for course_code, (course_name, category, credits, dept_field) in sorted(seen_in_csv.items()):
        if course_code in existing_codes:
            stats["skipped_existing"] += 1
            continue

        institution_wide = category == "일반선택" and dept_field in INSTITUTION_WIDE_OFFERING_UNITS
        if institution_wide:
            dept_id, major_id = None, None
        else:
            dept_id, major_id, reason = resolve(dept_field)
            if dept_id is None:
                stats[f"skipped_{reason}"] += 1
                skipped_rows.append({
                    "course_code": course_code, "course_name": course_name,
                    "category": category, "offering_department": dept_field, "reason": reason,
                })
                continue

        db.add(
            Course(
                course_code=course_code,
                course_name=course_name,
                category=category,
                credits=credits,
                department_id=dept_id,
                major_id=major_id,
                source_document=csv_path.name,
            )
        )
        existing_codes.add(course_code)
        stats["created_institution_wide" if institution_wide else "created_department_matched"] += 1
        if len(created_samples) < 15:
            created_samples.append(f"{course_code}:{course_name}({category}/{dept_field})")

    if commit:
        db.commit()
    else:
        db.rollback()

    return {
        "distinct_target_category_codes_in_csv": len(seen_in_csv),
        "stats": dict(stats),
        "created_samples": created_samples,
        "skipped_rows": skipped_rows,
        "committed": commit,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--commit", action="store_true", help="실제 반영. 기본은 dry-run(rollback).")
    parser.add_argument(
        "--skip-report", type=Path, default=None,
        help="매칭 실패/모호로 스킵한 행을 CSV로 저장 (다음 세션 백로그용).",
    )
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

    if args.skip_report and result["skipped_rows"]:
        args.skip_report.parent.mkdir(parents=True, exist_ok=True)
        with args.skip_report.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f, fieldnames=["course_code", "course_name", "category", "offering_department", "reason"],
            )
            writer.writeheader()
            writer.writerows(result["skipped_rows"])
        print(f"skip report written: {args.skip_report} ({len(result['skipped_rows'])} rows)")

    result_summary = {k: v for k, v in result.items() if k != "skipped_rows"}
    result_summary["skipped_rows_count"] = len(result["skipped_rows"])
    import json

    print(json.dumps(result_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
