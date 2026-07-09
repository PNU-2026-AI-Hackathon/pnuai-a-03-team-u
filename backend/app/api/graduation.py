"""졸업요건 계산 API.

현재 공개 API는 주전공(primary) 계산을 기본으로 한다. 부전공/복수전공/교직은
요건 seed가 완성된 뒤 include_non_primary=true 경로를 안정화한다.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.academics.graduation_engine import (
    CategoryResult,
    ProgramEvaluation,
    evaluate_graduation,
)
from app.domains.users.models import User

router = APIRouter(prefix="/me/graduation", tags=["graduation"])


def _decimal_to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


class CategoryEvaluationResponse(BaseModel):
    category_code: str
    category_name: str | None
    minimum_credits: float | None
    earned_credits: float
    remaining_credits: float | None
    satisfied: bool | None
    reason: str | None
    matched_course_names: list[str]

    @classmethod
    def from_result(cls, result: CategoryResult) -> "CategoryEvaluationResponse":
        remaining = None
        if result.minimum_credits is not None:
            remaining = max(result.minimum_credits - result.earned_credits, Decimal("0"))
        return cls(
            category_code=result.category_code,
            category_name=result.category_name,
            minimum_credits=_decimal_to_float(result.minimum_credits),
            earned_credits=float(result.earned_credits),
            remaining_credits=_decimal_to_float(remaining),
            satisfied=result.satisfied,
            reason=result.reason,
            matched_course_names=result.matched_course_names,
        )


class RequiredCourseEvaluationResponse(BaseModel):
    status: str
    missing_course_names: list[str]
    completed_course_names: list[str]


class ProgramEvaluationResponse(BaseModel):
    user_academic_program_id: int
    program_type: str
    major: str | None
    academic_program_code: str | None
    curriculum_year_used: str | None
    requirement_set_id: int | None
    status: str
    required_total_credits: float | None
    earned_total_credits: float
    remaining_total_credits: float | None
    satisfied: bool | None
    categories: list[CategoryEvaluationResponse]
    required_courses: RequiredCourseEvaluationResponse | None
    warnings: list[str]

    @classmethod
    def from_evaluation(cls, evaluation: ProgramEvaluation) -> "ProgramEvaluationResponse":
        required_courses = None
        if evaluation.required_courses is not None:
            required_courses = RequiredCourseEvaluationResponse(
                status=evaluation.required_courses.status,
                missing_course_names=evaluation.required_courses.missing_course_names,
                completed_course_names=evaluation.required_courses.completed_course_names,
            )
        return cls(
            user_academic_program_id=evaluation.user_academic_program_id,
            program_type=evaluation.program_type,
            major=evaluation.major,
            academic_program_code=evaluation.academic_program_code,
            curriculum_year_used=evaluation.curriculum_year_used,
            requirement_set_id=evaluation.requirement_set_id,
            status=evaluation.status,
            required_total_credits=_decimal_to_float(evaluation.required_total_credits),
            earned_total_credits=float(evaluation.earned_total_credits),
            remaining_total_credits=_decimal_to_float(evaluation.remaining_total_credits),
            satisfied=evaluation.satisfied,
            categories=[
                CategoryEvaluationResponse.from_result(category)
                for category in evaluation.categories
            ],
            required_courses=required_courses,
            warnings=evaluation.warnings,
        )


class GraduationEvaluationResponse(BaseModel):
    user_id: int
    scope: str
    programs: list[ProgramEvaluationResponse]
    warnings: list[str]


@router.get("", response_model=GraduationEvaluationResponse)
def get_graduation_evaluation(
    include_non_primary: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GraduationEvaluationResponse:
    """현재 사용자의 졸업요건 충족 여부를 계산한다.

    기본값은 주전공(primary)만 평가한다. 부전공/복수전공/교직은 아직 seed 우선순위에서
    제외되어 있으므로, 명시적으로 include_non_primary=true를 준 경우에만 같이 노출한다.
    """
    program_types = None if include_non_primary else {"primary"}
    evaluations = evaluate_graduation(db, current_user.id, program_types=program_types)
    warnings = []
    if not include_non_primary:
        warnings.append("부전공/복수전공/교직 요건은 아직 seed 미완성이라 기본 계산에서 제외됨")
    return GraduationEvaluationResponse(
        user_id=current_user.id,
        scope="all_active_programs" if include_non_primary else "primary_only",
        programs=[
            ProgramEvaluationResponse.from_evaluation(evaluation)
            for evaluation in evaluations
        ],
        warnings=warnings,
    )
