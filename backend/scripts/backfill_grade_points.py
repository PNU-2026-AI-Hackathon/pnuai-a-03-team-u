"""이미 저장된 이수기록의 grade_point를 성적등급에서 채운다 (backfill).

## 왜 필요한가

`map_grades`가 `grade`("C0")만 저장하고 `grade_point`를 채우지 않았다(2026-08-14 수정).
그래서 운영 DB의 이수기록 87건 전부 grade는 있는데 grade_point가 NULL이었고,
`roadmap_chat._compute_retake_candidates`가 `grade_point is None`인 행을 판단 불가로
전부 제외하기 때문에 **재수강 기능이 한 번도 동작한 적이 없었다** — 감지도, 안내도,
`propose_change(is_retake=True)`도.

코드 수정만으로는 **다음 포털 동기화 전까지** 기존 사용자가 여전히 혜택을 못 본다.
이 스크립트가 그 공백을 메운다.

## 안전성

- `grade`가 있고 `grade_point`가 NULL인 행만 건드린다. 이미 값이 있으면 손대지 않는다.
- 'S'(Pass)처럼 평점이 없는 등급은 NULL로 남긴다 — 0.0으로 채우면 재수강 후보로
  잘못 잡힌다.
- 기본이 dry-run이고, 등급별 건수를 보여준다.

## 사용법

    (venv) $ python scripts/backfill_grade_points.py
    (venv) $ python scripts/backfill_grade_points.py --commit
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.academics.models import StudentCourseRecord  # noqa: E402
# student_course_records.course_id FK 해석용. 없으면 commit 시 NoReferencedTableError로
# 죽는다 — dry-run은 조회만 해서 통과해버리므로 --commit에서야 드러난다.
from app.domains.courses import models as _courses_models  # noqa: E402,F401
from app.ingestion.normalizers.pnu_normalizer import _grade_to_point  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true", help="실제로 반영한다 (기본은 dry-run)")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        from app.core.config import settings
        url = settings.DATABASE_URL

    db = sessionmaker(bind=create_engine(url))()
    try:
        rows = db.scalars(
            select(StudentCourseRecord).where(
                StudentCourseRecord.grade.is_not(None),
                StudentCourseRecord.grade != "",
                StudentCourseRecord.grade_point.is_(None),
            )
        ).all()

        filled = Counter()
        skipped = Counter()
        for r in rows:
            point = _grade_to_point(r.grade)
            if point is None:
                # 평점이 없는 등급(S/P 등). NULL로 두는 게 맞다.
                skipped[r.grade] += 1
                continue
            r.grade_point = point
            filled[r.grade] += 1

        print(f"grade는 있고 grade_point가 비어 있는 행: {len(rows)}건\n")
        print("채울 수 있는 등급:")
        for grade, n in sorted(filled.items()):
            print(f"  {grade:<4} → {_grade_to_point(grade):<4} {n}건")
        if skipped:
            print("\n평점이 없어 NULL로 두는 등급 (Pass/Fail 계열):")
            for grade, n in sorted(skipped.items()):
                print(f"  {grade:<4} {n}건")

        total = sum(filled.values())
        if args.commit:
            db.commit()
            print(f"\n반영 완료: {total}건")
        else:
            db.rollback()
            print(f"\n[dry-run] {total}건이 채워질 예정. 실제 반영하려면 --commit")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
