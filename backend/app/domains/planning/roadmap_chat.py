"""로드맵 AI 상담. langchain tool-calling으로 로드맵 변경안을 "제안"한다.

LLM 호출은 langchain의 init_chat_model + bind_tools로 추상화한다 — settings의
ROADMAP_AGENT_MODEL("provider:model") 한 줄만 바꾸면 OpenAI/Anthropic/Google 등
프로바이더가 교체되고, tool 스키마·ToolContext 로직·아래 루프는 그대로 재사용된다.
tool_choice="any"(반드시 도구를 호출)와 finish_response 강제 규약도 프로바이더
무관하게 langchain이 각 SDK 형식으로 변환해준다.

Agent는 course_roadmap_items를 절대 직접 쓰지 않는다 — 항상 pending_roadmap_changes에
제안만 쌓고, 사용자가 confirm 엔드포인트(POST /me/roadmaps/{id}/agent/confirm)로
승인한 항목만 실제로 반영된다(human-in-the-loop). 생성/수정/삭제 모두 이 절차를 거친다.

LangGraph 같은 그래프 오케스트레이션은 쓰지 않는다 — 단일 에이전트가 도구 몇 개를
반복 호출하다 최종 텍스트로 답하는 단순 루프라서 bind_tools + 직접 루프만으로 충분하다.
대화 상태는 클라이언트가 매번 들고 있는 게 아니라 course_roadmap_chat_messages에
서버가 영속화한다(로드맵당 하나의 연속 대화).

과목 후보 검색(search_courses)은 RAG 담당자가 만든 CurriculumRetriever
(app/ai/rag/curriculum_retriever.py)를 그대로 쓴다 — pgvector 임베딩 검색이
가능하면 그걸 쓰고, 안 되면 courses 카탈로그 구조화 필터로 자동 폴백한다.
"""

from __future__ import annotations

import datetime
import json

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.rag.curriculum_retriever import CurriculumRetriever
from app.core.config import settings
from app.domains.academics.graduation_progress import compute_graduation_progress
from app.domains.courses.models import Course
from app.domains.academics.models import GraduationRequirement, StudentCourseRecord, UserAcademicProgram
from app.domains.planning.models import (
    CourseRoadmap,
    CourseRoadmapChatMessage,
    CourseRoadmapItem,
    PendingRoadmapChange,
)
from app.domains.users.models import User

_DEFAULT_CURRICULUM_YEAR = 2026

MAX_TOOL_ITERATIONS = 8


def _current_academic_term() -> tuple[int, int]:
    """오늘 날짜 기준 (학년도, 학기). portal_sync._current_academic_term과 같은 규칙:
    1~2월=전년도 2학기, 3~8월=당해 1학기, 9~12월=당해 2학기.
    """
    today = datetime.date.today()
    if today.month <= 2:
        return today.year - 1, 2
    if today.month <= 8:
        return today.year, 1
    return today.year, 2


def _next_term(year: int, semester: int) -> tuple[int, int]:
    return (year, 2) if semester == 1 else (year + 1, 1)


def _semester_str_to_int(value: str | None) -> int | None:
    """`"1학기"`/`"2학기"`/`"1"`/`"2"`는 int로, 계절수업·전학기·"1학기 또는 2학기"는 None으로."""
    if value is None:
        return None
    v = value.strip()
    if v.startswith("1") and "2" not in v:
        return 1
    if v.startswith("2") and "1" not in v.replace("2", "", 1):
        return 2
    return None


# courses.semester에서 "정규 학기" / "학기 무관"으로 취급하는 값들. 이 셋에 없는 값
# (예: '여름계절수업', '겨울계절수업', '여름도약수업', '겨울도약수업')은 방학 세션 전용
# 개설이라 정규 1/2학기 슬롯에 배치하면 안 된다.
_REGULAR_SEMESTER_VALUES = {"1", "2", "1학기", "2학기"}
_ANY_SEMESTER_VALUES = {"1,2", "1학기 또는 2학기", "전학기"}


def _is_session_only_course_semester(course_semester: str | None) -> bool:
    if not course_semester:
        return False
    v = course_semester.strip()
    return v not in _REGULAR_SEMESTER_VALUES and v not in _ANY_SEMESTER_VALUES


def _is_regular_planned_semester(planned_semester: str | None) -> bool:
    if not planned_semester:
        return False
    return planned_semester.strip() in _REGULAR_SEMESTER_VALUES


def _is_before_current_term(planned_year: str | None, planned_semester: str | None) -> bool:
    """(planned_year, planned_semester)가 현재 학기보다 과거인지. 형식이 명확한 경우만 True/False,
    파싱 불가면 False(가드가 오탐으로 정상 제안을 막지 않도록 보수적으로 통과)."""
    if not planned_year:
        return False
    try:
        py = int(planned_year)
    except ValueError:
        return False
    ps = _semester_str_to_int(planned_semester)
    if ps is None:
        return False
    cy, cs = _current_academic_term()
    return (py, ps) < (cy, cs)

# PNU 학사 규정 기반 정규 학기 수강신청 학점 상한. 졸업기준학점(required_total_credits)만
# 참고해서 판정한다 — 성적우수자 +3, 이월 +2, 학·석사 연계 +6 등 학생별 가변 요소는 로드맵
# 계획 단계에서 확정할 수 없어 base cap만 강제한다(실제 신청 때 CAP 완화 여지가 있어도
# 계획서에 미리 21학점 넘게 밀어넣지 않도록). 계절수업/도약수업은 정규 학기 상한과 별도라
# 이 가드가 걸리지 않는다.
_DEFAULT_TERM_CREDIT_CAP = 21


def _per_term_credit_cap(required_total_credits: int | None) -> int:
    """졸업기준학점을 기준으로 정규 학기당 최대 신청 학점을 리턴한다.
    - 132학점 이하: 19학점
    - 133학점 이상: 21학점
    (약대/의예/의학과 등 special track는 프로그램 유형이 다르므로 여기서는 커버하지 않는다 —
    나중에 program_type 등 확장 시 추가)
    """
    if required_total_credits is None:
        return _DEFAULT_TERM_CREDIT_CAP
    return 21 if required_total_credits >= 133 else 19


_SYSTEM_PROMPT = """너는 부산대학교 학생의 4년 학사 로드맵을 함께 짜주는 상담 AI다.

- **사용자에게 보이는 모든 응답은 finish_response 도구로만 전달한다.** 절대
  일반 텍스트로 직접 답하지 마라 — finish_response를 호출하지 않으면 네 말은
  사용자에게 전달되지 않는다.
- 학생의 졸업요건 남은 학점(get_graduation_progress)과 현재 로드맵(get_roadmap_items)을
  먼저 확인하고 답해라. 짐작으로 과목을 추천하지 마라.
- 과목을 추천할 때는 반드시 search_courses로 실재하는 과목을 찾아 course_id를 확인한 뒤
  propose_change(action="create")로 제안해라. **finish_response 메시지에 과목명을
  하나라도 언급하려면, 그 전에 반드시 그 과목에 대해 propose_change를 호출해야 한다.**
  검색으로 확인하지 않았거나 propose_change로 제안하지 않은 과목명을 finish_response에
  넣는 것은 금지다 — 그런 과목은 언급하지 말고 아예 빼라.
- **"다음 학기 추천" 같이 특정 학기 후보를 뽑아야 할 때는 search_courses를 semester
  필터로 좁혀서 호출해라.** 예: 다음 학기가 3학년 2학기이면
  `search_courses(query="", semester="2학기", grade="3", category="전공선택")`처럼
  category까지 붙여서 부족한 이수구분별로 훑어라. 특정 키워드가 있으면 query에 그
  키워드를, 없으면 query를 비워두고 필터만으로 목록을 받아 그중 학생 상황에 맞는
  과목을 골라 propose_change 해라. 한 번 검색해서 결과가 부족하면 필터/키워드를
  바꿔서 다시 검색해라 — 첫 검색 결과가 애매하다고 "추천할 과목이 없다"고 답하지 마라.
- **다음 학기 추천 시 `get_graduation_progress`에서 `remaining_credits > 0`인 모든
  이수구분에 대해 각각 `search_courses`를 호출해라.** 전공만 훑고 교양은 건너뛰지
  마라. 예: 조회 결과 전공필수·전공선택·교양필수 세 곳에 남은 학점이 있다면 세 번
  다 호출해라:
  - `search_courses(query="", semester="2학기", grade="3", category="전공필수")`
  - `search_courses(query="", semester="2학기", grade="3", category="전공선택")`
  - `search_courses(query="", semester="2학기", grade="3", category="교양필수")`
  특히 **효원핵심교양·기초교양 같은 학과 지정 교양(category="교양필수" 필터로 잡힌다)은
  졸업요건이라 반드시 이수해야 하니 남은 학점이 있으면 전공과 나란히 추천해라.**
  전공선택 남은 학점이 훨씬 많더라도 교양필수 3학점을 이번 학기에 안 넣으면 다음
  학기 부담이 커진다.
- search_courses 결과에 description(교과목개요)이 있으면 과목명만 보고 판단하지 말고
  그 내용을 실제로 읽고 학생의 진로/관심사와 맞는지 확인해라. 과목명에 키워드가 없어도
  description 내용상 관련 있는 과목일 수 있다(반대의 경우도 있다 — description이 없다고
  관련 없다고 단정하지는 마라, 그냥 참고 정보가 없는 것뿐이다).
- **이미 로드맵에 있는 과목(get_roadmap_items 결과의 course_id 목록)은 다시 create로 제안하지 마라 — 같은 과목이 두 번 만들어지는 걸 도구 단에서 거절한다.** 학기/학년만 옮기고 싶으면 그 항목의 `id`로 action='update'를 호출해라.
- **이미 이수한 과목(get_roadmap_items 결과의 `completed_courses`)은 다시 추천하지 마라.** 성적표에서 파싱된 이수내역은 `course_id` 매핑이 대부분 안 돼 있어 로드맵 중복 가드로는 잡히지 않는다. finish_response에서 언급하는 과목명이 `completed_courses`에 있는 이름과 겹치는지 반드시 이름 기준으로 재확인해라 — 부산대 성적표 표기와 교육과정표 표기가 조금 다를 수 있다는 점(예: '데이터구조' vs '자료구조')도 감안해서, 명백한 동일 과목이면 제외해라. 이수기록과 이름이 정확히 일치하는 create는 도구 단에서도 거절한다.
- 기존 항목의 학기/학년을 바꾸고 싶으면 propose_change(action="update", item_id=...)를,
  항목을 빼고 싶으면 propose_change(action="delete", item_id=...)를 써라. 절대
  course_roadmap_items를 직접 바꿀 수 있는 방법은 없다 — 항상 이 제안 도구를 거친다.
- **너는 실제로 아무것도 저장하지 않는다.** propose_change는 "제안"만 만든다.
  finish_response 메시지 마지막에는 반드시 "이 변경을 반영할까요?"처럼 사용자 확인을
  구하는 문장을 넣고, 사용자가 승인해야만 실제로 반영된다는 걸 분명히 말해라.
- 학생이 이미 만족한 이수구분에는 무리하게 과목을 더 넣지 말고, 부족한 이수구분 위주로
  추천해라.
- get_roadmap_items 결과의 earliest_recorded_grade를 반드시 확인해라. 값이 있으면
  그 학년 미만(예: earliest_recorded_grade가 3이면 1,2학년)으로는 propose_change를
  호출하지 마라 — 편입생 등 그 학년 미만 이수 기록이 아예 없는 학생이라는 뜻이고,
  그보다 낮은 학년 과목을 제안하면 거부된다. null이면 이 제약이 없다는 뜻이다.
- **학기 배치 규칙**:
  - `planned_semester`는 반드시 `"1학기"` 또는 `"2학기"` 문자열로 넘겨라. `"1"`, `"2"`,
    영문/숫자만은 저장 포맷과 어긋나 뒤에서 이수기록과 매칭이 깨진다.
  - `planned_year`는 실제 달력 연도(예: `"2027"`)다. `planned_grade`는 그 연도가
    학생 커리큘럼 기준 몇 학년인지(1~4)를 뜻한다. 두 값이 어긋나면 로드맵이 꼬인다.
  - **특별한 사유가 없으면 `search_courses` 결과의 `grade`/`semester`(교육과정표
    권장 학년/학기)를 그대로 `planned_grade`/`planned_semester`로 써라.** 권장값을
    무시하고 아무 학기나 배치하지 마라. `semester`가 `"1학기 또는 2학기"` 또는
    `"전학기"`인 경우(학기 무관 개설)에만 학생 상황에 맞는 정규 학기 하나를 골라라.
  - **계절수업/도약수업 전용 과목은 정규 학기 추천에서 제외해라.** `search_courses`
    결과의 `semester`가 `"여름계절수업"`, `"겨울계절수업"`, `"여름도약수업"`,
    `"겨울도약수업"` 등 방학 세션이면 그건 정규 1·2학기 개설이 아니라 방학 특별
    수업이다. 사용자가 "다음 학기", "N학년 M학기" 같은 정규 학기 추천을 요청했다면
    이런 과목은 finish_response에서 아예 언급하지 말고, propose_change도 하지 마라 —
    도구 단에서 정규 학기로의 create가 거부된다. 사용자가 명시적으로 "계절수업 뭐
    들을까"라고 물었을 때만 planned_semester를 원문 그대로(예: `"여름계절수업"`)
    넣어서 제안해라.
  - **과거 학기에는 새 항목을 만들지 마라.** `get_roadmap_items`가 돌려주는
    `current_academic_term`(현재 학년도/학기)과 `next_plannable_term`(다음 배치
    가능한 학기)을 기준으로, 그 이전 학기로는 create 제안이 거부된다. 새로
    추천하는 과목은 최소한 `next_plannable_term` 이후여야 한다.
  - **학기당 학점 상한(term_credit_cap)을 넘기지 마라.** `get_roadmap_items`가
    `term_credit_cap`(정규 학기 최대 신청 학점)과 `planned_credits_by_term`(학기별
    이미 계획된 학점 합)을 같이 돌려준다. 새 과목을 정규 학기(1학기/2학기)에 추가하면
    그 학기 합이 상한을 넘지 않도록 조정해라. 상한을 넘기는 create/update는 도구가
    거절하는데, 에러 응답에는 `current_items_in_term`(그 학기에 이미 있는 항목 목록),
    `course_semester`(이 과목이 개설되는 학기), `hint`(문맥별 대안 문구)가 같이 온다.
    그 목록 중 새로 넣으려는 과목과 **역할이 겹치거나 우선순위가 낮은 것**을 골라
    `propose_change(action='delete' 또는 'update')`로 먼저 빼거나 다른 학기로 옮긴 뒤,
    새 과목을 다시 create 하는 **대체(swap) 조합**을 사용자에게 제안해라.
  - **대체 후보가 없을 때 "다음 학기로 미루자"고 아무렇게나 말하지 마라.** 정규 과목은
    학기별로 개설이 다르다: `course_semester`가 `"1"`이면 1학기 전용, `"2"`면 2학기 전용,
    `"1,2"`/`"전학기"`면 어느 정규 학기든 가능. 1학기 전용을 2학기로, 2학기 전용을 1학기로
    옮기라고 제안하는 것은 실제로는 그 학기에 열리지 않는 자리에 넣자는 얘기라 잘못이다.
    학기 전용 과목을 미뤄야 하면 **같은 학기의 다음 연도**(예: 3-2 → 4-2)로 제안해라.
    계절수업/도약수업은 정규 상한과 별개라 이 가드가 적용되지 않는다.
- **사용자가 요청한 범위를 벗어나 제안을 남발하지 마라.** 사용자가 "이 과목을
  몇 학기로 옮겨줘"처럼 기존 항목 하나를 콕 집어 요청했으면 그 항목에 대한
  propose_change 하나만 호출하고 끝내라 — 물어보지도 않은 다른 과목을 추가로
  추천하지 마라. "수강계획 추천해줘"처럼 범위가 넓은 요청일 때만 여러 과목을
  한 번에 제안해라.
- 한국어로, 간결하게 답해라.
"""

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_graduation_progress",
            "description": "학생의 주전공 졸업요건 대비 이수구분별 남은 학점을 조회한다.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_roadmap_items",
            "description": (
                "현재 로드맵에 들어있는 모든 항목(학년/학기/과목/상태/출처)과 함께 "
                "현재 학년도/학기(current_academic_term), 다음 배치 가능한 학기"
                "(next_plannable_term), 학기당 학점 상한(term_credit_cap), "
                "학기별 이미 계획된 학점 합(planned_credits_by_term), "
                "성적표 기반 이수기록(completed_courses)을 돌려준다. "
                "새 항목 제안 전에 반드시 이걸 확인해라 — 특히 학점 상한 초과 여부와 "
                "이미 이수한 과목 중복 여부."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_courses",
            "description": (
                "학생 학과·교육과정연도 범위 안에서 교육과정표를 검색한다(RAG). "
                "course_id를 얻으려면 반드시 이걸 먼저 호출해야 한다. query가 비어 있어도 "
                "semester/grade/category 필터만으로 '그 학기 개설 과목 훑어보기'가 가능하다 — "
                "'다음 학기 전공선택 뭐 있냐' 같은 요청은 query='' + semester='2학기' + "
                "category='전공선택'로 호출해라. 결과의 grade(교육과정 권장 학년: '1'~'4' 또는 "
                "'전학년')과 semester(권장 학기: '1학기', '2학기', '1학기 또는 2학기', '전학기', "
                "계절수업 등)를 특별한 사유가 없으면 그대로 propose_change의 planned_grade/"
                "planned_semester로 써라. 결과의 description 필드에 교과목개요(있는 과목만)가 "
                "같이 온다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "검색할 과목명/토픽 키워드. 비워두면 필터 조건에 맞는 과목 목록을 훑어본다.",
                    },
                    "semester": {
                        "type": "string",
                        "description": (
                            "'1학기'/'2학기' 등 학기 필터. 지정하면 그 학기 개설 과목 + 학기 무관 "
                            "개설('전학기'/'1학기 또는 2학기') 과목만 반환. 정규 학기 추천에는 이걸 넣어라."
                        ),
                    },
                    "grade": {
                        "type": "string",
                        "description": "'1'~'4' 학년 필터(문자열). 지정하면 그 학년 + '전학년' 과목만 반환.",
                    },
                    "category": {
                        "type": "string",
                        "description": "'전공필수', '전공선택', '전공기초', '교양필수', '교양선택', '일반선택' 등 이수구분 필터.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_change",
            "description": "로드맵 변경(추가/수정/삭제)을 제안한다. 실제 저장은 사용자 승인 후에만 일어난다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "update", "delete"]},
                    "item_id": {"type": "integer", "description": "update/delete일 때 대상 항목 id"},
                    "course_id": {
                        "type": "integer",
                        "description": "create/update일 때 search_courses로 확인한 과목 id",
                    },
                    "planned_year": {
                        "type": "string",
                        "description": "달력 연도(예: '2027'). 학번/학년이 아니라 실제 학년도.",
                    },
                    "planned_semester": {
                        "type": "string",
                        "description": "반드시 '1학기' 또는 '2학기' 문자열로 넘긴다.",
                    },
                    "planned_grade": {
                        "type": "integer",
                        "description": "커리큘럼 기준 학년(1~4). planned_year와 학생 curriculum_year로부터 일관되게 계산돼야 한다.",
                    },
                    "reason": {"type": "string", "description": "이 변경을 제안하는 이유"},
                },
                "required": ["action", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_response",
            "description": (
                "사용자에게 보여줄 최종 답변을 제출한다. 이 턴에서 사용자에게 말을 전달하는 "
                "유일한 방법이다 — 이걸 호출하지 않으면 아무것도 사용자에게 보이지 않는다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "사용자에게 보여줄 최종 답변(한국어)"},
                },
                "required": ["message"],
            },
        },
    },
]


def _build_llm() -> BaseChatModel:
    """ROADMAP_AGENT_MODEL("provider:model")로 langchain ChatModel을 만든다.

    프로바이더별 API 키는 langchain이 환경변수(OPENAI_API_KEY / ANTHROPIC_API_KEY /
    GOOGLE_API_KEY)에서 읽으므로, settings에 있는 키를 os.environ에 채워준 뒤 만든다.
    """
    import os

    for env_key, value in (
        ("OPENAI_API_KEY", settings.OPENAI_API_KEY),
        ("ANTHROPIC_API_KEY", settings.ANTHROPIC_API_KEY),
        ("GOOGLE_API_KEY", settings.GOOGLE_API_KEY),
    ):
        if value and not os.environ.get(env_key):
            os.environ[env_key] = value

    try:
        return init_chat_model(settings.ROADMAP_AGENT_MODEL, max_tokens=1500)
    except Exception as exc:  # noqa: BLE001 - 설정/패키지 문제를 사용자에게 명확히 전달
        raise RuntimeError(
            f"로드맵 에이전트 LLM 초기화 실패(ROADMAP_AGENT_MODEL={settings.ROADMAP_AGENT_MODEL!r}). "
            f"해당 프로바이더의 API 키와 langchain 통합 패키지가 설치돼 있는지 확인하세요: {exc}"
        ) from exc


class _ToolContext:
    def __init__(self, db: Session, user: User, roadmap: CourseRoadmap):
        self.db = db
        self.user = user
        self.roadmap = roadmap
        self.pending_changes: list[PendingRoadmapChange] = []

    def get_graduation_progress(self) -> dict:
        progresses = compute_graduation_progress(self.db, self.user.id, program_types={"primary"})
        return {
            "programs": [
                {
                    "program_type": p.program_type,
                    "requirement_found": p.requirement_found,
                    "required_total_credits": p.required_total_credits,
                    "earned_total_credits": float(p.earned_total_credits),
                    "remaining_total_credits": float(p.remaining_total_credits)
                    if p.remaining_total_credits is not None
                    else None,
                    "categories": [
                        {
                            "category_name": c.category_name,
                            "required_credits": float(c.required_credits) if c.required_credits is not None else None,
                            "earned_credits": float(c.earned_credits),
                            "remaining_credits": float(c.remaining_credits) if c.remaining_credits is not None else None,
                        }
                        for c in p.categories
                    ],
                }
                for p in progresses
            ]
        }

    def _min_completed_grade(self) -> int | None:
        """편입생에게 1·2학년 과목을 새로 추천하지 않도록 하기 위한 "학생이 실제로
        밟아온 최저 학년"을 계산한다. propose_change의 planned_grade 하한으로 쓴다.

        결정 순서:
        1. 로드맵에 status='completed' + planned_grade IS NOT NULL 인 항목이 있으면
           그 min(planned_grade)를 그대로 쓴다. (일반 재학생이 이미 학기를 밟았을 때)
        2. 없으면(=편입 직후처럼 학기를 아직 안 밟은 상태) StudentCourseRecord에
           semester='입학전성적' 행이 하나라도 있는지 본다. 있으면 이 학생은 편입
           인정 학점을 갖고 3학년 이상에 편성됐다는 뜻이고, 편입 학년을 특정할 근거는
           지금 스키마에서 부족하니 안전측으로 3을 반환한다(부산대는 3학년 편입이
           표준). 3학년 편입생이 2학년 과목을 정규 학기에 새로 추천받는 것은 방지된다.
        3. 그것도 아니면 None을 반환 — 일반 신입생 또는 커리큘럼 미확정 상태. 이 경우
           1학년부터 자유롭게 create 가능.
        """
        grade = self.db.scalar(
            select(func.min(CourseRoadmapItem.planned_grade)).where(
                CourseRoadmapItem.roadmap_id == self.roadmap.id,
                CourseRoadmapItem.status == "completed",
                CourseRoadmapItem.planned_grade.is_not(None),
            )
        )
        if grade is not None:
            return grade
        transfer_row = self.db.scalar(
            select(StudentCourseRecord.id).where(
                StudentCourseRecord.user_id == self.user.id,
                StudentCourseRecord.semester == "입학전성적",
            ).limit(1)
        )
        if transfer_row is not None:
            return 3
        return None

    def _term_credit_cap(self) -> int:
        """이 학생의 정규 학기 학점 상한을 판정한다. primary 프로그램의 졸업기준학점 기반."""
        program = self.db.scalars(
            select(UserAcademicProgram).filter_by(user_id=self.user.id, program_type="primary")
        ).first()
        if program is None or self.user.department_id is None:
            return _DEFAULT_TERM_CREDIT_CAP
        req = self.db.scalars(
            select(GraduationRequirement).where(
                GraduationRequirement.department_id == self.user.department_id,
                GraduationRequirement.major_id == self.user.major_id,
                GraduationRequirement.program_type == "primary",
            )
        ).first()
        if req is None and self.user.major_id is not None:
            # major_id로 못 찾으면 학과 공통(major_id NULL) 요건에 폴백
            req = self.db.scalars(
                select(GraduationRequirement).where(
                    GraduationRequirement.department_id == self.user.department_id,
                    GraduationRequirement.major_id.is_(None),
                    GraduationRequirement.program_type == "primary",
                )
            ).first()
        total_req = req.required_total_credits if req and req.required_total_credits else None
        return _per_term_credit_cap(total_req)

    def _planned_credits_by_term(self, exclude_item_id: int | None = None) -> dict[tuple[str | None, str | None], float]:
        """(planned_year, planned_semester)별 이미 계획된 학점 합계.
        exclude_item_id는 update 시 자기 자신을 빼서 재배치 여지를 만들 때 쓴다.
        """
        items = self.db.scalars(
            select(CourseRoadmapItem).where(CourseRoadmapItem.roadmap_id == self.roadmap.id)
        ).all()
        out: dict[tuple[str | None, str | None], float] = {}
        for it in items:
            if exclude_item_id is not None and it.id == exclude_item_id:
                continue
            key = (it.planned_year, it.planned_semester)
            out[key] = out.get(key, 0.0) + float(it.credits or 0)
        return out

    def _completed_courses(self) -> list[dict]:
        """학생 성적표에서 매핑된 이수기록. course_id는 대부분 None(성적표 파싱이 이름만
        가진 경우가 많음)이라 name/category만으로 LLM에게 노출한다 — LLM이 새 추천을
        만들 때 이 목록에 이미 있는 이름은 제외하도록 활용."""
        records = self.db.scalars(
            select(StudentCourseRecord).where(StudentCourseRecord.user_id == self.user.id)
        ).all()
        return [
            {
                "course_name": r.raw_course_name,
                "category": r.category,
                "credits": float(r.credits) if r.credits is not None else None,
                "year": r.year,
                "semester": r.semester,
            }
            for r in records
        ]

    def get_roadmap_items(self) -> dict:
        items = self.db.scalars(
            select(CourseRoadmapItem)
            .where(CourseRoadmapItem.roadmap_id == self.roadmap.id)
            .order_by(CourseRoadmapItem.planned_year, CourseRoadmapItem.planned_semester)
        ).all()
        cy, cs = _current_academic_term()
        ny, ns = _next_term(cy, cs)
        credit_cap = self._term_credit_cap()
        planned = self._planned_credits_by_term()
        return {
            "items": [
                {
                    "id": item.id,
                    "course_id": item.course_id,
                    "course_name": item.course_name,
                    "category": item.category,
                    "credits": item.credits,
                    "planned_year": item.planned_year,
                    "planned_semester": item.planned_semester,
                    "planned_grade": item.planned_grade,
                    "status": item.status,
                    "source": item.source,
                    "is_confirmed": item.is_confirmed,
                }
                for item in items
            ],
            "earliest_recorded_grade": self._min_completed_grade(),
            "current_academic_term": {"year": str(cy), "semester": f"{cs}학기"},
            "next_plannable_term": {"year": str(ny), "semester": f"{ns}학기"},
            "term_credit_cap": credit_cap,
            "planned_credits_by_term": [
                {"planned_year": y, "planned_semester": s, "credits": c}
                for (y, s), c in sorted(planned.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or ""))
            ],
            "completed_courses": self._completed_courses(),
        }

    def search_courses(
        self,
        query: str = "",
        semester: str | None = None,
        grade: str | int | None = None,
        category: str | None = None,
    ) -> dict:
        # 학과가 없으면 학과 스코프를 잡을 수 없어 애초에 검색이 무의미하다.
        if self.user.department_id is None:
            return {"results": []}
        # query가 비어 있어도 이제는 통과 — semester/grade/category 필터만으로
        # "그 학기 개설된 과목 훑어보기"를 허용한다(다음 학기 추천처럼 특정 키워드
        # 없이 후보를 뽑아야 하는 케이스).
        query = (query or "").strip()

        program = self.db.scalars(
            select(UserAcademicProgram).filter_by(user_id=self.user.id, program_type="primary")
        ).first()
        curriculum_year = program.curriculum_year if program and program.curriculum_year else _DEFAULT_CURRICULUM_YEAR

        retriever = CurriculumRetriever(self.db)
        filters: dict = {"limit": 15}
        if semester:
            filters["semester"] = semester
        if grade is not None and str(grade).strip() != "":
            filters["grade"] = grade
        if category:
            filters["category"] = category
        results = retriever.search(
            query=query,
            department_id=self.user.department_id,
            major_id=self.user.major_id,
            curriculum_year=curriculum_year,
            filters=filters,
        )
        return {
            "results": [
                {
                    "course_id": r["course_id"],
                    "course_name": r["course_name"],
                    "category": r["category"],
                    "credits": r["credits"],
                    "grade": r["grade"],
                    "semester": r["semester"],
                    "evidence": r["evidence"],
                    "description": r["description"],
                }
                for r in results
                if r.get("course_id") is not None
            ]
        }

    def propose_change(
        self,
        action: str,
        reason: str,
        item_id: int | None = None,
        course_id: int | None = None,
        planned_year: str | None = None,
        planned_semester: str | None = None,
        planned_grade: int | None = None,
    ) -> dict:
        if action not in ("create", "update", "delete"):
            return {"error": f"알 수 없는 action: {action}"}

        before_snapshot = None
        if action in ("update", "delete"):
            if item_id is None:
                return {"error": "update/delete는 item_id가 필요합니다"}
            item = self.db.get(CourseRoadmapItem, item_id)
            if item is None or item.roadmap_id != self.roadmap.id:
                return {"error": "해당 로드맵의 항목이 아닙니다"}
            before_snapshot = {
                "course_name": item.course_name,
                "planned_year": item.planned_year,
                "planned_semester": item.planned_semester,
                "planned_grade": item.planned_grade,
            }

        course_obj: Course | None = None
        if action in ("create", "update") and course_id is not None:
            course_obj = self.db.get(Course, course_id)
            if course_obj is None:
                return {"error": f"course_id {course_id}는 존재하지 않는 과목입니다"}

        if action == "create" and course_obj is not None:
            # 계절수업/도약수업 전용 개설 과목을 정규 1/2학기 슬롯에 넣으려는 시도를 막는다.
            # 실제 관측 사고: 3학년 여름계절수업 개설 과목("로보틱스 AI PBL" 등)을
            # "다음 학기(=3학년 2학기)" 추천으로 propose한 사례. 여름/겨울 세션 과목은
            # 정규 학기에 개설되지 않으므로 planned_semester가 1/2학기면 잘못된 배치다.
            if _is_session_only_course_semester(course_obj.semester) and _is_regular_planned_semester(
                planned_semester
            ):
                return {
                    "error": (
                        f"{course_obj.course_name!r}는 교육과정표상 '{course_obj.semester}' 개설 "
                        f"과목이라 정규 학기({planned_semester})에 배치할 수 없습니다. "
                        f"계절수업/도약수업은 정규 1·2학기와 별개 슬롯입니다 — 계절수업으로 "
                        f"제안하려면 planned_semester를 '{course_obj.semester}'로 명시하고, "
                        f"정규 학기 추천이 목적이면 이 과목은 제외하세요."
                    )
                }

        if action in ("create", "update") and planned_grade is not None:
            min_completed_grade = self._min_completed_grade()
            if min_completed_grade is not None and planned_grade < min_completed_grade:
                return {
                    "error": (
                        f"planned_grade={planned_grade}는 제안할 수 없습니다. 이 학생의 이수 기록상 "
                        f"확인되는 최저 학년은 {min_completed_grade}학년입니다(예: 편입생이라 "
                        f"{min_completed_grade}학년 미만 이수 기록이 없음). {min_completed_grade}학년 "
                        "이상으로만 제안하세요."
                    )
                }

        if action == "create" and course_obj is not None:
            # 이미 이수한 과목(성적표 기반 student_course_records)을 다시 create하려는
            # 시도를 막는다. 성적표는 course_id 매핑이 안 되어있는 경우가 대부분이라
            # 이름 정규화 후 exact match로 확인한다(로마자 (I)/(II) 제거, 공백 제거).
            def _norm(n: str | None) -> str:
                """이수기록('컴퓨터프로그래밍 Ⅰ')과 교육과정('컴퓨터프로그래밍(I)')의 표기 차이를 흡수한다.
                - 유니코드 로마자(Ⅰ~Ⅳ)를 ASCII(I,II,III,IV)로 통일 → 숫자는 유지 (I과 II를 뭉치지 않는다)
                - 괄호/공백 제거로 '자료구조(I)'/'자료구조 I'를 같은 키로 만든다"""
                if not n: return ""
                roman = {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV"}
                s = "".join(roman.get(ch, ch) for ch in n)
                return s.replace("(", "").replace(")", "").replace(" ", "").strip()
            new_norm = _norm(course_obj.course_name)
            if new_norm:
                dup = self.db.scalar(
                    select(StudentCourseRecord.id).where(
                        StudentCourseRecord.user_id == self.user.id,
                    )
                )
                # 이름 매칭은 파이썬에서 (SQL LIKE로 정규화 못 하므로)
                completed = self.db.scalars(
                    select(StudentCourseRecord).where(StudentCourseRecord.user_id == self.user.id)
                ).all()
                match = next((r for r in completed if _norm(r.raw_course_name) == new_norm), None)
                if match is not None:
                    return {
                        "error": (
                            f"{course_obj.course_name!r}은(는) 이미 이수한 과목입니다"
                            f"(성적표 원문 '{match.raw_course_name}', {match.year} {match.semester}). "
                            f"이미 이수한 과목은 로드맵에 다시 넣지 마세요."
                        )
                    }

        if action == "create" and course_id is not None:
            # 이미 로드맵에 같은 course_id 항목이 있으면 create 거절.
            # (에이전트가 이미 계획된 과목을 또 추천해서 중복 행이 쌓이던 사고 방지)
            # 이 세션에서 방금 propose한 create도 함께 체크한다 — 커밋되지 않았지만
            # 승인 후 저장될 후보라 두 번 propose되는 걸 막는다.
            already_planned = self.db.scalar(
                select(CourseRoadmapItem.id).where(
                    CourseRoadmapItem.roadmap_id == self.roadmap.id,
                    CourseRoadmapItem.course_id == course_id,
                )
            )
            pending_same = next(
                (c for c in self.pending_changes
                 if c.action == "create" and c.course_id == course_id),
                None,
            )
            if already_planned is not None or pending_same is not None:
                name = course_obj.course_name if course_obj is not None else f"course_id={course_id}"
                where = "이미 로드맵에" if already_planned is not None else "방금 이 대화에서 이미"
                return {
                    "error": (
                        f"{name!r}은(는) {where} 제안된 과목입니다. 같은 과목을 두 번 새로 만들지 마세요. "
                        f"학기/학년만 바꾸려면 action='update'와 대응하는 item_id로 호출하세요."
                    )
                }

        # 정규 학기 학점 상한 초과 방지. create는 새 학점을 그 학기에 더하고, update는
        # (planned_year/semester가 넘어와 실제로 배치가 바뀌는 경우) 이동 대상 학기의
        # 합계에 대상 과목 학점을 더한다. 계절수업/도약수업은 정규 상한과 별도라 제외.
        if (
            action in ("create", "update")
            and _is_regular_planned_semester(planned_semester)
            and planned_year
        ):
            add_credits = 0.0
            if course_obj is not None and course_obj.credits is not None:
                add_credits = float(course_obj.credits)
            elif action == "update" and item_id is not None:
                # course_id가 안 넘어온 update는 기존 item의 credits를 그대로 유지한다고 가정
                existing = self.db.get(CourseRoadmapItem, item_id)
                if existing is not None and existing.credits is not None:
                    add_credits = float(existing.credits)
            planned = self._planned_credits_by_term(
                exclude_item_id=item_id if action == "update" else None
            )
            existing_credits = planned.get((planned_year, planned_semester), 0.0)
            cap = self._term_credit_cap()
            if existing_credits + add_credits > cap:
                # 그 학기에 이미 뭐가 계획돼 있는지 함께 알려준다. LLM이 무작정 거절
                # 문구만 받고 끝내는 대신, 목록 중 이 과목과 대체 가능한 걸 골라
                # delete/update로 바꾸는 방향을 제안할 수 있도록 하기 위함이다.
                same_term_items = self.db.scalars(
                    select(CourseRoadmapItem).where(
                        CourseRoadmapItem.roadmap_id == self.roadmap.id,
                        CourseRoadmapItem.planned_year == planned_year,
                        CourseRoadmapItem.planned_semester == planned_semester,
                    )
                ).all()
                current_items = [
                    {
                        "item_id": it.id,
                        "course_id": it.course_id,
                        "course_name": it.course_name,
                        "category": it.category,
                        "credits": float(it.credits) if it.credits is not None else None,
                        "status": it.status,
                    }
                    for it in same_term_items
                    if not (action == "update" and it.id == item_id)
                ]
                # 이 과목이 다른 학기로 미룰 수 있는 성격인지 안내한다. 정규 1학기 전용
                # 개설과목을 2학기로, 2학기 전용을 1학기로 옮기라고 잘못 유도하지 않기 위해
                # 개설 학기 정보와 대안 학기 후보를 명시적으로 준다.
                course_semester = course_obj.semester if course_obj is not None else None
                if course_semester in ("1,2", "전학기"):
                    defer_hint = (
                        "이 과목은 1학기·2학기 모두 개설(course.semester='"
                        f"{course_semester}')이라 다음 정규 학기로 미룰 수 있다."
                    )
                elif course_semester in ("1", "2"):
                    # 같은 학기 다음 연도로만 미룰 수 있다 (예: 3-2 → 4-2). 학년 상한
                    # 넘으면 이 과목은 이 학기에만 열리므로 반드시 이 학기 안에 넣어야 한다.
                    defer_hint = (
                        f"이 과목은 정규 {course_semester}학기 전용 개설이라 지금 배치하려는 "
                        f"{planned_semester}가 이 과목이 열리는 유일한 학기다. 다음 학기(=1↔2 반대 학기)로 "
                        f"미루면 그 학기에는 아예 열리지 않는다. 이 과목을 넣으려면 같은 "
                        f"{planned_semester}의 다음 연도 슬롯을 쓰거나, 이번 학기 항목 중 하나를 "
                        f"빼서 자리를 만들어야 한다."
                    )
                else:
                    defer_hint = (
                        f"이 과목의 개설 학기는 course.semester='{course_semester}'다 — 이 값이 정규 "
                        f"1/2학기 표기가 아니면 배치 가능한 학기를 신중히 확인해라."
                    )
                return {
                    "error": (
                        f"{planned_year}년 {planned_semester}는 이미 계획된 학점이 "
                        f"{existing_credits:g}학점입니다. 이 과목({add_credits:g}학점)을 더하면 "
                        f"{existing_credits + add_credits:g}학점이 되어 학기당 상한 {cap}학점을 초과합니다."
                    ),
                    "term_credit_cap": cap,
                    "term_existing_credits": existing_credits,
                    "current_items_in_term": current_items,
                    "course_semester": course_semester,
                    "hint": (
                        "이 학기에 이미 있는 current_items_in_term을 살펴봐라. 이 과목과 이수구분·역할이 "
                        "겹쳐서 대체 가능한 항목이 있으면 그것을 propose_change(action='delete', "
                        "item_id=...)로 먼저 빼거나 다른 학기로 옮기고(update), 그 뒤에 이 과목을 다시 "
                        f"create 하는 대체(swap) 방향을 사용자에게 제안해라. {defer_hint}"
                    ),
                }

        if action == "create" and _is_before_current_term(planned_year, planned_semester):
            cy, cs = _current_academic_term()
            ny, ns = _next_term(cy, cs)
            return {
                "error": (
                    f"planned_year={planned_year!r}, planned_semester={planned_semester!r}는 "
                    f"현재 학기({cy}년 {cs}학기)보다 과거라 새 항목으로 만들 수 없습니다. "
                    f"이미 지난 학기 과목은 이수기록으로만 표시됩니다. "
                    f"새 추천은 최소 next_plannable_term({ny}년 {ns}학기) 이후로 잡으세요."
                )
            }

        change = PendingRoadmapChange(
            roadmap_id=self.roadmap.id,
            item_id=item_id,
            action=action,
            course_id=course_id,
            planned_year=planned_year,
            planned_semester=planned_semester,
            planned_grade=planned_grade,
            before_snapshot=before_snapshot,
            reason=reason,
            status="pending",
        )
        self.db.add(change)
        self.db.flush()
        self.pending_changes.append(change)
        return {"change_id": change.id, "action": action}

    def dispatch(self, name: str, tool_input: dict) -> dict:
        handler = getattr(self, name, None)
        if handler is None:
            return {"error": f"알 수 없는 도구: {name}"}
        return handler(**tool_input)


def _load_history(db: Session, roadmap_id: int) -> list[CourseRoadmapChatMessage]:
    return db.scalars(
        select(CourseRoadmapChatMessage)
        .where(CourseRoadmapChatMessage.roadmap_id == roadmap_id)
        .order_by(CourseRoadmapChatMessage.id)
    ).all()


def _build_student_context_block(db: Session, user: User) -> str:
    """이 학생의 진로/전공/부전공/이수기록을 요약해 시스템 프롬프트에 붙일 블록으로 만든다.
    LLM이 매 턴 이 정보를 보고 진로에 맞는 과목·부족한 이수구분·이미 이수한 과목을
    한 번에 고려해 추천할 수 있게 한다. 정보가 없는 항목은 그 사실을 그대로 명시한다.
    """
    from app.domains.academics.models import Department as _Department, Major as _Major

    programs = db.scalars(
        select(UserAcademicProgram).where(UserAcademicProgram.user_id == user.id)
    ).all()
    program_lines: list[str] = []
    for p in programs:
        dept_name = db.get(_Department, p.department_id).name if p.department_id else "학과 미지정"
        major_name = db.get(_Major, p.major_id).name if p.major_id else None
        label = {"primary": "주전공", "double": "복수전공", "minor": "부전공", "teaching": "교직"}.get(
            p.program_type or "", p.program_type or "unknown"
        )
        line = f"  - {label}: {dept_name}"
        if major_name:
            line += f" / {major_name}"
        if p.curriculum_year:
            line += f" ({p.curriculum_year} 교육과정)"
        program_lines.append(line)
    if not program_lines:
        program_lines.append("  - (등록된 학적 프로그램 없음)")

    completed = db.scalars(
        select(StudentCourseRecord).where(StudentCourseRecord.user_id == user.id)
    ).all()
    completed_by_cat: dict[str | None, list[str]] = {}
    for r in completed:
        completed_by_cat.setdefault(r.category, []).append(r.raw_course_name)
    completed_lines: list[str] = []
    for cat in ["전공기초", "전공필수", "전공선택", "교양필수", "교양선택", "일반선택"]:
        names = completed_by_cat.get(cat)
        if names:
            completed_lines.append(f"  - {cat}: {', '.join(sorted(set(names)))}")
    if not completed_lines:
        completed_lines.append("  - (성적표 이수기록 없음 — 신입 또는 미동기화)")

    career = user.career_goal.strip() if user.career_goal else ""
    career_line = career if career else "(등록된 진로 목표 없음 — 프로필에서 입력하면 반영된다)"

    return f"""[이 학생 프로필 — 매 추천 판단 시 이 정보를 함께 고려해라]

- **진로 목표**: {career_line}
  → 전공선택·교양선택 후보가 여러 개일 때 이 방향에 맞는 과목(예: 진로가 "시스템 프로그래밍"이면
    운영체제·컴퓨터네트워크·임베디드 계열, "AI"면 머신러닝·딥러닝·데이터 계열)을 우선해라.
    다만 부족한 이수구분을 채우는 게 최우선이고, 진로 정합성은 후보 사이 우선순위 지표다.

- **학적 프로그램(전공/부전공 등)**:
{chr(10).join(program_lines)}
  → 복수전공/부전공이 있으면 그쪽 이수학점 요건도 병행해 챙겨야 한다. 없으면 주전공 요건만
    본다. get_graduation_progress는 현재 주전공 기준으로만 답한다는 걸 감안해라.

- **이수 완료 과목(성적표 원문 표기, 학과 커리큘럼 표기와 차이 있을 수 있음)**:
{chr(10).join(completed_lines)}
  → 이 목록에 있는 과목명은 다시 create로 제안하지 마라. 성적표 표기(예: "데이터구조")와
    부산대 교육과정 표기(예: "자료구조")가 다를 수 있으니 명백히 같은 과목이면 제외해라.
"""


def run_roadmap_chat(db: Session, user: User, roadmap: CourseRoadmap, message: str) -> dict:
    """사용자 메시지를 처리하고, AI 답변 + 이번 턴에 만들어진 pending change 목록을 반환한다.

    이 함수는 course_roadmap_items를 절대 쓰지 않는다 — 실제 반영은
    apply_pending_changes()가 사용자 승인 후에 한다.
    """
    db.add(CourseRoadmapChatMessage(roadmap_id=roadmap.id, role="user", content=message))
    db.flush()

    history = _load_history(db, roadmap.id)
    system_prompt = _SYSTEM_PROMPT + "\n\n" + _build_student_context_block(db, user)
    messages: list = [SystemMessage(content=system_prompt)]
    for m in history:
        if m.role == "user":
            messages.append(HumanMessage(content=m.content))
        else:
            messages.append(AIMessage(content=m.content))

    llm = _build_llm()
    ctx = _ToolContext(db, user, roadmap)

    # tool_choice="any"를 매 턴 강제한다(langchain이 각 프로바이더 형식으로 변환:
    # OpenAI "required", Anthropic "any" 등) — "일반 텍스트로 바로 답하기"라는
    # 탈출구를 아예 없애서, 모델이 search_courses/propose_change 없이 과목명을
    # 지어내 대충 텍스트로 답하고 끝내버리는 걸 막는다. 사용자에게 보이는 답변도
    # finish_response라는 도구 호출로만 나가게 만들어서(위 _TOOLS 참고),
    # "확인된 과목만 finish_response 전에 propose_change로 제안했어야 한다"는
    # 순서를 프롬프트뿐 아니라 도구 인터페이스 자체로 강제한다.
    llm_required = llm.bind_tools(_TOOLS, tool_choice="any")

    final_text = ""
    finished = False
    for _ in range(MAX_TOOL_ITERATIONS):
        ai_msg: AIMessage = llm_required.invoke(messages)
        messages.append(ai_msg)

        if not ai_msg.tool_calls:
            # 이론상 tool_choice="any"면 안 나와야 하지만, 방어적으로 처리.
            if isinstance(ai_msg.content, str) and ai_msg.content:
                final_text = ai_msg.content
            break

        for tool_call in ai_msg.tool_calls:
            name = tool_call["name"]
            arguments = tool_call["args"] or {}
            if name == "finish_response":
                final_text = arguments.get("message", "")
                result = {"delivered": True}
                finished = True
            else:
                result = ctx.dispatch(name, arguments)
            messages.append(
                ToolMessage(
                    tool_call_id=tool_call["id"],
                    content=json.dumps(result, ensure_ascii=False),
                )
            )

        if finished:
            break

    if not final_text:
        # MAX_TOOL_ITERATIONS를 다 쓰도록 finish_response를 못 부른 경우다.
        # propose_change 자체는 이미 성공적으로 쌓였을 수 있으므로(실제로 그런
        # 경우가 있었다 — 요청 범위를 벗어난 추가 제안을 만드느라 턴을 다 씀),
        # 뭉뚱그린 사과문 대신 도구 없이 한 번 더 불러서 지금까지 쌓인 tool
        # 결과를 바탕으로 실제 요약을 받아낸다.
        try:
            wrapup = llm.invoke(
                messages
                + [
                    HumanMessage(
                        content=(
                            "지금까지 확인/제안한 내용을 바탕으로 사용자에게 보여줄 "
                            "답변을 정리해서 말해줘. 새 도구는 호출하지 마."
                        )
                    )
                ]
            )
            final_text = wrapup.content if isinstance(wrapup.content, str) else ""
        except Exception:  # noqa: BLE001 - 마무리 요약 실패는 폴백 문구로 넘어간다
            final_text = ""
        if not final_text:
            final_text = "죄송해요, 답변을 정리하지 못했어요. 다시 한 번 말씀해 주세요."

    db.add(CourseRoadmapChatMessage(roadmap_id=roadmap.id, role="assistant", content=final_text))
    db.commit()

    return {"reply": final_text, "pending_changes": ctx.pending_changes}


def apply_pending_changes(
    db: Session, roadmap: CourseRoadmap, approved_ids: list[int], rejected_ids: list[int]
) -> dict:
    """사용자가 승인/거절한 pending change를 실제로 반영한다.

    승인된 항목만 course_roadmap_items에 create/update/delete로 반영하고,
    is_confirmed=true로 저장한다(승인 자체가 확정 행위라 이중 확정을 요구하지 않는다).
    거절된 항목은 그냥 status="rejected"로 남기고 버린다.
    """
    applied: list[int] = []
    rejected: list[int] = []

    for change_id in approved_ids:
        change = db.get(PendingRoadmapChange, change_id)
        if change is None or change.roadmap_id != roadmap.id or change.status != "pending":
            continue

        if change.action == "create":
            course = db.get(Course, change.course_id) if change.course_id else None
            item = CourseRoadmapItem(
                roadmap_id=roadmap.id,
                course_id=change.course_id,
                course_name=course.course_name if course else None,
                category=course.category if course else None,
                credits=course.credits if course else None,
                planned_year=change.planned_year,
                planned_semester=change.planned_semester,
                planned_grade=change.planned_grade,
                reason=change.reason,
                source="ai",
                is_confirmed=True,
            )
            db.add(item)
        elif change.action == "update":
            item = db.get(CourseRoadmapItem, change.item_id)
            if item is not None:
                if change.course_id is not None:
                    course = db.get(Course, change.course_id)
                    if course is not None:
                        item.course_id = course.id
                        item.course_name = course.course_name
                        item.category = course.category
                        item.credits = course.credits
                if change.planned_year is not None:
                    item.planned_year = change.planned_year
                if change.planned_semester is not None:
                    item.planned_semester = change.planned_semester
                if change.planned_grade is not None:
                    item.planned_grade = change.planned_grade
                item.reason = change.reason
                item.source = "ai"
                item.is_confirmed = True
        elif change.action == "delete":
            item = db.get(CourseRoadmapItem, change.item_id)
            if item is not None:
                # pending_roadmap_changes.item_id가 이 item을 가리키고 있으면(이번
                # change 자신 포함, 같은 item을 겨냥한 다른 미해결 제안도 포함) FK
                # 제약 때문에 item을 못 지운다 — 실제로 재현된 버그. 참조를 먼저
                # 끊어준다(item은 어차피 사라지므로 다른 제안의 item_id도 null이 맞다).
                db.query(PendingRoadmapChange).filter(
                    PendingRoadmapChange.item_id == item.id
                ).update({"item_id": None})
                db.delete(item)

        change.status = "approved"
        applied.append(change_id)

    for change_id in rejected_ids:
        change = db.get(PendingRoadmapChange, change_id)
        if change is None or change.roadmap_id != roadmap.id or change.status != "pending":
            continue
        change.status = "rejected"
        rejected.append(change_id)

    db.commit()
    return {"applied": applied, "rejected": rejected}
