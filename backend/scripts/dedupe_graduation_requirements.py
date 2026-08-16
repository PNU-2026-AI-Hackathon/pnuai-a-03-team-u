"""graduation_requirements의 완전 중복 행을 정리한다.

## 배경

`(program_type, department_id, major_id, curriculum_year)`에 유니크 제약이 없어서 같은
조건의 기준학점 행이 여러 개 존재할 수 있다. 판정 엔진(`_find_requirement`)은 예전에
`.one_or_none()`을 써서 이런 학생의 졸업요건 조회가 **500 에러**로 죽었다
(2026-08-13 발견, 간호학과 dual 2026). 지금은 id 오름차순 첫 행을 쓰고 경고를 남긴다.

## 이 스크립트가 지우는 것 / 안 지우는 것

**지운다**: 그룹 안의 모든 행이 `id`·`created_at`·`updated_at`을 뺀 **모든 컬럼이 동일**한
경우에만. 이건 같은 데이터가 두 번 적재된 것이라 하나만 남겨도 판정 결과가 바뀌지 않는다.

**안 지운다**: 기준학점이나 `special_rules`가 조금이라도 다르면 건너뛰고 보고만 한다.
어느 쪽이 맞는지는 학과 졸업요건 원문을 봐야 알 수 있고, 근거 없이 지우면 졸업 판정이
틀어진다.

**남기는 행**: 그룹에서 **가장 작은 id**. 판정 엔진이 이미 그 행을 쓰고 있어서 정리 후에도
동작이 그대로다.

## 사용법

    (venv) $ python scripts/dedupe_graduation_requirements.py            # dry-run (기본)
    (venv) $ python scripts/dedupe_graduation_requirements.py --commit

dry-run은 지울 행의 전체 내용을 출력한다 — 실행 로그가 곧 백업이 되도록.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# 동일성 판정에서 제외할 컬럼. 행마다 당연히 다르고, 판정 결과와 무관하다.
_IDENTITY_COLUMNS = {"id", "created_at", "updated_at"}

_GROUPS = """
SELECT program_type, department_id, major_id, curriculum_year,
       array_agg(id ORDER BY id) AS ids
FROM graduation_requirements
GROUP BY program_type, department_id, major_id, curriculum_year
HAVING count(*) > 1
ORDER BY department_id, program_type
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true",
                    help="실제로 삭제한다. 없으면 dry-run(롤백).")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        from app.core.config import settings
        url = settings.DATABASE_URL

    engine = create_engine(url)
    with engine.begin() as conn:
        columns = [r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='graduation_requirements' ORDER BY ordinal_position"
        )).all()]
        comparable = [c for c in columns if c not in _IDENTITY_COLUMNS]

        groups = conn.execute(text(_GROUPS)).all()
        print(f"중복 그룹 {len(groups)}개\n")

        deleted_total = 0
        skipped: list[str] = []

        for g in groups:
            ids = list(g.ids)
            rows = conn.execute(
                text(f"SELECT {', '.join(columns)} FROM graduation_requirements "
                     f"WHERE id = ANY(:ids) ORDER BY id"),
                {"ids": ids},
            ).mappings().all()

            dept_name = conn.execute(
                text("SELECT name FROM departments WHERE id = :d"), {"d": g.department_id}
            ).scalar() or f"dept={g.department_id}"
            label = f"{dept_name} / {g.program_type} / {g.curriculum_year}"

            keep, extras = rows[0], rows[1:]
            differing = [
                col for col in comparable
                if any(r[col] != keep[col] for r in extras)
            ]
            if differing:
                skipped.append(f"{label} (ids={ids}) — 다른 컬럼: {differing}")
                print(f"⏭  {label}  ids={ids}")
                print(f"    내용이 다르다 ({', '.join(differing)}) — 원문 확인 없이는 못 지운다. 건너뜀.\n")
                continue

            print(f"■ {label}  ids={ids}")
            print(f"    남길 행 id={keep['id']} (판정 엔진이 이미 쓰는 행)")
            for r in extras:
                # 실행 로그가 곧 백업이 되도록 지울 행의 전체 내용을 남긴다.
                print(f"    삭제 대상 id={r['id']}: "
                      + ", ".join(f"{c}={r[c]!r}" for c in comparable if r[c] is not None))
            extra_ids = [r["id"] for r in extras]
            if args.commit:
                conn.execute(
                    text("DELETE FROM graduation_requirements WHERE id = ANY(:ids)"),
                    {"ids": extra_ids},
                )
            deleted_total += len(extra_ids)
            print()

        mode = "삭제 완료" if args.commit else "삭제 예정 (dry-run — 반영 안 됨)"
        print("=" * 70)
        print(f"{mode}: {deleted_total}행")
        if skipped:
            print(f"\n건너뛴 그룹 {len(skipped)}개 — 사람이 판단해야 한다:")
            for s in skipped:
                print("  -", s)
        if not args.commit:
            print("\n실제로 반영하려면 --commit 을 붙여 다시 실행한다.")
            # dry-run이면 트랜잭션을 되돌린다.
            conn.rollback()

    return 0


if __name__ == "__main__":
    sys.exit(main())
