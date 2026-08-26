"""핀테크융합전공 연계전공(interdisciplinary) program_courses 그룹 라벨 정정.

배경: `GraduationRequirement`(dept=97, major=None, program_type='interdisciplinary',
id=286)의 `special_rules.groups`는 "전공기초 (이원화)"/"전공필수 (5과목)"/"전공선택"
세 그룹을 쓰는데, `program_courses.requirement_group`은 실제로 "필수후보"/
"핀테크융합전공 교차인정과목" 두 라벨만 쓰고 있었다(2026-08-27 확인). 라벨이 전혀
안 겹쳐서 `evaluate_program`이 세 그룹 모두 이수 0으로 판정 — 핀테크융합전공 연계전공
학생은 뭘 들어도 "완료" 판정을 절대 못 받는 상태였다.

이 스크립트가 고치는 것:
  1. "필수후보"(5개, 전부 핀테크 자체 개설분 FC*) → "전공필수 (5과목)"로 라벨 정정.
     이름이 special_rules.notes에 적힌 5과목(금융최적화·인공지능과금융·금융데이터
     마이닝·블록체인과플랫폼경영·디지털금융)과 정확히 일치함을 이미 확인함.
  2. "핀테크융합전공 교차인정과목"(37개) 중 확률통계·회계학원리·재무관리 3개를
     "전공기초 (이원화)"로 옮긴다 — notes가 "이공계열: 컴퓨터및프로그래밍입문,
     확률통계 / 상경계열: 회계학원리, 재무관리"라고 명시한 4과목 중 이미
     교차인정 목록에 있던 3개.
  3. 컴퓨터및프로그래밍입문(CB1501007, 컴퓨터공학전공 부전공에 쓴 것과 동일
     course_id — 이 42행 세트의 다른 이공계열 과목들도 전부 CB 계열 컴퓨터공학전공
     과목이라 일관됨)을 새로 "전공기초 (이원화)"에 추가.
  4. 나머지 34개는 "전공선택"으로 라벨 정정 — special_rules에 개별 과목명이
     없고 "24학점"만 명시돼 있어, 기존 교차인정 풀 전체를 후보로 남긴다.

CLAUDE.md 원칙에 따라 dry-run 기본, --apply로 실제 반영. upsert(멱등) — 두 번
돌려도 신규/변경 0건이어야 한다.

사용:
    ./backend/.venv/bin/python -m scripts.fix_fintech_interdisciplinary_groups            # dry-run
    ./backend/.venv/bin/python -m scripts.fix_fintech_interdisciplinary_groups --apply     # 실제 반영
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domains.academics.models import ProgramCourse
from app.domains.courses.models import Course

FINTECH_DEPT_ID = 97
CURRICULUM_YEAR = "2026"

REQUIRED_GROUP = "전공필수 (5과목)"
FOUNDATION_GROUP = "전공기초 (이원화)"
ELECTIVE_GROUP = "전공선택"

# 라벨을 바꿀 기존 과목명(현재 "필수후보" → 필수 5과목).
REQUIRED_COURSE_NAMES = {
    "금융최적화", "인공지능과금융", "금융데이터마이닝", "블록체인과플랫폼경영", "디지털금융",
}
# "교차인정과목" 중 전공기초(이원화)로 옮길 3과목. course_code로 정확히 집는다 —
# "금융데이터마이닝"/"인공지능과금융"처럼 같은 이름이 핀테크 자체 개설분(FC)에도
# 있어서 이름만으로는 필수 5과목 쪽과 헷갈릴 수 있다.
FOUNDATION_FROM_EXISTING = {
    ("CB1501012", "확률통계"),
    ("DB1600358", "회계학원리"),
    ("DB3000932", "재무관리"),
}
# 이 42행 세트에 아직 없는, 새로 추가해야 하는 전공기초 과목.
FOUNDATION_NEW = [
    ("CB1501007", "컴퓨터및프로그래밍입문", 108),
]


def run(dry_run: bool) -> dict:
    db = SessionLocal()
    stats = {"relabeled": 0, "inserted": 0, "unchanged": 0, "missing": []}
    try:
        rows = db.scalars(
            select(ProgramCourse).where(
                ProgramCourse.department_id == FINTECH_DEPT_ID,
                ProgramCourse.major_id.is_(None),
                ProgramCourse.curriculum_year == CURRICULUM_YEAR,
            )
        ).all()

        by_id = {pc.id: pc for pc in rows}
        courses_by_pc = {pc.id: db.get(Course, pc.course_id) for pc in rows}

        for pc in rows:
            course = courses_by_pc[pc.id]
            new_label = None
            if course.course_name in REQUIRED_COURSE_NAMES and course.department_id == FINTECH_DEPT_ID:
                new_label = REQUIRED_GROUP
            elif (course.course_code, course.course_name) in FOUNDATION_FROM_EXISTING:
                new_label = FOUNDATION_GROUP
            elif pc.requirement_group == "핀테크융합전공 교차인정과목":
                new_label = ELECTIVE_GROUP

            if new_label is None:
                continue
            if pc.requirement_group == new_label:
                stats["unchanged"] += 1
                continue
            stats["relabeled"] += 1
            print(f"  [relabel] {course.course_name}({course.course_code}) "
                  f"'{pc.requirement_group}' -> '{new_label}'")
            if not dry_run:
                pc.requirement_group = new_label

        # 새로 추가해야 하는 전공기초 과목(현재 42행 세트에 없음).
        for code, name, dept_id in FOUNDATION_NEW:
            course = db.scalars(
                select(Course).where(Course.course_code == code, Course.department_id == dept_id)
            ).first()
            if not course:
                stats["missing"].append(f"{name} ({code})")
                continue
            existing = db.scalars(
                select(ProgramCourse).where(
                    ProgramCourse.department_id == FINTECH_DEPT_ID,
                    ProgramCourse.major_id.is_(None),
                    ProgramCourse.course_id == course.id,
                    ProgramCourse.curriculum_year == CURRICULUM_YEAR,
                )
            ).first()
            if existing:
                if existing.requirement_group != FOUNDATION_GROUP:
                    stats["relabeled"] += 1
                    print(f"  [relabel] {name}({code}) '{existing.requirement_group}' -> '{FOUNDATION_GROUP}'")
                    if not dry_run:
                        existing.requirement_group = FOUNDATION_GROUP
                else:
                    stats["unchanged"] += 1
                continue
            stats["inserted"] += 1
            print(f"  [insert]  {name}({code}) -> '{FOUNDATION_GROUP}'")
            if not dry_run:
                db.add(ProgramCourse(
                    department_id=FINTECH_DEPT_ID,
                    major_id=None,
                    course_id=course.id,
                    requirement_group=FOUNDATION_GROUP,
                    curriculum_year=CURRICULUM_YEAR,
                ))
                db.flush()

        if dry_run:
            db.rollback()
        else:
            db.commit()
        return stats
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="실제 반영 (기본은 dry-run)")
    args = ap.parse_args()
    dry_run = not args.apply

    stats = run(dry_run)
    print(f"\n{'[DRY-RUN] ' if dry_run else '[COMMITTED] '}"
          f"relabeled={stats['relabeled']} inserted={stats['inserted']} unchanged={stats['unchanged']}")
    if stats["missing"]:
        print(f"  course not found: {stats['missing']}")


if __name__ == "__main__":
    main()
