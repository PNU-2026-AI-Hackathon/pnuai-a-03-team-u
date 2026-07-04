"""규칙 기반 졸업요건 판정 엔진 (MVP).

`requirement_sets`/`requirement_categories`/`requirement_courses` 시드 데이터를
학생의 `student_course_records`와 대조해 프로그램(주전공/복수전공/부전공/연계전공)별로
카테고리 충족 여부를 계산한다.

현재 시드 데이터의 한계 때문에 아래 범위로 판정을 제한한다 (자세한 내용은
docs/progress 아래 관련 문서 참고):

- `student_course_records.category`는 크롤러가 주는 대분류 텍스트(예: "전공필수",
  "교양")뿐이라 효원핵심/효원균형/효원창의 같은 세부 교양 영역은 구분할 수 없다.
  `RAW_CATEGORY_TO_CODES`에 없는 category_code는 항상 satisfied=None(판정 불가)으로 둔다.
- `requirement_categories.minimum_credits`는 자유 텍스트라 "-"처럼 숫자가 아닌 값이
  섞여 있다. 파싱 실패 시 판정 불가로 처리한다.
- `curriculum_year`가 시드 데이터에 "2026"만 있어, 학생의 실제 입학연도와 정확히
  일치하는 요건 세트가 없으면 최신 연도로 대체하고 warning을 남긴다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.courses.models import Course
from app.domains.academics.models import (
    RequirementCategory,
    RequirementCourse,
    RequirementSet,
    StudentCourseRecord,
    UserAcademicProgram,
)

# 학생 이수내역의 대분류 category 값 -> requirement_categories.category_code.
# 여기 없는 category_code(예: general_core/general_balanced/general_creative,
# major_total/minimum_major_total 같은 집계성 카테고리)는 현재 데이터로는
# 안전하게 산출할 수 없어 의도적으로 매핑하지 않는다.
RAW_CATEGORY_TO_CODES: dict[str, tuple[str, ...]] = {
    "전공필수": ("major_required",),
    "전공선택": ("major_elective",),
    "전공기초": ("major_foundation",),
    "심화전공": ("deep_major",),
    "교양": ("general_total",),
    "일반선택": ("free_elective",),
}


@dataclass
class CategoryResult:
    category_code: str
    category_name: str | None
    minimum_credits: Decimal | None
    earned_credits: Decimal
    satisfied: bool | None  # None = 세부 데이터 부족으로 판정 불가
    reason: str | None = None
    matched_course_names: list[str] = field(default_factory=list)


@dataclass
class RequiredCourseResult:
    status: str  # "no_data" | "checked"
    missing_course_names: list[str] = field(default_factory=list)
    completed_course_names: list[str] = field(default_factory=list)


@dataclass
class ProgramEvaluation:
    user_academic_program_id: int
    program_type: str
    major: str | None
    academic_program_code: str | None
    curriculum_year_used: str | None
    requirement_set_id: int | None
    status: str  # "evaluated" | "no_requirement_set" | "no_reviewed_categories"
    categories: list[CategoryResult] = field(default_factory=list)
    required_courses: RequiredCourseResult | None = None
    warnings: list[str] = field(default_factory=list)


def _parse_credits(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    raw = raw.strip()
    if not raw or raw in {"-", "—", "N/A", "n/a"}:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _find_requirement_set(
    db: Session,
    academic_program_code: str | None,
    program_type: str,
    curriculum_year: str | None,
) -> tuple[RequirementSet | None, list[str]]:
    warnings: list[str] = []
    if not academic_program_code:
        return None, ["academic_program_code가 없어 요건 세트를 찾을 수 없음"]

    base_stmt = select(RequirementSet).where(
        RequirementSet.academic_program_code == academic_program_code,
        RequirementSet.program_type == program_type,
        RequirementSet.is_active.is_(True),
    )

    if curriculum_year:
        exact = db.scalars(
            base_stmt.where(RequirementSet.curriculum_year == curriculum_year)
        ).first()
        if exact:
            return exact, warnings

    fallback = db.scalars(base_stmt.order_by(RequirementSet.curriculum_year.desc())).first()
    if fallback:
        warnings.append(
            f"{curriculum_year or '(미상)'} 학년도 요건 세트가 없어 "
            f"{fallback.curriculum_year} 요건으로 대체 판정함 "
            "(입학연도별 요건 차이는 반영되지 않음)"
        )
        return fallback, warnings

    return None, warnings


def _evaluate_categories(
    db: Session,
    requirement_set: RequirementSet,
    course_records: list[StudentCourseRecord],
) -> tuple[list[CategoryResult], list[str]]:
    warnings: list[str] = []
    categories = db.scalars(
        select(RequirementCategory).where(
            RequirementCategory.requirement_set_id == requirement_set.id,
            RequirementCategory.rule_type == "minimum_credits",
            RequirementCategory.needs_review.is_(False),
        )
    ).all()

    course_ids = [rec.course_id for rec in course_records if rec.course_id]
    course_map = {}
    if course_ids:
        courses = db.scalars(select(Course).where(Course.id.in_(course_ids))).all()
        course_map = {c.id: c for c in courses}

    credits_by_code: dict[str, Decimal] = {}
    names_by_code: dict[str, list[str]] = {}
    unmapped_courses: list[str] = []
    for rec in course_records:
        credit = Decimal(str(rec.credits)) if rec.credits is not None else Decimal("0")
        codes = RAW_CATEGORY_TO_CODES.get((rec.category or "").strip())
        if not codes:
            unmapped_courses.append(rec.raw_course_name)
            continue
            
        is_major_code = any(c.startswith("major_") or c == "deep_major" for c in codes)
        if is_major_code and rec.course_id and rec.course_id in course_map:
            course = course_map[rec.course_id]
            is_diff_dept = False
            if course.department_id and requirement_set.department_id:
                if course.department_id != requirement_set.department_id:
                    is_diff_dept = True
            elif course.department and requirement_set.department:
                if course.department != requirement_set.department:
                    is_diff_dept = True
            
            if is_diff_dept:
                # 다른 학과 과목을 전공필수/선택으로 들었어도 이 프로그램(학과) 입장에서는
                # 전공 학점으로 인정할 수 없다. 학점 자체가 사라지는 게 아니라 보통
                # 일반선택(자유선택) 학점으로 인정되므로, 원래 카테고리 대신
                # free_elective로 재분류해서 합산한다.
                credits_by_code["free_elective"] = credits_by_code.get("free_elective", Decimal("0")) + credit
                names_by_code.setdefault("free_elective", []).append(
                    f"{rec.raw_course_name} (타학과 과목 → 일반선택으로 인정)"
                )
                continue

        for code in codes:
            credits_by_code[code] = credits_by_code.get(code, Decimal("0")) + credit
            names_by_code.setdefault(code, []).append(rec.raw_course_name)

    if unmapped_courses:
        shown = ", ".join(unmapped_courses[:5])
        more = " 등" if len(unmapped_courses) > 5 else ""
        warnings.append(
            f"대분류 매핑에 없는 category 값이라 집계에서 제외된 과목 "
            f"{len(unmapped_courses)}건: {shown}{more}"
        )

    results: list[CategoryResult] = []
    for cat in categories:
        minimum = _parse_credits(cat.minimum_credits)
        reachable = cat.category_code in {c for codes in RAW_CATEGORY_TO_CODES.values() for c in codes}
        earned = credits_by_code.get(cat.category_code, Decimal("0"))

        if minimum is None:
            satisfied, reason = None, "minimum_credits 값이 숫자가 아니어서 판정 불가"
        elif not reachable:
            satisfied, reason = None, "학생 이수내역의 대분류 category로는 세부 영역을 구분할 수 없어 판정 불가"
        else:
            satisfied, reason = earned >= minimum, None

        results.append(
            CategoryResult(
                category_code=cat.category_code,
                category_name=cat.category_name,
                minimum_credits=minimum,
                earned_credits=earned,
                satisfied=satisfied,
                reason=reason,
                matched_course_names=names_by_code.get(cat.category_code, []),
            )
        )
    return results, warnings


def _evaluate_required_courses(
    db: Session, requirement_set_id: int, course_records: list[StudentCourseRecord]
) -> RequiredCourseResult:
    required = db.scalars(
        select(RequirementCourse).where(
            RequirementCourse.requirement_set_id == requirement_set_id,
            RequirementCourse.needs_review.is_(False),
            RequirementCourse.choice_rule_types.is_(None),
        )
    ).all()
    if not required:
        return RequiredCourseResult(status="no_data")

    completed_names = {
        (rec.raw_course_name or "").strip() for rec in course_records
    }
    missing: list[str] = []
    completed: list[str] = []
    for req in required:
        name = (req.matched_course_name or req.raw_course_name or "").strip()
        if name and name in completed_names:
            completed.append(name)
        elif name:
            missing.append(name)

    return RequiredCourseResult(status="checked", missing_course_names=missing, completed_course_names=completed)


def evaluate_program(
    db: Session, program: UserAcademicProgram, course_records: list[StudentCourseRecord]
) -> ProgramEvaluation:
    requirement_set, warnings = _find_requirement_set(
        db, program.academic_program_code, program.program_type, program.curriculum_year
    )

    evaluation = ProgramEvaluation(
        user_academic_program_id=program.id,
        program_type=program.program_type,
        major=program.major,
        academic_program_code=program.academic_program_code,
        curriculum_year_used=requirement_set.curriculum_year if requirement_set else None,
        requirement_set_id=requirement_set.id if requirement_set else None,
        status="no_requirement_set" if requirement_set is None else "evaluated",
        warnings=warnings,
    )

    if requirement_set is None:
        evaluation.warnings.append(
            f"'{program.major}'({program.program_type}) 조합의 졸업요건 데이터가 아직 없음"
        )
        return evaluation

    categories, cat_warnings = _evaluate_categories(db, requirement_set, course_records)
    evaluation.warnings.extend(cat_warnings)

    if not categories:
        evaluation.status = "no_reviewed_categories"
        evaluation.warnings.append("검토 완료(needs_review=false)된 학점 기준 카테고리가 없어 판정 불가")
        return evaluation

    evaluation.categories = categories
    evaluation.required_courses = _evaluate_required_courses(db, requirement_set.id, course_records)
    return evaluation


def evaluate_graduation(db: Session, user_id: int) -> list[ProgramEvaluation]:
    """활성 상태인 사용자의 모든 학적 프로그램(주전공/복수전공/부전공/연계전공)을 평가한다."""
    programs = db.scalars(
        select(UserAcademicProgram).where(
            UserAcademicProgram.user_id == user_id,
            UserAcademicProgram.status == "active",
        )
    ).all()
    course_records = db.scalars(
        select(StudentCourseRecord).where(StudentCourseRecord.user_id == user_id)
    ).all()
    return [evaluate_program(db, p, course_records) for p in programs]
