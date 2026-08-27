"""정보컴퓨터공학부 3개 전공 연계전공 이수판정을 확인하던 중 발견한 문제를 정리한다.

배경: `backfill_sw_convergence_rules.py`는 `program_courses`를 (department_id,
major_id, curriculum_year)로 묶어서 그룹이 하나라도 있으면 무조건
`program_type='interdisciplinary'` 요건 행을 만든다. 이 로직은 실제 SW연계전공
5개(빅데이터/산업수학SW/에너지IoT/임베디드SW/산업AI, 전부 `required_total_credits
=48`로 정상 시딩됨)에는 맞지만, **부전공(minor) 시딩이 이미 있는 일반 학과**
(사회학과·심리학과·경영학과·국어국문학과·정보컴퓨터공학부 3개 전공 등 40곳)에도
똑같이 적용돼서, 그 학과의 부전공 program_courses를 그대로 재사용한 가짜
"연계전공" 요건 행을 만들어냈다.

**이게 왜 오류인지 확인한 근거 (2026-08-27):**
- `_source_학사규정_2026-08-10.md`(학사규정 원문)의 "연계전공" 절은 정확히 10개
  지정 프로그램(의생명과학전공·통합사회전공·통합과학전공·빅데이터 연계전공·
  산업수학소프트웨어 연계전공·에너지IoT 연계전공·임베디드소프트웨어연계전공·
  차량용AI반도체 연계전공·산업AI 연계전공·탄소중립바이오기술연계전공)만
  나열한다 — 일반 학과 전체가 연계전공 대상이 되는 게 아니다.
- 경영학과로 직접 대조: 진짜 부전공(minor) 요건은
  `{"groups": [{"n": 3, "type": "min_courses", "label": "택3/9"}], "total_credits": 21}`,
  문제의 "연계전공" 백필 행은 `{"groups": [{"type": "all", "label": "택3/9"}]}`
  (규칙 타입도 틀리고 total_credits도 없음) — `program_courses`가 참조하는
  8개 과목도 완전히 동일(전부 경영학과 자체 개설분, 타 학과 교차인정 없음).
  즉 사람이 조사한 부전공 데이터를 프로그램 타입만 바꿔 기계적으로 복제한 것.
- 회원가입 폼(`AuthPage.tsx`)은 `program_type`으로 "primary"/"minor"/"dual"만
  보낸다 — "interdisciplinary"는 UI 어디서도 생성하지 않는다(AI융합트랙은
  `/me/tracks/enroll` 전용 경로). 이 40개 행에 걸린 실제 `UserAcademicProgram`도
  0건으로 확인함 — 지워도 영향받는 실사용자가 없다.
- 진짜 연계전공 5개(빅데이터/산업수학SW/에너지IoT/임베디드SW/산업AI, 학사규정과
  이름·48학점 정확히 일치)는 `required_total_credits`가 채워져 있어서 이
  스크립트의 필터(`required_total_credits IS NULL`)에 안 걸린다 — 안 지워짐.

**남은 갭(이 스크립트가 다루지 않음):** 학사규정의 나머지 5개 연계전공
(의생명과학전공·통합사회전공·통합과학전공·차량용AI반도체 연계전공·
탄소중립바이오기술연계전공)은 우리 DB에 아예 없다 — 별도 데이터 수집 과제.

사용:
    ./backend/.venv/bin/python -m scripts.remove_spurious_interdisciplinary_backfill            # dry-run
    ./backend/.venv/bin/python -m scripts.remove_spurious_interdisciplinary_backfill --apply     # 실제 삭제
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domains.academics.models import Department, GraduationRequirement, Major, UserAcademicProgram

BACKFILL_NOTE = "SW융합 라벨 자동 파싱 (backfill)"


def find_targets(db) -> list[GraduationRequirement]:
    grs = db.scalars(
        select(GraduationRequirement).where(
            GraduationRequirement.program_type == "interdisciplinary",
            GraduationRequirement.required_total_credits.is_(None),
        )
    ).all()
    return [gr for gr in grs if (gr.special_rules or {}).get("notes") == BACKFILL_NOTE]


def run(dry_run: bool) -> int:
    db = SessionLocal()
    try:
        targets = find_targets(db)
        print(f"삭제 대상: {len(targets)}개\n")
        for gr in targets:
            dept = db.get(Department, gr.department_id) if gr.department_id else None
            major = db.get(Major, gr.major_id) if gr.major_id else None
            name = major.name if major else (dept.name if dept else f"dept{gr.department_id}")

            # 안전장치: 삭제 직전 실사용자 등록 여부 재확인 (dry-run/apply 둘 다).
            q = select(UserAcademicProgram).where(
                UserAcademicProgram.department_id == gr.department_id,
                UserAcademicProgram.program_type == "interdisciplinary",
            )
            q = q.where(
                UserAcademicProgram.major_id == gr.major_id
                if gr.major_id is not None
                else UserAcademicProgram.major_id.is_(None)
            )
            users = db.scalars(q).all()
            if users:
                print(f"  [SKIP - 실사용자 {len(users)}명 있음] gr#{gr.id} {name}")
                continue

            print(f"  [{'would delete' if dry_run else 'delete'}] gr#{gr.id} {name} "
                  f"(dept={gr.department_id}, major={gr.major_id})")
            if not dry_run:
                db.delete(gr)

        if dry_run:
            db.rollback()
        else:
            db.commit()
        return len(targets)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="실제 삭제 (기본은 dry-run)")
    args = ap.parse_args()
    dry_run = not args.apply

    count = run(dry_run)
    print(f"\n{'[DRY-RUN]' if dry_run else '[COMMITTED]'} {count}개 처리")


if __name__ == "__main__":
    main()
