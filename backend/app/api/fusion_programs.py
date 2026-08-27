"""이수 가능한 융합전공 / 연계전공 / AI(SW)융합트랙 조회 — 읽기 전용.

로드맵 화면의 "AI융합 가능" 버튼이 쓴다. 학생 소속 학과
(`current_user.department_id`)가 그 프로그램의 **참여 학과**
(= `program_courses`가 인정하는 과목들의 distinct `courses.department_id`) 중
하나일 때만 노출한다. 학생 본인의 주전공 프로그램은 제외한다.

프로그램 식별: `majors.name` / `departments.name` 접미사(`(SW융합트랙)` /
`(SW연계전공)` / `(SW융합전공)` 등, 부분문자열 `융합트랙` / `연계전공` / `융합전공`)와
`is_ai_track()`. `program_type`은 필터로 쓰지 않는다 — SW 계열은 `interdisciplinary`,
`seed_interdisciplinary_majors_2026_08`은 `minor` / `dual`. 단 `primary` 행은 제외한다
(지능형헬스사이언스융합전공·핀테크융합전공처럼 주전공 세부전공으로도 등록된 케이스 방어).

엔드포인트: GET /me/fusion-programs/available
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.academics.models import (
    Department,
    GraduationRequirement,
    Major,
    ProgramCourse,
)
from app.domains.academics.tracks import is_ai_track
from app.domains.courses.models import Course
from app.domains.users.models import User

router = APIRouter(prefix="/me/fusion-programs", tags=["fusion-programs"])

# roadmap_chat._PROGRAM_TYPE_LABELS와 같은 값. planning 패키지를 import하면
# program_evaluator 등 무거운 의존이 딸려와서 여기서만 얇게 복제한다.
_ENROLLMENT_TYPE_LABELS = {"minor": "부전공", "dual": "복수전공"}
_KIND_ORDER = {"track": 0, "linked": 1, "convergence": 2}


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


def _suffix_label(name: str | None) -> str | None:
    """majors.name의 괄호 접미사에서 유형 라벨을 뽑는다.

    '빅데이터(SW연계전공)' → 'SW연계전공', '소셜데이터사이언스(SW융합트랙)' → 'SW융합트랙'.
    seed_sw_convergence_programs.py가 붙이는 접미사와 정확히 맞물린다.
    """
    if not name or "(" not in name or ")" not in name:
        return None
    inner = name[name.rfind("(") + 1 : name.rfind(")")].strip()
    if any(token in inner for token in ("연계전공", "융합전공", "융합트랙")):
        return inner
    return None


def _classify(
    requirement: GraduationRequirement, dept_name: str, major_name: str | None
) -> tuple[str, str] | None:
    """(kind, kind_label) 또는 None(융합 프로그램 아님).

    kind는 프론트 스타일링용 3분류(track/linked/convergence). kind_label은
    사용자에게 보이는 정확한 명칭 — AI융합교육원 프로그램은 접미사 그대로
    (SW연계전공 / SW융합전공 / SW융합트랙), AI융합트랙 인증은 'AI융합트랙',
    그 외(반도체·DX 등)는 일반 '융합전공'.
    """
    hay = f"{major_name or ''} {dept_name or ''}"
    suffix = _suffix_label(major_name)
    if is_ai_track(requirement):
        return "track", "AI융합트랙"
    if "융합트랙" in hay:
        return "track", suffix or "융합트랙"
    if "연계전공" in hay:
        return "linked", suffix or "연계전공"
    if "융합전공" in hay:
        return "convergence", suffix or "융합전공"
    return None


def _participating_departments(
    db: Session, dept_id: int, major_id: int | None
) -> list[ParticipatingDepartment]:
    """프로그램이 인정하는 과목들의 distinct 개설 학과.

    `curriculum_year`로 필터하지 않는다 —
    `curriculum_retriever._program_course_scope_ids`와 같은 근거(교차인정은 연도
    무관 사실, 시드가 '2026' 하드코딩이라 실재학생과 exact match 안 됨).
    """
    stmt = (
        select(Department.id, Department.name)
        .distinct()
        .join(Course, Course.department_id == Department.id)
        .join(ProgramCourse, ProgramCourse.course_id == Course.id)
        .where(ProgramCourse.department_id == dept_id)
    )
    stmt = stmt.where(
        ProgramCourse.major_id == major_id
        if major_id is not None
        else ProgramCourse.major_id.is_(None)
    )
    return [ParticipatingDepartment(id=row[0], name=row[1]) for row in db.execute(stmt).all()]


@router.get("/available", response_model=list[FusionProgramOption])
def list_available_fusion_programs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FusionProgramOption]:
    if current_user.department_id is None:
        return []
    my_dept = current_user.department_id
    my_program = (current_user.department_id, current_user.major_id)

    rows = db.execute(
        select(
            GraduationRequirement,
            Department.name,
            Major.id,
            Major.name,
        )
        .join(Department, Department.id == GraduationRequirement.department_id)
        .outerjoin(Major, Major.id == GraduationRequirement.major_id)
        .where(
            GraduationRequirement.program_type != "primary",
            or_(
                Major.name.like("%융합전공%"),
                Major.name.like("%연계전공%"),
                Major.name.like("%융합트랙%"),
                Department.name.like("%융합전공%"),
                Department.name.like("%연계전공%"),
                Department.name.like("%융합트랙%"),
                # is_ai_track는 special_rules 기반이라 이름 LIKE로 안 잡힌다.
                # interdisciplinary 후보를 넉넉히 끌어와 _classify가 최종 판별.
                GraduationRequirement.program_type == "interdisciplinary",
            ),
        )
    ).all()

    # (dept, major, program_type)별로 curriculum_year 사전식 최댓값 한 행만 남긴다.
    best: dict[tuple[int | None, int | None, str | None], tuple] = {}
    for requirement, dept_name, major_id, major_name in rows:
        classified = _classify(requirement, dept_name, major_name)
        if classified is None:
            continue
        key = (
            requirement.department_id,
            requirement.major_id,
            requirement.program_type,
        )
        current = best.get(key)
        if current is None or (requirement.curriculum_year or "") > (
            current[0].curriculum_year or ""
        ):
            best[key] = (requirement, dept_name, major_id, major_name, classified)

    # 같은 (dept, major)에 minor/dual 행이 있으면 interdisciplinary 행은 버린다.
    # (핀테크융합전공처럼 interdisciplinary(42) + dual(42)이 중복으로 뜨는 것 방지.
    #  SW연계전공은 interdisciplinary만 있어 그대로 남는다.)
    enrollment_scopes = {
        (dept, major)
        for (dept, major, ptype) in best
        if ptype in ("minor", "dual")
    }
    best = {
        key: value
        for key, value in best.items()
        if not (key[2] == "interdisciplinary" and (key[0], key[1]) in enrollment_scopes)
    }

    out: list[FusionProgramOption] = []
    for requirement, dept_name, major_id, major_name, (kind, kind_label) in best.values():
        if (requirement.department_id, requirement.major_id) == my_program:
            continue  # 본인 주전공 프로그램 제외
        parts = _participating_departments(
            db, requirement.department_id, requirement.major_id
        )
        if not any(part.id == my_dept for part in parts):
            continue  # 참여 학과에 내 학과가 없으면 스킵 (시드 미완이면 여기서 빠짐)
        parts.sort(key=lambda part: part.name)
        out.append(
            FusionProgramOption(
                program_id=requirement.id,
                department_id=requirement.department_id,
                department_name=dept_name,
                major_id=major_id,
                program_name=major_name or dept_name,
                kind=kind,
                kind_label=kind_label,
                program_type=requirement.program_type,
                program_type_label=_ENROLLMENT_TYPE_LABELS.get(
                    requirement.program_type or ""
                ),
                total_credits=requirement.required_total_credits,
                curriculum_year=requirement.curriculum_year,
                participating_departments=parts,
            )
        )

    out.sort(key=lambda option: (_KIND_ORDER.get(option.kind, 9), option.program_name))
    return out
