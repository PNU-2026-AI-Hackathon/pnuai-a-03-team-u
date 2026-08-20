"""교양 세부영역 placeholder 이수구분 교정 (courses.category).

배경 (2026-08-20 조사):
  교양 세부영역은 `courses`에 `ZFz` placeholder 한 행씩(department_id=NULL)으로 들어간다.
  `import_courses_from_ais.py`는 교양 행을 course_code 기준으로 **한 행만 남기고** 나머지를
  버리므로(`seen_ge`), CSV에서 **먼저 나온 행이 조용히 이긴다.**

  AIS 스냅샷(`raw_data/ais_courses_snapshot_2026.csv`, 그대로 `seeds/ais_courses_2026.csv`)에
  학과별 교육과정표 행이 학과 수만큼 반복되는데, 세 영역에서 각각 딱 1행씩 이수구분이
  어긋나 있었다:

      ZFz000098 효원브릿지       효원균형교양 58행 / 효원핵심교양 1행 (국어국문학과 311100)
      ZFz000092 사회와문화       효원균형교양 98행 / 효원핵심교양 1행 (원예생명과학과 471200)
      ZFz000110 인성과 사회봉사  효원창의교양 95행 / 효원균형교양 1행 (한국음악학과 423200)

  그 중 `ZFz000098`은 소수값 행이 CSV 앞쪽(국어국문학과, 67행)에 있어서 실제로 이겼고,
  Supabase `courses.id=57`이 `효원핵심교양`으로 들어가 있다. 나머지 둘이 다수값으로 들어간
  것은 행 순서 운이다.

원문 확인 (학과별 정책이 아니라 AIS 단일 셀 입력 오류로 판정):
  - 교육과정 편성 및 운영규정(260225) 제9조① 효원핵심교양은 **과목명으로 닫힌 목록**
    (열린사고와 표현/대학영어/인공지능과 디지털사고/고전읽기와 토론/공학작문 및 발표)이라
    "영역"이 들어갈 자리가 없다. ②③이 효원균형교양 6개·효원창의교양 3개 소영역을
    **전교 공통**으로 정한다.
  - 국어국문학과 공식 공지 「국어국문학과 졸업학점 기준(부복수포함)」(2026-04-10,
    https://bkorea.pusan.ac.kr/bbs/bkorea/224/1434362/artclView.do): 효원핵심교양 9학점 =
    대학영어2+열린사고와표현2+고전읽기와토론2+인공지능과디지털사고3. 효원브릿지(3)가 들어갈
    자리가 산술적으로 없다. 같은 공지가 효원브릿지를 **효원균형교양 소영역**으로 두되
    학과 요건 산정에서만 제외한다("효원브릿지 영역은 제외함").
  - 원예생명과학과: 교양교육원 「2026학년도 1학기 교양교과목 수강지도 지침」 p.27
    학과별 이수모형 표에 "효원균형교양 **6개 소영역** 중 최소 3개" — 사회와문화를 뺀
    5개라는 서술은 없다.
  - 한국음악학과: 교양교육원 효원창의교양 페이지(culedu.pusan.ac.kr/culedu/13961/subview.do)와
    타 학과 2026 교육과정표(관광컨벤션·미생물·통계) 모두 `인성과 사회봉사`를 효원창의교양
    3소영역에 넣는다. 한국음악학과 AIS 교양 블록은 2026 개편 반영 전 상태다
    (ZE1000453 인공지능과디지털사고가 없고 폐지된 ZE1000100/114/115가 남아 있다).

동작:
  course_code로 찾아 `현재 값이 정확히 잘못된 값일 때만` 교정한다. 이미 맞거나 예상 밖
  값이면 건드리지 않는다 → 재실행 안전(멱등). 교정 후 시드 CSV와 전체 대조 리포트를 낸다.

사용법:
    (venv) $ DATABASE_URL=... python scripts/fix_liberal_area_categories_2026_08_20.py --dry-run
    (venv) $ DATABASE_URL=... python scripts/fix_liberal_area_categories_2026_08_20.py --commit
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
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

# (course_code, 잘못 적재됐을 수 있는 값, 규정 제9조②③ 기준 정답).
# 2026-08-20 시점 Supabase 실측으로는 ZFz000098(id=57) 1건만 실제로 어긋나 있었고 나머지
# 둘은 우연히 다수값으로 들어가 있었다. 그래도 셋 다 목록에 두는 이유는, 시드 CSV를 고치기
# 전에 재적재가 한 번 더 돌면 행 순서에 따라 언제든 뒤집힐 수 있었기 때문이다.
CORRECTIONS: list[tuple[str, str, str, str]] = [
    ("ZFz000098", "효원브릿지", "효원핵심교양", "효원균형교양"),
    ("ZFz000092", "사회와문화", "효원핵심교양", "효원균형교양"),
    ("ZFz000110", "인성과 사회봉사", "효원균형교양", "효원창의교양"),
]


def _seed_categories() -> dict[str, set[str]]:
    cats: dict[str, set[str]] = {}
    with SEED_CSV.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            code = (row.get("course_code") or "").strip()
            category = (row.get("category") or "").strip()
            if code and category:
                cats.setdefault(code, set()).add(category)
    return cats


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    engine = create_engine(os.environ["DATABASE_URL"])
    fixed = already = unexpected = missing = 0
    with Session(engine) as db:
        for code, name, wrong, correct in CORRECTIONS:
            rows = db.scalars(select(Course).where(Course.course_code == code)).all()
            if not rows:
                print(f"[missing] {code} {name}: courses에 없음 — 건너뜀")
                missing += 1
                continue
            for row in rows:
                current = (row.category or "").strip()
                if current == correct:
                    print(f"[ok] {code} {name} (id={row.id}): 이미 {correct}")
                    already += 1
                elif current == wrong:
                    print(f"[fix] {code} {name} (id={row.id}): {current} → {correct}")
                    row.category = correct
                    fixed += 1
                else:
                    print(f"[skip] {code} {name} (id={row.id}): 예상 밖 값 {current!r} — 사람 확인 필요")
                    unexpected += 1

        print(f"\n교정 {fixed} / 이미 정상 {already} / 예상 밖 {unexpected} / 없음 {missing}")

        # 교정을 반영한 세션 상태로 시드 CSV와 전체 대조. ZFz 영역 행은 0건이어야 정상이다.
        seed = _seed_categories()
        drift = []
        for row in db.scalars(select(Course).where(Course.course_code.like("ZFz%"))).all():
            expected = seed.get((row.course_code or "").strip())
            if expected and (row.category or "").strip() not in expected:
                drift.append((row.id, row.course_code, row.category, sorted(expected)))
        print(f"\n[audit] 교정 후 시드 CSV와 이수구분이 다른 ZFz 행: {len(drift)}건 (0이어야 정상)")
        for d in drift:
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
