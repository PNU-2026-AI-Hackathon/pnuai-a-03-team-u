"""One-Stop 포털 학번/비밀번호로 학사 정보를 크롤링해 동기화한다.

사용자가 프론트엔드에서 학번/비밀번호를 입력하면, 그 자격증명으로 서버가
One-Stop에 로그인해 학적부·성적·졸업요건을 가져와 DB에 저장한다.
크롤링은 Playwright(동기 API)로 몇 초 걸리므로, 엔드포인트를 sync def로
선언해 FastAPI가 스레드풀에서 처리하도록 한다(이벤트 루프 블로킹 방지).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.planning.history import sync_completed_courses_to_roadmap
from app.domains.planning.models import CourseRoadmap
from app.domains.users.models import User
from app.ingestion.crawlers.graduation import fetch_graduation_requirement
from app.ingestion.crawlers.graduation_expected_info import extract_graduation_expected_info
from app.ingestion.crawlers.grades import fetch_all_grades
from app.ingestion.crawlers.pnu_session import PnuLoginError, pnu_session
from app.ingestion.crawlers.student_info import fetch_student_record
from app.ingestion.normalizers.pnu_normalizer import (
    map_academic_program_registrations,
    map_grades,
    map_student_record,
    save_portal_credential,
)

router = APIRouter(prefix="/me", tags=["portal-sync"])


class PortalSyncRequest(BaseModel):
    login_id: str
    password: str


class CourseRecordResponse(BaseModel):
    course_name: str
    category: str | None
    credits: float | None
    year: str | None
    semester: str | None
    grade: str | None
    match_status: str

    model_config = {"from_attributes": True}


class AcademicProgramResponse(BaseModel):
    program_type: str
    major: str | None

    model_config = {"from_attributes": True}


class PortalSyncResponse(BaseModel):
    student_record: dict[str, str]
    courses: list[CourseRecordResponse]
    academic_programs: list[AcademicProgramResponse]
    graduation_table_count: int


class AdvisorConsultedRequest(BaseModel):
    advisor_consulted: bool


@router.post("/portal-sync", response_model=PortalSyncResponse)
def sync_portal_data(
    payload: PortalSyncRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """학번/비밀번호로 One-Stop에 로그인해 학적부/성적/졸업요건을 가져와 저장한다."""
    try:
        with pnu_session(payload.login_id, payload.password) as page:
            student_record = fetch_student_record(page)
            grades_tables = fetch_all_grades(page)
            graduation_tables = fetch_graduation_requirement(page)
            expected_info = extract_graduation_expected_info(page)
    except PnuLoginError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    registration_rows = _table_rows_as_text(expected_info["tables"][0]) if expected_info["tables"] else []

    save_portal_credential(db, current_user.id, payload.login_id, payload.password)
    map_student_record(db, current_user.id, student_record)
    saved_records = map_grades(db, current_user.id, grades_tables)
    saved_programs = map_academic_program_registrations(db, current_user.id, registration_rows)

    # 새로 크롤링된 이수내역을 사용자의 모든 로드맵에 반영한다. 이 시점(크롤링
    # 직후)에만 하면 되므로, 로드맵을 열 때마다(GET /me/roadmaps/current) 매번
    # 다시 확인할 필요가 없다 — 조회는 항상 가볍게 유지된다. 로드맵 개수가 많아도
    # 항목 수 자체가 적어서(보통 수십 개) 크롤링 자체보다 훨씬 빠르다.
    roadmap_ids = db.scalars(
        select(CourseRoadmap.id).where(CourseRoadmap.user_id == current_user.id)
    ).all()
    for roadmap_id in roadmap_ids:
        sync_completed_courses_to_roadmap(db, user_id=current_user.id, roadmap_id=roadmap_id)

    db.commit()

    return PortalSyncResponse(
        student_record=student_record,
        courses=[CourseRecordResponse.model_validate(r) for r in saved_records],
        academic_programs=[AcademicProgramResponse.model_validate(p) for p in saved_programs],
        graduation_table_count=len(graduation_tables),
    )


def _table_rows_as_text(table: dict) -> list[list[str]]:
    """graduation_expected_info의 DOM 추출 구조(cells: [{text: ...}])를
    grades/graduation 크롤러와 같은 평범한 문자열 2차원 배열로 변환한다.
    """
    return [[cell["text"] for cell in row["cells"]] for row in table["rows"]]


@router.patch("/advisor-consulted")
def set_advisor_consulted(
    payload: AdvisorConsultedRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """지도교수 상담 여부를 사용자가 직접 체크/해제한다 (크롤링 대상 아님)."""
    current_user.advisor_consulted = payload.advisor_consulted
    db.commit()
    return {"advisor_consulted": current_user.advisor_consulted}
