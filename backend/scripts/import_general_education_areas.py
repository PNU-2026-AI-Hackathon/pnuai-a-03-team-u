"""효원균형교양·효원창의교양 세부영역 매핑 → courses.general_education_area 갱신.

## 배경

`courses.category`는 "효원균형교양"/"효원창의교양"까지만 말해준다. 하지만 졸업요건
규정 제9조는 영역 단위로 요구한다(균형 6영역 중 2영역, 창의 3영역 중 2영역). 수강편람
CSV/xlsx에는 이 영역 정보가 아예 없다 — Onestop 포털 UI의 "세부구분(영역별)" 필터를
통해서만 얻을 수 있다.

## 어떻게 얻는가

포털의 세부구분 드롭다운은 공통코드 `0001_AREA_GCD`(엔드포인트
`/core/function/getCodeByEtcParam`)에서 영역 코드 9개를 받아온다. 이 코드가 바로
`courses`의 `ZFz…` 영역 placeholder 코드의 뒷부분과 일치한다(`z000091` ↔ `ZFz000091`
= "사상과역사" 등). 그리고 과목구분=3(효원균형·창의교양-교양선택) 검색에
`SCH_DETAIL=<영역코드>`를 넣으면 그 영역에 속한 과목만 필터링돼서 나온다(과목 자체
응답엔 영역 필드가 없어서, 영역별로 따로 조회해서 태깅해야 한다).

9개 영역을 전부 조회해서 course_code별로 모아보면 한 과목이 정확히 한 영역에만
속한다(2026-2학기 기준 203개 코드, 중복 없음).

## 이 스크립트가 하는 일

`{code: {name, courses: [{course_code, course_name}, ...]}}` 형태의 JSON(사전 수집
결과)을 읽어 `courses.general_education_area`를 course_code로 매칭해 갱신한다.
`ZFz…` 영역 placeholder 자체는 건드리지 않는다(그 행들은 영역명 그대로가
`course_name`이라 area 컬럼이 의미 없다).

수집 스크립트는 별도로 없다 — RSA 세션 핸드셰이크가 매번 필요해 재사용 빈도가 낮으므로,
필요할 때 `app.ingestion.crawlers.onestop_course_catalog`의 `create_session`/
`build_search_payload`/`post_course_catalog`를 조합한 일회성 코드로 수집하고 이
스크립트로 반영한다.

사용:
    ./backend/.venv/bin/python -m scripts.import_general_education_areas \
        --json /path/to/area_mapping_raw.json
    # dry-run(기본). --commit으로 반영.

**JSON 스키마**: `[{"area_code": "z000091", "area_name": "사상과역사",
"course_code": "ZF1100729", "course_name": "...", "category": "효원균형교양"}, ...]`
(영역별 조회 결과를 그대로 이어붙인 리스트. 행 단위 = 분반이라 course_code 중복 있음.)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.domains.academics.models import Department, Major  # noqa: F401 (FK 메타데이터 등록)
from app.domains.courses.models import Course


def import_mapping(path: Path, db: Session, *, commit: bool) -> dict:
    stats = Counter()
    raw_rows = json.loads(path.read_text(encoding="utf-8"))

    area_by_code: dict[str, set[str]] = defaultdict(set)
    for row in raw_rows:
        code = (row.get("course_code") or "").strip()
        area = (row.get("area_name") or "").strip()
        if not code or not area:
            continue
        area_by_code[code].add(area)

    conflicts = {code: areas for code, areas in area_by_code.items() if len(areas) > 1}
    if conflicts:
        # 한 과목이 두 영역에 동시에 걸리면 학생 대체과목/졸업요건 판단이 갈리므로
        # 자동으로 아무거나 고르지 않고 전부 스킵 + 리포트만 한다.
        stats["skipped_conflicting_area"] = len(conflicts)

    codes = [c for c in area_by_code if c not in conflicts]
    courses = db.scalars(select(Course).where(Course.course_code.in_(codes))).all()
    course_by_code = {c.course_code: c for c in courses}

    updated_samples: list[str] = []
    for code in codes:
        course = course_by_code.get(code)
        if course is None:
            stats["skipped_not_found_in_courses"] += 1
            continue
        area = next(iter(area_by_code[code]))
        if course.general_education_area == area:
            stats["skipped_already_set"] += 1
            continue
        course.general_education_area = area
        stats["updated"] += 1
        if len(updated_samples) < 15:
            updated_samples.append(f"{code}:{course.course_name}→{area}")

    if commit:
        db.commit()
    else:
        db.rollback()

    return {
        "distinct_codes_in_mapping": len(area_by_code),
        "stats": dict(stats),
        "conflicting_codes": {k: sorted(v) for k, v in conflicts.items()},
        "updated_samples": updated_samples,
        "committed": commit,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--commit", action="store_true", help="실제 반영. 기본은 dry-run(rollback).")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.json.exists():
        print(f"JSON not found: {args.json}", file=sys.stderr)
        sys.exit(1)
    db = SessionLocal()
    try:
        result = import_mapping(args.json, db, commit=args.commit)
    finally:
        db.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
