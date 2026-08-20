"""컴퓨터공학전공 과목명 접미사 유실 교정 (courses.course_name).

배경 (2026-08-20 조사):
  2026-07-23 PR #92("PNU 로그인 크롤러 개편…", 8c76dd3)에서 컴퓨터공학전공 정규
  커리큘럼 58행을 `seeds/ais_courses_2026.csv`에 **손으로 append**했다. 그때 AIS 원문
  (`raw_data/draft_curriculum_table_2026-07-06.csv`,
  `raw_data/manual_staging/.../U04080100419__.../{00_sources_discovered,03_reviewed_rules}`)에는
  있던 로마숫자 접미사가 4행에서 빠졌고, 3행에는 원문에 없는 공백이 끼었다.

  적재 스크립트(`import_courses_from_ais.py`)의 정규화는 NFC + 공백 축약뿐이라 괄호를
  지우지 않는다 — 즉 코드 버그가 아니라 시드 CSV의 입력 오류다. 그 CSV로 2026-07-22
  15:11에 적재된 courses 4행이 서로 다른 과목인데 같은 이름을 갖게 됐다.

  실제 피해: `timetable_chat._sibling_course_ids`는 (과목명·학과·전공·이수구분·학점)이
  같은 행을 "같은 과목의 형제"로 묶어 개설(course_offerings)을 합친다. 일반물리학 두 행은
  이 다섯 값이 전부 같아져서 (I)의 분반과 (II)의 분반이 한 덩어리로 보였다
  (CB1501005=0개, CB1501009=2개 / 2026-2학기). 이수 완료 제외는 과목명 정규화 비교라
  전적 원문 "일반물리학(I)"이 DB의 "일반물리학"과 안 맞아 제외도 어긋난다.

동작:
  course_code로 찾아 `현재 이름이 정확히 잘못된 값일 때만` 원문 이름으로 교정한다.
  이미 교정됐거나 예상 밖 값이면 건드리지 않는다 → 재실행 안전(멱등).
  교정을 반영한 세션 상태로 `seeds/ais_courses_2026.csv`와 전체 대조 리포트를 낸다(0건이어야 정상).

사용법:
    (venv) $ DATABASE_URL=... python scripts/fix_truncated_course_names_2026_08_20.py --dry-run
    (venv) $ DATABASE_URL=... python scripts/fix_truncated_course_names_2026_08_20.py --commit
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import unicodedata
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.domains.courses.models import Course  # noqa: E402
# FK 대상 모델을 import해두지 않으면 SQLAlchemy가 매핑 시점에 NoReferencedTableError로 뻗는다
# (courses.department_id → departments.id).
from app.domains.academics.models import Department, Major  # noqa: E402,F401

SEED_CSV = Path(__file__).resolve().parent.parent / "seeds" / "ais_courses_2026.csv"

# (course_code, 잘못 적재된 이름, AIS 원문 이름).
# 앞 4건이 접미사 유실(서로 다른 과목이 동명이 된 진짜 사고), 뒤 3건은 같은 수기 append에서
# 끼어든 공백. 둘 다 원문과 다르므로 같이 되돌린다.
CORRECTIONS: list[tuple[str, str, str]] = [
    ("CB1501027", "이산수학", "이산수학(I)"),
    ("CB2001104", "이산수학", "이산수학(II)"),
    ("CB1501005", "일반물리학", "일반물리학(I)"),
    ("CB1501009", "일반물리학", "일반물리학(II)"),
    ("CB1501014", "C++ 프로그래밍과실습", "C++프로그래밍과실습"),
    ("CB2001103", "AI 프로그래밍", "AI프로그래밍"),
    ("CB2001611", "지능형 IoT 플랫폼", "지능형IoT플랫폼"),
]


def _norm(s: str | None) -> str:
    return " ".join(unicodedata.normalize("NFC", s or "").split())


def _seed_names() -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}
    with SEED_CSV.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            code = (row.get("course_code") or "").strip()
            name = _norm(row.get("course_name"))
            if code and name:
                names.setdefault(code, set()).add(name)
    return names


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    engine = create_engine(os.environ["DATABASE_URL"])
    fixed = already = unexpected = missing = 0
    with Session(engine) as db:
        for code, wrong, correct in CORRECTIONS:
            rows = db.scalars(select(Course).where(Course.course_code == code)).all()
            if not rows:
                print(f"[missing] {code}: courses에 없음 — 건너뜀")
                missing += 1
                continue
            for row in rows:
                current = _norm(row.course_name)
                if current == _norm(correct):
                    print(f"[ok] {code} (id={row.id}): 이미 {correct!r}")
                    already += 1
                elif current == _norm(wrong):
                    print(f"[fix] {code} (id={row.id}): {current!r} → {correct!r}")
                    row.course_name = correct
                    fixed += 1
                else:
                    print(f"[skip] {code} (id={row.id}): 예상 밖 값 {current!r} — 사람 확인 필요")
                    unexpected += 1

        print(f"\n교정 {fixed} / 이미 정상 {already} / 예상 밖 {unexpected} / 없음 {missing}")

        # 교정을 반영한 세션 상태로 시드 CSV와 전체 대조. 0건이어야 정상이다.
        seed = _seed_names()
        drift = []
        for row in db.scalars(select(Course).where(Course.course_code.is_not(None))).all():
            expected = seed.get((row.course_code or "").strip())
            if expected and _norm(row.course_name) not in expected:
                drift.append((row.id, row.course_code, row.course_name, sorted(expected)))
        print(f"\n[audit] 교정 후 seeds/ais_courses_2026.csv와 이름이 다른 courses 행: {len(drift)}건 (0이어야 정상)")
        for d in drift[:20]:
            print("   -", d)

        if args.commit:
            db.commit()
            print("\n✅ [commit] 반영 완료")
        else:
            db.rollback()
            print("\n🔍 [dry-run] 실제 변경 안 함. 반영하려면 --commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
