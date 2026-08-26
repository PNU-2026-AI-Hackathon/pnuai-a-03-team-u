"""AI융합트랙 (SW융합트랙) 이수 지원 API.

배경: 학생 소속 학과가 14개 대상 학과 중 하나면 트랙 이수를 선택할 수 있다.
트랙은 졸업요건이 아니라 인증(certification) — 이수 시 졸업증명서에 이수
과정명 표기. 학과전공 12~15학점 + AI융합공통 6~9학점 = 총 21학점.

엔드포인트:
- GET  /me/tracks/available — 학생 dept 기반 이수 가능 트랙 목록
- GET  /me/tracks/enrolled  — 이미 등록한 트랙 목록 (진도 요약 포함)
- POST /me/tracks/enroll    — UserAcademicProgram(program_type='interdisciplinary')로 등록
- DELETE /me/tracks/{program_id} — 등록 취소

트랙 판정(진도·완료 여부)은 기존 evaluate_program을 그대로 재활용한다 —
special_rules의 groups(학과전공/AI공통)로 채점.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.academics.tracks import (
    find_ai_tracks_for_department, is_ai_track, list_ai_common_courses,
)
from app.domains.courses.models import Course
from app.domains.academics.models import (
    Department, GraduationRequirement, Major, UserAcademicProgram,
)
from app.domains.academics.program_evaluator import evaluate_program
from app.domains.users.models import User


router = APIRouter(prefix="/me/tracks", tags=["tracks"])

# 회원가입 화면용 공개 라우터. 가입은 로그인 전이라 /me/*를 못 쓴다 —
# 학과 자동완성(/departments/search)과 같은 이유로 인증 없이 연다.
public_router = APIRouter(prefix="/tracks", tags=["tracks"])


# --- Response models ---------------------------------------------------------


class AvailableTrack(BaseModel):
    track_program_id: int  # graduation_requirements.id (트랙 정의 참조용)
    department_id: int
    department_name: str
    major_id: int
    track_name: str  # major name (예: "심리데이터사이언스(SW융합트랙)")
    total_credits: int
    dept_credits: dict  # {"min": N, "max": M}
    ai_common_credits: dict
    source: str | None
    is_enrolled: bool


class EnrolledTrack(BaseModel):
    enrollment_id: int  # user_academic_programs.id
    department_id: int
    major_id: int
    track_name: str
    total_credits: int
    earned_credits: float
    remaining_credits: float
    completed: bool


class AiCommonCourseResult(BaseModel):
    """AI융합 공통교과목 한 줄. 로드맵 "과목 담기" 화면이 department_id/major_id로는
    이 과목들을 못 찾는다 — 트랙 공통과목은 특정 학과 소속이 아니라 이름 목록으로만
    관리되기 때문이다(`domains/academics/tracks.py` 참고). course_id가 없으면
    (in_catalog=False) 로드맵에 담을 수 없다 — 우리 카탈로그 적재가 아직 안 된 것."""

    course_id: int | None
    course_name: str
    category: str | None
    credits: float | None
    # 담기 화면이 정규 학기 과목과 같은 방식으로 배치 실수를 미리 걸러낼 수 있게
    # 노출한다. AI융합 공통교과목은 대부분 courses.year/semester가 "전학년"/"전학기"다
    # (실측) — 학년/학기 제한 없이 아무 때나 들어도 된다는 뜻이라 정규 1/2학기처럼
    # 엄격히 안 막아도 된다.
    year: str | None
    semester: str | None
    module: int
    summary: str
    in_catalog: bool


class EnrollRequest(BaseModel):
    major_id: int  # 트랙의 major_id를 넘김. dept는 major로부터 유추


# --- Helpers -----------------------------------------------------------------


# 판별 규칙은 `domains/academics/tracks.py`에 모아 두었다 — 로드맵 챗도 같은 규칙을
# 써야 화면과 AI가 같은 말을 한다. 여기서는 얇게 감싸기만 한다.
def _find_tracks_for_dept(db: Session, department_id: int) -> list[GraduationRequirement]:
    """이 학과 학생이 이수 가능한 SW융합트랙 GR 목록."""
    return find_ai_tracks_for_department(db, department_id)


def _is_track(gr: GraduationRequirement) -> bool:
    return is_ai_track(gr)


# --- Endpoints ---------------------------------------------------------------


class TrackPreview(BaseModel):
    """회원가입 홍보 카드 한 장 분량 — 등록 여부 같은 사용자 종속 정보는 없다."""

    department_id: int
    department_name: str
    major_id: int
    track_name: str
    total_credits: int
    dept_credits: dict
    ai_common_credits: dict


@public_router.get("/preview", response_model=list[TrackPreview])
def preview_tracks(department: str, db: Session = Depends(get_db)) -> list[TrackPreview]:
    """학과 이름으로 그 학과의 AI융합트랙을 조회한다 (비로그인).

    회원가입에서 학부/학과를 고르는 순간 "이 학과는 트랙 대상"이라고 알려주기
    위한 것. 이름은 자동완성에서 고른 정식 편제 명칭이 온다는 전제라 완전
    일치로만 찾는다 — 부분 일치를 허용하면 오타 입력에도 카드가 떠서 오히려
    잘못된 안내가 된다.
    """
    name = department.strip()
    if not name:
        return []
    dept = db.scalars(select(Department).where(Department.name == name)).first()
    if dept is None:
        return []
    out: list[TrackPreview] = []
    for gr in _find_tracks_for_dept(db, dept.id):
        if not _is_track(gr) or gr.major_id is None:
            continue
        m = db.get(Major, gr.major_id)
        rules = gr.special_rules or {}
        out.append(TrackPreview(
            department_id=dept.id,
            department_name=dept.name,
            major_id=gr.major_id,
            track_name=m.name if m else "?",
            total_credits=gr.required_total_credits or 21,
            dept_credits=rules.get("dept_credits", {}),
            ai_common_credits=rules.get("ai_common_credits", {}),
        ))
    return out


@router.get("/ai-common-courses", response_model=list[AiCommonCourseResult])
def list_track_ai_common_courses(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AiCommonCourseResult]:
    """AI융합트랙의 "AI융합 공통교과목 6~9학점" 목록. 학생마다 다르지 않은
    고정 목록이라 department_id 등 스코프 파라미터가 없다 — 로그인만 요구한다."""
    entries = list_ai_common_courses(db)
    course_ids = [entry["course_id"] for entry in entries if entry.get("course_id") is not None]
    # list_ai_common_courses 자체는 year/semester를 안 채운다(roadmap_chat 프롬프트용
    # 요약이라 필요 없었음) — 담기 화면 배치 검증용으로 여기서 따로 붙인다.
    courses_by_id = {
        course.id: course
        for course in db.scalars(select(Course).where(Course.id.in_(course_ids)))
    } if course_ids else {}
    return [
        AiCommonCourseResult(
            course_id=entry.get("course_id"),
            course_name=entry["course_name"],
            category=entry.get("category"),
            credits=entry.get("credits"),
            year=courses_by_id[entry["course_id"]].year if entry.get("course_id") in courses_by_id else None,
            semester=courses_by_id[entry["course_id"]].semester if entry.get("course_id") in courses_by_id else None,
            module=entry["module"],
            summary=entry["summary"],
            in_catalog=entry["in_catalog"],
        )
        for entry in entries
    ]


@router.get("/available", response_model=list[AvailableTrack])
def list_available_tracks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AvailableTrack]:
    """학생 주전공 학과 기준으로 이수 가능한 AI융합트랙 목록."""
    if current_user.department_id is None:
        return []
    grs = [gr for gr in _find_tracks_for_dept(db, current_user.department_id) if _is_track(gr)]
    if not grs:
        return []

    # 이미 등록한 트랙 major_id 조회
    enrolled_major_ids: set[int] = set(db.scalars(
        select(UserAcademicProgram.major_id).where(
            UserAcademicProgram.user_id == current_user.id,
            UserAcademicProgram.program_type == "interdisciplinary",
            UserAcademicProgram.status == "active",
            UserAcademicProgram.major_id.in_([gr.major_id for gr in grs if gr.major_id]),
        )
    ).all())

    out: list[AvailableTrack] = []
    for gr in grs:
        d = db.get(Department, gr.department_id) if gr.department_id else None
        m = db.get(Major, gr.major_id) if gr.major_id else None
        rules = gr.special_rules or {}
        out.append(AvailableTrack(
            track_program_id=gr.id,
            department_id=gr.department_id or 0,
            department_name=d.name if d else "",
            major_id=gr.major_id or 0,
            track_name=m.name if m else "?",
            total_credits=gr.required_total_credits or 21,
            dept_credits=rules.get("dept_credits", {}),
            ai_common_credits=rules.get("ai_common_credits", {}),
            source=rules.get("source"),
            is_enrolled=(gr.major_id in enrolled_major_ids),
        ))
    return out


@router.get("/enrolled", response_model=list[EnrolledTrack])
def list_enrolled_tracks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[EnrolledTrack]:
    """등록한 트랙 + 진도 요약. 진도는 evaluate_program으로 계산."""
    progs = list(db.scalars(
        select(UserAcademicProgram).where(
            UserAcademicProgram.user_id == current_user.id,
            UserAcademicProgram.program_type == "interdisciplinary",
            UserAcademicProgram.status == "active",
        )
    ).all())

    out: list[EnrolledTrack] = []
    for p in progs:
        if p.department_id is None or p.major_id is None:
            continue
        # 이 프로그램이 정말 AI융합트랙인지 GR로 재확인 (연계전공·융합전공 제외)
        gr = db.scalars(
            select(GraduationRequirement).where(
                GraduationRequirement.department_id == p.department_id,
                GraduationRequirement.major_id == p.major_id,
                GraduationRequirement.program_type == "interdisciplinary",
            )
        ).first()
        if gr is None or not _is_track(gr):
            continue

        result = evaluate_program(
            db, user_id=current_user.id,
            department_id=p.department_id, major_id=p.major_id,
            program_type="interdisciplinary",
            curriculum_year=p.curriculum_year,
        )
        earned = float(result.total_credits_earned) if result else 0.0
        total = gr.required_total_credits or 21
        m = db.get(Major, p.major_id)
        out.append(EnrolledTrack(
            enrollment_id=p.id,
            department_id=p.department_id,
            major_id=p.major_id,
            track_name=m.name if m else "?",
            total_credits=total,
            earned_credits=earned,
            remaining_credits=max(0.0, total - earned),
            completed=(earned >= total),
        ))
    return out


@router.post("/enroll", response_model=EnrolledTrack, status_code=201)
def enroll_track(
    payload: EnrollRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EnrolledTrack:
    """학생이 트랙 이수를 시작. UserAcademicProgram에 interdisciplinary로 저장."""
    if current_user.department_id is None:
        raise HTTPException(status_code=422, detail="주전공 학과가 없어 트랙을 선택할 수 없습니다")

    # 대상 트랙 GR 조회 — 학생 학과와 매칭돼야 함
    gr = db.scalars(
        select(GraduationRequirement).where(
            GraduationRequirement.department_id == current_user.department_id,
            GraduationRequirement.major_id == payload.major_id,
            GraduationRequirement.program_type == "interdisciplinary",
        )
    ).first()
    if gr is None or not _is_track(gr):
        raise HTTPException(
            status_code=404,
            detail="해당 트랙이 없거나 학생 학과에서 이수 가능한 AI융합트랙이 아닙니다",
        )

    # 이미 등록됐는지
    existing = db.scalars(
        select(UserAcademicProgram).where(
            UserAcademicProgram.user_id == current_user.id,
            UserAcademicProgram.department_id == current_user.department_id,
            UserAcademicProgram.major_id == payload.major_id,
            UserAcademicProgram.program_type == "interdisciplinary",
        )
    ).first()
    if existing is not None:
        # 상태만 active로 갱신 (이전에 cancel 상태였다면)
        existing.status = "active"
        db.commit()
        prog = existing
    else:
        prog = UserAcademicProgram(
            user_id=current_user.id,
            department_id=current_user.department_id,
            major_id=payload.major_id,
            program_type="interdisciplinary",
            status="active",
        )
        db.add(prog)
        db.commit()
        db.refresh(prog)

    # 등록 직후 진도 요약
    result = evaluate_program(
        db, user_id=current_user.id,
        department_id=prog.department_id, major_id=prog.major_id,
        program_type="interdisciplinary", curriculum_year=prog.curriculum_year,
    )
    earned = float(result.total_credits_earned) if result else 0.0
    total = gr.required_total_credits or 21
    m = db.get(Major, prog.major_id)
    return EnrolledTrack(
        enrollment_id=prog.id,
        department_id=prog.department_id,
        major_id=prog.major_id,
        track_name=m.name if m else "?",
        total_credits=total,
        earned_credits=earned,
        remaining_credits=max(0.0, total - earned),
        completed=(earned >= total),
    )


@router.delete("/{enrollment_id}", status_code=204)
def cancel_track(
    enrollment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """트랙 이수 취소. hard delete하지 않고 status='cancelled'로 소프트 삭제."""
    prog = db.get(UserAcademicProgram, enrollment_id)
    if prog is None or prog.user_id != current_user.id or prog.program_type != "interdisciplinary":
        raise HTTPException(status_code=404, detail="트랙 등록을 찾을 수 없습니다")
    # 이 프로그램이 실제로 SW융합트랙인지 확인 (연계전공·융합전공은 API에서 취소 불가)
    gr = db.scalars(
        select(GraduationRequirement).where(
            GraduationRequirement.department_id == prog.department_id,
            GraduationRequirement.major_id == prog.major_id,
            GraduationRequirement.program_type == "interdisciplinary",
        )
    ).first()
    if gr is None or not _is_track(gr):
        raise HTTPException(
            status_code=400,
            detail="AI융합트랙이 아닌 프로그램은 이 API로 취소할 수 없습니다",
        )
    prog.status = "cancelled"
    db.commit()
