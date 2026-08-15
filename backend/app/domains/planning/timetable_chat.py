"""시간표 LLM 에이전트 (스파이크).

로드맵과 독립적으로 동작한다. 사용자 수강기록 + 진로 + 대화 내용만 보고, 이번 학기 실제
개설 과목 중 시간 충돌 없는 조합을 후보로 제안한다. `roadmap_id`가 필요 없다.

**패턴**: 로드맵 채팅과 완전 동일 — LLM은 "어떤 분반 조합을 시도할지"만 판단하고, 규칙 코드가
그 조합의 유효성(시간 충돌·학점 상한)을 되돌려준다. LLM이 시간표를 문자로 직접 만들지 않는다
(CLAUDE.md 절대원칙 #1: 판정은 규칙 기반, LLM은 설명·추천 문장만).

**정책 (c)**: 로드맵은 LLM이 필요 판단 시에만 `get_roadmap_hint` 도구로 조회한다. 로드맵
확정 안 한 학생도 이 에이전트를 쓸 수 있고, 확정한 학생은 힌트로만 참고한다.

**스코프 (스파이크)**: 세션 영속화 없음. 매 호출이 독립. 대화 히스토리는 클라이언트가
`history` 파라미터로 전달. 세션 저장은 Phase 3c에서 `CourseRoadmapChatSession.roadmap_id`
nullable 마이그레이션 후 추가.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.rag.career_keywords import expand_career_query
from app.ai.rag.curriculum_retriever import CurriculumRetriever
from app.core.config import settings
from app.domains.academics.models import StudentCourseRecord
from app.domains.courses.models import Course, CourseOffering, CourseTime
from app.domains.planning.models import (
    CourseRoadmap,
    CourseRoadmapItem,
    TimetableChatMessage,
    TimetableChatSession,
)
from app.domains.planning.roadmap_chat import (
    _build_llm, _compute_critical_missing_required, _compute_prereq_blocked,
    _compute_retake_candidates, _safe_call,
)
from app.domains.planning.timetable import (
    _combo_is_feasible,
    _completed_course_norms,
    _sections_conflict,
    _serialize_section,
    _term_credit_cap,
    _SectionInfo,
)
from app.domains.users.models import User


MAX_TOOL_ITERATIONS = 8


# Core prompt = 모든 시간표 대화에 항상 실리는 규칙. 상황별 규칙은 아래
# `_TIMETABLE_CONDITIONAL_RULES`에서 관리하고 `_build_timetable_system_prompt`가
# 학생 상태를 probe해 필요한 것만 append. roadmap_chat 리팩터와 동일 패턴.
_TIMETABLE_CORE_PROMPT = """너는 부산대 학생의 이번 학기 시간표를 함께 짜주는 상담 AI다.

**사용자에게 보이는 모든 응답은 finish_response 도구로만 전달한다.** 일반 텍스트로
직접 답하면 사용자에게 아무것도 안 보인다.

**너는 시간표를 직접 만들지 않는다.** 시간이 겹치는 시간표를 내놓으면 수강신청이
막힌다. 대신:
1. `get_student_context`로 학생 수강기록·진로·학과·학점상한·**카테고리별 남은 학점
   (`remaining_by_category`)** 을 먼저 본다.
2. **`remaining_by_category`가 비어있지 않으면 각 카테고리별로 `list_offered_courses`를
   반드시 호출해라.** 예: `remaining_by_category=[{전공필수: 12}, {교양필수: 3}]` 이면
   `list_offered_courses(category="전공필수")` 와 `list_offered_courses(category="교양필수")`
   두 번은 최소로 호출한다. career 관련 소수 과목만 뽑고 부족한 요건 못 채우는 걸 방지.
3. 진로 관련 심화 후보가 필요하면 `list_offered_courses(query=...)` 로 토픽 검색 병행.
   career 검색은 카테고리 훑기의 보조지 대체가 아니다.
4. 후보 과목 조합을 골라 `validate_timetable`에 넘긴다 — 규칙 코드가 시간 충돌·학점
   상한을 검증해 유효한 조합만 되돌려준다. **매 대화 턴에서 finish_response 전에
   validate_timetable을 최소 1회 반드시 호출**해라. validate 없이 finish_response로
   가면 사용자에게 검증 안 된 조합이 노출된다.
5. 유효 조합을 얻으면 `finish_response`에 후보 시간표(offering_ids 배열들)와 사용자에게
   보여줄 설명 메시지를 담아 넘긴다. validate_timetable에서 나온 유효 조합만 schedules
   에 담을 것 — 검증 안 된 offering_ids는 절대 schedules에 넣지 마라.

**학점 목표**: `get_student_context.target_credit_floor` (상한의 80%) 학점 **이상** 채우는
조합을 만들어라. 사용자가 "가볍게 듣고 싶다"고 명시한 경우에만 이 하한을 무시한다.
소수 유효 조합(예: 6~8학점)만 만들고 조기 종료하지 마라 — 추가 후보를 더 찾아 조합 확장.

**진로 반영 검색 (중요)**:
`get_student_context.career_goal` 원문을 그대로 사전 매칭하려 하지 마라 — 대부분 실패.
대신 학생의 진로를 **네 세계 지식으로 해석해 관련 학부 과목 서브토픽 3~5개를 뽑아**
각각 `list_offered_courses(query=...)`로 검색해라.
예:
- career_goal="시스템 프로그래머" → "운영체제" / "시스템프로그래밍" / "컴파일러" /
  "임베디드" / "컴퓨터네트워크"
- career_goal="게임 백엔드" → "네트워크" / "데이터베이스" / "서버" / "분산시스템"

각 검색 결과에서 학생 학과·이수기록·학점 상한을 고려해 3~5과목을 최종 조합으로 고른다.
학생 학과와 무관하거나 이수 완료된 과목은 제외.

**우선순위**:
- 이미 이수한 과목은 다시 추천 X (`completed_course_names`).
- 학생이 "가볍게 듣고 싶어" 같은 학점/과목수 선호 말하면 그 방향으로 좁힌다.
- 진로 관련 전공 과목을 우선. 부족한 학점은 관련 있는 교양으로 채운다.
- 사용자가 로드맵을 언급하거나 "내 계획대로" 같은 표현을 쓰면 그때만 `get_roadmap_hint`.

**저장 흐름**: 시간표 저장은 서버가 이번 학기 로드맵 항목으로 upsert (같은 과목·학기면
스킵). 사용자가 이미 이번 학기 로드맵에 등록한 과목과 겹치면 자동으로 거르지 말고
`finish_response`에서 "OO는 이미 이번 학기 로드맵에 있어서 저장하면 스킵됩니다"라고
알려라. "그래도 저장" 하겠다면 그대로 조합에 포함 (서버가 스킵 처리).

**선수과목 확인**: `check_prereqs`로 학생이 필요한 사전 이수를 마쳤는지 개별 확인 가능.
선수과목 정보가 없으면 이수기록 이름으로 대조.

**사용자 시간·요일 제약 반드시 존중 (매우 중요)**:
사용자가 "월수금만", "화목 빼고", "오전만" 같은 제약을 명시하면 **위반하는 offering은
조합에 절대 넣지 마라**. `validate_timetable`은 시간 충돌·학점 상한만 판정하지 사용자
요일/시간대 요청은 판단 안 함. 절차:
1. `list_offered_courses` 결과의 `offered_sections.times` 검사, 제약과 하나라도 어긋나는
   분반은 후보에서 뺀다.
2. **같은 과목이라도 다른 분반이 제약에 맞으면 그걸 골라라.**
3. 제약을 지키면 목표 학점 도달 못 하는 경우, 억지로 부풀리지 말고 `finish_response`에서
   "월수 오전 제약을 지키면 최대 X학점까지만 가능합니다"처럼 이유 밝히고 축소 조합 제안.
4. 제약이 없으면 이 규칙 무시.

예: "월수 오전만" 요청에 화요일 오후 offering이 있으면 그 과목은 조합에 넣지 마라.
finish_response 텍스트에도 그 요일/시간이 등장하지 않아야 한다.

한국어로, 간결하게 답해라.
"""


# 상황별 규칙 — 학생 상태 probe로 필요한 것만 시스템 프롬프트에 붙는다.
_TIMETABLE_CONDITIONAL_RULES: dict[str, str] = {

    "staggered_semester": """
- **엇학기 대응**: 이 학생은 target_term(달력)과 target_curriculum_term(커리큘럼 학년/학기)
  이 다를 수 있다 (휴학 이력). 예: target_term이 2025-2(달력 2학기)여도
  target_curriculum_term은 4학년 1학기.
  - **개설 과목 필터는 target_term(달력) 기준.** `list_offered_courses`는 그대로 쓰면 됨.
  - **요건·학년 설명은 target_curriculum_term 기준.** finish_response에서 "너는 커리큘럼
    4-1 진행 중이라 전공필수 우선"처럼 커리큘럼 학기로 설명하되, "이번 학기(달력 2학기)
    개설"이라고 스케줄은 달력으로 명시.""",

    "critical_missing": """
- **필수 미이수 + 이번 학기 개설 X → 반드시 안내**: `critical_missing_required`에 항목이
  있다. finish_response 앞부분에서 "이 필수 과목(예: '컴퓨터구조')은 X학기 전용 개설이라
  이번 학기(Y학기)엔 못 담습니다. 다음 학년도 X학기에 반드시 들어야 졸업 가능합니다"처럼
  지연·위험 + 대안 명시. 시간표 후보에는 넣지 마라 (이번 학기 개설 안 됨).""",

    "prereq_blocked": """
- **선수과목 부족 과목 이번 시간표 제외**: `prereq_blocked`에 항목이 있다. 이 course_id는
  시간표 조합에 넘기지 마라. `list_offered_courses` 결과에 있어도 걸러라. description
  파싱 기반이라 오탐 가능성 있으니 학생 "선수 이미 들었어" 반박하면 그대로 수용. 명시적
  요청 시 "선수 X가 미이수라 X부터 이수 권장"이라고 안내.""",

    "retake_candidates": """
- **재수강 권유만, 강요 X**: `retake_candidates`에 C+ 이하 성적 과목이 있다. 학생이
  (a) GPA 개선 명시 언급 (b) "재수강 뭐 좋아?" 직접 질문할 때만 후보 제시. 이번 학기
  시간표에 자동으로 넣지는 마라 — 재수강은 별도 신청 절차 (UI 사용자 선택). 매 답변
  "재수강 어때?" 강권 X. 질문 없으면 언급도 하지 마라.""",
}


def _select_timetable_rules(db: Session, user: User, target_semester: str) -> list[str]:
    """학생 상태를 cheap probe해 활성화할 timetable 조건부 규칙 키 목록.

    roadmap_chat._select_applicable_rules와 상당 부분 공유 (staggered/critical/prereq/
    retake). 단 timetable은 target_semester를 이번 학기 기준으로 넘긴다.
    """
    applicable: list[str] = []

    # 엇학기 힌트 — SCR 최신 연도가 curriculum_year + 4 이상 지났으면 휴학 가능성
    from app.domains.academics.models import UserAcademicProgram
    scr_years = db.scalars(
        select(StudentCourseRecord.year).where(
            StudentCourseRecord.user_id == user.id,
            StudentCourseRecord.year.is_not(None),
            StudentCourseRecord.semester != "입학전성적",
        )
    ).all()
    if scr_years:
        try:
            year_ints = [int(y) for y in scr_years if str(y).isdigit()]
            primary_prog = db.scalars(
                select(UserAcademicProgram).filter_by(user_id=user.id, program_type="primary")
            ).first()
            if primary_prog and primary_prog.curriculum_year and year_ints:
                cy = int(str(primary_prog.curriculum_year))
                if (max(year_ints) - cy) >= 4:
                    applicable.append("staggered_semester")
        except (TypeError, ValueError):
            pass

    # 자동 판정 필드 3개 — get_student_context가 어차피 계산하는 값이라 double-compute
    # 감수 (사용자당 로드맵 1개, 쿼리 저렴).
    if _compute_critical_missing_required(db, user, None, target_semester):
        applicable.append("critical_missing")
    if _compute_prereq_blocked(db, user, None):
        applicable.append("prereq_blocked")
    if _compute_retake_candidates(db, user):
        applicable.append("retake_candidates")

    return applicable


def _build_timetable_system_prompt(
    db: Session, user: User, target_semester: str,
) -> tuple[str, list[str]]:
    """timetable 챗의 최종 시스템 프롬프트 + 적용된 rule 키 목록.

    roadmap_chat._build_system_prompt와 동일 패턴. Rule 키 목록은 trace metadata용.
    """
    rules = _select_timetable_rules(db, user, target_semester)
    conditional_text = "".join(_TIMETABLE_CONDITIONAL_RULES[k] for k in rules)
    return _TIMETABLE_CORE_PROMPT + conditional_text, rules


# 하위 호환: 기존 참조 있으면 core만 반환.
_SYSTEM_PROMPT = _TIMETABLE_CORE_PROMPT


_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_student_context",
            "description": (
                "학생의 학과·진로·이수기록·이번 학기 학점 상한과 함께 "
                "**critical_missing_required**(이번 학기 개설 X 미이수 필수 = 지연 위험), "
                "**retake_candidates**(C+ 이하 성적 이수 = 재수강 권유 후보), "
                "**prereq_blocked**(선수과목 미이수라 담기 부적절한 학과 과목 목록)"
                "를 조회한다. 새 후보를 뽑기 전에 반드시 먼저 호출해라."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_offered_courses",
            "description": (
                "이번 학기(호출 컨텍스트의 year/semester) 실제 개설 과목을 검색한다. "
                "query 비워두고 필터만 걸어도 '이 학과 전공선택 뭐 열렸나' 훑기가 가능하다. "
                "각 결과는 course_id, course_name, category, credits, offered_sections(분반 목록)을 담는다. "
                "offered_sections의 offering_id를 validate_timetable에 넘겨 조합을 검증한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "과목명·토픽 키워드. 비워두면 필터로만 훑는다."},
                    "category": {
                        "type": "string",
                        "description": (
                            "이수구분 필터. 학생이 말한 자연어를 그대로 넘기면 백엔드가 매핑한다 "
                            "(예: '핵심교양' → 효원핵심교양, '교양필수' → 효원핵심교양+기초교양). "
                            "빈 결과가 오면 응답의 `available_categories`를 보고 다른 값으로 재시도해라 — "
                            "같은 인수로 재호출하지 마라."
                        ),
                    },
                    "limit": {"type": "integer", "description": "결과 상한 (기본 10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_by_career",
            "description": (
                "학생 진로 키워드에 맞는 이번 학기 개설 과목을 찾는다. career_hint를 안 넘기면 "
                "학생 프로필의 career_goal을 그대로 쓴다. list_offered_courses와 응답 스키마는 동일."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "career_hint": {
                        "type": "string",
                        "description": "진로 키워드 (예: '백엔드', '데이터'). 미지정 시 학생 프로필 career_goal 사용.",
                    },
                    "limit": {"type": "integer", "description": "결과 상한 (기본 10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_prereqs",
            "description": (
                "특정 과목의 선수과목을 학생이 이수했는지 확인한다. courses.description에서 명시된 "
                "선수과목 텍스트가 있는 경우에만 유효한 판단. 없으면 이수기록에 이름 기준으로 대조만 한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "course_id": {"type": "integer"},
                },
                "required": ["course_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_timetable",
            "description": (
                "후보 분반 조합(offering_id 배열)이 시간 충돌 없이 성립하고 학점 상한 안에 들어오는지 "
                "검증한다. 반환: {ok, total_credits, over_credit_cap, conflicts: [...], sections: [...]}"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "offering_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "list_offered_courses/search_by_career 결과의 offering_id 목록",
                    },
                },
                "required": ["offering_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_roadmap_hint",
            "description": (
                "학생이 로드맵을 언급했을 때만 호출해라. 활성 로드맵에서 이번 학기(year/semester) "
                "계획된 항목들을 돌려준다. 로드맵 없으면 빈 배열."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_response",
            "description": (
                "사용자에게 보여줄 최종 답변을 제출한다. schedules 배열에 validate_timetable로 "
                "이미 검증된 조합들만 넣어라 (검증 안 된 조합 넣으면 안 됨)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "사용자에게 보여줄 설명 (한국어)"},
                    "schedules": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "offering_ids": {"type": "array", "items": {"type": "integer"}},
                                "rationale": {"type": "string", "description": "이 조합을 왜 골랐는지"},
                            },
                            "required": ["offering_ids"],
                        },
                    },
                },
                "required": ["message"],
            },
        },
    },
]


class _TimeTableToolContext:
    """도구 실행 상태. LLM 대화 한 턴 동안 살아 있음."""

    def __init__(self, db: Session, user: User, year: str, semester: str):
        self.db = db
        self.user = user
        self.year = year
        self.semester = semester

    # ------------ 도구 구현 ------------

    def get_student_context(self) -> dict:
        from app.domains.academics.graduation_progress import compute_graduation_progress
        from app.domains.planning.history import project_curriculum_term

        completed = _completed_course_norms(self.db, self.user.id)
        cap = _term_credit_cap(self.db, self.user)
        # 엇학기 대응 — target_term은 달력이고, 커리큘럼 상으로는 다른 학년/학기일 수 있다.
        target_grade, target_curr_sem = project_curriculum_term(
            self.db, self.user.id, self.year, self.semester
        )

        # 카테고리별 남은 학점을 노출 — LLM이 "전공필수 12학점 남음, 교양필수 3학점 남음"
        # 같은 breakdown을 보고 카테고리별로 훑도록 유도한다. 없으면 mini가 career_goal
        # 하나만 보고 좁게 검색해서 결국 소수 과목만 확정하는 문제가 있음(2026-08-10 관찰).
        remaining_by_category: list[dict] = []
        try:
            progresses = compute_graduation_progress(
                self.db, self.user.id, program_types={"primary"}
            )
            if progresses:
                p = progresses[0]  # 주전공만 노출 (시간표는 로드맵 독립이라 부전공까진 안 봄)
                for c in p.categories:
                    if c.remaining_credits is None or c.remaining_credits <= 0:
                        continue
                    remaining_by_category.append({
                        "category": c.category_name,
                        "remaining_credits": float(c.remaining_credits),
                    })
        except Exception:  # noqa: BLE001 - 판정 실패 시 시간표 챗 자체가 죽으면 안 됨
            pass

        return {
            # user_id는 학번이 아니라 내부 PK다. 필드명을 "student_id"로 두면 LLM이
            # 실제 학번으로 오해해서 응답 문자열에 그대로 노출할 수 있어 이름을 바꿨다.
            "user_id": self.user.id,
            "department_id": self.user.department_id,
            "major_id": self.user.major_id,
            "career_goal": self.user.career_goal,
            "term_credit_cap": cap,
            "target_credit_floor": max(1, int((cap or 15) * 0.8)),  # 상한의 80%가 목표 최소치
            "target_term": {"year": self.year, "semester": self.semester},
            # 엇학기 학생은 target_term(달력)과 커리큘럼 학년·학기가 어긋난다.
            # target_curriculum_term은 학생의 재학 순번 기준. list_offered_courses는
            # 달력 학기로 필터해야 하고, 요건·학년 판단은 커리큘럼으로 해라.
            "target_curriculum_term": {"grade": target_grade, "semester": target_curr_sem},
            "completed_course_names": sorted(completed),
            # 카테고리별 부족분. 이 목록을 훑어 각 항목별로 list_offered_courses 호출해라.
            "remaining_by_category": remaining_by_category,
            # 이번 학기(target_term)에 개설 안 되는 미이수 필수 과목 목록. 비어있지
            # 않으면 finish_response에서 사용자에게 "이 필수 과목은 X학기 전용이라
            # 이번엔 못 담는다, 다음 학년도 X학기에 반드시" 라고 안내해라. 이 시간표
            # 조합에는 넣지 마라 (개설 안 됨). roadmap 챗의 동일 기능(critical_missing_
            # required)과 로직 공유. 로드맵이 없어도 SCR 기반으로 판정 가능.
            "critical_missing_required": _compute_critical_missing_required(
                self.db, self.user, roadmap_id=None,
                reference_semester=self.semester,
            ),
            # 재수강 권유 후보 (성적 낮은 이수 과목). 사용자가 명시적으로 GPA 개선
            # 관심 표하거나 재수강 물을 때만 제시. 매번 강권 X. 로드맵 챗과 동일 로직.
            "retake_candidates": _compute_retake_candidates(self.db, self.user),
            # 선수과목 미이수라 이번 학기 시간표에 담기 부적절한 학과 과목. best-effort
            # description 파싱 기반. 이 목록의 course_id는 조합에 넣지 마라.
            "prereq_blocked": _compute_prereq_blocked(self.db, self.user, roadmap_id=None),
        }

    def list_offered_courses(
        self, query: str | None = None, category: str | None = None, limit: int | None = None
    ) -> dict:
        retriever = CurriculumRetriever(self.db)
        results = retriever.search(
            query=query or "",
            department_id=self.user.department_id,
            major_id=self.user.major_id,
            curriculum_year=2026,
            filters={"semester": self.semester, "category": category},
        )
        cap = max(1, min(limit or 10, 30))
        payload: dict = {"results": [self._attach_offerings(r) for r in results[:cap]]}
        # 빈 결과에는 hint 부착 — LLM이 같은 인수로 반복 호출하지 않도록.
        if not payload["results"]:
            from app.ai.rag.curriculum_retriever import available_categories_for_scope
            cats = available_categories_for_scope(
                self.db,
                department_id=self.user.department_id,
                major_id=self.user.major_id,
                semester=self.semester,
            )
            payload["available_categories"] = cats
            reason_parts = []
            if category and category not in cats:
                reason_parts.append(f"category={category!r}는 이번 학기 개설 목록에 없음")
            if query:
                reason_parts.append(f"query={query!r}로 매치 없음")
            payload["note"] = (
                (" · ".join(reason_parts) or "결과 없음")
                + ". available_categories 참고해서 다른 값으로 재시도하거나, "
                  "매치되는 과목이 정말 없으면 finish_response로 사용자에게 알려라."
            )
        return payload

    def search_by_career(self, career_hint: str | None = None, limit: int | None = None) -> dict:
        hint = career_hint or self.user.career_goal
        if not hint:
            return {"results": [], "note": "학생 career_goal이 비어 있고 career_hint도 없음."}
        keywords = expand_career_query(hint)
        retriever = CurriculumRetriever(self.db)
        seen: dict[int, dict] = {}
        cap = limit or 10
        for kw in keywords:
            results = retriever.search(
                query=kw,
                department_id=self.user.department_id,
                major_id=self.user.major_id,
                curriculum_year=2026,
                filters={"semester": self.semester},
            )
            for r in results[:5]:
                cid = r.get("course_id")
                if cid is not None and cid not in seen:
                    seen[cid] = self._attach_offerings(r)
                    if len(seen) >= cap:
                        break
            if len(seen) >= cap:
                break
        return {"results": list(seen.values()), "keywords_used": list(keywords)}

    def check_prereqs(self, course_id: int) -> dict:
        course = self.db.get(Course, course_id)
        if course is None:
            return {"ok": False, "reason": "course_not_found"}
        completed = _completed_course_norms(self.db, self.user.id)
        # 이 스파이크는 선수과목 스키마가 아직 없어서 이름 기반 텍스트 검사만.
        # 실제 선수과목 필드가 생기면 그걸 우선.
        return {
            "ok": True,
            "course_name": course.course_name,
            "student_completed_names": sorted(completed)[:20],
            "note": "선수과목 필드가 스키마에 없음 — 이수기록 이름만 조회해 LLM이 판단.",
        }

    def validate_timetable(self, offering_ids: list[int]) -> dict:
        if not offering_ids:
            return {"ok": False, "reason": "empty_offering_ids"}
        offerings = self.db.scalars(
            select(CourseOffering).where(CourseOffering.id.in_(offering_ids))
        ).all()
        if len(offerings) != len(set(offering_ids)):
            return {"ok": False, "reason": "some_offerings_not_found"}
        times_by_offering: dict[int, list[CourseTime]] = {o.id: [] for o in offerings}
        for t in self.db.scalars(
            select(CourseTime).where(CourseTime.offering_id.in_(offering_ids))
        ).all():
            times_by_offering.setdefault(t.offering_id, []).append(t)
        courses = {
            c.id: c
            for c in self.db.scalars(
                select(Course).where(Course.id.in_({o.course_id for o in offerings}))
            ).all()
        }
        sections: list[_SectionInfo] = []
        for o in offerings:
            c = courses.get(o.course_id)
            sections.append(
                _SectionInfo(
                    item_id=0,
                    course_id=o.course_id,
                    course_code=c.course_code if c else None,
                    course_name=c.course_name if c else "",
                    category=c.category if c else None,
                    credits=float(c.credits) if c and c.credits is not None else None,
                    offering_id=o.id,
                    section=o.section,
                    professor=o.professor,
                    times=tuple(times_by_offering.get(o.id, [])),
                )
            )
        conflicts: list[dict] = []
        for i, a in enumerate(sections):
            for b in sections[i + 1 :]:
                if _sections_conflict(a, b):
                    conflicts.append(
                        {
                            "a": {"offering_id": a.offering_id, "course_name": a.course_name},
                            "b": {"offering_id": b.offering_id, "course_name": b.course_name},
                        }
                    )
        total_credits = sum(s.credits or 0.0 for s in sections)
        cap = _term_credit_cap(self.db, self.user)
        return {
            "ok": not conflicts and total_credits <= cap,
            "total_credits": total_credits,
            "credit_cap": cap,
            "over_credit_cap": total_credits > cap,
            "conflicts": conflicts,
            "sections": [_serialize_section(s) for s in sections],
        }

    def get_roadmap_hint(self) -> dict:
        roadmap = self.db.scalars(
            select(CourseRoadmap).where(CourseRoadmap.user_id == self.user.id)
        ).first()
        if roadmap is None:
            return {"roadmap_exists": False, "items": []}
        items = self.db.scalars(
            select(CourseRoadmapItem).where(
                CourseRoadmapItem.roadmap_id == roadmap.id,
                CourseRoadmapItem.planned_year == self.year,
                CourseRoadmapItem.planned_semester == self.semester,
            )
        ).all()
        return {
            "roadmap_exists": True,
            "roadmap_id": roadmap.id,
            "items": [
                {
                    "item_id": i.id,
                    "course_id": i.course_id,
                    "course_name": i.course_name,
                    "category": i.category,
                    "credits": float(i.credits) if i.credits is not None else None,
                }
                for i in items
            ],
        }

    # ------------ 헬퍼 ------------

    def _attach_offerings(self, retriever_result: dict) -> dict:
        """CurriculumRetriever 결과에 이번 학기 실제 offered_sections(offering_id·분반·시간)를 붙인다."""
        course_id = retriever_result.get("course_id")
        if course_id is None:
            return {**retriever_result, "offered_sections": []}
        offerings = self.db.scalars(
            select(CourseOffering).where(
                CourseOffering.course_id == course_id,
                CourseOffering.year == self.year,
                CourseOffering.semester == self.semester,
            )
        ).all()
        if not offerings:
            return {**retriever_result, "offered_sections": []}
        times_by_off: dict[int, list[CourseTime]] = {o.id: [] for o in offerings}
        for t in self.db.scalars(
            select(CourseTime).where(CourseTime.offering_id.in_([o.id for o in offerings]))
        ).all():
            times_by_off.setdefault(t.offering_id, []).append(t)
        return {
            **retriever_result,
            "offered_sections": [
                {
                    "offering_id": o.id,
                    "section": o.section,
                    "professor": o.professor,
                    "times": [
                        {
                            "day_of_week": t.day_of_week,
                            "start_time": t.start_time.strftime("%H:%M") if t.start_time else None,
                            "end_time": t.end_time.strftime("%H:%M") if t.end_time else None,
                            "classroom": t.classroom,
                        }
                        for t in times_by_off.get(o.id, [])
                    ],
                }
                for o in offerings
            ],
        }

    # ------------ 디스패치 ------------

    def dispatch(self, name: str, tool_input: dict) -> dict:
        handler = {
            "get_student_context": self.get_student_context,
            "list_offered_courses": self.list_offered_courses,
            "search_by_career": self.search_by_career,
            "check_prereqs": self.check_prereqs,
            "validate_timetable": self.validate_timetable,
            "get_roadmap_hint": self.get_roadmap_hint,
        }.get(name)
        if handler is None:
            return {"error": f"unknown_tool:{name}"}
        return _safe_call(handler, tool_input)


# LLM 컨텍스트로 실을 최근 대화 턴 수. 로드맵 챗의 _LLM_HISTORY_WINDOW와 값 정합.
# DB에는 전부 저장하지만 매 요청 시 LLM에는 최근 N턴만 넘겨서 오래된 실패 컨텍스트가
# 후속 응답을 오염시키는 문제를 방지 (2026-08-10 관찰).
_LLM_HISTORY_WINDOW = 6


def create_chat_session(
    db: Session, user: User, year: str, semester: str, title: str | None = None
) -> TimetableChatSession:
    session = TimetableChatSession(
        user_id=user.id, year=year, semester=semester, title=(title or "새 대화")
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def list_chat_sessions(
    db: Session, user: User, year: str | None = None, semester: str | None = None
) -> list[TimetableChatSession]:
    stmt = select(TimetableChatSession).where(TimetableChatSession.user_id == user.id)
    if year is not None:
        stmt = stmt.where(TimetableChatSession.year == year)
    if semester is not None:
        stmt = stmt.where(TimetableChatSession.semester == semester)
    return db.scalars(stmt.order_by(TimetableChatSession.id.desc())).all()


def delete_chat_session(db: Session, user: User, session_id: int) -> bool:
    session = db.get(TimetableChatSession, session_id)
    if session is None or session.user_id != user.id:
        return False
    db.query(TimetableChatMessage).filter(
        TimetableChatMessage.session_id == session_id
    ).delete(synchronize_session=False)
    db.delete(session)
    db.commit()
    return True


def clear_chat_messages(db: Session, user: User, session_id: int) -> int | None:
    """세션은 남기고 메시지만 비운다. 소유자 불일치·없는 세션이면 None.

    로드맵 챗의 "이 대화 비우기"와 같은 동작 — 스레드(제목·학기 맥락)는
    유지한 채 대화만 새로 시작하고 싶을 때 쓴다.
    """
    session = db.get(TimetableChatSession, session_id)
    if session is None or session.user_id != user.id:
        return None
    deleted = db.query(TimetableChatMessage).filter(
        TimetableChatMessage.session_id == session_id
    ).delete(synchronize_session=False)
    db.commit()
    return deleted


def load_chat_messages(
    db: Session, user: User, session_id: int
) -> list[TimetableChatMessage] | None:
    """세션 소유자만 조회 가능. 오래된 것부터 순서대로. 소유자 불일치면 None."""
    session = db.get(TimetableChatSession, session_id)
    if session is None or session.user_id != user.id:
        return None
    return list(db.scalars(
        select(TimetableChatMessage)
        .where(TimetableChatMessage.session_id == session_id)
        .order_by(TimetableChatMessage.id)
    ).all())


def _get_or_create_default_session(
    db: Session, user: User, year: str, semester: str, first_message: str
) -> TimetableChatSession:
    """session_id 없이 호출된 경우: 같은 (user, year, semester)의 최근 세션이 있으면
    이어쓰고, 없으면 첫 메시지 앞부분을 title로 새 세션 생성.
    """
    existing = db.scalars(
        select(TimetableChatSession)
        .where(
            TimetableChatSession.user_id == user.id,
            TimetableChatSession.year == year,
            TimetableChatSession.semester == semester,
        )
        .order_by(TimetableChatSession.id.desc())
        .limit(1)
    ).first()
    if existing is not None:
        return existing
    title = (first_message or "새 대화")[:20]
    return create_chat_session(db, user, year, semester, title=title)


def _load_recent_history(db: Session, session_id: int) -> list[TimetableChatMessage]:
    """LLM 프롬프트에 실을 최근 N턴. desc + limit 후 뒤집는다."""
    latest = db.scalars(
        select(TimetableChatMessage)
        .where(TimetableChatMessage.session_id == session_id)
        .order_by(TimetableChatMessage.id.desc())
        .limit(_LLM_HISTORY_WINDOW)
    ).all()
    return list(reversed(latest))


def run_timetable_chat(
    db: Session,
    user: User,
    year: str,
    semester: str,
    message: str,
    session_id: int | None = None,
) -> dict:
    """시간표 AI 상담 실행. session_id 없으면 (user, year, semester)의 최근 세션을
    이어 쓰거나 새로 만든다.

    반환: {"reply": str, "schedules": [{"offering_ids": [...], "rationale": "..."}, ...],
           "iterations": int, "tool_calls": [...], "session_id": int}
    """
    if session_id is not None:
        session = db.get(TimetableChatSession, session_id)
        if session is None or session.user_id != user.id:
            raise ValueError(f"session_id={session_id}는 이 사용자의 세션이 아닙니다")
        # 기존 세션의 (year, semester)와 요청이 다르면 새 세션 강제 — 다른 학기 대화가
        # 섞이면 컨텍스트가 완전 엉망이 되므로 방어.
        if session.year != year or session.semester != semester:
            raise ValueError(
                f"session {session_id}는 {session.year}-{session.semester} 세션인데 "
                f"요청은 {year}-{semester}입니다. 새 세션을 시작해주세요."
            )
    else:
        session = _get_or_create_default_session(db, user, year, semester, message)

    # 유저 메시지 저장.
    db.add(TimetableChatMessage(session_id=session.id, role="user", content=message))
    db.flush()

    # LLM 컨텍스트용 최근 히스토리 (방금 저장한 유저 메시지 포함, 슬라이딩 윈도우).
    recent_messages = _load_recent_history(db, session.id)

    # Langfuse trace.
    from app.ai.llm.langfuse_callback import observe_agent_call

    with observe_agent_call(
        agent="timetable_chat",
        user_id=user.id,
        session_id=str(session.id),
        user_message=message,
        extra_metadata={"target_term": f"{year}-{semester}"},
    ) as trace:
        trace.add_metadata({
            "year": year,
            "semester": semester,
            "history_length": len(recent_messages),
            "model": settings.ROADMAP_AGENT_MODEL,
            "timetable_session_id": session.id,
        })
        # LLM 초기화·tool 바인딩 + 학생 상태 기반 프롬프트 assembly (fatigue 완화).
        with trace.span("build_llm_and_context"):
            ctx = _TimeTableToolContext(db=db, user=user, year=year, semester=semester)
            llm = _build_llm().bind_tools(_TOOLS, tool_choice="any")
            system_prompt, applied_rules = _build_timetable_system_prompt(db, user, semester)

        # 관측: 어떤 학생에게 어떤 조건부 규칙이 활성화됐는지 + 프롬프트 총 길이.
        trace.add_metadata({
            "applied_conditional_rules": applied_rules,
            "system_prompt_chars": len(system_prompt),
        })

        # DB에서 로드한 최근 히스토리를 langchain 메시지로. 방금 저장한 유저 메시지가
        # 이 목록의 맨 뒤에 이미 포함돼 있어 별도 append 불필요.
        messages: list = [SystemMessage(content=system_prompt)]
        for m in recent_messages:
            if m.role == "user":
                messages.append(HumanMessage(content=m.content))
            elif m.role == "assistant":
                messages.append(AIMessage(content=m.content))

        reply_text = ""
        schedules: list[dict] = []
        tool_call_log: list[dict] = []
        finished = False
        non_finish_tool_calls = 0

        for iteration in range(MAX_TOOL_ITERATIONS):
            ai_msg = llm.invoke(messages, config=trace.config)
            messages.append(ai_msg)
            tool_calls = getattr(ai_msg, "tool_calls", None) or []
            if not tool_calls:
                reply_text = ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
                break
            for call in tool_calls:
                name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
                args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
                call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", "")
                tool_call_log.append({"name": name, "args": args})
                if name == "finish_response":
                    reply_text = args.get("message", "")
                    schedules = args.get("schedules", []) or []
                    messages.append(
                        ToolMessage(content=json.dumps({"ok": True}), tool_call_id=call_id or "")
                    )
                    finished = True
                    break
                non_finish_tool_calls += 1
                with trace.span(f"tool:{name}", as_type="tool", input=args) as tool_span:
                    result = ctx.dispatch(name, args or {})
                    if tool_span is not None:
                        tool_span.update(output=result)
                messages.append(
                    ToolMessage(
                        content=json.dumps(result, ensure_ascii=False, default=str),
                        tool_call_id=call_id or "",
                    )
                )
            if finished:
                break

        # 빈 응답 폴백. mini가 finish_response를 안 부르거나 message="" 로 부르면
        # 유저 화면에 아무것도 안 뜬다 — 최소한 무슨 상황인지 알려주는 문구로 대체.
        if not reply_text or not reply_text.strip():
            reply_text = (
                "죄송해요, 이번엔 시간표 후보를 정리하지 못했어요. "
                "요청을 조금 더 구체적으로 다시 말씀해 주세요 "
                "(예: '전공 필수 위주로', '월수금만', '오전 몰빵')."
            )

        # assistant 메시지 저장 (트레이스 안에서 페이즈로 노출).
        with trace.span("persist_assistant_message"):
            db.add(TimetableChatMessage(
                session_id=session.id,
                role="assistant",
                content=reply_text,
            ))
            db.commit()

        trace.set_output({
            "reply": reply_text,
            "schedules_count": len(schedules),
            "iterations": iteration + 1,
        })
        # 대시보드용 정량 스코어.
        trace.score("finished_with_tool", finished)
        trace.score("iterations_used", iteration + 1)
        trace.score(
            "iteration_efficiency",
            round(1 - iteration / max(MAX_TOOL_ITERATIONS - 1, 1), 3),
        )
        trace.score("tool_calls", non_finish_tool_calls)
        trace.score("schedules_returned", len(schedules))

    return {
        "reply": reply_text,
        "schedules": schedules,
        "iterations": iteration + 1,
        "tool_calls": tool_call_log,
        "session_id": session.id,
    }
