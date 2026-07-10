"""flat graduation_requirements 기준 졸업 진행 현황 API.

requirement_sets 기반 판정 엔진(app/api/graduation.py)과 별개로, 학과별
기준학점(graduation_requirements)과 학생 이수내역을 카테고리 합계로만 단순
대조한다. 택N/M·개별 필수과목 판정은 하지 않는다.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.academics.graduation_progress import (
    CategoryProgress,
    ProgramProgress,
    compute_graduation_progress,
)
from app.domains.users.models import User

router = APIRouter(prefix="/me/graduation-progress", tags=["graduation"])


def _decimal_to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


class CategoryProgressResponse(BaseModel):
    category_code: str
    category_name: str
    required_credits: float | None
    earned_credits: float
    remaining_credits: float | None
    satisfied: bool | None

    @classmethod
    def from_result(cls, result: CategoryProgress) -> "CategoryProgressResponse":
        return cls(
            category_code=result.category_code,
            category_name=result.category_name,
            required_credits=_decimal_to_float(result.required_credits),
            earned_credits=float(result.earned_credits),
            remaining_credits=_decimal_to_float(result.remaining_credits),
            satisfied=result.satisfied,
        )


class ProgramProgressResponse(BaseModel):
    user_academic_program_id: int
    program_type: str
    department_id: int | None
    major_id: int | None
    curriculum_year: str | None
    requirement_found: bool
    required_total_credits: int | None
    earned_total_credits: float
    remaining_total_credits: float | None
    satisfied: bool | None
    categories: list[CategoryProgressResponse]
    warnings: list[str]

    @classmethod
    def from_progress(cls, progress: ProgramProgress) -> "ProgramProgressResponse":
        return cls(
            user_academic_program_id=progress.user_academic_program_id,
            program_type=progress.program_type,
            department_id=progress.department_id,
            major_id=progress.major_id,
            curriculum_year=progress.curriculum_year,
            requirement_found=progress.requirement_found,
            required_total_credits=progress.required_total_credits,
            earned_total_credits=float(progress.earned_total_credits),
            remaining_total_credits=_decimal_to_float(progress.remaining_total_credits),
            satisfied=progress.satisfied,
            categories=[
                CategoryProgressResponse.from_result(category)
                for category in progress.categories
            ],
            warnings=progress.warnings,
        )


class GraduationProgressResponse(BaseModel):
    user_id: int
    programs: list[ProgramProgressResponse]


@router.get("", response_model=GraduationProgressResponse)
def get_graduation_progress(
    include_non_primary: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GraduationProgressResponse:
    """현재 사용자의 학과별 기준학점 대비 졸업까지 남은 학점을 계산한다.

    기본값은 주전공(primary)만 계산한다. 복수전공/부전공까지 보려면
    include_non_primary=true.
    """
    program_types = None if include_non_primary else {"primary"}
    progresses = compute_graduation_progress(db, current_user.id, program_types=program_types)
    return GraduationProgressResponse(
        user_id=current_user.id,
        programs=[ProgramProgressResponse.from_progress(p) for p in progresses],
    )
