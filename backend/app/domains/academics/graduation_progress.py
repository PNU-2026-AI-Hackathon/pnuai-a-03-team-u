"""flat graduation_requirements 테이블과 학생 이수내역(student_course_records)을
카테고리별로 단순 대조해 졸업까지 남은 학점을 계산한다.

택N/M·개별 필수과목 판정 같은 세부 규칙은 다루지 않고, 이수구분별 합계 학점만
비교한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domains.academics.models import GraduationRequirement, StudentCourseRecord, UserAcademicProgram
from app.domains.academics.program_status import ACTIVE_PROGRAM_STATUSES

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

# 효원균형교양 7개 세부영역.
#
# portal_sync._refine_liberal_area_categories가 One-Stop 졸업예정정보를 근거로
# student_course_records.category를 '교양선택' → 세부영역명으로 덮어쓴다(로드맵 챗이
# "너 사상과역사 아직 안 들었네" 같은 조언을 하려면 이 값이 필요하다).
#
# 그래서 집계할 때 이 값들을 다시 '교양선택'으로 롤업하지 않으면 **이수학점이 통째로
# 사라진다** — 균형교양 18학점을 이수한 학생이 포털 동기화 후 "교양선택 0학점 이수,
# 18학점 남음"으로 표시되는 실제 버그가 있었다(2026-08-13 발견).
#
# 여기(academics)에 두는 이유: 판정 엔진이 진짜 소비자이고, planning(로드맵 챗)이
# 이걸 가져다 쓰는 방향이 모듈 경계상 맞다.
BALANCED_LIBERAL_AREAS: tuple[str, ...] = (
    "사상과역사",
    "사회와문화",
    "문학과예술",
    "과학과기술",
    "건강과레포츠",
    "외국어",
    "융복합",
)

# 이수기록 category 원값 → 요건 집계에 쓸 상위 이수구분.
_CATEGORY_ROLLUP: dict[str, str] = {area: "교양선택" for area in BALANCED_LIBERAL_AREAS}

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
_COURSE_CATEGORY_TO_REQUIREMENT: dict[str, str] = {
    "효원핵심교양": "교양필수",
    "효원균형교양": "교양선택",
    "효원창의교양": "교양선택",
    "기초교양": "교양선택",
}


def requirement_category_for_course(category: str | None) -> str | None:
    """수강편람 과목의 이수구분을 졸업요건 라벨로 정규화한다.

    대응이 없으면 원값을 그대로 돌려준다 — 모르는 값을 임의의 요건에 밀어 넣는 것보다
    "이 이수구분은 요건에 매핑되지 않는다"가 드러나는 편이 안전하다.
    """
    if category is None:
        return None
    return _COURSE_CATEGORY_TO_REQUIREMENT.get(
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
        remaining_total = None
        satisfied_total = None
        if required_total is not None:
            remaining_total = max(Decimal(required_total) - total_earned, Decimal("0"))
            satisfied_total = total_earned >= Decimal(required_total)

        results.append(
            ProgramProgress(
                user_academic_program_id=program.id,
                program_type=program.program_type,
                department_id=program.department_id,
                major_id=program.major_id,
                curriculum_year=program.curriculum_year,
                requirement_found=True,
                required_total_credits=required_total,
                earned_total_credits=total_earned,
                remaining_total_credits=remaining_total,
                satisfied=satisfied_total,
                categories=categories,
                warnings=warnings,
            )
        )

    return results
