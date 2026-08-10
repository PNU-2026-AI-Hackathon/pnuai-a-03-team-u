"""dept 120 (전자공학과 껍데기) 정리 + user 62 학적 정정.

배경 (2026-08-10):
  회원가입 학과 자동완성에서 껍데기 학과 `전자공학과 (dept=120)`가 노출돼
  user 62가 부전공으로 이 dept에 등록됨. 부산대 공식 명칭은
  "전기전자공학부 전자공학전공" (dept=45, major=4)이 맞다.

  dept 120은 8/3에 어떤 seed 스크립트가 만들어놓고 데이터를 안 채운
  상태 — courses=0, program_courses=0, graduation_requirements=0.
  참조는 user 62의 UserAcademicProgram 1건뿐.

동작:
  1. user 62의 부전공 학적을 dept=45, major=4로 재지정 (upsert)
  2. dept 120을 삭제

사용법:
    (venv) $ DATABASE_URL=... python scripts/cleanup_dept_120_electronic_engineering.py --dry-run
    (venv) $ DATABASE_URL=... python scripts/cleanup_dept_120_electronic_engineering.py --commit
"""
from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from app.domains.academics.models import (
    Department,
    Major,
    UserAcademicProgram,
)
# FK 대상 모델을 import해두지 않으면 SQLAlchemy가 flush 시점에
# `NoReferencedTableError`로 뻗는다 (user_academic_programs.user_id → users.id).
from app.domains.users.models import User  # noqa: F401

# 이번 정리에서 참조되는 고정 ID (감사 결과에 기반). 값이 바뀌면 스크립트가
# 매치 못 찾아 no-op으로 끝나서 안전.
LEGACY_DEPT_ID = 120  # 껍데기 "전자공학과"
CORRECT_DEPT_ID = 45  # 전기전자공학부
CORRECT_MAJOR_ID = 4  # 전자공학전공


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    db_url = os.environ["DATABASE_URL"]
    engine = create_engine(db_url)
    with Session(engine) as db:
        legacy = db.get(Department, LEGACY_DEPT_ID)
        if legacy is None:
            print(f"[skip] dept {LEGACY_DEPT_ID} 이미 없음 — 이전 실행에서 정리됨")
            return 0
        print(f"[found] legacy dept: {legacy.id} {legacy.name!r}")

        correct = db.get(Department, CORRECT_DEPT_ID)
        correct_major = db.get(Major, CORRECT_MAJOR_ID)
        if correct is None or correct_major is None:
            print(f"[abort] 정정 대상 dept {CORRECT_DEPT_ID}/major {CORRECT_MAJOR_ID} 확인 실패")
            return 1
        print(f"[target] dept={correct.id} {correct.name!r}, major={correct_major.id} {correct_major.name!r}")

        # 1. legacy dept 참조 감사
        affected = db.scalars(
            select(UserAcademicProgram).where(UserAcademicProgram.department_id == LEGACY_DEPT_ID)
        ).all()
        print(f"\n[audit] legacy dept 참조: {len(affected)}건")
        for p in affected:
            print(
                f"  user_academic_programs id={p.id} user={p.user_id} "
                f"program_type={p.program_type} major={p.major_id} status={p.status}"
            )

        # 2. 각 참조를 correct dept/major로 재지정
        for p in affected:
            # 같은 유저가 이미 (correct_dept, correct_major, program_type) 로 등록돼 있으면
            # 중복이 되므로 upsert 방식으로 처리한다.
            dup = db.scalars(
                select(UserAcademicProgram).where(
                    UserAcademicProgram.user_id == p.user_id,
                    UserAcademicProgram.department_id == CORRECT_DEPT_ID,
                    UserAcademicProgram.major_id == CORRECT_MAJOR_ID,
                    UserAcademicProgram.program_type == p.program_type,
                )
            ).first()
            if dup is not None:
                print(f"  → user {p.user_id} 중복(id={dup.id}) 있음 → legacy row(id={p.id}) 삭제")
                db.delete(p)
            else:
                print(f"  → user {p.user_id} row id={p.id}: dept {LEGACY_DEPT_ID}→{CORRECT_DEPT_ID}, major NULL→{CORRECT_MAJOR_ID}")
                p.department_id = CORRECT_DEPT_ID
                p.major_id = CORRECT_MAJOR_ID

        # 3. 다른 테이블 참조 재확인 (안전장치)
        for tbl in ("graduation_requirements", "program_courses", "courses", "majors"):
            from sqlalchemy import text
            n = db.scalar(text(f"SELECT COUNT(*) FROM {tbl} WHERE department_id = :did"), {"did": LEGACY_DEPT_ID})
            if n:
                print(f"[abort] {tbl}에 legacy dept 참조 {n}건 남음 — 예상외 상태. 사람 확인 필요.")
                db.rollback()
                return 2

        # 4. legacy dept 삭제
        print(f"\n[delete] dept {LEGACY_DEPT_ID} 삭제")
        db.delete(legacy)

        if args.commit:
            db.commit()
            print("\n✅ [commit] 반영 완료")
        else:
            db.rollback()
            print("\n🔍 [dry-run] 실제 변경 안 함. 반영하려면 --commit")

    return 0


if __name__ == "__main__":
    sys.exit(main())
