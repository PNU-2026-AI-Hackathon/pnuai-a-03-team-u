"""graduation_requirements의 중복 행을 찾아 보고한다 (read-only).

## 왜 필요한가

`(program_type, department_id, major_id, curriculum_year)`에 유니크 제약이 없다.
그래서 같은 조건의 기준학점 행이 두 개 존재할 수 있고, 실제로 있다 —
2026-08-13 기준 간호학과(dept=95) dual 2026이 2행.

판정 엔진(`graduation_progress._find_requirement`)은 예전에 `.one_or_none()`을 써서
이 학생의 졸업요건 조회가 **MultipleResultsFound로 500 에러**가 났다. 지금은 id 순으로
하나를 고르고 `warnings`에 남기지만, 어느 행을 쓰느냐에 따라 **판정 결과가 달라질 수
있으므로** 중복 자체를 정리해야 한다.

## 정리 전에 확인할 것

두 행의 기준학점이 같으면 단순 중복이라 하나를 지우면 된다. 다르면 어느 쪽이 맞는지
학과 졸업요건 원문으로 확인해야 한다 — 근거 없이 지우면 졸업 판정이 틀어진다.
이 스크립트는 **보고만 하고 아무것도 지우지 않는다.**

## 사용법

    (venv) $ python scripts/report_duplicate_requirements.py
    (venv) $ python scripts/report_duplicate_requirements.py --fail-on-duplicate
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# 판정 엔진이 행을 고르는 기준과 같은 키여야 한다 (_find_requirement 참고).
_QUERY = """
SELECT
    g.program_type,
    g.department_id,
    d.name                                          AS department_name,
    g.major_id,
    m.name                                          AS major_name,
    g.curriculum_year,
    count(*)                                        AS row_count,
    string_agg(g.id::text, ', ' ORDER BY g.id)      AS ids,
    count(DISTINCT g.required_total_credits)        AS total_variants,
    string_agg(DISTINCT coalesce(g.required_total_credits::text, 'NULL'), ' | ') AS totals
FROM graduation_requirements g
LEFT JOIN departments d ON d.id = g.department_id
LEFT JOIN majors m      ON m.id = g.major_id
GROUP BY g.program_type, g.department_id, d.name, g.major_id, m.name, g.curriculum_year
HAVING count(*) > 1
ORDER BY count(*) DESC, d.name
"""

# 행별 상세 — 기준학점이 실제로 다른지 눈으로 본다.
_DETAIL = """
SELECT id, required_total_credits, required_major_required, required_major_elective,
       required_general_required, required_general_elective,
       (special_rules IS NOT NULL) AS has_special_rules,
       md5(coalesce(special_rules::text, '')) AS rules_hash,
       left(coalesce(special_rules::text, ''), 90) AS rules_preview
FROM graduation_requirements
WHERE program_type = :ptype
  AND department_id IS NOT DISTINCT FROM :dept
  AND major_id IS NOT DISTINCT FROM :major
  AND curriculum_year IS NOT DISTINCT FROM :cyear
ORDER BY id
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fail-on-duplicate", action="store_true",
                    help="중복이 하나라도 있으면 exit 1 (적재 후 검증·CI용)")
    ap.add_argument("--check-coverage", action="store_true",
                    help="요건을 못 찾는 활성 학적도 함께 보고한다 (판정 불가 학생 감지)")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        from app.core.config import settings
        url = settings.DATABASE_URL

    with create_engine(url).connect() as conn:
        groups = conn.execute(text(_QUERY)).all()
        total = conn.execute(text("SELECT count(*) FROM graduation_requirements")).scalar()
        print(f"graduation_requirements {total}행 중 중복 조합: {len(groups)}개\n")

        for g in groups:
            scope = g.major_name or g.department_name or f"dept={g.department_id}"
            # count(DISTINCT NULL)은 0이라 "전부 NULL"과 "값이 두 종류"를 구분해야 한다.
            same = "⚠️ 기준학점이 서로 다름" if g.total_variants > 1 else "기준학점 동일"
            print(f"■ {scope} / {g.program_type} / {g.curriculum_year}  "
                  f"행 {g.row_count}개 (id: {g.ids})  — {same}")
            if g.total_variants > 1:
                print(f"    졸업기준학점: {g.totals}")
            rows = conn.execute(text(_DETAIL), {
                "ptype": g.program_type, "dept": g.department_id,
                "major": g.major_id, "cyear": g.curriculum_year,
            }).all()
            for r in rows:
                print(f"    id={r.id}  총={r.required_total_credits} 전필={r.required_major_required} "
                      f"전선={r.required_major_elective} 교필={r.required_general_required} "
                      f"교선={r.required_general_elective} special_rules={r.has_special_rules}")
                if r.has_special_rules:
                    print(f"           rules: {r.rules_preview}...")
            if len({r.rules_hash for r in rows}) > 1:
                print("    ⚠️ special_rules 내용이 서로 다르다 — 어느 쪽이 맞는지 원문 확인 필수.")
            print(f"    → 판정 엔진은 id={rows[0].id}를 쓴다 (id 오름차순 첫 행).")
            print()

        if groups:
            print("=" * 72)
            print("정리 방법: 두 행의 기준학점이 같으면 하나를 지우면 된다. 다르면 학과 졸업요건")
            print("원문으로 어느 쪽이 맞는지 확인한 뒤 정리한다 — 근거 없이 지우면 졸업 판정이")
            print("틀어진다. 정리 후 유니크 제약을 걸어 재발을 막는 것이 근본 해결이다:")
            print("  (program_type, department_id, major_id, curriculum_year)")

        if args.check_coverage:
            _report_coverage_gaps(conn)

    return 1 if (groups and args.fail_on_duplicate) else 0


# 요건을 전공 단위로도 학과 단위로도 못 찾는 활성 학적. 이 학생들은 졸업요건 화면에
# "기준학점 데이터가 없어 계산할 수 없음"만 보게 된다 — 중복만큼이나 실사용에 직접 영향이
# 있어서 같이 본다. `_find_requirement`의 탐색 순서(전공 → 학과)를 그대로 재현한다.
_COVERAGE_GAPS = """
SELECT d.name AS dept, m.name AS major, uap.program_type, uap.curriculum_year
FROM user_academic_programs uap
JOIN departments d ON d.id = uap.department_id
LEFT JOIN majors m ON m.id = uap.major_id
WHERE uap.status = 'active'
  AND NOT EXISTS (
        SELECT 1 FROM graduation_requirements g
        WHERE g.program_type = uap.program_type
          AND (   (uap.major_id IS NOT NULL AND g.major_id = uap.major_id)
               OR (g.department_id = uap.department_id AND g.major_id IS NULL)))
ORDER BY d.name, uap.program_type
"""


def _report_coverage_gaps(conn) -> None:
    rows = conn.execute(text(_COVERAGE_GAPS)).all()
    print("=" * 72)
    print(f"요건을 못 찾는 활성 학적: {len(rows)}건")
    if not rows:
        print("  없음 — 모든 활성 학적이 전공 단위 또는 학과 단위 요건에 매칭된다.")
        return
    print("  이 학생들은 졸업요건 화면에서 '기준학점 데이터가 없어 계산할 수 없음'만 본다.")
    print("  전공 단위 요건을 등록하거나, 학과 전체에 공통 적용이면 major_id=NULL 행을 추가한다.\n")
    for r in rows:
        scope = f"{r.dept} / {r.major}" if r.major else r.dept
        print(f"  - {scope} / {r.program_type} / {r.curriculum_year}")


if __name__ == "__main__":
    sys.exit(main())
