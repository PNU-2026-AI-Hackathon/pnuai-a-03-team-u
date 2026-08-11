"""부산대 학사규정 별표 2에는 있으나 DB에 없는 학과·대학 동기화.

배경 (2026-08-11 감사):
  seed_dual_and_special_2026_08_10.py 실행 시 별표 2의 학과 8건이 DB에 없어
  dual/minor 시드가 스킵됐다. AIS 위젯 조회로 실제 학과 코드 확보 후 dept 신설.

추가 대상:
  1. college '나노과학기술대학' (AIS 코드 460000) — 이미 있어야 하는데 누락
  2. 나노에너지공학과, 나노메카트로닉스공학과, 광메카트로닉스공학과, 나노메디컬공학과,
     나노시스템공정공학과, 나노정보소재공학과 (나노과학기술대학 소속)
  3. 식물생명과학과, 동물생명자원과학과 (생명자원과학대학 소속)
  4. 미래자동차융합전공 (공과대학 소속)

동기화 후:
  이 스크립트로 dept 신설만 하고, dual/minor 시드는
  seed_dual_and_special_2026_08_10.py 재실행으로 자동 반영된다 (별표 2 파서가
  dept 이름 매칭으로 upsert).

사용법:
    (venv) $ DATABASE_URL=... python scripts/sync_missing_departments_2026_08_11.py --dry-run
    (venv) $ DATABASE_URL=... python scripts/sync_missing_departments_2026_08_11.py --commit
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domains.academics.models import College, Department, School
# FK 대상
from app.domains.users.models import User  # noqa: F401


SCHOOL_NAME = "부산대학교"

# 신규 college (school 이름 · college 이름)
NEW_COLLEGES: list[str] = [
    "나노과학기술대학",
]

# 신규 학과 (college_name · dept_name)
NEW_DEPARTMENTS: list[tuple[str, str]] = [
    # 나노과학기술대학
    ("나노과학기술대학", "나노에너지공학과"),
    ("나노과학기술대학", "나노메카트로닉스공학과"),
    ("나노과학기술대학", "광메카트로닉스공학과"),
    ("나노과학기술대학", "나노메디컬공학과"),
    ("나노과학기술대학", "나노시스템공정공학과"),
    ("나노과학기술대학", "나노정보소재공학과"),
    # 생명자원과학대학 (이미 존재)
    ("생명자원과학대학", "식물생명과학과"),
    ("생명자원과학대학", "동물생명자원과학과"),
    # 공과대학 (이미 존재). 이름은 학사규정 별표 2 표기("미래자동차 융합전공", 공백)를 따라 저장한다 —
    # AIS 위젯은 공백 없이 "미래자동차융합전공"으로 뜨지만 정식 규정 표기가 우선.
    ("공과대학", "미래자동차 융합전공"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        school = db.scalars(select(School).where(School.name == SCHOOL_NAME)).first()
        if school is None:
            print(f"[abort] school '{SCHOOL_NAME}' 없음")
            return 1

        college_ids: dict[str, int] = {
            c.name: c.id for c in db.scalars(select(College).where(College.school_id == school.id)).all()
        }

        # 1. 신규 college
        col_inserted = 0
        for cname in NEW_COLLEGES:
            if cname in college_ids:
                print(f"  [college skip] '{cname}' 이미 있음 (id={college_ids[cname]})")
                continue
            c = College(school_id=school.id, name=cname)
            db.add(c)
            db.flush()  # id 필요
            college_ids[cname] = c.id
            col_inserted += 1
            print(f"  [college insert] '{cname}' → id {c.id}")

        # 2. 신규 학과
        dept_inserted = 0
        for cname, dname in NEW_DEPARTMENTS:
            cid = college_ids.get(cname)
            if cid is None:
                print(f"  [dept skip] '{dname}' — college '{cname}' 없음")
                continue
            existing = db.scalars(
                select(Department).where(Department.name == dname)
            ).first()
            if existing:
                print(f"  [dept skip] '{dname}' 이미 있음 (id={existing.id}, college={existing.college_id})")
                continue
            d = Department(college_id=cid, name=dname)
            db.add(d)
            db.flush()
            dept_inserted += 1
            print(f"  [dept insert] '{dname}' → id {d.id} (college={cid})")

        print(f"\n[summary] college 신규 {col_inserted}건 / dept 신규 {dept_inserted}건")

        if args.commit:
            db.commit()
            print("✅ [commit] 반영 완료. 다음 단계: seed_dual_and_special_2026_08_10.py 재실행.")
        else:
            db.rollback()
            print("🔍 [dry-run] 실제 변경 안 함. 반영하려면 --commit")

    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
