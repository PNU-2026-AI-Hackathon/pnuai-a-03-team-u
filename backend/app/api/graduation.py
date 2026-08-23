"""flat graduation_requirements 기준 졸업 진행 현황 API.

학과별 기준학점(graduation_requirements)과 학생 이수내역(student_course_records)을
이수구분별 합계로 대조해 졸업까지 남은 학점을 계산한다. 택N/M·개별 필수과목
판정은 하지 않는 단순 합계 비교다.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.academics.models import (
    Department,
    Major,
    StudentGraduationCategory,
    StudentGraduationRequirement,
)
from app.domains.academics.graduation_progress import (
    CategoryProgress,
    ProgramProgress,
    compute_graduation_progress,
)
from app.domains.users.models import User

router = APIRouter(prefix="/me/graduation", tags=["graduation"])


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
    department_name: str | None = None
    major_id: int | None
    major_name: str | None = None
    is_ai_track: bool = False
    curriculum_year: str | None
    requirement_found: bool
    required_total_credits: float | None
    earned_total_credits: float
    remaining_total_credits: float | None
    satisfied: bool | None
    categories: list[CategoryProgressResponse]
    warnings: list[str]

    @classmethod
    def from_progress(
        cls, progress: ProgramProgress, db: Session | None = None
    ) -> "ProgramProgressResponse":
        department = (
            db.get(Department, progress.department_id)
            if db and progress.department_id
            else None
        )
        major = db.get(Major, progress.major_id) if db and progress.major_id else None
        return cls(
            user_academic_program_id=progress.user_academic_program_id,
            program_type=progress.program_type,
            department_id=progress.department_id,
            department_name=department.name if department else None,
            major_id=progress.major_id,
            major_name=major.name if major else None,
            is_ai_track=progress.is_ai_track,
            curriculum_year=progress.curriculum_year,
            requirement_found=progress.requirement_found,
            required_total_credits=progress.required_total_credits,
            earned_total_credits=float(progress.earned_total_credits),
            remaining_total_credits=_decimal_to_float(progress.remaining_total_credits),
            satisfied=progress.satisfied,
            categories=[CategoryProgressResponse.from_result(category) for category in progress.categories],
            warnings=progress.warnings,
        )


class GraduationProgressResponse(BaseModel):
    user_id: int
    programs: list[ProgramProgressResponse]


class GraduationOverrideInput(BaseModel):
    required_total_credits: float | None
    earned_total_credits: float
    categories: list[CategoryProgressResponse]

    @model_validator(mode="after")
    def validate_totals(self):
        category_codes = [category.category_code for category in self.categories]
        if len(category_codes) != len(set(category_codes)):
            raise ValueError("졸업요건 하위 항목이 중복되었습니다")

        earned_total = sum(category.earned_credits for category in self.categories)
        required_total = sum(category.required_credits or 0 for category in self.categories)
        if abs(self.earned_total_credits - earned_total) >= 0.001:
            raise ValueError("총 이수학점은 하위 항목의 이수학점 합계와 같아야 합니다")
        if self.required_total_credits is None or abs(self.required_total_credits - required_total) >= 0.001:
            raise ValueError("졸업 기준학점은 하위 항목의 기준학점 합계와 같아야 합니다")
        return self


def _apply_user_override(
    progress: ProgramProgressResponse, override_data: dict | None
) -> ProgramProgressResponse:
    if progress.program_type != "primary" or not override_data:
        return progress

    override = GraduationOverrideInput.model_validate(override_data)
    required_total = override.required_total_credits
    remaining_total = (
        max(0.0, required_total - override.earned_total_credits)
        if required_total is not None
        else None
    )
    return progress.model_copy(
        update={
            "required_total_credits": required_total,
            "earned_total_credits": override.earned_total_credits,
            "remaining_total_credits": remaining_total,
            "satisfied": (
                override.earned_total_credits >= required_total
                if required_total is not None
                else None
            ),
            "categories": override.categories,
            "warnings": [
                *progress.warnings,
                "사용자가 저장한 졸업요건 보정값이 적용되었습니다.",
            ],
        }
    )


def _build_graduation_response(
    db: Session, current_user: User, include_non_primary: bool = False
) -> GraduationProgressResponse:
    program_types = None if include_non_primary else {"primary"}
    progresses = compute_graduation_progress(db, current_user.id, program_types=program_types)
    return GraduationProgressResponse(
        user_id=current_user.id,
        programs=[
            _apply_user_override(
                ProgramProgressResponse.from_progress(progress, db),
                current_user.graduation_override,
            )
            for progress in progresses
        ],
    )


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
    return _build_graduation_response(db, current_user, include_non_primary)


@router.patch("/override", response_model=GraduationProgressResponse)
def save_graduation_override(
    payload: GraduationOverrideInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GraduationProgressResponse:
    """공식 학과 기준은 유지하고 현재 사용자에게만 적용할 보정값을 저장한다."""
    current_user.graduation_override = payload.model_dump(mode="json")
    db.commit()
    db.refresh(current_user)
    return _build_graduation_response(db, current_user)


@router.delete("/override", status_code=204)
def delete_graduation_override(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    current_user.graduation_override = None
    db.commit()


# --- 학교 공식 판정 스냅샷 -------------------------------------------------
#
# 위의 `GET /me/graduation`은 **우리 엔진의 추정**이다 — 우리가 수집한 학과 기준학점
# (`graduation_requirements`)과 성적표 카테고리 합계를 대조한 결과. 아래는 **학교가
# 직접 판정한 값**(One-Stop 졸업예정정보)이라 성격이 다르다.
#
# 둘을 한 응답에 섞지 않는 이유: 어긋날 때 어느 쪽이 학교 판정인지 구분이 안 되면
# 사용자가 잘못된 쪽을 믿는다. 어긋나면 **학교 쪽이 맞다.**


class OfficialCategoryResponse(BaseModel):
    program_type: str
    category: str
    required_credits: float | None
    earned_credits: float | None
    registered_credits: float | None
    expected_credits: float | None
    satisfied: bool | None
    failure_reason: str | None


class OfficialRequirementResponse(BaseModel):
    program_type: str
    requirement_name: str
    detail_name: str
    pass_type: str | None
    acquired_date: str | None
    satisfied: bool | None
    note: str | None


class OfficialGraduationStatusResponse(BaseModel):
    """학교 공식 판정 스냅샷. 한 번도 동기화 안 했으면 전부 빈 배열 + synced_at=None."""

    user_id: int
    synced_at: str | None
    categories: list[OfficialCategoryResponse]
    requirements: list[OfficialRequirementResponse]


@router.get("/official", response_model=OfficialGraduationStatusResponse)
def get_official_graduation_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OfficialGraduationStatusResponse:
    """One-Stop 졸업예정정보에서 가져온 **학교 공식** 졸업 판정.

    포털 동기화(`POST /me/portal-sync`) 시점의 스냅샷이라 실시간이 아니다 —
    `synced_at`으로 언제 기준인지 알려준다.
    """
    categories = db.scalars(
        select(StudentGraduationCategory)
        .where(StudentGraduationCategory.user_id == current_user.id)
        .order_by(StudentGraduationCategory.program_type, StudentGraduationCategory.id)
    ).all()
    requirements = db.scalars(
        select(StudentGraduationRequirement)
        .where(StudentGraduationRequirement.user_id == current_user.id)
        .order_by(StudentGraduationRequirement.program_type, StudentGraduationRequirement.id)
    ).all()

    stamps = [row.synced_at for row in (*categories, *requirements) if row.synced_at]
    return OfficialGraduationStatusResponse(
        user_id=current_user.id,
        synced_at=max(stamps).isoformat() if stamps else None,
        categories=[
            OfficialCategoryResponse(
                program_type=row.program_type,
                category=row.category,
                required_credits=_decimal_to_float(row.required_credits),
                earned_credits=_decimal_to_float(row.earned_credits),
                registered_credits=_decimal_to_float(row.registered_credits),
                expected_credits=_decimal_to_float(row.expected_credits),
                satisfied=row.satisfied,
                failure_reason=row.failure_reason,
            )
            for row in categories
        ],
        requirements=[
            OfficialRequirementResponse(
                program_type=row.program_type,
                requirement_name=row.requirement_name,
                detail_name=row.detail_name,
                pass_type=row.pass_type,
                acquired_date=row.acquired_date,
                satisfied=row.satisfied,
                note=row.note,
            )
            for row in requirements
        ],
    )
