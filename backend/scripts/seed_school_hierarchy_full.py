"""공유 DB의 학사 계층 스냅샷(school_hierarchy_full.json)을 통째로 적재한다.

왜 CSV 시드(seed_school_hierarchy.py)와 별개로 두나: CSV 매핑표는 2026-07-08
수집 대상 109개 학과 기준이라, 이후 별표 2 동기화(#118, #123)로 추가된 학과
9개와 세부전공·트랙류가 빠져 있다. 새 PC에서 클론 후 로컬 DB로 시작하면
학과 자동완성이 반쪽이 되고, 최악의 경우(시드 생략) 회원가입 get-or-create가
만든 학과 한두 개만 남는다 — "자동완성에 의생명융합공학부만 나온다" 증상의
정체가 이것이다.

이 스크립트는 공유 Supabase에서 내보낸 전체 스냅샷(학과 121·전공 62)을
get-or-create로 적재한다. 재실행해도 중복이 생기지 않고(idempotent), 공유
DB를 향해 실행해도 이미 있는 행은 그대로 지나간다.

스냅샷 갱신: 공유 DB에 학과·전공이 추가되면 아래를 다시 실행해 커밋한다.
  python -m scripts.seed_school_hierarchy_full --export

실행: python -m scripts.seed_school_hierarchy_full [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

from sqlalchemy import text

from app.core.db import SessionLocal
from app.domains.academics.hierarchy import resolve_hierarchy
from app.domains.academics.models import College, Department, Major, School

FIXTURE = Path(__file__).resolve().parent.parent / "seeds" / "school_hierarchy_full.json"


def normalize(name: str) -> str:
    return " ".join(unicodedata.normalize("NFC", name).split())


def seed_from_fixture(dry_run: bool = False) -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        before = {
            m.__tablename__: db.query(m).count() for m in (School, College, Department, Major)
        }
        count = 0
        for school in data["schools"]:
            for college in school["colleges"]:
                for dept in college["departments"]:
                    majors = dept["majors"] or [None]
                    for major in majors:
                        resolve_hierarchy(
                            db,
                            school_name=normalize(school["name"]),
                            college_name=normalize(college["name"]),
                            department_name=normalize(dept["name"]),
                            major_name=normalize(major) if major else None,
                        )
                        count += 1
        after = {
            m.__tablename__: db.query(m).count() for m in (School, College, Department, Major)
        }
        if dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    print(f"스냅샷 {count}행 적재 시도")
    for table in before:
        print(f"{table}: {before[table]} -> {after[table]} (+{after[table] - before[table]})"
              + (" [dry-run, 롤백됨]" if dry_run else ""))


def export_snapshot() -> None:
    """현재 DB의 계층을 스냅샷 JSON으로 다시 내보낸다 (팀 공유 DB에서 실행할 것).

    한글이 전혀 없는 이름은 테스트 쓰레기(회원가입 자유 입력으로 생긴 행)로
    보고 제외한다 — 실제 부산대 편제에 로마자 단독 표기 학과는 없다.
    """
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            select s.name school, col.name college, d.name dept, m.name major
            from departments d
            join colleges col on col.id = d.college_id
            join schools s on s.id = col.school_id
            left join majors m on m.department_id = d.id
            order by s.name, col.name, d.name, m.name
        """)).all()
    finally:
        db.close()

    schools: dict = {}
    for school, college, dept, major in rows:
        if not re.search(r"[가-힣]", dept):
            continue
        depts = schools.setdefault(school, {}).setdefault(college, {})
        majors = depts.setdefault(dept, [])
        if major and re.search(r"[가-힣]", major) and major not in majors:
            majors.append(major)

    out = {"schools": [
        {"name": s, "colleges": [
            {"name": col, "departments": [
                {"name": d, "majors": ms} for d, ms in depts.items()
            ]} for col, depts in cols.items()
        ]} for s, cols in schools.items()
    ]}
    FIXTURE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    n_dept = sum(len(c["departments"]) for sc in out["schools"] for c in sc["colleges"])
    print(f"스냅샷 갱신: 학과 {n_dept}건 → {FIXTURE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--export", action="store_true", help="현재 DB → 스냅샷 JSON 갱신")
    args = parser.parse_args()
    if args.export:
        export_snapshot()
    else:
        seed_from_fixture(dry_run=args.dry_run)
