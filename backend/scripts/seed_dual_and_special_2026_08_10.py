"""부·복수전공 통합 시드 (2026-08-10 배치).

배경:
  `raw_data/manual_staging/05_minor_dual_programs/_source_학사규정_2026-08-10.md`
  (부산대 교육과정 편성 및 운영규정, 별표 2·2-2·2-4 파싱본)와
  Track 2/3 조사 결과를 근거로 다음 4가지를 upsert.

1. 복수전공(dual) 학점 총량 — 별표 2에서 학과별 최소전공 학점
2. 이수 불가 학과(약학·간호·건축·예술 등) 마킹 — special_rules.excluded=True
3. 핀테크융합전공(dept 97) minor 신규 + interdisciplinary special_rules 업데이트
4. 고고학과(2) · 지리교육과(67) 부전공 필수 3과목 → program_courses 업서트

사용:
  ./backend/.venv/bin/python -m scripts.seed_dual_and_special_2026_08_10
      [--apply]  # 기본은 dry-run

원칙:
  - upsert(멱등). 두 번 돌려도 신규 0건이어야 함.
  - dry-run 기본, --apply로 실제 반영.
  - curriculum_year 신규 시드는 '2026' (별표 2가 2026학년도 기준).
  - major_id는 이름 매칭. 매칭 실패 시 로그로 남기고 스킵.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domains.academics.models import (
    Department,
    GraduationRequirement,
    Major,
    ProgramCourse,
)
from app.domains.courses.models import Course
# FK 대상 (SessionLocal flush 시점 리졸브용). CLAUDE.md 스타일에 맞춰 lazy noqa.
from app.domains.users.models import User  # noqa: F401


ROOT = Path(__file__).resolve().parent.parent.parent  # backend/scripts → repo root
SOURCE_MD = ROOT / "raw_data/manual_staging/05_minor_dual_programs/_source_학사규정_2026-08-10.md"
CURRICULUM_YEAR = "2026"


# --- 이수 불가 학과 (규정 명시) --------------------------------------------
#
# 별표 2 및 제22조② / 제22조⑦ 원문에 명시. 이수 불가 학과에도 명시적으로
# special_rules.excluded=True 행을 넣어서, 챗이 "이 학과는 부·복수전공 불가"를
# 답할 수 있게 한다 (행 자체가 없으면 판정 결과가 requirement_found=False라
# "미시딩"인지 "불가"인지 분간 못 함).
#
# 각 항목: (dept_name, block_minor, block_dual, reason)
EXCLUDED_DEPTS: list[tuple[str, bool, bool, str]] = [
    # 약학대학 (약학·제약학 전공): 부·복수전공 모두 불가
    ("약학과", True, True, "약학대학 소속 학과는 부·복수전공 이수 불가 (규정 제22조②·⑦)"),
    ("제약학과", True, True, "약학대학 소속 학과는 부·복수전공 이수 불가 (규정 제22조②·⑦)"),
    ("약학부", True, True, "약학대학 소속 학과는 부·복수전공 이수 불가 (규정 제22조②·⑦)"),
    # 예술대학 (예술문화영상학과 제외)
    ("음악학과", True, True, "예술대학 소속 학과는 부·복수전공 이수 불가 (규정 제22조②·⑦, 예술문화영상학과 예외)"),
    ("미술학과", True, True, "예술대학 소속 학과는 부·복수전공 이수 불가"),
    ("조형학과", True, True, "예술대학 소속 학과는 부·복수전공 이수 불가"),
    ("한국음악학과", True, True, "예술대학 소속 학과는 부·복수전공 이수 불가"),
    ("무용학과", True, True, "예술대학 소속 학과는 부·복수전공 이수 불가"),
    ("디자인학과", True, True, "예술대학 소속 학과는 부·복수전공 이수 불가"),
    # 간호대학
    ("간호학과", True, True, "간호대학 소속 학과는 부·복수전공 이수 불가 (규정 제22조②·⑦)"),
    # 공대 건축학과(5년제) — 건축공학과와 구별
    ("건축학과", True, True, "5년제 건축학과는 부·복수전공 이수 불가 (규정 제22조②·⑦). 건축공학과와 별개."),
    # 국제학부: 부전공만 불가 (복수전공은 GSP/KEASP 명칭으로 가능)
    ("국제학부", True, False, "부전공 이수 불가 (제22조⑦). 복수전공은 Global Studies Program / Korean East Asian Studies Program(각 55명)."),
    # 치과·의과: 규정 명시는 아니나 실질적으로 부·복수전공 이수 대상 아님
    ("의예과", True, True, "의과대학 학제상 부·복수전공 실질 불가"),
    ("의학과", True, True, "의과대학 학제상 부·복수전공 실질 불가"),
    ("치의예과", True, True, "치과대학 학제상 부·복수전공 실질 불가"),
    ("치의학과", True, True, "치과대학 학제상 부·복수전공 실질 불가"),
]


# --- 핀테크융합전공 시드 (Track 2 결과) --------------------------------------
# dept_97_핀테크융합전공.md의 special_rules 초안을 그대로 반영.
FINTECH_DEPT_ID = 97

FINTECH_MINOR_SPECIAL = {
    "total_credits": 21,
    "notes": "핀테크융합전공 부전공. 2024년부터 1학기 1회 선발. 전공기초 불인정.",
    "groups": [
        {
            "type": "min_courses",
            "label": "전공필수 중 3개 택",
            "required_n": 3,
            "required_credits": 9,
            "notes": "전공필수 5과목 중 3개 선택하여 9학점 이수.",
        },
        {
            "type": "min_credits",
            "label": "전공필수+전공선택 합계",
            "required_credits": 21,
            "notes": "전공필수(위) + 전공선택 합쳐 최소 21학점. 전공기초는 인정하지 않는다.",
        },
    ],
    "exclude_categories": ["전공기초"],
}

FINTECH_INTERDISCIPLINARY_SPECIAL = {
    "total_credits": 42,
    "notes": (
        "핀테크융합전공 융합전공. 42학점 = 전공기초 6 + 전공필수 12 + 전공선택 24. "
        "전공기초는 이공/상경 이원화(주전공 반대 계열 이수). 자세한 필수·선택 과목은 "
        "dept_97_핀테크융합전공.md의 원문 발췌 참고."
    ),
    "groups": [
        {
            "type": "min_credits",
            "label": "전공기초 (이원화)",
            "required_credits": 6,
            "notes": "이공계열: 컴퓨터및프로그래밍입문, 확률통계 / 상경계열: 회계학원리, 재무관리. 주전공과 반대 계열 이수.",
        },
        {
            "type": "min_credits",
            "label": "전공필수 (5과목)",
            "required_credits": 12,
            "notes": "금융최적화, 인공지능과금융, 금융데이터마이닝, 블록체인과플랫폼경영, 디지털금융.",
        },
        {
            "type": "min_credits",
            "label": "전공선택",
            "required_credits": 24,
        },
    ],
}


# --- 고고학과 · 지리교육과 부전공 program_courses 시드 -----------------------
# Track 3 결과 (Agent 3이 학과 원문에서 확보). 3과목씩 필수.
# 형식: (dept_id, course_code, course_name, group_label)
MINOR_COURSES_TRACK_3: list[tuple[int, str, str, str]] = [
    # 고고학과 (dept_id=2), 2017년 이후 부전공 신청자
    (2, "AY1500057", "고고학입문", "필수"),
    (2, "AY1600599", "한국고고학개설", "필수"),
    (2, "AY1500911", "고고학방법론입문", "필수"),
    # 지리교육과 (dept_id=67) — 기존 시드와 100% 일치하지만 재확인용으로 upsert
    (67, "GE1600392", "지도학", "필수"),
    (67, "GE1500946", "지리교육론", "필수"),
    (67, "GE2900302", "지형학", "필수"),
]


# --- 별표 2 파서 -------------------------------------------------------------
# 표 행 예시:
#   `| 국어국문학과 | 12 | 18 | 18 | **48** | 126 |`
#   `| 전기전자공학부 - 전자공학전공 | 25 | 36 | – | **61** | 12/33 | 137 |`
#   `| 건축학과 (5년제, 부·복수전공 불가) | 15 | 102 | 18 | **135** | – | 168 |`
#
# 파싱:
#   name = 첫 컬럼 (앞뒤 공백 제거)
#   min_transfer_credits = **N** 로 표기된 열 (최소전공 합계)
_TABLE_ROW = re.compile(
    r"^\|\s*(?P<name>[^|]+?)\s*\|(?:\s*[^|]*\|){2,}\s*\*\*(?P<credits>\d+)\*\*"
)


def parse_table(md_path: Path) -> list[dict]:
    """별표 2 표 행을 파싱해 [{"name": ..., "min_credits": N, "excluded": bool}, ...]."""
    if not md_path.exists():
        print(f"[error] 원문 파일 없음: {md_path}", file=sys.stderr)
        return []
    rows: list[dict] = []
    for line in md_path.read_text(encoding="utf-8").splitlines():
        m = _TABLE_ROW.match(line)
        if not m:
            continue
        name_raw = m.group("name")
        credits = int(m.group("credits"))
        excluded = "부·복수전공 불가" in name_raw or "부복수전공 불가" in name_raw
        # 이름 정리: 괄호 안 부기(폐지·불가 안내) 제거
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name_raw).strip()
        # "학부 - 전공" 분리
        if " - " in name:
            dept_name, major_name = [s.strip() for s in name.split(" - ", 1)]
        else:
            dept_name, major_name = name, None
        rows.append({
            "dept_name": dept_name,
            "major_name": major_name,
            "min_credits": credits,
            "excluded": excluded,
            "raw": name_raw,
        })
    return rows


# --- upsert 헬퍼 -------------------------------------------------------------

def _normalize_dept_name(name: str) -> str:
    """규정문서/DB 사이 문자 표기 차이 정규화.
    - `·` (U+00B7 middle dot) ↔ `.` (마침표): 화공생명·환경공학부 vs 화공생명.환경공학부
    """
    return name.replace("·", ".").replace("・", ".")


def _find_dept(db, name: str) -> Department | None:
    variants = {name, _normalize_dept_name(name), name.replace(".", "·")}
    return db.scalars(
        select(Department).where(Department.name.in_(variants)).order_by(Department.id)
    ).first()


def _find_major(db, dept_id: int, name: str) -> Major | None:
    return db.scalars(
        select(Major).where(Major.department_id == dept_id, Major.name == name).order_by(Major.id)
    ).first()


def _upsert_gr(
    db,
    dept_id: int,
    major_id: int | None,
    program_type: str,
    special: dict,
    total_credits: int | None,
    dry_run: bool,
) -> str:
    """graduation_requirements upsert. curriculum_year=CURRICULUM_YEAR 고정."""
    existing = db.scalars(
        select(GraduationRequirement).where(
            GraduationRequirement.department_id == dept_id,
            GraduationRequirement.major_id == major_id,
            GraduationRequirement.program_type == program_type,
            GraduationRequirement.curriculum_year == CURRICULUM_YEAR,
        )
    ).first()
    if existing:
        if existing.special_rules == special and existing.required_total_credits == total_credits:
            return "unchanged"
        if not dry_run:
            existing.special_rules = special
            existing.required_total_credits = total_credits
        return "update"
    if not dry_run:
        db.add(GraduationRequirement(
            department_id=dept_id,
            major_id=major_id,
            program_type=program_type,
            curriculum_year=CURRICULUM_YEAR,
            required_total_credits=total_credits,
            special_rules=special,
        ))
        # SessionLocal이 autoflush=False라, flush를 안 하면 방금 add한 행이 **같은 실행의
        # 이후 조회에 보이지 않는다**. 이 스크립트는 한 실행에서 같은 (학과, program_type)을
        # 두 번 건드릴 수 있다 — 별표 2 대량 처리와 이수 불가 학과 마킹이 겹치는 경우다
        # (실측: 간호학과 dept=95 dual이 133건 중 유일하게 2회 호출된다).
        # flush가 없으면 두 번째 호출이 위 조회에서 못 찾고 또 add해서 중복 행이 생긴다 —
        # 2026-08-13에 정리한 간호학과 dual 2026 중복(created_at 34µs 차이)의 실제 원인이다.
        db.flush()
    return "insert"


def _upsert_pc(
    db,
    dept_id: int,
    major_id: int | None,
    course_id: int,
    group_label: str,
    dry_run: bool,
) -> str:
    existing = db.scalars(
        select(ProgramCourse).where(
            ProgramCourse.department_id == dept_id,
            ProgramCourse.major_id == major_id,
            ProgramCourse.course_id == course_id,
            ProgramCourse.curriculum_year == CURRICULUM_YEAR,
        )
    ).first()
    if existing:
        if existing.requirement_group == group_label:
            return "unchanged"
        if not dry_run:
            existing.requirement_group = group_label
        return "update"
    if not dry_run:
        db.add(ProgramCourse(
            department_id=dept_id,
            major_id=major_id,
            course_id=course_id,
            requirement_group=group_label,
            curriculum_year=CURRICULUM_YEAR,
        ))
    return "insert"


# --- 각 시드 함수 ------------------------------------------------------------

def seed_dual_from_source(db, dry_run: bool) -> dict:
    """별표 2에서 학과별 최소전공 학점을 dual로 upsert."""
    rows = parse_table(SOURCE_MD)
    stats = {"total": len(rows), "insert": 0, "update": 0, "unchanged": 0, "dept_missed": [], "major_missed": []}
    for r in rows:
        if r["excluded"]:
            continue  # excluded 처리는 별도 함수
        dept = _find_dept(db, r["dept_name"])
        if not dept:
            stats["dept_missed"].append(r["dept_name"])
            continue
        major_id = None
        if r["major_name"]:
            m = _find_major(db, dept.id, r["major_name"])
            if not m:
                stats["major_missed"].append(f"{r['dept_name']} / {r['major_name']}")
                continue
            major_id = m.id
        special = {
            "total_credits": r["min_credits"],
            "notes": f"복수전공 이수학점. 학사규정 별표 2({CURRICULUM_YEAR}학년도 기준).",
            "groups": [{
                "type": "min_credits",
                "label": "최소전공 합계",
                "required_credits": r["min_credits"],
                "notes": "복수전공 이수 시 해당 학과의 최소전공 교과목 전체 이수 필요 (규정 제22조③).",
            }],
        }
        action = _upsert_gr(db, dept.id, major_id, "dual", special, r["min_credits"], dry_run)
        stats[action] += 1
    return stats


def seed_excluded(db, dry_run: bool) -> dict:
    """이수 불가 학과에 minor/dual excluded 행 upsert."""
    stats = {"insert": 0, "update": 0, "unchanged": 0, "dept_missed": []}
    for name, block_minor, block_dual, reason in EXCLUDED_DEPTS:
        dept = _find_dept(db, name)
        if not dept:
            stats["dept_missed"].append(name)
            continue
        for program_type, block in (("minor", block_minor), ("dual", block_dual)):
            if not block:
                continue
            special = {
                "excluded": True,
                "reason": reason,
                "notes": "이 학과는 규정상 이 프로그램을 이수할 수 없습니다.",
            }
            action = _upsert_gr(db, dept.id, None, program_type, special, None, dry_run)
            stats[action] += 1
    return stats


def seed_fintech(db, dry_run: bool) -> dict:
    """핀테크융합전공 minor 신규 + interdisciplinary special_rules 업데이트."""
    stats = {"insert": 0, "update": 0, "unchanged": 0}
    dept = db.get(Department, FINTECH_DEPT_ID)
    if not dept:
        return {"error": f"dept {FINTECH_DEPT_ID} 없음"}
    for program_type, special in (
        ("minor", FINTECH_MINOR_SPECIAL),
        ("interdisciplinary", FINTECH_INTERDISCIPLINARY_SPECIAL),
    ):
        total = special.get("total_credits")
        action = _upsert_gr(db, dept.id, None, program_type, special, total, dry_run)
        stats[action] += 1
    return stats


def seed_track3_courses(db, dry_run: bool) -> dict:
    """고고학과·지리교육과 부전공 필수 3과목 program_courses upsert."""
    stats = {"insert": 0, "update": 0, "unchanged": 0, "course_missed": []}
    for dept_id, code, name, group in MINOR_COURSES_TRACK_3:
        course = db.scalars(
            select(Course).where(
                Course.department_id == dept_id, Course.course_code == code
            )
        ).first()
        if not course:
            # 이름으로만 재시도
            course = db.scalars(
                select(Course).where(
                    Course.department_id == dept_id, Course.course_name == name
                )
            ).first()
        if not course:
            stats["course_missed"].append(f"dept {dept_id} · {code} {name}")
            continue
        action = _upsert_pc(db, dept_id, None, course.id, group, dry_run)
        stats[action] += 1
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 upsert (기본은 dry-run)")
    args = ap.parse_args()
    dry_run = not args.apply

    db = SessionLocal()
    try:
        print(f"=== 시드 대상: {SOURCE_MD.name} · curriculum_year={CURRICULUM_YEAR} ===\n")

        print("--- 1. dual 대량 (별표 2) ---")
        s = seed_dual_from_source(db, dry_run)
        print(f"  전체 {s['total']}건 파싱")
        print(f"  insert={s['insert']} update={s['update']} unchanged={s['unchanged']}")
        if s["dept_missed"]:
            print(f"  dept 매칭 실패: {len(s['dept_missed'])}건 → {s['dept_missed'][:10]}")
        if s["major_missed"]:
            print(f"  major 매칭 실패: {len(s['major_missed'])}건 → {s['major_missed'][:10]}")

        print("\n--- 2. 이수 불가 학과 excluded 마킹 ---")
        s = seed_excluded(db, dry_run)
        print(f"  insert={s['insert']} update={s['update']} unchanged={s['unchanged']}")
        if s["dept_missed"]:
            print(f"  dept 매칭 실패: {s['dept_missed']}")

        print("\n--- 3. 핀테크융합전공 (minor + interdisciplinary) ---")
        s = seed_fintech(db, dry_run)
        print(f"  {s}")

        print("\n--- 4. 고고·지리교육 program_courses ---")
        s = seed_track3_courses(db, dry_run)
        print(f"  insert={s['insert']} update={s['update']} unchanged={s['unchanged']}")
        if s["course_missed"]:
            print(f"  course 매칭 실패: {s['course_missed']}")

        if dry_run:
            print("\n🔍 [DRY-RUN] 실제 변경 안 함. --apply로 반영.")
            db.rollback()
        else:
            db.commit()
            print("\n✅ [COMMITTED] 반영 완료.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
