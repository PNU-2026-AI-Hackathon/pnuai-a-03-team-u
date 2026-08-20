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
from app.domains.academics.graduation_progress import BALANCED_LIBERAL_AREAS
from app.domains.academics.models import Major, StudentCourseRecord, UserAcademicProgram
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
    credits: float | None
    year: str | None
    semester: str | None
    grade: str | None
    match_status: str
    source: str

    model_config = {"from_attributes": True, "populate_by_name": True}


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
    try:
        with pnu_session(payload.login_id, payload.password.get_secret_value()) as page:
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
                extracurricular = fetch_extracurricular_certificate(page)
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
    expected_normalized = normalize_graduation_expected_info(expected_info)

    # 학교 포털 비밀번호는 저장하지 않는다 (프론트 회원가입 온보딩 문구 정합).
    # 실제로 이 값을 재사용하는 코드가 없다 — 스케줄된 백그라운드 크롤이 없고
    # decrypt_secret은 호출되지 않는다. 매 sync 요청마다 사용자가 다시 입력하는
    # 흐름을 유지한다. 자동 크롤 도입 시점에 이 정책 재검토.
    map_student_record(db, current_user.id, student_record, status_changes)
    saved_records = map_grades(db, current_user.id, grades_tables)
    saved_programs = map_academic_program_registrations(db, current_user.id, registration_rows)
    liberal_area_updates = _refine_liberal_area_categories(
        db, current_user.id, expected_normalized.get("requirement_items", [])
    )
    if liberal_area_updates:
        logging.getLogger(__name__).info(
            "균형교양 세부영역 category 반영 (user_id=%s): %s개 record 업데이트",
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
        courses=[CourseRecordResponse.model_validate(r) for r in saved_records],
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


def _refine_liberal_area_categories(
    db: Session,
    user_id: int,
    requirement_items: list[dict],
) -> int:
    """One-Stop 졸업예정정보 general_education_area_completion 표에서 학생이 실제로 어느
    세부영역(예: '사회와문화', '사상과역사')에 이수했는지 뽑아 student_course_records.category를
    상위값('교양선택')에서 세부값으로 override 한다.

    로드맵 챗이 균형교양 6개 세부영역별로 "너 사상과역사 3학점 이수했네" 같은 조언을
    하려면 이 세부값이 이수기록에 있어야 한다. 학교 공식 판정 결과를 근거로 채우므로
    학과 규칙 판별 로직 없이도 안전.

    - 매칭: 학생이수정보_교과목명을 student_course_records.raw_course_name과 정규화(공백 제거) 후 비교
    - 이수여부='이수'인 rows만 반영. '미이수'는 원 category 유지.
    - '1영역 : 사상과역사' 형식에서 접두 '숫자영역 :' 제거해 순수 영역명만 저장.
    """
    area_rows = [
        r for r in requirement_items
        if r.get("requirement_area") == "general_education_area_completion"
    ]
    if not area_rows:
        return 0

    records = _list_course_records(db, user_id)
    def _norm(name: str | None) -> str:
        return (name or "").replace(" ", "").strip()
    records_by_name: dict[str, list[StudentCourseRecord]] = {}
    for r in records:
        key = _norm(r.raw_course_name)
        if key:
            records_by_name.setdefault(key, []).append(r)

    updated = 0
    unknown_areas: set[str] = set()
    for row in area_rows:
        raw = row.get("raw_record", {})
        student_course = raw.get("학생이수정보_교과목명", "").strip()
        if not student_course or raw.get("학생이수정보_이수여부", "").strip() != "이수":
            continue
        area_raw = row.get("required_category", "")
        # "1영역 : 사상과역사" → "사상과역사"
        area_name = area_raw.split(":", 1)[-1].strip() if ":" in area_raw else area_raw.strip()
        if not area_name:
            continue

        # **판정 엔진이 아는 영역명일 때만 덮어쓴다.**
        # 이 값은 졸업요건 집계에서 `_CATEGORY_ROLLUP`이 '교양선택'으로 되돌리는데, 그
        # 롤업은 고정된 7개 이름 목록(BALANCED_LIBERAL_AREAS)으로 동작한다. One-Stop 원문이
        # 조금만 달라도(예: '사상과 역사'처럼 공백 하나) 롤업이 못 알아보고 그 학점이
        # 교양선택 집계에서 통째로 사라진다 — 2026-08-13에 고친 버그가 그대로 재발한다.
        # 모르는 이름이면 덮어쓰지 않고 '교양선택'을 유지한다(집계는 정확, 세부영역 조언만 못함).
        normalized_area = _match_known_liberal_area(area_name)
        if normalized_area is None:
            unknown_areas.add(area_name)
            continue

        for rec in records_by_name.get(_norm(student_course), []):
            if rec.category != normalized_area:
                rec.category = normalized_area
                updated += 1

    if unknown_areas:
        logging.getLogger(__name__).warning(
            "One-Stop 균형교양 영역명을 판정 엔진이 모른다 (user_id=%s): %s. "
            "덮어쓰지 않고 '교양선택'을 유지했다 — BALANCED_LIBERAL_AREAS 갱신이 필요한지 확인할 것.",
            user_id, sorted(unknown_areas),
        )
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
    return _list_course_records(db, current_user.id)


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
        record.category = course.category.strip() if course.category else None
        record.credits = course.credits
        record.year = course.year.strip() if course.year else None
        record.semester = course.semester.strip() if course.semester else None
        record.grade = course.grade.strip() if course.grade else None

    db.commit()
    return _list_course_records(db, current_user.id)


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
