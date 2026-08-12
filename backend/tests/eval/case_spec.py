"""페르소나·기대 assertion 데이터클래스.

한 케이스 = (PersonaSpec 시드 + 대화 프롬프트 + ExpectedBehavior 리스트).
프레임 명세는 골든 데이터셋 계획 memo(`project_golden_dataset_plan.md`) 참고.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal


# --- 시드 스펙 --------------------------------------------------------------


@dataclass
class DepartmentSpec:
    id: int
    name: str
    college_name: str = "테스트대학"


@dataclass
class MajorSpec:
    id: int
    name: str
    department_id: int


@dataclass
class RequirementSpec:
    """graduation_requirements 한 행."""

    department_id: int
    program_type: str = "primary"           # primary / minor / dual / interdisciplinary
    major_id: int | None = None
    curriculum_year: str = "2024"
    required_total_credits: int | None = 133
    required_major_foundation: int | None = None
    required_major_required: int | None = None
    required_major_elective: int | None = None
    required_general_required: int | None = None
    required_general_elective: int | None = None
    required_free_elective: int | None = None
    special_rules: dict | None = None       # 부·복수·SW융합 규칙 JSONB


@dataclass
class ProgramSpec:
    """user_academic_programs 한 행 (primary/minor/dual/interdisciplinary)."""

    department_id: int
    program_type: str = "primary"
    major_id: int | None = None
    curriculum_year: str = "2024"
    status: str = "active"


@dataclass
class CourseSpec:
    """courses 한 행 (교육과정 카탈로그)."""

    id: int
    course_name: str
    department_id: int
    major_id: int | None = None
    category: str = "전공선택"
    credits: float = 3.0
    year: str = "3"
    semester: str = "1"                     # '1'/'2'/'전학기'/'여름계절수업' 등
    description: str | None = None


@dataclass
class RecordSpec:
    """student_course_records 한 행 (성적표 기반 이수기록)."""

    raw_course_name: str
    category: str = "전공필수"
    credits: float = 3.0
    year: str = "2024"
    semester: str = "1학기"                  # 또는 '입학전성적'
    course_id: int | None = None


@dataclass
class RoadmapItemSpec:
    """course_roadmap_items 한 행 (이미 계획/이수 처리된 로드맵 항목)."""

    course_name: str
    planned_grade: int | None = None
    # 달력 축. 휴학·편입이 없는 페르소나는 커리큘럼 축과 같다.
    planned_year: str | None = None
    planned_semester: str | None = None
    # 커리큘럼 축. 생략하면 시드가 planned_semester를 그대로 쓴다 — 두 축이 같은
    # 페르소나(대다수)를 매번 두 번 적지 않기 위한 기본값이다. 엇학기 페르소나는
    # 반드시 명시해야 실제 데이터와 같은 모양이 된다.
    curriculum_semester: str | None = None
    credits: float | None = None
    course_id: int | None = None
    category: str | None = None
    status: str | None = None                # 'completed' 등


@dataclass
class OfferingSpec:
    """course_offerings + course_times 한 벌 (시간표 챗용)."""

    id: int
    course_id: int
    year: str
    semester: str                            # '1학기'/'2학기'
    section: str = "01"
    times: list[tuple[str, str, str]] = field(default_factory=list)
    # times: [(요일, 시작 HH:MM, 끝 HH:MM), ...]


@dataclass
class PersonaSpec:
    """페르소나 하나. cases.py에서 만들어 personas.build_persona_db(spec)에 넘긴다."""

    id: str                                  # 케이스 슬러그 (예: "cs-freshman-backend")
    label: str                               # 사람이 읽는 라벨
    departments: list[DepartmentSpec] = field(default_factory=list)
    majors: list[MajorSpec] = field(default_factory=list)
    # user
    user_id: int = 1
    user_name: str = "테스트"
    department_id: int | None = None
    major_id: int | None = None
    career_goal: str | None = None
    admission_type: str = "freshman"        # 'freshman' | 'transfer'
    # 학적/이수/카탈로그
    programs: list[ProgramSpec] = field(default_factory=list)
    requirements: list[RequirementSpec] = field(default_factory=list)
    courses: list[CourseSpec] = field(default_factory=list)
    records: list[RecordSpec] = field(default_factory=list)
    roadmap_items: list[RoadmapItemSpec] = field(default_factory=list)
    # 시간표 챗용
    offerings: list[OfferingSpec] = field(default_factory=list)


# --- assertion 명세 ---------------------------------------------------------

AssertionKind = Literal[
    "tool_called",           # target: 호출돼야 하는 tool 이름
    "tool_not_called",
    "response_mentions",     # target: 답변 텍스트에 반드시 포함될 substring
    "response_absent",       # target: 반드시 없어야 할 substring
    "iterations_le",         # target: max 반복 수 (int)
    "pending_change_count",  # target: (op, n) op ∈ {"==","<=",">="}
    "schedules_count",       # 시간표 챗 전용: (op, n)
    "custom",                # target: Callable[[EvalResult], str | None] — None이면 pass
    "llm_judge",             # target: 자연어 판정 기준. 판정 LLM(gpt-4o-mini 기본)이 yes/no 결정
]


@dataclass
class ExpectedBehavior:
    kind: AssertionKind
    target: object                           # kind별 의미 다름 (위 주석 참고)
    reason: str = ""                         # 왜 이걸 검증하는지 (관찰된 버그 등)


# --- 케이스 --------------------------------------------------------------


AgentKind = Literal["roadmap", "timetable"]


@dataclass
class EvalCase:
    slug: str                                # id (파일 내 유일)
    persona: PersonaSpec
    prompt: str
    agent: AgentKind = "roadmap"
    expectations: list[ExpectedBehavior] = field(default_factory=list)
    # 시간표 챗 전용 — 어느 학기를 대상으로 짤 지
    timetable_year: str = "2026"
    timetable_semester: str = "2학기"


@dataclass
class EvalResult:
    """run_eval에서 assertion 채점에 넘겨줄 실행 결과 뷰."""

    reply: str
    tool_calls: list[dict]                   # [{"name": str, "args": dict}, ...]
    iterations_used: int
    pending_changes_count: int = 0
    schedules_count: int = 0
