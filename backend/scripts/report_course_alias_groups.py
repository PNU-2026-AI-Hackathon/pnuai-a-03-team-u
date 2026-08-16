"""같은 과목인데 course_code가 갈려 있는 그룹을 찾아 보고한다 (read-only).

## 왜 필요한가

2026-08-13에 시간표 챗이 **실제로 개설된 과목을 "이번 학기 미개설"이라고 답하는** 버그가
발견됐다. 원인은 데이터 구조다:

`공학작문및발표`는 courses에 5개 행으로 들어와 있고(교과목코드가 각각 다름), 2026-2학기
분반 28개가 그 행들에 흩어져 붙어 있었다.

    id    course_code   카탈로그 semester   2026-2 개설
    1326  ZE1000043     1                  24   ← 분반 대부분
    1513  DM1100179     2                   0
    6010  ZE1000118     2                   2
    6166  ZE1000119     2                   0   ← 검색이 반환하던 행
    6503  CB1000119     2                   2

검색이 카탈로그 `semester='2'`로 후보를 거르면 분반이 가장 많은 1326이 빠지고, 살아남은
6166은 개설이 0이라 "미개설"이 된다.

## 이건 ingestion 버그가 아니다

- 같은 (course_code, 과목명, 학과, 전공) 완전 중복 행: **0건**. importer는 멱등하다.
- 코드가 갈린 건 부산대가 같은 교양 과목명에 여러 교과목코드를 발급하기 때문이다
  (ZE/DM/CB/MS/SE/BH = 개설 주체별 접두사).
- 같은 course_code가 여러 행인 경우(44개)는 교직과목(XA4xxxxx)이 학과별로 등록된
  **의도된 구조**다 (학과별 이수 처리 때문).

따라서 **행을 합치면 안 된다** — 수강신청에 필요한 교과목코드가 사라진다. 조회 시점에
형제 행을 묶어 보는 게 맞고(`timetable_chat._sibling_course_ids`), 이 스크립트는 그 대상
그룹이 늘거나 성격이 바뀌는지 감시한다.

## 사용법

    (venv) $ DATABASE_URL=... python scripts/report_course_alias_groups.py
    (venv) $ DATABASE_URL=... python scripts/report_course_alias_groups.py --fail-on-inconsistent

`--fail-on-inconsistent`는 같은 과목인데 학점·이수구분이 서로 다른 그룹이 있으면 exit 1.
데이터 적재 후 검증 단계나 CI에 걸어 쓴다.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

# `python scripts/...`로 직접 실행해도 app.core.config를 읽을 수 있게 backend/를 경로에 넣는다
# (DATABASE_URL을 env로 안 넘겨도 .env에서 집어오도록).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# 같은 과목으로 볼 기준. timetable_chat._sibling_course_ids와 반드시 같은 키를 써야 한다 —
# 한쪽만 바꾸면 조회는 묶는데 감시는 못 하거나 그 반대가 된다.
#
# 이수구분·학점까지 넣는 이유: 컴퓨터공학전공(major=36) 안에도 이산수학이 두 항목이다
# (CB1501027 1-1 전공기초 / CB2001104 2-2 전공선택). 요건이 다르므로 합치면 안 된다.
# 반대로 학과·전공을 빼면 남의 학과 분반이 섞인다(일반물리학(I)은 31개 학과에 존재).
_GROUP_KEY = "course_name, department_id, major_id, category, credits"

_QUERY = f"""
SELECT
    course_name,
    department_id,
    major_id,
    count(*)                                   AS row_count,
    count(DISTINCT course_code)                AS code_count,
    max(credits)                               AS credits,
    max(category)                              AS category,
    string_agg(course_code, ', ' ORDER BY id)  AS codes,
    string_agg(id::text, ', ' ORDER BY id)     AS ids
FROM courses
GROUP BY {_GROUP_KEY}
HAVING count(*) > 1
ORDER BY count(*) DESC, course_name
"""

# 2번째 관점: 이수구분·학점이 서로 다른 동명 과목.
#
# 위 그룹 기준에는 category/credits가 들어가 있어서 이 불일치가 잡히지 않는다 — 별도로 본다.
# 이건 "합쳐야 하는데 안 합쳐진 것"이 아니라 **원본 확인이 필요한 데이터 품질 이슈**다.
# 졸업요건 집계가 이수구분 기준이라 판정 결과가 실제로 달라진다.
# 예: 컴퓨터공학전공 이산수학이 전공기초(1-1)와 전공선택(2-2) 두 항목으로 존재.
_INCONSISTENT_QUERY = """
SELECT
    course_name, department_id, major_id,
    count(*)                                                   AS row_count,
    string_agg(DISTINCT category, ' | ')                       AS categories,
    string_agg(DISTINCT credits::text, ' | ')                  AS credits_list,
    string_agg(course_code || '(' || coalesce(category,'?') || ', '
               || coalesce(year,'?') || '-' || coalesce(semester,'?') || ')',
               ', ' ORDER BY id)                               AS detail
FROM courses
GROUP BY course_name, department_id, major_id
HAVING count(DISTINCT category) > 1 OR count(DISTINCT credits) > 1
ORDER BY course_name
"""

# 각 그룹이 실제로 이번 학기 개설을 몇 개 갖고 있는지 — 흩어짐 정도를 눈으로 본다.
_OFFERING_QUERY = """
SELECT c.id, c.course_code,
       (SELECT count(*) FROM course_offerings o
         WHERE o.course_id = c.id AND o.year = :year AND o.semester = :semester) AS off_count
FROM courses c
WHERE c.course_name = :name
  AND c.department_id IS NOT DISTINCT FROM :dept
  AND c.major_id IS NOT DISTINCT FROM :major
  AND c.category IS NOT DISTINCT FROM :category
  AND c.credits IS NOT DISTINCT FROM :credits
ORDER BY c.id
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", default="2026", help="개설 분산을 확인할 학년도 (기본 2026)")
    ap.add_argument("--semester", default="2학기", help="개설 분산을 확인할 학기 (기본 2학기)")
    ap.add_argument("--fail-on-inconsistent", action="store_true",
                    help="같은 과목인데 학점·이수구분이 다른 그룹이 있으면 exit 1")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        from app.core.config import settings
        url = settings.DATABASE_URL
    engine = create_engine(url)

    inconsistent: list[str] = []
    with engine.connect() as conn:
        groups = conn.execute(text(_QUERY)).all()
        total_courses = conn.execute(text("SELECT count(*) FROM courses")).scalar()

        print(f"courses 전체 {total_courses}행 중, 같은 ({_GROUP_KEY})인데 "
              f"course_code가 갈린 그룹: {len(groups)}개\n")

        for g in groups:
            name, dept, major = g.course_name, g.department_id, g.major_id
            print(f"■ {name}  dept={dept} major={major}  행 {g.row_count}개")
            print(f"    codes: {g.codes}")

            rows = conn.execute(text(_OFFERING_QUERY), {
                "name": name, "dept": dept, "major": major,
                "category": g.category, "credits": g.credits,
                "year": args.year, "semester": args.semester,
            }).all()
            spread = [f"{r.course_code}({r.id}): {r.off_count}" for r in rows]
            total_off = sum(r.off_count for r in rows)
            with_off = sum(1 for r in rows if r.off_count)
            print(f"    {args.year} {args.semester} 개설: 총 {total_off}개 "
                  f"({with_off}/{len(rows)} 행에 분산) — {', '.join(spread)}")
            if total_off and with_off < len(rows):
                print("    → 개설이 일부 행에만 붙어 있다. 조회 시 형제 행을 함께 봐야 "
                      "'미개설' 오답이 안 난다 (timetable_chat._sibling_course_ids).")
            print()

        # --- 2번째 관점: 이수구분·학점 불일치 ---
        rows = conn.execute(text(_INCONSISTENT_QUERY)).all()
        print("=" * 78)
        print(f"같은 (과목명, 학과, 전공)인데 이수구분·학점이 서로 다른 그룹: {len(rows)}개")
        if rows:
            print("→ 이건 '합쳐야 하는데 안 합쳐진 것'이 아니라 **원본 확인이 필요한 항목**이다.")
            print("  졸업요건 집계가 이수구분 기준이라 판정 결과가 실제로 달라진다.")
            print("  교육과정 개편으로 학년·학기가 옮겨간 경우일 수도 있으니, 수강편람/학과")
            print("  문서로 확인하기 전에는 근거 없이 고치지 마라.\n")
        for r in rows:
            inconsistent.append(f"{r.course_name} (dept={r.department_id}, "
                                f"major={r.major_id}): {r.categories}")
            print(f"■ {r.course_name}  dept={r.department_id} major={r.major_id}  행 {r.row_count}개")
            print(f"    이수구분: {r.categories}   학점: {r.credits_list}")
            print(f"    {r.detail}")
            print()

    if inconsistent and args.fail_on_inconsistent:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
