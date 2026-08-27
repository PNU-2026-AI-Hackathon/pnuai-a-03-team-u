"""이수 가능한 융합전공 / 연계전공 / AI(SW)융합트랙 목록 (읽기 전용).

`app/api/fusion_programs.py`(로드맵 "AI융합 가능" 패널)와
`app/domains/planning/roadmap_chat.py`(로드맵 챗의 `get_fusion_programs` 도구)가
같은 판별·게이트 로직을 쓰도록 여기 한곳에 둔다. enroll/cancel 같은 쓰기 동작과
FastAPI 응답 스키마는 api 레이어에 남긴다.

프로그램 식별: `majors.name` / `departments.name` 접미사(`(SW융합트랙)` /
`(SW연계전공)` / `(SW융합전공)` 등, 부분문자열 `융합트랙` / `연계전공` / `융합전공`)와
`is_ai_track()`. `program_type`은 필터로 쓰지 않는다 — SW 계열은 `interdisciplinary`,
`seed_interdisciplinary_majors_2026_08`은 `minor` / `dual`. 단 `primary` 행은 제외한다
(지능형헬스사이언스융합전공·핀테크융합전공처럼 주전공 세부전공으로도 등록된 케이스 방어).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domains.academics.models import (
    Department,
    GraduationRequirement,
    Major,
    ProgramCourse,
    UserAcademicProgram,
)
from app.domains.academics.tracks import is_ai_track, track_scope_major_ids
from app.domains.courses.models import Course
from app.domains.users.models import User

# UserAcademicProgram.program_type의 등록 가능한(=부·복수전공) 값 → 한글 라벨.
ENROLLMENT_TYPE_LABELS = {"minor": "부전공", "dual": "복수전공"}
KIND_ORDER = {"track": 0, "linked": 1, "convergence": 2}

# 패널의 "이수 계획에 저장"이 다루는 UserAcademicProgram.program_type 전부.
# interdisciplinary는 연계전공(kind='linked')만 — AI융합트랙(kind='track')은
# 같은 program_type지만 전용 경로(app/api/tracks.py)로 등록한다.
PLAN_SAVE_PROGRAM_TYPES = ("minor", "dual", "interdisciplinary")


def enrollable_label(program_type: str | None, kind: str | None) -> str | None:
    """이 프로그램을 패널에서 이수 계획으로 저장할 수 있으면 표시용 라벨, 아니면 None.

    부전공/복수전공은 kind와 무관하게 저장 가능. 연계전공은 interdisciplinary +
    kind='linked'일 때만 — AI융합트랙(kind='track')은 여기서 제외한다.
    """
    if program_type in ENROLLMENT_TYPE_LABELS:
        return ENROLLMENT_TYPE_LABELS[program_type]
    if program_type == "interdisciplinary" and kind == "linked":
        return "연계전공"
    return None


@dataclass(frozen=True)
class ParticipatingDept:
    id: int
    name: str


@dataclass
class FusionProgramInfo:
    program_id: int  # graduation_requirements.id
    department_id: int  # 개설(host) 학과
    department_name: str
    major_id: int | None  # 학과 자체가 프로그램이면 None (핀테크/반도체 등)
    program_name: str  # major.name or department.name
    kind: str  # "track" | "linked" | "convergence"
    kind_label: str  # "SW연계전공" | "AI융합트랙" | "융합전공" ...
    program_type: str | None  # 원시값: interdisciplinary | minor | dual
    program_type_label: str | None  # "부전공" | "복수전공" | "연계전공" | None(=저장 불가)
    total_credits: int | None
    curriculum_year: str | None
    participating_departments: list[ParticipatingDept] = field(default_factory=list)
    enrolled: bool = False
    user_academic_program_id: int | None = None
    enrollment_editable: bool = False


def suffix_label(name: str | None) -> str | None:
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


def classify(
    requirement: GraduationRequirement, dept_name: str, major_name: str | None
) -> tuple[str, str] | None:
    """(kind, kind_label) 또는 None(융합 프로그램 아님).

    kind는 프론트 스타일링용 3분류(track/linked/convergence). kind_label은
    사용자에게 보이는 정확한 명칭 — AI융합교육원 프로그램은 접미사 그대로
    (SW연계전공 / SW융합전공 / SW융합트랙), AI융합트랙 인증은 'AI융합트랙',
    그 외(반도체·DX 등)는 일반 '융합전공'.
    """
    hay = f"{major_name or ''} {dept_name or ''}"
    suffix = suffix_label(major_name)
    if is_ai_track(requirement):
        return "track", "AI융합트랙"
    if "융합트랙" in hay:
        return "track", suffix or "융합트랙"
    if "연계전공" in hay:
        return "linked", suffix or "연계전공"
    if "융합전공" in hay:
        return "convergence", suffix or "융합전공"
    return None


def participating_departments(
    db: Session, dept_id: int, major_id: int | None
) -> list[ParticipatingDept]:
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
    return [ParticipatingDept(id=row[0], name=row[1]) for row in db.execute(stmt).all()]


def student_can_pursue(
    home_dept: int | None,
    my_dept: int,
    participating: list[ParticipatingDept],
    kind: str | None = None,
) -> bool:
    """학생이 이 프로그램을 이수 대상으로 볼 수 있는가.

    판별 기준은 `program_type`이 아니라 프로그램 종류(`kind`)와 **실제
    교차인정(cross-listing) 여부**다.

    - `program_courses`가 아예 없는 프로그램(시드 미완): 확인할 근거가 없으므로
      어느 학과에도 안 뜬다.
    - 연계전공(`kind='linked'`, SW연계전공): 참여학과가 아닌 학생도 이수 가능하다
      (학사 안내) — 학과 무관 노출.
    - 참여학과가 프로그램 자기 학과(`home_dept`) 하나뿐인 융합전공(반도체·DX·
      그린바이오 등 새 융합전공): AIS가 참여학과 과목까지 융합전공 유닛 코드 하나로
      통합 제공해서 `program_courses`의 개설학과가 그 융합전공 하나뿐이다. 참여학과
      게이트를 걸면 어느 학과 학생에게도 안 뜨므로 학과 무관 노출한다.
    - 참여학과가 실제로 갈리는 융합전공·융합트랙(SW융합트랙·핀테크융합전공):
      내 학과가 참여학과에 있을 때만 노출한다.
    """
    if not participating:
        return False
    if kind == "linked":
        return True
    cross_listed = any(part.id != home_dept for part in participating)
    if not cross_listed:
        return True
    return any(part.id == my_dept for part in participating)


def available_fusion_programs(db: Session, user: User) -> list[FusionProgramInfo]:
    """이 학생이 이수할 수 있는 융합/연계전공·AI(SW)융합트랙 목록.

    학생 본인의 주전공 프로그램은 제외. 이미 계획/학적으로 등록한 minor/dual
    프로그램은 목록에 남기되 `enrolled=True`로 표시한다.
    """
    if user.department_id is None:
        return []
    my_dept = user.department_id
    my_program = (user.department_id, user.major_id)

    rows = db.execute(
        select(GraduationRequirement, Department.name, Major.id, Major.name)
        .join(Department, Department.id == GraduationRequirement.department_id)
        .outerjoin(Major, Major.id == GraduationRequirement.major_id)
        .where(
            # 주전공 세부전공(지능형헬스사이언스융합전공·핀테크융합전공 등)이 이름에
            # '융합전공'을 갖고 primary GR로도 등록돼 있어 제외한다. SQL상 program_type
            # 이 NULL인 행도 함께 빠지는데(NULL != 'primary' → not true), 융합 프로그램
            # 중 program_type NULL인 건 없어 무해하다.
            GraduationRequirement.program_type != "primary",
            or_(
                Major.name.like("%융합전공%"),
                Major.name.like("%연계전공%"),
                Major.name.like("%융합트랙%"),
                Department.name.like("%융합전공%"),
                Department.name.like("%연계전공%"),
                Department.name.like("%융합트랙%"),
                # is_ai_track는 special_rules 기반이라 이름 LIKE로 안 잡힌다.
                # interdisciplinary 후보를 넉넉히 끌어와 classify가 최종 판별.
                GraduationRequirement.program_type == "interdisciplinary",
            ),
        )
    ).all()

    # (dept, major, program_type)별로 curriculum_year 사전식 최댓값 한 행만 남긴다.
    best: dict[tuple[int | None, int | None, str | None], tuple] = {}
    for requirement, dept_name, major_id, major_name in rows:
        classified = classify(requirement, dept_name, major_name)
        if classified is None:
            continue
        key = (requirement.department_id, requirement.major_id, requirement.program_type)
        current = best.get(key)
        if current is None or (requirement.curriculum_year or "") > (
            current[0].curriculum_year or ""
        ):
            best[key] = (requirement, dept_name, major_id, major_name, classified)

    # 같은 (dept, major)에 minor/dual 행이 있으면 interdisciplinary 행은 버린다.
    # (핀테크융합전공처럼 interdisciplinary(42) + dual(42)이 중복으로 뜨는 것 방지.
    #  SW연계전공은 interdisciplinary만 있어 그대로 남는다.)
    enrollment_scopes = {
        (dept, major) for (dept, major, ptype) in best if ptype in ("minor", "dual")
    }
    best = {
        key: value
        for key, value in best.items()
        if not (key[2] == "interdisciplinary" and (key[0], key[1]) in enrollment_scopes)
    }

    enrolled_by_scope: dict[tuple[int | None, int | None, str], list[UserAcademicProgram]] = {}
    for program in db.scalars(
        select(UserAcademicProgram).where(
            UserAcademicProgram.user_id == user.id,
            UserAcademicProgram.status == "active",
            UserAcademicProgram.program_type.in_(PLAN_SAVE_PROGRAM_TYPES),
        )
    ):
        enrolled_by_scope.setdefault(
            (program.department_id, program.major_id, program.program_type), []
        ).append(program)

    out: list[FusionProgramInfo] = []
    for requirement, dept_name, major_id, major_name, (kind, kind_label) in best.values():
        if (requirement.department_id, requirement.major_id) == my_program:
            continue  # 본인 주전공 프로그램 제외
        parts = participating_departments(
            db, requirement.department_id, requirement.major_id
        )
        if not student_can_pursue(requirement.department_id, my_dept, parts, kind):
            continue  # 연계전공이 아니고, 교차인정 있는데 참여 학과에 내 학과가 없으면 스킵
        if kind == "track" and user.major_id is not None:
            scope = track_scope_major_ids(db, requirement)
            if scope and user.major_id not in scope:
                continue  # 같은 학부의 다른 전공 대상 트랙 (바이오메디컬디바이스 등)
        parts.sort(key=lambda part: part.name)
        # 저장 불가한 종류(AI융합트랙 등)는 enrolled 계산에서 제외 — 트랙은 전용
        # 경로로 등록해도 이 패널에선 계획으로 안 다룬다(종전 동작 유지).
        label = enrollable_label(requirement.program_type, kind)
        enrolled_programs = (
            enrolled_by_scope.get(
                (requirement.department_id, requirement.major_id, requirement.program_type), []
            )
            if label
            else []
        )
        planned_program = next(
            (program for program in enrolled_programs if program.source == "fusion_plan"),
            None,
        )
        anchor = planned_program or (enrolled_programs[0] if enrolled_programs else None)
        out.append(
            FusionProgramInfo(
                program_id=requirement.id,
                department_id=requirement.department_id,
                department_name=dept_name,
                major_id=major_id,
                program_name=major_name or dept_name,
                kind=kind,
                kind_label=kind_label,
                program_type=requirement.program_type,
                program_type_label=label,
                total_credits=requirement.required_total_credits,
                curriculum_year=requirement.curriculum_year,
                participating_departments=parts,
                enrolled=bool(enrolled_programs),
                user_academic_program_id=anchor.id if anchor else None,
                enrollment_editable=planned_program is not None,
            )
        )

    out.sort(key=lambda info: (KIND_ORDER.get(info.kind, 9), info.program_name))
    return out
