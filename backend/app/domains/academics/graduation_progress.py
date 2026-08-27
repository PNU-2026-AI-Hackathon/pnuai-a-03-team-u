"""flat graduation_requirements 테이블과 학생 이수내역(student_course_records)을
카테고리별로 단순 대조해 졸업까지 남은 학점을 계산한다.

주전공은 이수구분별 합계 학점만 비교한다(flat). **부전공/복수전공/연계전공**은
`special_rules.groups`나 `program_courses`가 있으면 `program_evaluator.evaluate_program`
(택N/M·그룹 학점 채점)으로 실판정하고(하이브리드, 2026-08-27), 그 데이터가 없으면
총 이수학점 비교로 폴백하며 경고를 남긴다. 균형/창의교양 세부영역은 규칙 파서 없이
학교 공식 판정 스냅샷·영역별 이수 현황을 경고로만 노출한다(satisfied 불변).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, inspect, select
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.orm import Session

from app.domains.academics.models import (
    GraduationRequirement,
    ProgramCourse,
    StudentCourseRecord,
    StudentCourseSubstitution,
    StudentGraduationCategory,
    UserAcademicProgram,
)
from app.domains.academics.course_substitution import liberal_area_completions
from app.domains.academics.program_evaluator import evaluate_program
from app.domains.academics.program_status import ACTIVE_PROGRAM_STATUSES
from app.domains.academics.tracks import is_ai_track as _is_ai_track

# StudentCourseRecord.category(성적표 원문 정규화 값) -> GraduationRequirement의
# 기준학점 컬럼 매핑. "심화전공"은 우리 카테고리 체계에 없어 전공선택에 흡수된다.
_REQUIRED_FIELD_TO_LABEL: dict[str, str] = {
    "required_major_foundation": "전공기초",
    "required_major_required": "전공필수",
    "required_major_elective": "전공선택",
    "required_general_required": "교양필수",
    "required_general_elective": "교양선택",
    "required_free_elective": "일반선택",
}

# One-Stop 졸업예정정보 표의 학적신청구분 → 앱의 program_type. 이 표는 학생별 학교
# 공식 판정이므로, 학과 공통 기준이 없는 경우에만 fallback으로 쓴다. 공통 기준 행을
# 만들거나 갱신하는 용도로 쓰면 다른 학생에게 잘못 전파된다.
_ONESTOP_PROGRAM_TYPE_MAP = {
    "주전공": "primary",
    "복수전공": "dual",
    "부전공": "minor",
    "연합전공": "interdisciplinary",
    "연계전공": "interdisciplinary",
    "융합전공": "interdisciplinary",
}

_ONESTOP_TOTAL_CATEGORY = "총이수학점"
_ONESTOP_FALLBACK_REQUIRED_CATEGORIES = {
    _ONESTOP_TOTAL_CATEGORY,
    "전공필수",
    "교양필수",
}
_ONESTOP_FALLBACK_MAX_AGE = datetime.timedelta(days=31)

# "교양선택" 세부영역 — 세대별로 이름과 구성이 다르다
# (docs/progress/liberal-arts-area-requirements.md §4.1/§6/§7.2/§7.3 조사 참고).
#
# 2021교육과정(2022~2025학번) 구체계: 8개 영역, 전부 "교양선택" 하나로 롤업.
# 2026교육과정 신체계: 효원균형교양 6개 + 효원창의교양 3개로 나뉘지만, 이 flat 엔진의
# GraduationRequirement에는 균형/창의를 나눠 담을 컬럼이 없어 결국 둘 다 "교양선택"으로
# 롤업된다 — 그래서 롤업 대상(_CATEGORY_ROLLUP 값)은 세대 상관없이 항상 "교양선택"이다.
# 세대가 실제로 갈라야 하는 곳은 롤업이 아니라 **자문(advisory) 컨텍스트**다: 2021학번에게
# "세계와 소통 미이수"라고 말하면 안 되고, 2026학번에게 "외국어 미이수"라고 말하면 안
# 된다 — `liberal_areas_for_generation()`으로 세대별 부분집합을 골라 써라
# (roadmap_chat/timetable_chat의 균형교양 세부영역 안내 블록 참고).
#
# 이름 표기는 `courses.general_education_area` 운영 DB 실값 그대로다(2026-08-24 확인) —
# "세계와 소통"/"융합과 창의"/"인성과 사회봉사"는 **공백 포함**이 맞다. 설계 문서 초안의
# 무공백 표기("세계와소통")는 오타였다.
#
# portal_sync._refine_liberal_area_categories는 One-Stop 졸업예정정보를 근거로
# student_course_records.liberal_area에 세부영역명을 별도 저장한다. _CATEGORY_ROLLUP은
# 마이그레이션 전 데이터나 테스트처럼 category에 세부영역이 남은 경우의 호환 장치다.
#
# 여기(academics)에 두는 이유: 판정 엔진이 진짜 소비자이고, planning(로드맵/시간표 챗)이
# 이걸 가져다 쓰는 방향이 모듈 경계상 맞다.
LIBERAL_AREAS_2021: tuple[str, ...] = (
    "사상과역사",
    "사회와문화",
    "문학과예술",
    "과학과기술",
    "건강과레포츠",
    "외국어",
    "융복합",
    "효원브릿지",  # 8영역. 2022학년도 신입생부터 적용(REG 부칙) — 이전엔 누락돼 있었다.
)

LIBERAL_AREAS_2026: tuple[str, ...] = (
    # 효원균형교양 6개
    "사상과역사",
    "사회와문화",
    "문학과예술",
    "과학과기술",
    "세계와 소통",  # 구체계 "외국어" 개편
    "효원브릿지",
    # 효원창의교양 3개
    "융합과 창의",  # 구체계 "융복합" 개편
    "건강과레포츠",
    "인성과 사회봉사",  # 신설
)

LIBERAL_AREAS_BY_GENERATION: dict[str, tuple[str, ...]] = {
    "2021": LIBERAL_AREAS_2021,
    "2026": LIBERAL_AREAS_2026,
}

# 개편 전후로 이름만 바뀐 같은 영역. 수강편람/One-Stop이 신체계 이름으로 주는데
# 학생이 구체계면(그 반대도) 그대로 두면 화면·판정이 "다른 영역"으로 본다.
_LIBERAL_AREA_ALIASES: dict[str, dict[str, str]] = {
    "2021": {"세계와 소통": "외국어", "융합과 창의": "융복합"},
    "2026": {"외국어": "세계와 소통", "융복합": "융합과 창의"},
}


def liberal_area_in_generation(area: str | None, generation: str) -> str | None:
    """세부영역명을 해당 교양 체계의 표기로 정규화한다. 그 체계에 없으면 None.

    예: "세계와 소통"을 2021 구체계 학생에게는 "외국어"로, 2026 신체계에서만 있는
    "인성과 사회봉사"를 2021 학생에게는 None으로 돌려준다.
    """
    if not area:
        return None
    mapped = _LIBERAL_AREA_ALIASES.get(generation, {}).get(area, area)
    return mapped if mapped in LIBERAL_AREAS_BY_GENERATION.get(generation, ()) else None

# 매칭·집계(One-Stop 영역명 인식, category 필터, 롤업 대상 판별)는 세대를 몰라도 되므로
# 두 세대의 합집합을 쓴다 — 순서는 두 튜플을 이어붙인 뒤 중복만 제거(첫 등장 순서 유지).
BALANCED_LIBERAL_AREAS: tuple[str, ...] = tuple(
    dict.fromkeys(LIBERAL_AREAS_2021 + LIBERAL_AREAS_2026)
)

# 이수기록 category 원값 → 요건 집계에 쓸 상위 이수구분. 세대 상관없이 전부 "교양선택".
_CATEGORY_ROLLUP: dict[str, str] = {area: "교양선택" for area in BALANCED_LIBERAL_AREAS}


def resolve_liberal_area_generation(curriculum_year: str | int | None) -> str:
    """학생의 curriculum_year로 교양 체계 세대("2021" | "2026")를 판별한다.

    2026 이상이면 신체계, 그 외(2025 이하 또는 파싱 불가·None)는 구체계로 본다.
    2026-08-24 기준 실사용자 curriculum_year는 2023/2024 또는 결측뿐이라(전원 구체계),
    None을 구체계로 보는 기본값이 지금 데이터와 맞는다 — 2026학번이 실제로 유입되면
    이 함수 하나만 바뀌면 된다.
    """
    if curriculum_year is None:
        return "2021"
    try:
        year = int(curriculum_year)
    except (TypeError, ValueError):
        return "2021"
    return "2026" if year >= 2026 else "2021"


def liberal_areas_for_generation(curriculum_year: str | int | None) -> tuple[str, ...]:
    """학생의 curriculum_year에 맞는 교양 세부영역 목록(자문용 부분집합)."""
    return LIBERAL_AREAS_BY_GENERATION[resolve_liberal_area_generation(curriculum_year)]

# `courses.category`(수강편람 어휘) → `graduation_requirements` 라벨(성적표 어휘).
#
# 두 어휘가 교양에서 겹치지 않는다. 요건은 `교양필수`/`교양선택`인데 수강편람 과목은
# `효원핵심교양`/`효원균형교양`/`효원창의교양`/`기초교양`으로 들어온다 — 운영 DB 기준
# `교양필수`/`교양선택` category를 가진 courses 행은 **0건**이다. 정규화 없이 이름으로
# 맞추면 교양 과목을 아무리 계획해도 교양 잔여가 1학점도 안 줄어든다.
#
# 대응 근거는 2026학년도 교양교육 전면 개편이다
# (`docs/progress/liberal-arts-area-requirements.md` §3.3, 교양교육원 수강지도 지침 p.1/p.18):
#   - 교양필수 10학점  → 효원핵심교양 10학점 (같은 과목 묶음)
#   - 교양선택 12 + 기초교양 3 → 효원균형교양 6 + 기초교양 3 + 효원창의교양 6
#
# `교직과목`은 어느 요건 컬럼에도 대응이 없다(사범대 요건 행은 카테고리 합보다
# 총요구학점이 22학점 크고, 그 차이가 교직이다). 여기 넣지 않고 미분류로 남긴다 —
# 총 이수학점에는 잡히되 특정 이수구분을 채웠다고 주장하지 않는다.
COURSE_CATEGORY_TO_REQUIREMENT: dict[str, str] = {
    "효원핵심교양": "교양필수",
    "효원균형교양": "교양선택",
    "효원창의교양": "교양선택",
    "기초교양": "교양선택",
}


def requirement_category_for_course(category: str | None) -> str | None:
    """수강편람 과목의 이수구분을 졸업요건 라벨로 정규화한다.

    대응이 없으면 원값을 그대로 돌려준다 — 모르는 값을 임의의 요건에 밀어 넣는 것보다
    "이 이수구분은 요건에 매핑되지 않는다"가 드러나는 편이 안전하다.

    ⚠️ 폴백으로 쓰는 `_CATEGORY_ROLLUP`(균형교양 세부영역 → 교양선택)은
    `curriculum_retriever`의 역인덱싱 대상이 **아니다**. 지금은 무해하다 —
    `courses.category`에 세부영역명(`사상과역사` 등)이 0건이고 그 값은
    `student_course_records`에만 나타난다. 만약 수강편람에 세부영역명이 들어오기
    시작하면 검색↔집계가 또 갈리므로, 그때는 `COURSE_CATEGORY_TO_REQUIREMENT`로 옮겨야
    한다(두 벌을 손으로 유지하다 `기초교양`에서 실제로 어긋났던 전례가 있다).
    """
    if category is None:
        return None
    return COURSE_CATEGORY_TO_REQUIREMENT.get(
        category, _CATEGORY_ROLLUP.get(category, category)
    )


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
    # `_find_requirement`가 실제로 고른 그 행 기준으로 판정한다 — API 레이어가
    # department_id/major_id/program_type만으로 GraduationRequirement를 curriculum_year
    # 필터 없이 다시 조회하면, 같은 조합에 연도가 다른 중복 행이 있을 때(간호학과 dual
    # 2026이 2행인 사례처럼) 이 진행도 계산에 실제로 쓰인 행과 다른 행을 집을 수 있다.
    is_ai_track: bool = False


def _find_requirement(db: Session, program: UserAcademicProgram) -> GraduationRequirement | None:
    """program_type + curriculum_year + (major_id 우선, 없으면 department_id)로
    가장 구체적인 기준학점 행을 찾는다. 정확한 연도 매칭이 없으면 같은
    학과/전공의 가장 최근 연도 행으로 폴백한다.
    """
    if program.major_id is None and program.department_id is None:
        return None

    # 전공 단위 요건을 먼저 찾고, 없으면 **학과 단위(major_id IS NULL)로 폴백**한다.
    #
    # `graduation_requirements.major_id = NULL`은 "모름"이 아니라 "이 학과 전체에 공통 적용"
    # 이라는 확정적 의미다. 실제로 전공이 있는 학과인데 요건은 학과 단위로만 등록된 경우가
    # 64행 있다 (예: 기계공학부 primary 2026 — 전공 5개 각각의 요건 행은 없다).
    #
    # 폴백이 없던 옛 구현은 그런 학과의 학생을 `requirement_found=False`로 떨어뜨려
    # **졸업요건 판정을 아예 못 받게** 했다 — 2026-08-13 실측으로 활성 학적 6건 중 3건이
    # 여기 걸렸다. `timetable._term_credit_cap`은 이미 같은 폴백을 하고 있어서 두 코드
    # 경로가 서로 다르게 동작하고 있었다.
    scopes = []
    if program.major_id is not None:
        scopes.append(GraduationRequirement.major_id == program.major_id)
    if program.department_id is not None:
        scopes.append(
            (GraduationRequirement.department_id == program.department_id)
            & GraduationRequirement.major_id.is_(None)
        )

    for scope in scopes:
        found = _find_in_scope(db, program, scope)
        if found is not None:
            return found
    return None


def _find_in_scope(db: Session, program: UserAcademicProgram, scope) -> GraduationRequirement | None:
    """한 스코프(전공 단위 또는 학과 단위) 안에서 연도 매칭 → 최신 연도 폴백."""
    query = db.query(GraduationRequirement).filter(
        GraduationRequirement.program_type == program.program_type,
        scope,
    )

    if program.curriculum_year:
        # `.one_or_none()`이 아니라 `.first()`인 이유: graduation_requirements에
        # (program_type, department_id, major_id, curriculum_year) 유니크 제약이 없어서
        # 같은 조합이 두 행 존재할 수 있다. 실제로 있다 — 간호학과 dual 2026이 2행이라
        # 해당 학생은 졸업요건 조회에서 MultipleResultsFound로 **500 에러**가 났다
        # (2026-08-13 발견). 판정 불가로 죽는 것보다 하나를 골라 계산하고 경고를 남기는
        # 쪽이 낫다. 근본 해결은 유니크 제약 + 중복 정리이고, 중복은
        # scripts/report_duplicate_requirements.py로 감시한다.
        exact = (
            query.filter(GraduationRequirement.curriculum_year == program.curriculum_year)
            .order_by(GraduationRequirement.id)
            .first()
        )
        if exact is not None:
            return exact

    return query.order_by(GraduationRequirement.curriculum_year.desc()).first()


def _count_matching_requirements(
    db: Session, program: UserAcademicProgram, requirement: GraduationRequirement
) -> int:
    """실제로 고른 요건 행과 같은 조건인 행이 몇 개인지 (중복 감지용).

    스코프는 **프로그램이 아니라 고른 행(`requirement`) 기준**이어야 한다. 프로그램
    기준으로 세면 학과 단위 폴백 경로에서 경고가 절대 안 뜬다:

        학생은 major_id가 있는데 전공 단위 요건 행이 없어 `_find_in_scope`가 학과 단위
        행(major_id IS NULL)으로 폴백한다 → 그런데 프로그램 기준으로 세면
        `major_id == program.major_id`로 거르므로 학과 단위 행은 하나도 안 세어져 0이
        나온다 → `duplicate_count > 1`이 성립하지 않아 경고가 사라진다.

    즉 경고가 필요한 바로 그 상황(폴백으로 집은 학과 단위 행이 중복일 때)에서만
    조용해지는 셈이었다. curriculum_year도 이미 `requirement` 것을 쓰고 있으므로
    (연도 폴백까지 반영), 스코프도 같은 기준으로 맞춘다.
    """
    query = db.query(func.count(GraduationRequirement.id)).filter(
        GraduationRequirement.program_type == program.program_type,
        GraduationRequirement.curriculum_year == requirement.curriculum_year,
    )
    if requirement.major_id is not None:
        query = query.filter(GraduationRequirement.major_id == requirement.major_id)
    else:
        query = query.filter(
            GraduationRequirement.department_id == requirement.department_id,
            GraduationRequirement.major_id.is_(None),
        )
    return query.scalar() or 0


def _earned_credits_by_category(db: Session, user_id: int) -> dict[str, Decimal]:
    """이수구분별 이수학점. 균형교양 세부영역은 '교양선택'으로 합산한다(_CATEGORY_ROLLUP)."""
    rows = (
        db.query(StudentCourseRecord.category, func.sum(StudentCourseRecord.credits))
        .filter(StudentCourseRecord.user_id == user_id)
        .group_by(StudentCourseRecord.category)
        .all()
    )
    totals: dict[str, Decimal] = {}
    for category, total in rows:
        if not category:
            continue
        label = _CATEGORY_ROLLUP.get(category, category)
        totals[label] = totals.get(label, Decimal("0")) + (total or Decimal("0"))
    return totals


def _official_onestop_fallback(
    db: Session, user_id: int, program: UserAcademicProgram
) -> ProgramProgress | None:
    """학과 공통 기준이 없을 때만 One-Stop 학교 공식 판정을 보여준다.

    One-Stop의 `student_graduation_categories`는 특정 학생의 학적·학번·예외를 모두
    반영한 결과다. 따라서 `graduation_requirements`를 채우는 소스로 쓰지 않고,
    그 학생의 기준 행을 찾지 못했을 때에만 이 진행도 응답을 대체한다. 총이수학점 행이
    없으면 표가 부분 파싱됐을 가능성이 있으므로 사용하지 않는다.
    """
    # 일부 단위 테스트와 아직 마이그레이션하지 않은 개발 DB에는 이 테이블이 없다.
    # 그런 환경에서 "기준 없음" 경로 자체가 500이 되면 안 되므로 기존 동작을 유지한다.
    # Engine을 inspect하면 SQLite in-memory 환경에서 별도 연결의 rollback이 현재
    # 트랜잭션을 되돌릴 수 있다. 현재 세션 연결을 검사해 진행 중인 대화/제안 쓰기를
    # 건드리지 않는다.
    if not inspect(db.connection()).has_table(StudentGraduationCategory.__tablename__):
        return None

    # One-Stop 표에는 신청학과/전공 식별자가 없다. 특히 연합·연계·융합전공은 앱에서
    # 모두 `interdisciplinary`로 접히므로, 원문 프로그램을 보존하는 스키마를 만들기
    # 전까지는 다른 프로그램의 판정을 붙이지 않기 위해 fallback 대상에서 제외한다.
    if program.program_type == "interdisciplinary":
        return None

    # 같은 internal program_type을 두 개
    # 이상 가진 학생(복수 복수전공, 여러 연계전공 등)은 어느 행이 어느 프로그램인지
    # 확정할 수 없으므로 공식 결과를 억지로 붙이지 않는다.
    active_same_type_count = db.query(func.count(UserAcademicProgram.id)).filter(
        UserAcademicProgram.user_id == user_id,
        UserAcademicProgram.program_type == program.program_type,
        UserAcademicProgram.status.in_(ACTIVE_PROGRAM_STATUSES),
    ).scalar() or 0
    if active_same_type_count != 1:
        return None

    portal_program_types = [
        label for label, internal in _ONESTOP_PROGRAM_TYPE_MAP.items()
        if internal == program.program_type
    ]
    if not portal_program_types:
        return None
    rows = db.scalars(
        select(StudentGraduationCategory)
        .where(
            StudentGraduationCategory.user_id == user_id,
            StudentGraduationCategory.program_type.in_(portal_program_types),
        )
        .order_by(StudentGraduationCategory.id)
    ).all()
    total_row = next(
        (row for row in rows if (row.category or "").strip() == _ONESTOP_TOTAL_CATEGORY),
        None,
    )
    if total_row is None or total_row.required_credits is None or total_row.earned_credits is None:
        return None

    # 표가 일부만 파싱된 경우를 학교 공식 전체 판정으로 보이면 안 된다. 학사 기준의
    # 공통 핵심 세 행(총계·전공필수·교양필수)이 모두 같은 동기화에서 왔을 때만 쓴다.
    # 학과별 기준을 알 수 없는 경우에도, 이 조건을 못 만족하면 기존 "판정 불가"가
    # 더 안전하다.
    category_names = {(row.category or "").strip() for row in rows}
    if not _ONESTOP_FALLBACK_REQUIRED_CATEGORIES.issubset(category_names):
        return None
    synced_at = total_row.synced_at
    if synced_at.tzinfo is None:
        synced_at = synced_at.replace(tzinfo=datetime.UTC)
    if datetime.datetime.now(datetime.UTC) - synced_at > _ONESTOP_FALLBACK_MAX_AGE:
        return None
    if any(row.synced_at != total_row.synced_at for row in rows):
        return None

    required_total = Decimal(total_row.required_credits)
    earned_total = Decimal(total_row.earned_credits)
    satisfied = total_row.satisfied
    categories = [
        CategoryProgress(
            category_code=f"onestop:{row.id}",
            category_name=(row.category or "").strip(),
            required_credits=Decimal(row.required_credits) if row.required_credits is not None else None,
            earned_credits=Decimal(row.earned_credits) if row.earned_credits is not None else Decimal("0"),
            remaining_credits=(
                Decimal("0") if row.satisfied is True else
                max(Decimal("0"), Decimal(row.required_credits) - Decimal(row.earned_credits))
                if row.required_credits is not None and row.earned_credits is not None else None
            ),
            satisfied=row.satisfied,
        )
        for row in rows
        if (row.category or "").strip() != _ONESTOP_TOTAL_CATEGORY
    ]
    return ProgramProgress(
        user_academic_program_id=program.id,
        program_type=program.program_type,
        department_id=program.department_id,
        major_id=program.major_id,
        curriculum_year=program.curriculum_year,
        requirement_found=True,
        required_total_credits=int(required_total),
        earned_total_credits=earned_total,
        remaining_total_credits=(
            Decimal("0") if satisfied is True else max(Decimal("0"), required_total - earned_total)
        ),
        satisfied=satisfied,
        categories=categories,
        warnings=[
            "학과 공통 기준학점 데이터가 없어 One-Stop의 학생별 학교 공식 졸업사정 결과로 표시함.",
            f"학교 공식 판정 동기화 시각: {total_row.synced_at.isoformat()}",
        ],
    )


@dataclass
class _RuleJudgment:
    """비주전공 프로그램의 규칙 기반 판정 결과(하이브리드용)."""

    satisfied: bool
    earned_total: Decimal
    remaining_total: Decimal | None
    warnings: list[str]


def _program_rule_judgment(
    db: Session,
    user_id: int,
    program: UserAcademicProgram,
    requirement: GraduationRequirement,
) -> _RuleJudgment | None:
    """부전공/복수전공/연계전공을 지정 과목·그룹 규칙으로 판정한다.

    `special_rules.groups`나 `program_courses`가 있는 프로그램은
    `program_evaluator.evaluate_program`(택N/M·그룹 학점 채점)으로 실판정한다.
    그 데이터가 하나도 없으면 None을 돌려주고, 호출부는 총 이수학점 비교(flat)로
    폴백하되 "총 학점만 대조됨" 경고를 붙인다.
    """
    # 일부 단위 테스트·미마이그레이션 DB에는 program_courses가 없다. 그 경우
    # 하이브리드 판정을 건너뛰고 호출부가 flat로 폴백한다(_official_onestop_fallback과 동일 방침).
    if not inspect(db.connection()).has_table(ProgramCourse.__tablename__):
        return None

    special = requirement.special_rules or {}
    has_groups = bool(special.get("groups"))
    # evaluate_program은 program_courses를 requirement 행의 curriculum_year로 필터한다
    # (program_evaluator.py). 게이트도 같은 연도로 봐야 "하이브리드로 갔는데 인정과목이
    # 0건이라 전부 미충족" 같은 어긋남이 안 생긴다. (evaluate_program이 학번 정확 매칭에
    # 실패해 curriculum_year=NULL 요건으로 폴백하면 게이트와 연도가 갈릴 수 있으나,
    # 시드 스크립트가 그런 연도 불일치를 만들지 않는다.)
    has_program_courses = (
        db.query(ProgramCourse.id)
        .filter(
            ProgramCourse.department_id == program.department_id,
            ProgramCourse.major_id == program.major_id
            if program.major_id is not None
            else ProgramCourse.major_id.is_(None),
            ProgramCourse.curriculum_year == requirement.curriculum_year,
        )
        .first()
        is not None
    )
    if not has_groups and not has_program_courses:
        return None

    try:
        result = evaluate_program(
            db,
            user_id,
            program.department_id,
            program.major_id,
            program.program_type,
            curriculum_year=program.curriculum_year,
        )
    except MultipleResultsFound:
        # graduation_requirements에 unique 제약이 없어 같은 조건 행이 여럿일 수 있다
        # (TC11 참고). flat 경로는 _find_in_scope가 .first()로 결정적으로 고르지만
        # evaluate_program은 .scalar_one_or_none()이라 여기서 터진다. 프로그램 하나
        # 때문에 전체 판정이 500나지 않게 flat로 폴백한다(중복 경고는 flat 쪽이 붙인다).
        return None
    if result is None:
        # _find_requirement가 학과 단위로 폴백해 잡았는데 evaluate_program은
        # major_id 정확 매칭이라 못 찾는 경우 등. flat로 폴백시킨다.
        return None

    earned = Decimal(str(result.total_credits_earned))
    # satisfied(result.completed)가 실제로 대조하는 총량과 remaining을 맞춘다 —
    # evaluate_program은 special_rules.total_credits > required_total_credits 순으로 본다.
    required = (
        result.total_credits_required
        if result.total_credits_required is not None
        else requirement.required_total_credits
    )
    remaining = (
        max(Decimal(required) - earned, Decimal("0")) if required is not None else None
    )
    warnings = ["프로그램 지정 과목 기준으로 판정함"]
    for ge in result.groups:
        if ge.completed:
            continue
        detail = ge.shortage or f"{ge.rule_type} 조건 미충족"
        warnings.append(f"{ge.label}: {detail}")
    return _RuleJudgment(
        satisfied=result.completed,
        earned_total=earned,
        remaining_total=remaining,
        warnings=warnings,
    )


def _liberal_area_warnings(
    db: Session, user_id: int, program: UserAcademicProgram
) -> list[str]:
    """주전공 결과에 얹을 균형/창의교양 세부영역 자문 경고.

    `_CATEGORY_ROLLUP`이 세부영역을 '교양선택' 하나로 뭉쳐 판정에서 빠지므로,
    (1) One-Stop 학교 공식 판정 스냅샷의 교양 관련 미이수 행,
    (2) 세대별 세부영역 중 이수 0과목인 영역
    을 경고로만 노출한다. `satisfied`는 건드리지 않는다(규칙 파서는 후속 과제).
    """
    warnings: list[str] = []
    conn_inspect = inspect(db.connection())
    # 미마이그레이션 DB·단위 테스트엔 이 테이블들이 없다. 자문용이므로 조용히 스킵.
    if not (
        conn_inspect.has_table(StudentGraduationCategory.__tablename__)
        and conn_inspect.has_table(StudentCourseSubstitution.__tablename__)
    ):
        return warnings

    official_rows = db.execute(
        select(StudentGraduationCategory).where(
            StudentGraduationCategory.user_id == user_id,
            StudentGraduationCategory.program_type == "주전공",
        )
    ).scalars().all()
    for row in official_rows:
        cat = (row.category or "").strip()
        if ("균형교양" in cat or "창의교양" in cat or "교양선택" in cat) and row.satisfied is False:
            reason = f" ({row.failure_reason})" if row.failure_reason else ""
            warnings.append(f"학교 공식 판정: {cat} 미이수{reason}")

    areas = liberal_areas_for_generation(program.curriculum_year)
    completions = liberal_area_completions(db, user_id, areas)
    empty = [
        area
        for area in areas
        if not completions[area].direct_records and not completions[area].substituted_records
    ]
    if empty and len(empty) < len(areas):
        # 전부 비어 있으면(교양을 아예 안 들은 저학년) 굳이 나열하지 않는다.
        warnings.append(f"균형/창의교양 이수 0과목인 세부영역: {', '.join(empty)}")
    return warnings


def compute_graduation_progress(
    db: Session, user_id: int, program_types: set[str] | None = None
) -> list[ProgramProgress]:
    """사용자의 활성 학적 프로그램별로 기준학점 대비 이수학점/남은 학점을 계산한다."""
    programs_query = db.query(UserAcademicProgram).filter(
        UserAcademicProgram.user_id == user_id,
        # 휴학생도 판정 대상이다 (program_status 정책 참고).
        UserAcademicProgram.status.in_(ACTIVE_PROGRAM_STATUSES),
    )
    if program_types:
        programs_query = programs_query.filter(UserAcademicProgram.program_type.in_(program_types))
    programs = programs_query.all()

    earned_by_category = _earned_credits_by_category(db, user_id)
    total_earned = sum(earned_by_category.values(), Decimal("0"))

    results: list[ProgramProgress] = []
    for program in programs:
        requirement = _find_requirement(db, program)
        warnings: list[str] = []

        if requirement is None:
            official_fallback = _official_onestop_fallback(db, user_id, program)
            if official_fallback is not None:
                results.append(official_fallback)
                continue
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

        # 전공 단위 요건이 없어 학과 단위로 폴백한 경우. 판정은 되지만 전공별 세부 기준이
        # 아니라는 걸 사용자·LLM이 알아야 한다.
        if program.major_id is not None and requirement.major_id is None:
            warnings.append(
                "이 전공의 기준학점 행이 없어 학과 단위 기준으로 판정함 — "
                "전공별 세부 기준이 다르면 결과가 어긋날 수 있음"
            )

        # 같은 조합의 기준학점 행이 여럿이면 어느 걸 썼는지 드러낸다 — 조용히 하나를 고르면
        # 판정 결과가 달라진 이유를 아무도 모른다.
        duplicate_count = _count_matching_requirements(db, program, requirement)
        if duplicate_count > 1:
            warnings.append(
                f"같은 조건의 기준학점 행이 {duplicate_count}개 있어 id={requirement.id}를 "
                f"사용함 — 데이터 정리 필요 (scripts/report_duplicate_requirements.py)"
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
        # flat 기본값 — 학생 전체 이수학점 합 대 required_total.
        earned_for_program = total_earned
        remaining_total = None
        satisfied_total = None
        if required_total is not None:
            remaining_total = max(Decimal(required_total) - total_earned, Decimal("0"))
            satisfied_total = total_earned >= Decimal(required_total)

        if program.program_type == "primary":
            # 균형/창의교양 세부영역 자문(경고만, satisfied 불변).
            warnings.extend(_liberal_area_warnings(db, user_id, program))
        else:
            # 부전공/복수전공/연계전공: 지정 과목·그룹 규칙이 있으면 실판정.
            judgment = _program_rule_judgment(db, user_id, program, requirement)
            if judgment is not None:
                satisfied_total = judgment.satisfied
                earned_for_program = judgment.earned_total
                remaining_total = judgment.remaining_total
                warnings.extend(judgment.warnings)
            else:
                warnings.append(
                    "총 이수학점만 대조됨 — 이 프로그램의 지정 과목 이수 여부는 확인하지 못함"
                )

        results.append(
            ProgramProgress(
                user_academic_program_id=program.id,
                program_type=program.program_type,
                department_id=program.department_id,
                major_id=program.major_id,
                curriculum_year=program.curriculum_year,
                requirement_found=True,
                is_ai_track=_is_ai_track(requirement),
                required_total_credits=required_total,
                earned_total_credits=earned_for_program,
                remaining_total_credits=remaining_total,
                satisfied=satisfied_total,
                categories=categories,
                warnings=warnings,
            )
        )

    return results
