"""프로그램(부전공·복수전공·SW융합트랙·연계전공·융합전공) 이수 판정.

주전공 졸업요건 판정은 `graduation_progress.py`(카테고리별 학점 합계 대조)가 담당.
이건 그걸로 표현할 수 없는 **프로그램 단위 규칙**(택N/M, 특정 그룹 학점 최소 등)의
판정을 담당한다.

**입력 데이터:**
- `graduation_requirements.special_rules` JSONB — 프로그램 규칙 (부전공 시드·SW융합 백필)
- `program_courses` — 프로그램별 인정 과목 목록 (requirement_group 라벨 포함)
- `student_course_records` — 학생 이수 과목 이력

**규칙 어휘 (rule types):**
- `all` — 그룹의 모든 인정 과목 이수
- `min_courses` — 그룹에서 최소 N과목 이수
- `min_credits` — 그룹에서 최소 M학점 이수
- `min_distinct_departments` — 이수 과목이 최소 K개 개설학과 걸침

CLAUDE.md 원칙: 판정은 규칙 기반, LLM 사용 금지.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.academics.models import (
    Department,
    GraduationRequirement,
    ProgramCourse,
    StudentCourseRecord,
)
from app.domains.courses.models import Course


@dataclass
class GroupEval:
    label: str
    rule_type: str
    required_n: int | None = None
    required_credits: float | None = None
    matched_courses: list[str] = None  # course names
    completed: bool = False
    shortage: str | None = None


@dataclass
class ProgramEvalResult:
    program_type: str
    department_id: int
    major_id: int | None
    curriculum_year: str | None
    total_credits_required: int | None
    total_credits_earned: float
    total_credits_ok: bool
    groups: list[GroupEval]
    completed: bool  # 모든 group + 총량 충족
    excluded_categories: list[str]
    notes: str | None = None


def _resolve_completed_courses(db: Session, user_id: int) -> dict[int, Course]:
    """user_id의 이수완료 과목을 (course_id → Course) 매핑으로 반환.

    student_course_records.course_id가 NULL인 이력은 이름 매칭으로 course를 찾는다.
    (현재 스키마상 course_id는 NULL이 대부분이라 name fallback 필수 — PR #99 참고.)
    """
    records = db.execute(
        select(StudentCourseRecord).where(StudentCourseRecord.user_id == user_id)
    ).scalars().all()
    result: dict[int, Course] = {}
    for r in records:
        if r.course_id:
            course = db.get(Course, r.course_id)
            if course:
                result[course.id] = course
                continue
        # name fallback (department 무관 first-match — 보수적 매칭)
        if r.raw_course_name:
            course = db.execute(
                select(Course).where(Course.course_name == r.raw_course_name).limit(1)
            ).scalar_one_or_none()
            if course:
                result[course.id] = course
    return result


def evaluate_program(
    db: Session,
    user_id: int,
    department_id: int,
    major_id: int | None,
    program_type: str,
    curriculum_year: str | None = None,
) -> ProgramEvalResult | None:
    """단일 프로그램 판정. 요건 행 없으면 None."""
    # curriculum_year는 정확 매칭 or NULL 요건 fallback
    q = select(GraduationRequirement).where(
        GraduationRequirement.department_id == department_id,
        GraduationRequirement.major_id == major_id,
        GraduationRequirement.program_type == program_type,
    )
    if curriculum_year:
        # 학번 기준 curriculum_year 우선, 못 찾으면 NULL로 fallback
        exact = db.execute(q.where(GraduationRequirement.curriculum_year == curriculum_year)).scalar_one_or_none()
        req = exact or db.execute(q.where(GraduationRequirement.curriculum_year.is_(None))).scalar_one_or_none()
    else:
        req = db.execute(q).scalar_one_or_none()
    if not req:
        return None

    special: dict[str, Any] = req.special_rules or {}
    excluded = special.get("exclude_categories", []) or []
    notes = special.get("notes")

    # 이 프로그램 인정 과목
    pc_rows = db.execute(select(ProgramCourse).where(
        ProgramCourse.department_id == department_id,
        ProgramCourse.major_id == major_id,
        ProgramCourse.curriculum_year == (req.curriculum_year),  # 같은 curriculum_year row 매칭
    )).scalars().all()

    completed_courses = _resolve_completed_courses(db, user_id)
    # course_id → matched ProgramCourse
    course_to_pc: dict[int, list[ProgramCourse]] = {}
    for pc in pc_rows:
        course_to_pc.setdefault(pc.course_id, []).append(pc)

    # 학생이 이수한 프로그램 인정 과목
    matched: list[tuple[Course, ProgramCourse]] = []
    for cid, course in completed_courses.items():
        # exclude_categories 필터
        if course.category and course.category in excluded:
            continue
        for pc in course_to_pc.get(cid, []):
            matched.append((course, pc))

    # 라벨별 그룹핑
    by_label: dict[str, list[tuple[Course, ProgramCourse]]] = {}
    for course, pc in matched:
        by_label.setdefault(pc.requirement_group or "", []).append((course, pc))

    # 각 그룹별 판정
    group_evals: list[GroupEval] = []
    for grp in special.get("groups", []):
        label = grp.get("label", "")
        rule_type = grp.get("type", "unknown")
        matched_here = by_label.get(label, [])
        ge = GroupEval(
            label=label,
            rule_type=rule_type,
            required_n=grp.get("n"),
            required_credits=grp.get("min_credits"),
            matched_courses=[c.course_name for c, _ in matched_here],
        )
        # 이 그룹의 전체 인정 과목 (참고용, min_courses에서 후보 개수 대비)
        total_in_group = sum(1 for pc in pc_rows if (pc.requirement_group or "") == label)
        if rule_type == "all":
            ge.completed = len(matched_here) >= total_in_group and total_in_group > 0
            if not ge.completed:
                ge.shortage = f"이수 {len(matched_here)}/{total_in_group} (전체 필수)"
        elif rule_type == "min_courses":
            n = grp.get("n", 0)
            ge.completed = len(matched_here) >= n
            if not ge.completed:
                ge.shortage = f"이수 {len(matched_here)}/{n} ({total_in_group}개 후보 중)"
        elif rule_type == "min_credits":
            min_c = grp.get("min_credits", 0)
            earned = sum((c.credits or 0) for c, _ in matched_here)
            ge.completed = earned >= min_c
            if not ge.completed:
                ge.shortage = f"이수 {earned:.1f}/{min_c} 학점"
        elif rule_type == "min_distinct_departments":
            k = grp.get("n", 0)
            distinct_depts = {c.department_id for c, _ in matched_here if c.department_id}
            ge.completed = len(distinct_depts) >= k
            if not ge.completed:
                ge.shortage = f"이수 학과 {len(distinct_depts)}/{k}개"
        else:
            ge.shortage = f"unknown rule_type={rule_type}"
        group_evals.append(ge)

    # 총량 (special_rules.total_credits > graduation_requirements.required_total_credits 순)
    total_required = special.get("total_credits") or req.required_total_credits
    total_earned = sum((c.credits or 0) for c, _ in matched)
    total_ok = (total_required is None) or (total_earned >= total_required)

    all_groups_ok = all(ge.completed for ge in group_evals) if group_evals else True
    return ProgramEvalResult(
        program_type=program_type,
        department_id=department_id,
        major_id=major_id,
        curriculum_year=req.curriculum_year,
        total_credits_required=total_required,
        total_credits_earned=total_earned,
        total_credits_ok=total_ok,
        groups=group_evals,
        completed=all_groups_ok and total_ok,
        excluded_categories=list(excluded),
        notes=notes,
    )
