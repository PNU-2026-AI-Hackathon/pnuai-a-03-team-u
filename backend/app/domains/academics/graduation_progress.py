"""flat graduation_requirements 테이블과 학생 이수내역(student_course_records)을
카테고리별로 단순 대조해 졸업까지 남은 학점을 계산한다.

requirement_sets/requirement_categories/requirement_courses(graduation_engine)와
달리 택N/M·개별 필수과목 판정은 하지 않고, 이수구분별 합계 학점만 비교한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domains.academics.models import GraduationRequirement, StudentCourseRecord, UserAcademicProgram

# StudentCourseRecord.category(성적표 원문 정규화 값) -> GraduationRequirement의
# 기준학점 컬럼 매핑. "심화전공"은 우리 카테고리 체계에 없어 전공선택에 흡수된다.
_CATEGORY_TO_REQUIRED_FIELD: dict[str, str] = {
    "전공기초": "required_major_foundation",
    "전공필수": "required_major_required",
    "전공선택": "required_major_elective",
    "교양필수": "required_general_required",
    "교양선택": "required_general_elective",
    "일반선택": "required_free_elective",
}

# required_field -> 표시용 카테고리 이름
_REQUIRED_FIELD_TO_LABEL: dict[str, str] = {
    "required_major_foundation": "전공기초",
    "required_major_required": "전공필수",
    "required_major_elective": "전공선택",
    "required_general_required": "교양필수",
    "required_general_elective": "교양선택",
    "required_free_elective": "일반선택",
}


@dataclass
class CategoryProgress:
    category_code: str
    category_name: str
    required_credits: Decimal | None
    earned_credits: Decimal
    remaining_credits: Decimal | None
    satisfied: bool | None


@dataclass
class ProgramProgress:
    user_academic_program_id: int
    program_type: str
    department_id: int | None
    major_id: int | None
    curriculum_year: str | None
    requirement_found: bool
    required_total_credits: int | None
    earned_total_credits: Decimal
    remaining_total_credits: Decimal | None
    satisfied: bool | None
    categories: list[CategoryProgress] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _find_requirement(
    db: Session, program: UserAcademicProgram
) -> GraduationRequirement | None:
    """program_type + curriculum_year + (major_id 우선, 없으면 department_id)로
    가장 구체적인 기준학점 행을 찾는다. 정확한 연도 매칭이 없으면 같은
    학과/전공의 가장 최근 연도 행으로 폴백한다.
    """
    if program.major_id is None and program.department_id is None:
        return None

    query = db.query(GraduationRequirement).filter(
        GraduationRequirement.program_type == program.program_type
    )
    if program.major_id is not None:
        query = query.filter(GraduationRequirement.major_id == program.major_id)
    else:
        query = query.filter(
            GraduationRequirement.department_id == program.department_id,
            GraduationRequirement.major_id.is_(None),
        )

    if program.curriculum_year:
        exact = query.filter(
            GraduationRequirement.curriculum_year == program.curriculum_year
        ).one_or_none()
        if exact is not None:
            return exact

    return query.order_by(GraduationRequirement.curriculum_year.desc()).first()


def _earned_credits_by_category(db: Session, user_id: int) -> dict[str, Decimal]:
    rows = (
        db.query(StudentCourseRecord.category, func.sum(StudentCourseRecord.credits))
        .filter(StudentCourseRecord.user_id == user_id)
        .group_by(StudentCourseRecord.category)
        .all()
    )
    return {category: (total or Decimal("0")) for category, total in rows if category}


def compute_graduation_progress(
    db: Session, user_id: int, program_types: set[str] | None = None
) -> list[ProgramProgress]:
    """사용자의 활성 학적 프로그램별로 기준학점 대비 이수학점/남은 학점을 계산한다."""
    programs_query = db.query(UserAcademicProgram).filter(
        UserAcademicProgram.user_id == user_id,
        UserAcademicProgram.status == "active",
    )
    if program_types:
        programs_query = programs_query.filter(
            UserAcademicProgram.program_type.in_(program_types)
        )
    programs = programs_query.all()

    earned_by_category = _earned_credits_by_category(db, user_id)
    total_earned = sum(earned_by_category.values(), Decimal("0"))

    results: list[ProgramProgress] = []
    for program in programs:
        requirement = _find_requirement(db, program)
        warnings: list[str] = []

        if requirement is None:
            results.append(
                ProgramProgress(
                    user_academic_program_id=program.id,
                    program_type=program.program_type,
                    department_id=program.department_id,
                    major_id=program.major_id,
                    curriculum_year=program.curriculum_year,
                    requirement_found=False,
                    required_total_credits=None,
                    earned_total_credits=total_earned,
                    remaining_total_credits=None,
                    satisfied=None,
                    categories=[],
                    warnings=["해당 학과/전공×이수유형의 기준학점 데이터가 없어 계산할 수 없음"],
                )
            )
            continue

        if requirement.curriculum_year != program.curriculum_year:
            warnings.append(
                f"학생 교육과정연도({program.curriculum_year})와 정확히 일치하는 기준학점이 없어 "
                f"{requirement.curriculum_year}년 기준으로 대체함"
            )

        categories: list[CategoryProgress] = []
        for required_field, label in _REQUIRED_FIELD_TO_LABEL.items():
            required_value = getattr(requirement, required_field)
            earned_value = earned_by_category.get(label, Decimal("0"))
            remaining = None
            satisfied = None
            if required_value is not None:
                remaining = max(Decimal(required_value) - earned_value, Decimal("0"))
                satisfied = earned_value >= Decimal(required_value)
            categories.append(
                CategoryProgress(
                    category_code=required_field,
                    category_name=label,
                    required_credits=Decimal(required_value) if required_value is not None else None,
                    earned_credits=earned_value,
                    remaining_credits=remaining,
                    satisfied=satisfied,
                )
            )

        required_total = requirement.required_total_credits
        remaining_total = None
        satisfied_total = None
        if required_total is not None:
            remaining_total = max(Decimal(required_total) - total_earned, Decimal("0"))
            satisfied_total = total_earned >= Decimal(required_total)

        results.append(
            ProgramProgress(
                user_academic_program_id=program.id,
                program_type=program.program_type,
                department_id=program.department_id,
                major_id=program.major_id,
                curriculum_year=program.curriculum_year,
                requirement_found=True,
                required_total_credits=required_total,
                earned_total_credits=total_earned,
                remaining_total_credits=remaining_total,
                satisfied=satisfied_total,
                categories=categories,
                warnings=warnings,
            )
        )

    return results
