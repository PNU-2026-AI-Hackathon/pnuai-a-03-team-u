"""One-Stop 포털 학번/비밀번호로 학사 정보를 크롤링해 동기화한다.

사용자가 프론트엔드에서 학번/비밀번호를 입력하면, 그 자격증명으로 서버가
One-Stop에 로그인해 학적부·성적·졸업요건을 가져와 DB에 저장한다.
크롤링은 Playwright(동기 API)로 몇 초 걸리므로, 엔드포인트를 sync def로
선언해 FastAPI가 스레드풀에서 처리하도록 한다(이벤트 루프 블로킹 방지).
"""

from __future__ import annotations

import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.core.ratelimit import PORTAL_SYNC_LIMIT, limiter
from app.domains.academics.graduation_progress import (
    BALANCED_LIBERAL_AREAS,
    LIBERAL_AREAS_BY_GENERATION,
    liberal_area_in_generation,
    resolve_liberal_area_generation,
)
from app.domains.academics.course_substitution import (
    is_transfer_credit_record,
    set_substitutions,
)
from app.domains.academics.models import (
    Major,
    StudentCourseRecord,
    StudentCourseSubstitution,
    UserAcademicProgram,
)
from app.domains.courses.models import Course
from app.domains.planning.history import sync_completed_courses_to_roadmap
from app.domains.planning.models import CourseRoadmap
from app.domains.users.models import User
from app.ingestion.crawlers.advisor_consultation import fetch_current_term_consultation_status
from app.ingestion.crawlers.graduation import fetch_graduation_requirement
from app.ingestion.crawlers.graduation_expected_info import extract_graduation_expected_info
from app.ingestion.parsers.onestop_graduation_expected_info import normalize_graduation_expected_info
from app.ingestion.crawlers.grades import fetch_all_grades
from app.ingestion.crawlers.my_pusan_extracurricular import (
    fetch_extracurricular_certificate,
    safe_location,
)
from app.ingestion.crawlers.pnu_session import PnuLoginError, pnu_session
from app.ingestion.crawlers.student_info import fetch_academic_status_changes, fetch_student_record
from app.ingestion.normalizers.graduation_status_normalizer import (
    upsert_official_graduation_status,
)
from app.ingestion.normalizers.my_pusan_normalizer import (
    upsert_certifications,
    upsert_extracurricular_activities,
    upsert_language_scores,
)
from app.ingestion.normalizers.pnu_normalizer import (
    map_academic_program_registrations,
    map_grades,
    map_student_record,
)

router = APIRouter(prefix="/me", tags=["portal-sync"])

# 학적부 원문(fetch_student_record)에는 `주민등록번호`·`주소`·`보호자성명`/`보호자전화번호`
# ·`이메일`·`휴대폰번호`가 라벨 그대로 들어 있다. DB에 저장하지는 않지만 응답에 그대로
# 실으면 브라우저까지 흘러간다(개발자도구·네트워크 탭·확장 프로그램) — CLAUDE.md
# 개인정보 원칙 2(최소 수집)에 어긋난다. 그래서 응답에는 프론트가 실제로 쓰는 키만 남긴다.
#
# (`sessionStorage`에는 들어가지 않는다. 거기 쓰는 `InfoPage`는 목 모드 전용 분기이고,
#  목 모드면 `syncPortalData`가 API를 호출하지 않고 하드코딩 목을 돌려주므로 서버 응답이
#  도달할 수 없다 — 조건이 상호 배타적이다.)
#
# 화이트리스트인 이유: 블랙리스트로 뒤집으면 학적부 화면에 라벨이 하나 추가되는
# 순간 조용히 새기 시작한다. 새 키가 필요해지면 여기에 명시적으로 추가하고,
# "나중에 쓸지도 몰라서"로는 넣지 않는다.
#
# 실제 소비처:
#   - frontend/src/api/portal.ts:summarizePortalSync — 성명·이름·학번·소속학과·학부·
#     학년/학기·학적상태
#   - frontend/src/pages/{InfoPage,DashboardPage}.tsx — 이름·성명·학번·학부·전공
#     (목 데이터 경로)
# `학년`은 실제 학적부에 없는 라벨이지만(진짜 라벨은 `학년/학기`) 표기가 되돌아가도
# 안 깨지도록 같이 통과시킨다.
STUDENT_RECORD_PUBLIC_KEYS = (
    "성명",
    "이름",
    "학번",
    "소속학과",
    "학부",
    "전공",
    "학년/학기",
    "학년",
    "학적상태",
)


def _public_student_record(record: dict[str, str]) -> dict[str, str]:
    """학적부 원문에서 응답으로 내보내도 되는 키만 추린다.

    서버 내부(map_student_record, 지도교수 보정 등)는 원문 dict를 그대로 쓴다 —
    걸러내는 지점은 **응답 경계 한 곳**이다.
    """
    return {key: record[key] for key in STUDENT_RECORD_PUBLIC_KEYS if key in record}


class PortalSyncRequest(BaseModel):
    """One-Stop 자격증명. 저장하지 않고 이 요청 처리 동안만 메모리에 있는다.

    password를 SecretStr로 두는 이유: 저장은 안 하지만 예외 로깅·APM 연동·모델 repr에
    본문이 딸려갈 수 있다. SecretStr이면 그런 경로에서 `**********`으로 찍힌다
    (security-privacy-plan.md P0-3). 실제 값은 `.get_secret_value()`로만 꺼낸다.
    """

    login_id: str
    password: SecretStr


class CourseRecordResponse(BaseModel):
    id: int
    course_name: str = Field(validation_alias="raw_course_name")
    category: str | None
    liberal_area: str | None
    # liberal_area 판정 근거: 'override'(학생 지정) | 'onestop' | 'catalog' | None.
    liberal_area_source: str | None = None
    # 이 행에 학생이 세부영역을 직접 지정할 수 있는가 (교양선택류만 True).
    liberal_area_editable: bool = False
    # 이 학생의 교양 체계에서 고를 수 있는 세부영역 목록 (2021 구체계 / 2026 신체계).
    liberal_area_options: list[str] = []
    credits: float | None
    year: str | None
    semester: str | None
    grade: str | None
    match_status: str
    source: str
    # 편입/조기이수로 "입학 전 인정"된 행인지. 화면이 이 행에만 "어떤 PNU 과목을
    # 대체했나요?" 를 띄운다. 프론트가 semester 문자열을 다시 해석하지 않도록
    # 서버가 판정해서 내려준다(`course_substitution.is_transfer_credit_record`).
    is_transfer_credit: bool = False
    # 학생이 직접 지정한 대체 대상 PNU 과목들. 추측하지 않는다 — 지정 전에는 빈 목록.
    # 한 줄이 여러 개를 대체할 수 있다(전적대 `교양선택 15학점` → 교양 세부영역 여러 개).
    substitutes: list["SubstitutedCourseResponse"] = []

    model_config = {"from_attributes": True, "populate_by_name": True}


class SubstitutedCourseResponse(BaseModel):
    """전적대 이수기록이 대체한 PNU 과목 하나. 교양은 세부영역 placeholder가 온다."""

    course_id: int
    course_name: str
    category: str | None = None


def _primary_curriculum_year(db: Session, user_id: int) -> str | None:
    primary = db.scalars(
        select(UserAcademicProgram)
        .where(
            UserAcademicProgram.user_id == user_id,
            UserAcademicProgram.program_type == "primary",
        )
        .order_by(UserAcademicProgram.id)
    ).first()
    return primary.curriculum_year if primary else None


def _liberal_area_options_for_user(db: Session, user_id: int) -> list[str]:
    """이 학생의 교양 체계(2021 구체계 / 2026 신체계)에서 고를 수 있는 세부영역 목록."""
    generation = resolve_liberal_area_generation(_primary_curriculum_year(db, user_id))
    return list(LIBERAL_AREAS_BY_GENERATION[generation])


def _course_record_responses(
    db: Session, records: list[StudentCourseRecord], *, user_id: int | None = None
) -> list[CourseRecordResponse]:
    """이수기록 ORM 행을 응답 모델로. 대체 과목은 한 번에 모아서 붙인다(N+1 방지)."""
    options = (
        _liberal_area_options_for_user(db, user_id)
        if user_id is not None and records
        else []
    )
    record_ids = [r.id for r in records]
    by_record: dict[int, list[SubstitutedCourseResponse]] = {}
    if record_ids:
        rows = db.execute(
            select(StudentCourseSubstitution.record_id, Course)
            .join(Course, Course.id == StudentCourseSubstitution.course_id)
            .where(StudentCourseSubstitution.record_id.in_(record_ids))
            .order_by(Course.course_name)
        ).all()
        for record_id, course in rows:
            by_record.setdefault(record_id, []).append(
                SubstitutedCourseResponse(
                    course_id=course.id,
                    course_name=course.course_name,
                    category=course.category,
                )
            )
    responses = []
    for record in records:
        response = CourseRecordResponse.model_validate(record)
        response.is_transfer_credit = is_transfer_credit_record(record)
        response.substitutes = by_record.get(record.id, [])
        response.liberal_area_editable = record.category in _LIBERAL_CATEGORIES
        response.liberal_area_options = options if response.liberal_area_editable else []
        responses.append(response)
    return responses


class AcademicProgramResponse(BaseModel):
    program_type: str
    major: str | None

    model_config = {"from_attributes": True}


class PortalSyncResponse(BaseModel):
    # 학적부 원문이 아니라 `STUDENT_RECORD_PUBLIC_KEYS`로 추린 결과만 들어간다
    # (주민등록번호·주소·보호자 연락처 등은 응답에 싣지 않는다).
    student_record: dict[str, str]
    courses: list[CourseRecordResponse]
    academic_programs: list[AcademicProgramResponse]
    graduation_table_count: int
    # my.pusan.ac.kr 이수 프로그램·자격증·어학성적 동기화 결과 요약.
    # sso_ok=false면 크롤 자체가 실패한 것(로그인 페이지로 튕김).
    # One-Stop 졸업예정정보의 **학교 공식 판정** 반영 결과. 이수구분별 기준/취득학점과
    # 표준외국어능력시험·TOPCIT·졸업과제 같은 자격 요건이 여기 들어간다.
    official_categories_synced: int = 0
    official_requirements_synced: int = 0
    my_pusan_sso_ok: bool = False
    # sso_ok=false일 때 왜 실패했는지. 프론트가 "왜 비어 있는지"를 사용자에게 보여줄 수
    # 있어야 한다 — 예전엔 조용히 스킵돼서 학교 장애인지 우리 버그인지 알 방법이 없었다.
    my_pusan_error: str | None = None
    activities_created: int = 0
    activities_updated: int = 0
    certifications_created: int = 0
    certifications_updated: int = 0
    language_scores_created: int = 0
    language_scores_updated: int = 0


class AdvisorConsultedRequest(BaseModel):
    advisor_consulted: bool


class CourseRecordInput(BaseModel):
    id: int | None = None
    course_name: str
    category: str | None = None
    liberal_area: str | None = None
    credits: float | None = Field(default=None, ge=0)
    year: str | None = None
    semester: str | None = None
    grade: str | None = None


class CourseRecordsReplaceRequest(BaseModel):
    courses: list[CourseRecordInput]

    @model_validator(mode="after")
    def validate_unique_ids(self):
        ids = [course.id for course in self.courses if course.id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("같은 교과 이력 ID를 두 번 저장할 수 없습니다")
        return self


@router.post("/portal-sync", response_model=PortalSyncResponse)
@limiter.limit(PORTAL_SYNC_LIMIT)
def sync_portal_data(
    request: Request,
    payload: PortalSyncRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """학번/비밀번호로 One-Stop에 로그인해 학적부/성적/졸업요건을 가져와 저장한다."""
    portal_password = payload.password.get_secret_value()
    try:
        with pnu_session(payload.login_id, portal_password) as page:
            student_record = fetch_student_record(page)
            # 학적변동 내역(편입학 여부). 같은 학적부 메뉴라 추가 로그인/이동 비용이
            # 거의 없다. 실패해도 동기화 전체를 깨지 않는다 — 못 읽으면 기존
            # admission_type을 그대로 둔다.
            try:
                status_changes = fetch_academic_status_changes(page)
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "학적변동 내역 조회 실패 (user_id=%s): %s", current_user.id, exc
                )
                status_changes = []
            grades_tables = fetch_all_grades(page)
            graduation_tables = fetch_graduation_requirement(page)
            expected_info = extract_graduation_expected_info(page)
            current_year, current_semester = _current_academic_term()
            consultation_status = fetch_current_term_consultation_status(
                page, current_year, current_semester, user_id=current_user.id
            )
            # my.pusan.ac.kr는 별도 서브도메인이라 SSO 세션 공유 여부를 검증할 필요가
            # 있다. 이수 프로그램 크롤이 실패해도(로그인 튕김·페이지 구조 변경) 전체
            # portal-sync가 실패하면 안 되므로 여기서 예외 흡수. 성공 시에도 fetch 결과의
            # authenticated=False면 데이터 반영 스킵.
            try:
                extracurricular = fetch_extracurricular_certificate(
                    page,
                    login_id=payload.login_id,
                    login_pw=portal_password,
                )
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "my.pusan.ac.kr 이수 프로그램 크롤 실패 (user_id=%s): %s",
                    current_user.id, exc,
                )
                extracurricular = {
                    "authenticated": False,
                    "failure_reason": "my.pusan.ac.kr 연결 중 오류가 발생했습니다.",
                    "activities": [],
                    "certifications": [],
                    "language_scores": [],
                }
    except PnuLoginError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        # 로그인은 됐는데 One-Stop 페이지 구조가 예상과 달라 크롤링 도중 깨지는
        # 경우(셀렉터 변경, 타임아웃 등) — 원인 불문하고 프론트에는 스택트레이스
        # 대신 명확한 에러로 알려준다. 서버 로그에는 원본 예외를 그대로 남긴다.
        logging.getLogger(__name__).exception("portal-sync 크롤링 실패 (user_id=%s)", current_user.id)
        raise HTTPException(
            status_code=502,
            detail="One-Stop 포털에서 정보를 가져오는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
        ) from exc

    registration_rows = _table_rows_as_text(expected_info["tables"][0]) if expected_info["tables"] else []
    # 학적신청 표의 헤더까지 실제로 확인한 경우에만 "없는 행=해제됨"으로 해석한다.
    # 크롤러가 빈/다른 표를 주었을 때 기존 부·복수·연계전공을 잘못 비활성화하지 않기
    # 위한 안전장치다.
    registration_snapshot_is_complete = any(
        any(cell.strip() == "학적신청구분" for cell in row)
        for row in registration_rows
    )
    expected_normalized = normalize_graduation_expected_info(expected_info)

    # 학교 포털 비밀번호는 저장하지 않는다 (프론트 회원가입 온보딩 문구 정합).
    # 실제로 이 값을 재사용하는 코드가 없다 — 스케줄된 백그라운드 크롤이 없고
    # decrypt_secret은 호출되지 않는다. 매 sync 요청마다 사용자가 다시 입력하는
    # 흐름을 유지한다. 자동 크롤 도입 시점에 이 정책 재검토.
    map_student_record(db, current_user.id, student_record, status_changes)
    saved_records = map_grades(db, current_user.id, grades_tables)
    saved_programs = map_academic_program_registrations(
        db,
        current_user.id,
        registration_rows,
        reconcile_portal_snapshot=registration_snapshot_is_complete,
    )
    liberal_area_updates = _refine_liberal_area_categories(
        db, current_user.id, expected_normalized.get("requirement_items", [])
    )
    if liberal_area_updates:
        logging.getLogger(__name__).info(
            "균형교양 세부영역 liberal_area 반영 (user_id=%s): %s개 record 업데이트",
            current_user.id, liberal_area_updates,
        )
    # 학교 공식 졸업 판정 스냅샷. 예전엔 이 페이지에서 표 0(학적신청)과 균형교양
    # 세부영역만 쓰고 **나머지를 통째로 버렸다** — 크롤링은 되는데 저장이 안 돼서
    # "졸업요건·자격증을 못 가져온다"로 보였다.
    official_stats = upsert_official_graduation_status(db, current_user.id, expected_normalized)
    if official_stats["categories_deleted"] or official_stats["requirements_deleted"]:
        logging.getLogger(__name__).info(
            "학교 공식 졸업 판정 스냅샷에서 옛 행 제거 (user_id=%s): %s",
            current_user.id, official_stats,
        )

    advisor_name = student_record.get("지도교수", "").strip()
    if advisor_name:  # 아직 배정 전이면 빈 문자열 — 기존 값을 지우지 않고 그대로 둔다
        current_user.advisor_name = advisor_name
    if consultation_status is not None:  # 이번 학기 신청 내역 자체가 없으면 기존 값 유지
        current_user.advisor_consulted = "완료" in consultation_status

    activities_created = activities_updated = 0
    certifications_created = certifications_updated = 0
    language_scores_created = language_scores_updated = 0
    my_pusan_sso_ok = bool(extracurricular.get("authenticated"))
    if my_pusan_sso_ok:
        if extracurricular.get("activities"):
            activities_created, activities_updated = upsert_extracurricular_activities(
                db, current_user.id, extracurricular["activities"]
            )
        if extracurricular.get("certifications"):
            certifications_created, certifications_updated = upsert_certifications(
                db, current_user.id, extracurricular["certifications"]
            )
        if extracurricular.get("language_scores"):
            language_scores_created, language_scores_updated = upsert_language_scores(
                db, current_user.id, extracurricular["language_scores"]
            )
        if extracurricular.get("unknown_sections"):
            logging.getLogger(__name__).info(
                "my.pusan.ac.kr certificate 페이지에서 미매핑 섹션 (user_id=%s): %s",
                current_user.id, extracurricular["unknown_sections"],
            )
    else:
        logging.getLogger(__name__).info(
            "my.pusan.ac.kr SSO 공유 실패 — 이수/자격/어학 동기화 스킵 "
            "(user_id=%s, final_url=%s, reason=%s)",
            current_user.id,
            # rSSO 왕복 URL에는 SSO 토큰·학번이 붙을 수 있다. 응답 본문만 막고 로그를
            # 안 막으면 반쪽이다 (CLAUDE.md 개인정보 원칙 2).
            safe_location(extracurricular.get("final_url") or ""),
            extracurricular.get("failure_reason"),
        )

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
        student_record=_public_student_record(student_record),
        courses=_course_record_responses(db, saved_records, user_id=current_user.id),
        academic_programs=[_to_academic_program_response(db, p) for p in saved_programs],
        graduation_table_count=len(graduation_tables),
        official_categories_synced=(
            official_stats["categories_created"] + official_stats["categories_updated"]
        ),
        official_requirements_synced=(
            official_stats["requirements_created"] + official_stats["requirements_updated"]
        ),
        my_pusan_sso_ok=my_pusan_sso_ok,
        my_pusan_error=None if my_pusan_sso_ok else extracurricular.get("failure_reason"),
        activities_created=activities_created,
        activities_updated=activities_updated,
        certifications_created=certifications_created,
        certifications_updated=certifications_updated,
        language_scores_created=language_scores_created,
        language_scores_updated=language_scores_updated,
    )


def _to_academic_program_response(db: Session, program: UserAcademicProgram) -> AcademicProgramResponse:
    major = db.get(Major, program.major_id) if program.major_id else None
    return AcademicProgramResponse(
        program_type=program.program_type,
        major=major.name if major else None,
    )


def _current_academic_term() -> tuple[int, int]:
    """오늘 날짜 기준 학년도/학기. frontend의 getCurrentAcademicTerm()과 동일한 규칙:
    1~2월=전년도 2학기, 3~8월=당해 1학기, 9~12월=당해 2학기.
    """
    today = datetime.date.today()
    if today.month <= 2:
        return today.year - 1, 2
    if today.month <= 8:
        return today.year, 1
    return today.year, 2


def _table_rows_as_text(table: dict) -> list[list[str]]:
    """graduation_expected_info의 DOM 추출 구조(cells: [{text: ...}])를
    grades/graduation 크롤러와 같은 평범한 문자열 2차원 배열로 변환한다.
    """
    return [[cell["text"] for cell in row["cells"]] for row in table["rows"]]


# 균형/창의교양 세부영역을 붙일 대상 이수구분. 롤업된 세부영역명(사상과역사 등)도
# 포함(_CATEGORY_ROLLUP이 category를 세부영역명으로 덮어쓴 과거 데이터 방어).
_LIBERAL_CATEGORIES = frozenset(
    {"교양선택", "효원균형교양", "효원창의교양"} | set(BALANCED_LIBERAL_AREAS)
)


def _norm_name(name: str | None) -> str:
    return (name or "").replace(" ", "").strip()


def _onestop_area_by_course(requirement_items: list[dict]) -> dict[str, str]:
    """One-Stop general_education_area_completion 표 → {정규화 과목명: 세부영역명}.

    실측상 부산대 졸업예정정보 페이지는 이 표의 학생이수정보 칸을 비워서 주는
    경우가 대부분이라(레퍼런스 샘플로 확인) 보통 빈 dict가 나온다 — 그때는
    카탈로그 폴백으로 넘어간다. 표가 채워져 오는 계정/연도에서는 이 값이 우선.
    """
    out: dict[str, str] = {}
    unknown: set[str] = set()
    for row in requirement_items:
        if row.get("requirement_area") != "general_education_area_completion":
            continue
        raw = row.get("raw_record", {})
        course = raw.get("학생이수정보_교과목명", "").strip()
        if not course or raw.get("학생이수정보_이수여부", "").strip() != "이수":
            continue
        area_raw = row.get("required_category", "")
        area = area_raw.split(":", 1)[-1].strip() if ":" in area_raw else area_raw.strip()
        known = _match_known_liberal_area(area) if area else None
        if known:
            out[_norm_name(course)] = known
        elif area:
            unknown.add(area)
    if unknown:
        # 학교가 균형교양 영역을 추가·개명했다는 신호. 조용히 흘리면 놓친다.
        logging.getLogger(__name__).warning(
            "One-Stop 균형교양 영역명을 판정 엔진이 모른다: %s. "
            "graduation_progress.LIBERAL_AREAS_* 갱신이 필요한지 확인할 것.",
            sorted(unknown),
        )
    return out


def _catalog_area_by_course(db: Session) -> dict[str, str]:
    """수강편람 → {정규화 과목명: 세부영역명}. 졸업예정정보 표가 비어 있을 때의 폴백.

    `courses.general_education_area`가 채워진 행만. 같은 과목명이 여러 영역으로
    오면(개편 전후) 첫 값을 쓴다 — 어차피 학생이 '내 정보'에서 고칠 수 있다.
    """
    out: dict[str, str] = {}
    rows = db.execute(
        select(Course.course_name, Course.general_education_area).where(
            Course.general_education_area.isnot(None),
            Course.general_education_area != "",
        )
    ).all()
    for name, area in rows:
        known = _match_known_liberal_area(area or "")
        if not known:
            continue
        out.setdefault(_norm_name(name), known)
    return out


def _refine_liberal_area_categories(
    db: Session,
    user_id: int,
    requirement_items: list[dict],
) -> int:
    """교양 이수기록마다 균형/창의교양 세부영역(사상과역사 등)을 다시 계산해
    `student_course_records.liberal_area` / `liberal_area_source`에 저장한다.
    상위 이수구분 `category`(교양선택)는 그대로 둬서 학점 집계와 세부영역 판정을 분리.

    우선순위: 학생 지정(`liberal_area_override`) > One-Stop 학교 판정 표 > 수강편람
    카탈로그(`courses.general_education_area`). 어디서도 못 찾으면 None.
    `map_grades`가 sync마다 `liberal_area`를 None으로 비우므로 매번 전부 다시 채운다.
    """
    onestop_map = _onestop_area_by_course(requirement_items)
    catalog_map = _catalog_area_by_course(db)
    generation = resolve_liberal_area_generation(_primary_curriculum_year(db, user_id))

    updated = 0
    for rec in _list_course_records(db, user_id):
        if rec.category not in _LIBERAL_CATEGORIES and not rec.liberal_area_override:
            continue
        key = _norm_name(rec.raw_course_name)
        area: str | None = None
        source: str | None = None
        if rec.liberal_area_override:
            # 학생이 자기 체계 안에서 고른 값이라 그대로 신뢰한다(remap 안 함).
            area, source = rec.liberal_area_override, "override"
        elif key in onestop_map:
            area, source = onestop_map[key], "onestop"
        elif key in catalog_map:
            area, source = catalog_map[key], "catalog"

        # 자동 매칭값만 학생 체계 표기로 맞춘다("세계와 소통" → 구체계 학생에겐
        # "외국어"). 그 체계에 없는 영역이면 버린다. override는 이미 학생 체계 값이라
        # 이 remap을 태우면 안 된다(연도 파싱이 흔들리면 멀쩡한 지정이 사라질 수 있다).
        if source in ("onestop", "catalog"):
            area = liberal_area_in_generation(area, generation)
            if area is None:
                source = None

        if rec.liberal_area != area or rec.liberal_area_source != source:
            rec.liberal_area = area
            rec.liberal_area_source = source
            updated += 1
    return updated


def _match_known_liberal_area(area_name: str) -> str | None:
    """One-Stop 영역명을 판정 엔진이 아는 표준 이름으로 정규화. 모르면 None.

    공백 차이 정도는 흡수한다("사상과 역사" → "사상과역사"). 그 이상 다르면 새 영역이
    생겼거나 표기 체계가 바뀐 것이므로 조용히 추측하지 말고 None을 돌려준다.
    """
    compact = area_name.replace(" ", "")
    for known in BALANCED_LIBERAL_AREAS:
        if compact == known.replace(" ", ""):
            return known
    return None


def _list_course_records(db: Session, user_id: int) -> list[StudentCourseRecord]:
    return db.scalars(
        select(StudentCourseRecord)
        .where(StudentCourseRecord.user_id == user_id)
        .order_by(
            StudentCourseRecord.year.desc(),
            StudentCourseRecord.semester.desc(),
            StudentCourseRecord.id,
        )
    ).all()


@router.get("/course-records", response_model=list[CourseRecordResponse])
def list_course_records(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """마지막 포털 동기화 및 사용자 편집 결과를 DB에서 다시 조회한다."""
    return _course_record_responses(db, _list_course_records(db, current_user.id), user_id=current_user.id)


@router.put("/course-records", response_model=list[CourseRecordResponse])
def replace_course_records(
    payload: CourseRecordsReplaceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """내 정보 편집 화면의 교과 이력을 한 트랜잭션으로 저장한다."""
    existing = {
        record.id: record
        for record in db.scalars(
            select(StudentCourseRecord).where(StudentCourseRecord.user_id == current_user.id)
        ).all()
    }
    submitted_ids = {course.id for course in payload.courses if course.id is not None}
    unknown_ids = submitted_ids.difference(existing)
    if unknown_ids:
        raise HTTPException(status_code=404, detail="수정할 수 없는 교과 이력이 포함되어 있습니다")

    for record_id, record in existing.items():
        if record_id not in submitted_ids:
            db.delete(record)

    for course in payload.courses:
        name = course.course_name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="과목명을 입력해 주세요")
        record = existing.get(course.id) if course.id is not None else None
        if record is None:
            record = StudentCourseRecord(
                user_id=current_user.id,
                raw_course_name=name,
                source="manual",
                match_status="manual",
            )
            db.add(record)
        record.raw_course_name = name
        category = course.category.strip() if course.category else None
        liberal_area = course.liberal_area.strip() if course.liberal_area else None
        # 구버전 프론트나 수동 편집 화면이 세부영역을 category로 보내도 DB 경계에서
        # 올바른 두 필드로 정규화한다.
        if category in BALANCED_LIBERAL_AREAS:
            liberal_area = category
            category = "교양선택"
        if liberal_area is not None and liberal_area not in BALANCED_LIBERAL_AREAS:
            raise HTTPException(status_code=422, detail="알 수 없는 교양 세부영역입니다")
        if category != "교양선택":
            # liberal_area는 교양선택일 때만 의미가 있다. 프론트가 category를 다른 값으로
            # 바꾸면서도 이전 liberal_area를 payload에 그대로 들고 오면(예: 기존 레코드를
            # 불러와 category만 고친 뒤 재제출), 그 stale 값이 그대로 저장돼
            # liberal_area_completions()가 이미 다른 이수구분으로 옮겨간 과목을 계속 그
            # 세부영역 이수로 잘못 집계한다. 여기서 강제로 지운다.
            liberal_area = None
        # 폼에서 세부영역을 바꾸거나 지웠으면 학생 지정(override)으로 저장한다 —
        # 안 그러면 다음 portal-sync의 `_refine_liberal_area_categories`가 자동 매칭으로
        # 이 값을 덮어써 버린다(크롤 대상 행은 map_grades가 매번 liberal_area를 비운다).
        # 값이 그대로면 기존 override를 건드리지 않는다(자동값을 override로 승격 안 함).
        if category == "교양선택":
            if liberal_area != record.liberal_area:
                record.liberal_area_override = liberal_area
        else:
            record.liberal_area_override = None
        record.category = category
        record.liberal_area = liberal_area
        if record.liberal_area_override is not None:
            record.liberal_area_source = "override"
        elif liberal_area is None:
            record.liberal_area_source = None
        record.credits = course.credits
        record.year = course.year.strip() if course.year else None
        record.semester = course.semester.strip() if course.semester else None
        record.grade = course.grade.strip() if course.grade else None

    db.commit()
    return _course_record_responses(db, _list_course_records(db, current_user.id), user_id=current_user.id)


# 한 이수기록이 대체할 수 있는 과목 수 상한. 실제로는 교양 세부영역 9개 + 교양과목
# 몇 개가 최대라 두 자리면 충분한데, 상한이 없으면 한 요청으로 `courses` 전량(운영 DB
# 기준 6천 행대)을 밀어 넣을 수 있다.
MAX_SUBSTITUTION_COURSES = 50


class CourseSubstitutionRequest(BaseModel):
    """이 전적대 이수기록이 대체한 PNU 과목 **전체 집합**. 빈 목록이면 대체 해제.

    기본값을 두지 않는다 — 필드를 빼먹은 요청이 조용히 "전체 해제"로 처리되면,
    프론트 버그 하나로 학생이 등록해 둔 대체가 통째로 날아간다. 해제하려면 `[]`를
    명시해야 한다.
    """

    course_ids: list[int] = Field(..., max_length=MAX_SUBSTITUTION_COURSES)


@router.put("/course-records/{record_id}/substitutions", response_model=CourseRecordResponse)
def set_course_substitutions(
    record_id: int,
    payload: CourseSubstitutionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """전적대 이수기록이 대체한 PNU 과목들을 학생이 직접 지정한다.

    편입 학점 인정은 학과가 학생 개인에게 통보하는 것이라 데이터에 근거가 없다.
    그래서 서버는 이름 유사도로 추천하지 않고 **학생이 고른 course_ids만 저장한다**
    (`app.domains.academics.course_substitution` 참고).

    부분 갱신이 아니라 **치환**이다 — 화면이 체크박스 전체 상태를 보낸다. 통보를
    나중에 받거나 잘못 골랐을 때 언제든 다시 부를 수 있게 멱등으로 만든다.

    학점은 건드리지 않는다. 전적대에서 인정받은 학점은 이 행에 그대로 남고,
    졸업요건 판정 합계도 그대로다. 바뀌는 건 시간표/로드맵 추천에서 그 PNU 과목이
    "이미 이수함"으로 빠지는 것뿐이다.
    """
    record = db.get(StudentCourseRecord, record_id)
    # 남의 기록인지 없는 기록인지 구분해 주지 않는다(존재 여부 노출 방지).
    if record is None or record.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="이수 기록을 찾을 수 없습니다")
    if not is_transfer_credit_record(record):
        raise HTTPException(
            status_code=422,
            detail="입학 전 인정 학점(전적대 이수) 과목에만 대체 관계를 지정할 수 있습니다",
        )

    course_ids = set(payload.course_ids)
    if course_ids:
        found = set(db.scalars(select(Course.id).where(Course.id.in_(course_ids))).all())
        missing = course_ids - found
        if missing:
            raise HTTPException(status_code=404, detail="대체할 과목을 찾을 수 없습니다")

    set_substitutions(db, record.id, list(course_ids))
    db.commit()
    db.refresh(record)
    return _course_record_responses(db, [record], user_id=current_user.id)[0]


class LiberalAreaRequest(BaseModel):
    """이 교양 이수기록이 어느 균형/창의교양 세부영역인지 학생이 직접 지정.

    `liberal_area=None`이면 지정 해제(자동 매칭에 다시 맡김). 기본값을 두지 않아
    필드 누락이 조용히 "해제"로 처리되지 않게 한다.
    """

    liberal_area: str | None = Field(...)


@router.put("/course-records/{record_id}/liberal-area", response_model=CourseRecordResponse)
def set_course_liberal_area(
    record_id: int,
    payload: LiberalAreaRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """교양선택 이수기록의 균형/창의교양 세부영역을 학생이 직접 고른다.

    졸업예정정보 표가 세부영역을 안 주는 경우가 많고 수강편람 카탈로그 매칭도
    빈틈이 있어(`_refine_liberal_area_categories`), 자동 매칭이 비거나 틀렸을 때
    학생이 바로잡을 수 있게 한다. 편입 대체 지정(`.../substitutions`)과 같은 패턴:
    치환이고 멱등이며 언제든 다시 부를 수 있다.

    학점은 건드리지 않는다 — `category`(교양선택)는 그대로라 졸업요건 합계는 불변.
    바뀌는 건 '효원균형교양 이수 현황' 영역별 표시와 로드맵/시간표의 영역 조언뿐.
    """
    record = db.get(StudentCourseRecord, record_id)
    if record is None or record.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="이수 기록을 찾을 수 없습니다")
    if record.category not in _LIBERAL_CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail="교양선택 과목에만 세부영역을 지정할 수 있습니다",
        )

    area = (payload.liberal_area or "").strip() or None
    if area is not None:
        options = _liberal_area_options_for_user(db, current_user.id)
        if area not in options:
            raise HTTPException(
                status_code=422,
                detail=f"이 학생의 교양 체계에 없는 세부영역입니다: {area}",
            )

    record.liberal_area_override = area
    # 즉시 반영: override가 있으면 그게 곧 effective 값이고, 지웠으면 자동 매칭
    # 결과는 다음 portal-sync에서 다시 계산되므로 지금은 일단 비운다.
    if area is not None:
        record.liberal_area = area
        record.liberal_area_source = "override"
    else:
        record.liberal_area = None
        record.liberal_area_source = None
    db.commit()
    db.refresh(record)
    return _course_record_responses(db, [record], user_id=current_user.id)[0]


@router.patch("/advisor-consulted")
def set_advisor_consulted(
    payload: AdvisorConsultedRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """지도교수 상담 여부를 사용자가 직접 체크/해제한다.

    portal-sync가 이번 학기 상담 신청 내역에서 크롤링한 값으로 덮어쓸 수 있으니,
    다음 동기화 전까지만 유효한 임시 오버라이드로 봐야 한다."""
    current_user.advisor_consulted = payload.advisor_consulted
    db.commit()
    return {"advisor_consulted": current_user.advisor_consulted}
