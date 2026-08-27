"""이수 가능한 융합전공 / 연계전공 / AI(SW)융합트랙 조회·이수계획 저장.

로드맵 화면의 "AI융합 가능" 버튼이 쓴다. 학생 소속 학과
(`current_user.department_id`)가 그 프로그램의 **참여 학과**
(= `program_courses`가 인정하는 과목들의 distinct `courses.department_id`) 중
하나일 때만 노출한다. 학생 본인의 주전공 프로그램은 제외한다.

프로그램 식별: `majors.name` / `departments.name` 접미사(`(SW융합트랙)` /
`(SW연계전공)` / `(SW융합전공)` 등, 부분문자열 `융합트랙` / `연계전공` / `융합전공`)와
`is_ai_track()`. `program_type`은 필터로 쓰지 않는다 — SW 계열은 `interdisciplinary`,
`seed_interdisciplinary_majors_2026_08`은 `minor` / `dual`. 단 `primary` 행은 제외한다
(지능형헬스사이언스융합전공·핀테크융합전공처럼 주전공 세부전공으로도 등록된 케이스 방어).

엔드포인트:
- GET /me/fusion-programs/available
- POST /me/fusion-programs/enroll
- DELETE /me/fusion-programs/{user_academic_program_id}
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.academics.fusion_catalog import (
    ENROLLMENT_TYPE_LABELS as _ENROLLMENT_TYPE_LABELS,
)
from app.domains.academics.fusion_catalog import (
    available_fusion_programs,
    classify as _classify,
    participating_departments as _participating_departments,
    student_can_pursue as _student_can_pursue,
)
from app.domains.academics.models import (
    Department,
    GraduationRequirement,
    Major,
    UserAcademicProgram,
)
from app.domains.users.models import User

router = APIRouter(prefix="/me/fusion-programs", tags=["fusion-programs"])


class ParticipatingDepartment(BaseModel):
    id: int
    name: str


class FusionProgramOption(BaseModel):
    program_id: int  # graduation_requirements.id
    department_id: int  # 개설(host) 학과
    department_name: str
    major_id: int | None  # 학과 자체가 프로그램이면 None (핀테크/반도체 등)
    program_name: str  # major.name or department.name
    kind: str  # "track" | "linked" | "convergence"
    kind_label: str  # "융합트랙" | "연계전공" | "융합전공"
    program_type: str | None  # 원시값: interdisciplinary | minor | dual
    program_type_label: str | None  # "부전공" | "복수전공" | None
    total_credits: int | None
    curriculum_year: str | None
    participating_departments: list[ParticipatingDepartment]
    enrolled: bool
    user_academic_program_id: int | None
    enrollment_editable: bool


class EnrollFusionProgramRequest(BaseModel):
    program_id: int


@router.get("/available", response_model=list[FusionProgramOption])
def list_available_fusion_programs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FusionProgramOption]:
    return [
        FusionProgramOption(
            program_id=info.program_id,
            department_id=info.department_id,
            department_name=info.department_name,
            major_id=info.major_id,
            program_name=info.program_name,
            kind=info.kind,
            kind_label=info.kind_label,
            program_type=info.program_type,
            program_type_label=info.program_type_label,
            total_credits=info.total_credits,
            curriculum_year=info.curriculum_year,
            participating_departments=[
                ParticipatingDepartment(id=part.id, name=part.name)
                for part in info.participating_departments
            ],
            enrolled=info.enrolled,
            user_academic_program_id=info.user_academic_program_id,
            enrollment_editable=info.enrollment_editable,
        )
        for info in available_fusion_programs(db, current_user)
    ]


def _eligible_requirement(
    db: Session, user: User, program_id: int
) -> GraduationRequirement:
    """등록 가능한 minor/dual 융합전공인지, 학생 학과가 참여하는지 확인한다."""
    requirement = db.get(GraduationRequirement, program_id)
    if requirement is None or requirement.program_type not in _ENROLLMENT_TYPE_LABELS:
        raise HTTPException(status_code=404, detail="등록 가능한 융합전공을 찾을 수 없습니다")
    dept = db.get(Department, requirement.department_id)
    major = db.get(Major, requirement.major_id) if requirement.major_id is not None else None
    if dept is None or _classify(requirement, dept.name, major.name if major else None) is None:
        raise HTTPException(status_code=404, detail="등록 가능한 융합전공을 찾을 수 없습니다")
    if current_dept := user.department_id:
        parts = _participating_departments(
            db, requirement.department_id, requirement.major_id
        )
        # 목록 조회와 같은 기준. 교차인정이 실재하는 프로그램(SW연계전공·핀테크 등)은
        # 참여학과가 아닌 학생을 여기서 막고, 참여학과가 자기 자신뿐인 융합전공은
        # 학과 무관 허용한다. 후자는 `source='fusion_plan'` 계획 플래그일 뿐이라
        # (되돌리기 가능, 실제 학적 아님) 시드 미완으로 잘못 열려도 피해가 작다.
        if _student_can_pursue(requirement.department_id, current_dept, parts):
            return requirement
    raise HTTPException(status_code=403, detail="현재 학과에서는 이수 가능한 융합전공이 아닙니다")


@router.post("/enroll", response_model=FusionProgramOption, status_code=201)
def enroll_fusion_program(
    payload: EnrollFusionProgramRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FusionProgramOption:
    """융합전공을 이수 계획에 저장한다. 취소 이력이 있으면 같은 행을 되살린다."""
    requirement = _eligible_requirement(db, current_user, payload.program_id)
    programs = db.scalars(
        select(UserAcademicProgram)
        .where(
            UserAcademicProgram.user_id == current_user.id,
            UserAcademicProgram.department_id == requirement.department_id,
            UserAcademicProgram.major_id.is_(None)
            if requirement.major_id is None
            else UserAcademicProgram.major_id == requirement.major_id,
            UserAcademicProgram.program_type == requirement.program_type,
        )
        .order_by(UserAcademicProgram.id.desc())
    ).all()
    if any(program.status == "active" and program.source != "fusion_plan" for program in programs):
        raise HTTPException(status_code=409, detail="학교 학적에 이미 등록된 융합전공입니다")
    program = next((program for program in programs if program.source == "fusion_plan"), None)
    if program is None:
        program = UserAcademicProgram(
            user_id=current_user.id,
            department_id=requirement.department_id,
            major_id=requirement.major_id,
            program_type=requirement.program_type,
            curriculum_year=requirement.curriculum_year,
            status="active",
            source="fusion_plan",
        )
        db.add(program)
    else:
        program.status = "active"
        program.curriculum_year = requirement.curriculum_year
    db.commit()

    return next(
        option for option in list_available_fusion_programs(current_user=current_user, db=db)
        if option.program_id == requirement.id
    )


@router.delete("/{user_academic_program_id}", status_code=204)
def cancel_fusion_program(
    user_academic_program_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """융합전공 이수 계획을 취소한다. 이력은 남기고 status만 변경한다."""
    program = db.get(UserAcademicProgram, user_academic_program_id)
    if (
        program is None
        or program.user_id != current_user.id
        or program.program_type not in _ENROLLMENT_TYPE_LABELS
        or program.source != "fusion_plan"
    ):
        raise HTTPException(status_code=404, detail="융합전공 이수 계획을 찾을 수 없습니다")
    requirement = db.scalars(
        select(GraduationRequirement).where(
            GraduationRequirement.department_id == program.department_id,
            GraduationRequirement.major_id.is_(None)
            if program.major_id is None
            else GraduationRequirement.major_id == program.major_id,
            GraduationRequirement.program_type == program.program_type,
            GraduationRequirement.curriculum_year == program.curriculum_year,
        )
    ).first()
    if requirement is None:
        raise HTTPException(status_code=404, detail="융합전공 이수 기준을 찾을 수 없습니다")
    dept = db.get(Department, requirement.department_id)
    major = db.get(Major, requirement.major_id) if requirement.major_id is not None else None
    if dept is None or _classify(requirement, dept.name, major.name if major else None) is None:
        raise HTTPException(status_code=400, detail="융합전공이 아닌 학적 프로그램입니다")
    program.status = "cancelled"
    db.commit()
