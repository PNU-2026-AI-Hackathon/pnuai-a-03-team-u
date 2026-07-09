"""규칙 기반 졸업요건 판정 엔진 (MVP).

`requirement_sets`/`requirement_categories`/`requirement_courses` 시드 데이터를
학생의 `student_course_records`와 대조해 프로그램(주전공/복수전공/부전공/연계전공)별로
카테고리 충족 여부를 계산한다.

현재 시드 데이터의 한계 때문에 아래 범위로 판정을 제한한다 (자세한 내용은
docs/CHANGELOG.md의 최신 DB seed/졸업요건 항목 참고):

- `student_course_records.category`는 크롤러가 주는 대분류 텍스트(예: "전공필수",
  "교양")뿐이라 효원핵심/효원균형/효원창의 같은 세부 교양 영역은 구분할 수 없다.
  `RAW_CATEGORY_TO_CODES`에 없는 category_code는 항상 satisfied=None(판정 불가)으로 둔다.
- `requirement_categories.minimum_credits`는 자유 텍스트라 "-"처럼 숫자가 아닌 값이
  섞여 있다. 파싱 실패 시 판정 불가로 처리한다.
- `curriculum_year`가 시드 데이터에 "2026"만 있어, 학생의 실제 입학연도와 정확히
  일치하는 요건 세트가 없으면 최신 연도로 대체하고 warning을 남긴다.
- university_default 폴백, offering_status="not_offered" 판정, 교직
  (teacher_training_*) 카테고리 학점 매핑, 조건그룹(택N/M) 판정은 스키마만
  준비된 상태로 아직 미구현이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.courses.models import Course
from app.domains.academics.models import (
    Department,
    Major,
    RequirementCategory,
    RequirementCourse,
    RequirementSet,
    StudentCourseRecord,
    UserAcademicProgram,
)

# 학생 이수내역의 대분류 category 값 -> requirement_categories.category_code.
# 여기 없는 category_code(예: general_core/general_balanced/general_creative)는
# 현재 데이터로는 안전하게 산출할 수 없어 의도적으로 매핑하지 않는다.
RAW_CATEGORY_TO_CODES: dict[str, tuple[str, ...]] = {
    "전공필수": ("major_required",),
    "전공선택": ("major_elective",),
    "전공기초": ("major_foundation",),
    "심화전공": ("deep_major",),
    "교양": ("general_total",),
    "일반선택": ("free_elective",),
}

# 최소전공 총학점(주로 복수전공/부전공 요건) 집계 카테고리 — 개별 코드 학점의 합으로
# 판정한다. 심화전공(deep_major)은 최소전공 정의(전공기초+전공필수+전공선택)에
# 포함되지 않으므로 제외.
MAJOR_TOTAL_CATEGORY_CODES: tuple[str, ...] = ("minimum_major_total", "major_total")
MAJOR_TOTAL_COMPONENT_CODES: tuple[str, ...] = (
    "major_foundation",
    "major_required",
    "major_elective",
)

# requirement_courses 중 "이 특정 과목을 반드시 이수해야 한다"는 의미인 category_code만.
# major_elective/general_elective_area/free_elective는 여러 과목 중 학점 기준을 채우면
# 되는 메뉴형 이수 규칙이라, 특정 한 과목을 안 들었다고 미이수로 잡으면 안 된다
# (그런 카테고리는 이수학점 기준 판정만 가능 — _evaluate_categories 참고).
MANDATORY_COURSE_CATEGORIES: tuple[str, ...] = (
    "major_required",
    "major_foundation",
    "general_required",
    "teacher_training_basic",
)


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
    required_total_credits: Decimal | None = None
    earned_total_credits: Decimal = Decimal("0")
    remaining_total_credits: Decimal | None = None
    satisfied: bool | None = None
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


def _resolve_program_display_name(db: Session, program: UserAcademicProgram) -> str | None:
    """표시용 전공/학과명. major_id 우선, 없으면 department_id로 해석한다."""
    if program.major_id:
        name = db.scalar(select(Major.name).where(Major.id == program.major_id))
        if name:
            return name
    if program.department_id:
        return db.scalar(select(Department.name).where(Department.id == program.department_id))
    return None


def _resolve_program_code(db: Session, program: UserAcademicProgram) -> tuple[str | None, list[str]]:
    """요건세트 조회용 academic_program_code.

    portal-sync/signup이 아직 code를 못 채운 과거 데이터도 평가할 수 있도록
    major/department 브리지 컬럼에서 한 번 더 보강한다.
    """
    if program.academic_program_code:
        return program.academic_program_code, []

    if program.major_id:
        code = db.scalar(select(Major.academic_program_code).where(Major.id == program.major_id))
        if code:
            return code, ["user_academic_programs.academic_program_code가 비어 있어 major 브리지 코드로 판정함"]

    if program.department_id:
        code = db.scalar(
            select(Department.academic_program_code).where(Department.id == program.department_id)
        )
        if code:
            return code, ["user_academic_programs.academic_program_code가 비어 있어 department 브리지 코드로 판정함"]

    return None, ["academic_program_code가 없어 요건 세트를 찾을 수 없음"]


def _find_requirement_set(
    db: Session,
    academic_program_code: str | None,
    program_type: str,
    curriculum_year: str | None,
) -> tuple[RequirementSet | None, list[str]]:
    warnings: list[str] = []
    if not academic_program_code:
        return None, []

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


def _sum_credits(course_records: list[StudentCourseRecord]) -> Decimal:
    return sum(
        (Decimal(str(rec.credits)) for rec in course_records if rec.credits is not None),
        Decimal("0"),
    )


def _remaining(required: Decimal | None, earned: Decimal) -> Decimal | None:
    if required is None:
        return None
    return max(required - earned, Decimal("0"))


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
            # 타학과 판별은 courses.department_id ↔ requirement_sets.department_id
            # FK 비교로만 한다. 어느 한쪽이라도 비어 있으면 판별하지 않는다
            # (courses가 비어 있는 환경에서는 이 필터가 동작하지 않는 알려진 한계).
            is_diff_dept = bool(
                course.department_id
                and requirement_set.department_id
                and course.department_id != requirement_set.department_id
            )

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
        if cat.category_code in MAJOR_TOTAL_CATEGORY_CODES:
            # 최소전공 총학점: 전공기초+전공필수+전공선택 합산으로 판정한다.
            # (타학과 과목 재분류가 이미 credits_by_code에 반영된 뒤라 그대로 합산하면 됨)
            reachable = True
            earned = sum(
                (credits_by_code.get(code, Decimal("0")) for code in MAJOR_TOTAL_COMPONENT_CODES),
                Decimal("0"),
            )
            matched_names = [
                name
                for code in MAJOR_TOTAL_COMPONENT_CODES
                for name in names_by_code.get(code, [])
            ]
        else:
            reachable = cat.category_code in {c for codes in RAW_CATEGORY_TO_CODES.values() for c in codes}
            earned = credits_by_code.get(cat.category_code, Decimal("0"))
            matched_names = names_by_code.get(cat.category_code, [])

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
                matched_course_names=matched_names,
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
            RequirementCourse.category_code.in_(MANDATORY_COURSE_CATEGORIES),
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
        raw_name = (req.matched_course_name or req.raw_course_name or "").strip()
        if not raw_name:
            continue
        # matched_course_name/matched_course_code는 같은 요건을 여러 과목 중 하나로
        # 채울 수 있는 경우(택1) "이름1|이름2"처럼 파이프로 묶여 한 행에 들어올 수
        # 있다. 대체 과목 중 하나만 이수해도 충족으로 인정해야 하며, 문자열 그대로
        # 비교하면 어떤 학생도 절대 충족시킬 수 없다.
        alternatives = [n.strip() for n in raw_name.split("|") if n.strip()]
        display_name = " / ".join(alternatives)
        if any(alt in completed_names for alt in alternatives):
            completed.append(display_name)
        else:
            missing.append(display_name)

    return RequiredCourseResult(status="checked", missing_course_names=missing, completed_course_names=completed)


def evaluate_program(
    db: Session, program: UserAcademicProgram, course_records: list[StudentCourseRecord]
) -> ProgramEvaluation:
    academic_program_code, code_warnings = _resolve_program_code(db, program)
    requirement_set, warnings = _find_requirement_set(
        db, academic_program_code, program.program_type, program.curriculum_year
    )
    warnings = code_warnings + warnings
    display_name = _resolve_program_display_name(db, program)
    earned_total = _sum_credits(course_records)
    required_total = (
        Decimal(str(requirement_set.required_total_credits))
        if requirement_set and requirement_set.required_total_credits is not None
        else None
    )

    evaluation = ProgramEvaluation(
        user_academic_program_id=program.id,
        program_type=program.program_type,
        major=display_name,
        academic_program_code=academic_program_code,
        curriculum_year_used=requirement_set.curriculum_year if requirement_set else None,
        requirement_set_id=requirement_set.id if requirement_set else None,
        required_total_credits=required_total,
        earned_total_credits=earned_total,
        remaining_total_credits=_remaining(required_total, earned_total),
        status="no_requirement_set" if requirement_set is None else "evaluated",
        warnings=warnings,
    )

    if requirement_set is None:
        evaluation.warnings.append(
            f"'{display_name or program.academic_program_code or '(미상)'}'"
            f"({program.program_type}) 조합의 졸업요건 데이터가 아직 없음"
        )
        return evaluation

    categories, cat_warnings = _evaluate_categories(db, requirement_set, course_records)
    evaluation.warnings.extend(cat_warnings)

    if not categories:
        evaluation.status = "no_reviewed_categories"
        evaluation.satisfied = None
        evaluation.warnings.append("검토 완료(needs_review=false)된 학점 기준 카테고리가 없어 판정 불가")
        return evaluation

    evaluation.categories = categories
    evaluation.required_courses = _evaluate_required_courses(db, requirement_set.id, course_records)
    has_failed_category = any(cat.satisfied is False for cat in categories)
    has_unknown_category = any(cat.satisfied is None for cat in categories)
    has_missing_required = bool(evaluation.required_courses.missing_course_names)
    has_total_shortage = (
        evaluation.remaining_total_credits is not None and evaluation.remaining_total_credits > 0
    )

    if has_failed_category or has_missing_required or has_total_shortage:
        evaluation.satisfied = False
    elif has_unknown_category:
        evaluation.satisfied = None
    else:
        evaluation.satisfied = True
    return evaluation


def evaluate_graduation(
    db: Session, user_id: int, program_types: set[str] | None = None
) -> list[ProgramEvaluation]:
    """활성 상태인 사용자의 학적 프로그램을 평가한다.

    program_types를 넘기면 해당 이수유형만 평가한다. 현재 서비스 API는
    부전공/복수전공/교직 seed가 완성될 때까지 primary만 기본 평가한다.
    """
    programs = db.scalars(
        select(UserAcademicProgram).where(
            UserAcademicProgram.user_id == user_id,
            UserAcademicProgram.status == "active",
        )
    ).all()
    if program_types is not None:
        programs = [program for program in programs if program.program_type in program_types]
    course_records = db.scalars(
        select(StudentCourseRecord).where(StudentCourseRecord.user_id == user_id)
    ).all()
    return [evaluate_program(db, p, course_records) for p in programs]
