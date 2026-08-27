"""융합전공(부·복수전공 대상) 이수요건·과목을 graduation_requirements / program_courses에 적재한다.

배경 (2026-08-27 조사, `raw_data/manual_staging/06_interdisciplinary_majors/`):
  DB에 등록만 돼 있고 graduation_requirements가 비어 있던 융합전공들의 이수요건을
  수집했다. 이수요건 총괄은 대부분 이미 레포에 있던 학사규정 별표
  (`raw_data/manual_staging/05_minor_dual_programs/_source_학사규정_2026-08-10.md`
  별표 2-2 / 2-4)로 확인됐고, 첨단융합학부 4개(AI융합계산과학·EES·이차전지·지식재산)는
  각 학과 공식 사이트로 교차확인했다(지식재산 복수전공 42→36 조정 반영).

모델링 결정
-----------
- 이 융합전공들은 주전공 신입 선발이 없고 **부전공(minor)·복수전공(dual)** 대상이다.
  그래서 `program_type`은 SW연계전공 시드(`seed_sw_convergence_programs.py`)의
  `interdisciplinary`가 아니라 일반 학과와 동일하게 `minor` / `dual`을 쓴다
  (`AuthPage.tsx`가 보내는 값과 일치, 2026-08-27 PR #278로 가짜 interdisciplinary 행 정리됨).
- 이미 주전공/복수전공 graduation_requirements가 있는 3개
  (지능형헬스사이언스융합전공 primary126·dual57, AI융합계산과학전공 primary137·dual64,
  미래자동차 융합전공 dual48)는 **덮어쓰지 않는다.** 배분 컬럼만 비어 있으면 채운다.
- `program_courses`는 이미 `courses` 테이블에 각 융합전공(department_id / major_id)으로
  스코프돼 category까지 채워진 행을 그대로 옮긴다. `courses.category`
  (전공기초/전공필수/전공선택) → `program_courses.category` + `requirement_group`.

과목 데이터 (2026-08-27 갱신)
----------------------------
- AIS(bkorea) 위젯을 재조회해서 6개 유닛(341200 미래자동차 / 347200 반도체 /
  442510 DX / 475900 그린바이오 / 442106 AI융합계산과학 / 347820 미래도시건축환경)의
  2026 전체 교육과정을 `seeds/ais_courses_2026.csv`에 추가했다(+374행, 341200 매핑도
  `seeds/school_hierarchy_mapping.csv`에 추가). **이 스크립트 실행 전에
  `python -m scripts.import_courses_from_ais`를 먼저 돌려 `courses`에 반영해야 한다.**
- 반도체 199행은 AIS가 참여학과(전자·재료·컴공 등) 과목까지 전부 SV 코드로 통합해
  제공한 것 — 참여학과 course_id를 따로 매칭할 필요 없이 이 목록이 곧 pool이다.

아직 못 하는 것
--------------
- **미래도시건축환경융합전공(dept#37)**: 전공자율선택 라우팅 모집단위(2학년부터
  환경공학·건축학·건축공학·도시공학·조경학 중 택1). 독립 이수요건 없음 → 스킵.
- 첨단융합학부 4개(EES·이차전지 등)의 "초급/중급/고급", "N과목" 같은 그룹 조건은
  flat graduation_requirements가 담지 못한다. 총학점만 넣고 special_rules.notes에 남긴다.
- AI융합계산과학전공 전공기초 25학점분은 AIS 유닛(442106) 커리큘럼에 없다 —
  첨단융합학부 공통 전공기초로 별도 편성된 것으로 보임. GR 배분엔 25로 넣되
  program_courses엔 안 잡힌다.

실행:
    python -m scripts.seed_interdisciplinary_majors_2026_08            # dry-run
    python -m scripts.seed_interdisciplinary_majors_2026_08 --apply    # 실제 반영
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domains.academics.models import (
    Department,
    GraduationRequirement,
    Major,
    ProgramCourse,
)
from app.domains.courses.models import Course

CURRICULUM_YEAR = "2026"

# courses.category → program_courses.requirement_group 매핑 (그대로 유지)
_CATEGORY_GROUP = {
    "전공기초": "전공기초",
    "전공필수": "전공필수",
    "전공선택": "전공선택",
}


@dataclass
class Req:
    """한 이수형태(minor/dual)의 요건 행."""

    program_type: str  # "minor" | "dual"
    total_credits: int
    foundation: int | None = None  # required_major_foundation (전공기초)
    required: int | None = None  # required_major_required (전공필수)
    elective: int | None = None  # required_major_elective (전공선택)
    notes: str = ""
    # True면 이미 있는 행을 덮어쓰지 않고 배분 컬럼이 비었을 때만 채운다.
    preserve_existing: bool = False


@dataclass
class Program:
    label: str
    department_name: str
    major_name: str | None
    reqs: list[Req] = field(default_factory=list)
    seed_program_courses: bool = True
    course_note: str = ""


# 근거: 학사규정 별표 2-2(융합전공 본과) / 별표 2-4(최소전공 미구성 융합전공) +
# 각 학과 공식 사이트. 상세 인용은 raw_data/manual_staging/06_interdisciplinary_majors/.
PROGRAMS: list[Program] = [
    Program(
        label="지능형헬스사이언스융합전공",
        department_name="지능형헬스사이언스융합전공",
        major_name=None,
        reqs=[
            Req("dual", 57, foundation=18, required=21, elective=18,
                notes="학사규정 별표2-2. 전공기초18+전공필수21+전공선택18=57.",
                preserve_existing=True),
        ],
    ),
    Program(
        label="AI융합계산과학전공",
        department_name="첨단융합학부",
        major_name="AI융합계산과학전공",
        reqs=[
            Req("dual", 64, foundation=25, required=39,
                notes="학사규정 별표(첨단융합학부 세부전공) 전공기초25+전공필수39=최소전공64. "
                      "ste.pusan.ac.kr 페이지의 기본36/심화45는 주전공 트랙 프레이밍 — 별표값 우선.",
                preserve_existing=True),
        ],
        course_note="AIS 스냅샷에 전공기초 행 없음(전공필수13/전공선택13만). 전공기초 25학점분 재조회 필요.",
    ),
    Program(
        label="EES융합전공",
        department_name="첨단융합학부",
        major_name="EES융합전공",
        reqs=[
            Req("minor", 21,
                notes="학사규정 별표2-4 + ees.pusan.ac.kr. 에너지기초 3학점 이내, 중·고급 9학점 이상 필수."),
            Req("dual", 42,
                notes="학사규정 별표2-4 + ees.pusan.ac.kr. 에너지기초 3학점 이내, 중·고급 18학점 이상 필수. "
                      "복수전공 신청 평점평균 3.5 이상."),
        ],
        course_note="공식 이수구분이 초급/중급/고급 — 특정 과목을 전공필수로 지정하지 않음. 전 과목 전공선택 pool.",
    ),
    Program(
        label="이차전지융합전공",
        department_name="첨단융합학부",
        major_name="이차전지융합전공",
        reqs=[
            Req("minor", 21,
                notes="학사규정 별표2-4 + 2battery.pusan.ac.kr. 이차전지융합전공 개설 교과목 중 7과목(21학점). "
                      "교양선택 3과목 제외. 2학년 1학기부터. 복수전공(dual) 없음."),
        ],
        course_note="부전공 7과목은 '개설 교과목 중' 범주 요건만 확인 — 특정 7과목 고정 아님.",
    ),
    Program(
        label="지식재산융합전공",
        department_name="첨단융합학부",
        major_name="지식재산융합전공",
        reqs=[
            Req("minor", 21, required=6,
                notes="학사규정 별표2-4 + ipc.pusan.ac.kr. 필수 2과목(지식재산권개론·지식재산창출과창업 6학점) "
                      "+ 지정 교과목 중 7과목(21학점)."),
            Req("dual", 36, required=6,
                notes="ipc.pusan.ac.kr 공지로 기존 42→36 조정 확인(학사규정 별표2-4 md도 36). "
                      "필수 6학점 + 지정 교과목 중 12과목(36학점). "
                      "※ dual_major_minor_credit_requirements_2026.csv엔 아직 42/14과목 — CSV 갱신 필요."),
        ],
    ),
    Program(
        label="반도체융합전공",
        department_name="반도체융합전공",
        major_name=None,
        reqs=[
            Req("minor", 21,
                notes="학사규정 별표2-4 + pnusemi PDF 교육과정표(2026-1). "
                      "2024-2학기 선발자부터 필수지정과목(◎) 중 12학점 포함."),
            Req("dual", 48, foundation=9, required=15, elective=24,
                notes="pnusemi PDF: 전공기초9(지정3)+전공필수15(지정6)+전공선택24(심화9). "
                      "주관 반도체공학전공. AIS 유닛 347200이 참여학과(전자·전기·재료·고분자·"
                      "유기소재·기계·화공생명·첨단융합학부·컴공·인공지능·물리) 과목까지 SV 코드로 통합 제공."),
        ],
        course_note="AIS 199행(기초16/필수63/선택120). 동명이코드 21건은 참여학과별 '동일과목' — "
                    "import_courses_from_ais는 --allow-name-collisions로 실행할 것.",
    ),
    Program(
        label="DX융합전공",
        department_name="DX융합전공",
        major_name=None,
        reqs=[
            Req("minor", 21, required=6,
                notes="학사규정 별표2-4. 전공필수 6학점 포함."),
            Req("dual", 36, required=6,
                notes="학사규정 별표2-4. 전공필수 6학점 + 타대학개설 교과목 6학점 이상 포함(타대학개설 pool 미반영)."),
        ],
        course_note="AIS 89행(필수5/선택80/일반선택4) — import_courses_from_ais 선행 필요.",
    ),
    Program(
        label="그린바이오융합전공",
        department_name="그린바이오융합전공",
        major_name=None,
        reqs=[
            Req("minor", 21, notes="학사규정 별표2-4. 세부 배분·필수과목 지정 없음."),
            Req("dual", 48, notes="학사규정 별표2-4. 세부 배분 없음."),
        ],
        course_note="AIS 32행(필수3/선택29) — import_courses_from_ais 선행 필요.",
    ),
    Program(
        label="미래자동차 융합전공",
        department_name="미래자동차 융합전공",
        major_name=None,
        reqs=[
            Req("dual", 48, foundation=9, required=15, elective=24,
                notes="학사규정 별표2-2. 전공기초9+전공필수15+전공선택24=48. primary 126.",
                preserve_existing=True),
        ],
        course_note="AIS 58행(기초3/필수5/선택50) — import_courses_from_ais 선행 필요.",
    ),
]

# GR/과목 둘 다 스킵 (사유만 기록)
SKIPPED = {
    "미래도시건축환경융합전공": "전공자율선택 라우팅 모집단위 — 독립 이수요건 없음",
}


def _resolve_scope(db, prog: Program) -> tuple[int, int | None]:
    dept = db.scalars(select(Department).where(Department.name == prog.department_name)).first()
    if dept is None:
        raise RuntimeError(f"department 없음: {prog.department_name}")
    major_id = None
    if prog.major_name:
        major = db.scalars(
            select(Major).where(Major.name == prog.major_name, Major.department_id == dept.id)
        ).first()
        if major is None:
            raise RuntimeError(f"major 없음: {prog.department_name} / {prog.major_name}")
        major_id = major.id
    return dept.id, major_id


def _upsert_requirement(db, dept_id: int, major_id: int | None, req: Req, dry_run: bool) -> str:
    q = select(GraduationRequirement).where(
        GraduationRequirement.department_id == dept_id,
        GraduationRequirement.major_id.is_(None) if major_id is None else GraduationRequirement.major_id == major_id,
        GraduationRequirement.program_type == req.program_type,
        GraduationRequirement.curriculum_year == CURRICULUM_YEAR,
    )
    existing = db.scalars(q).first()
    special = {"notes": req.notes} if req.notes else None

    if existing is not None:
        if req.preserve_existing:
            filled = []
            if existing.required_major_foundation is None and req.foundation is not None:
                existing.required_major_foundation = req.foundation
                filled.append("foundation")
            if existing.required_major_required is None and req.required is not None:
                existing.required_major_required = req.required
                filled.append("required")
            if existing.required_major_elective is None and req.elective is not None:
                existing.required_major_elective = req.elective
                filled.append("elective")
            if existing.required_total_credits is None:
                existing.required_total_credits = req.total_credits
                filled.append("total")
            return f"preserved (filled: {','.join(filled) or 'nothing'})"
        existing.required_total_credits = req.total_credits
        existing.required_major_foundation = req.foundation
        existing.required_major_required = req.required
        existing.required_major_elective = req.elective
        if special:
            existing.special_rules = special
        return "updated"

    if not dry_run:
        db.add(
            GraduationRequirement(
                department_id=dept_id,
                major_id=major_id,
                program_type=req.program_type,
                curriculum_year=CURRICULUM_YEAR,
                required_total_credits=req.total_credits,
                required_major_foundation=req.foundation,
                required_major_required=req.required,
                required_major_elective=req.elective,
                special_rules=special,
            )
        )
    return "created"


def _upsert_program_courses(db, dept_id: int, major_id: int | None, dry_run: bool) -> tuple[int, int, int]:
    """이미 courses에 이 프로그램으로 스코프된 행을 program_courses로 옮긴다 (멱등)."""
    scoped = db.scalars(
        select(Course).where(
            Course.department_id == dept_id,
            Course.major_id.is_(None) if major_id is None else Course.major_id == major_id,
        )
    ).all()
    created = existing = skipped = 0
    for c in scoped:
        group = _CATEGORY_GROUP.get(c.category or "")
        if group is None:
            skipped += 1  # 교양·일반선택 등은 program_courses 대상 아님
            continue
        row = db.scalars(
            select(ProgramCourse).where(
                ProgramCourse.department_id == dept_id,
                ProgramCourse.major_id.is_(None) if major_id is None else ProgramCourse.major_id == major_id,
                ProgramCourse.course_id == c.id,
                ProgramCourse.curriculum_year == CURRICULUM_YEAR,
            )
        ).first()
        if row is not None:
            if row.requirement_group != group or row.category != c.category:
                row.requirement_group = group
                row.category = c.category
            existing += 1
            continue
        created += 1
        if not dry_run:
            db.add(
                ProgramCourse(
                    department_id=dept_id,
                    major_id=major_id,
                    course_id=c.id,
                    requirement_group=group,
                    category=c.category,
                    curriculum_year=CURRICULUM_YEAR,
                )
            )
    return created, existing, skipped


def run(dry_run: bool) -> None:
    db = SessionLocal()
    try:
        for name, reason in SKIPPED.items():
            print(f"[SKIP] {name} — {reason}")
        print()

        for prog in PROGRAMS:
            dept_id, major_id = _resolve_scope(db, prog)
            print(f"■ {prog.label} (dept={dept_id}, major={major_id})")
            for req in prog.reqs:
                action = _upsert_requirement(db, dept_id, major_id, req, dry_run)
                print(f"    GR {req.program_type:<5} total={req.total_credits} "
                      f"(기초{req.foundation}/필수{req.required}/선택{req.elective}) → {action}")
            if prog.seed_program_courses:
                c, e, s = _upsert_program_courses(db, dept_id, major_id, dry_run)
                print(f"    program_courses: 신규 {c} / 기존 {e} / 대상외(교양 등) {s}")
            if prog.course_note:
                print(f"    ⚠ {prog.course_note}")
            print()

        if dry_run:
            db.rollback()
            print("[DRY-RUN] 롤백함. 반영하려면 --apply")
        else:
            db.commit()
            print("[COMMITTED]")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="실제 반영 (기본은 dry-run)")
    args = ap.parse_args()
    run(dry_run=not args.apply)


if __name__ == "__main__":
    main()
