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
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.ai.rag.curriculum_retriever import CurriculumRetriever
from app.core.config import settings
from app.domains.academics.course_substitution import (
    substituted_course_names,
    substituting_record,
)
from app.domains.academics.graduation_progress import compute_graduation_progress
from app.domains.academics.program_evaluator import evaluate_program
from app.domains.academics.models import (
    GraduationRequirement, Major as _Major, ProgramCourse, StudentCourseRecord, UserAcademicProgram,
)
from app.domains.academics.tracks import (
    AI_COMMON_SCHEDULING_NOTE, find_ai_tracks_for_department, list_ai_common_courses,
)
from app.domains.courses.models import Course
from app.domains.planning.models import (
    CourseRoadmap,
    CourseRoadmapChatMessage,
    CourseRoadmapChatSession,
    CourseRoadmapItem,
    PendingRoadmapChange,
)
from app.domains.users.admission import (
    PRE_ADMISSION_SEMESTERS, TRANSFER_ENTRY_GRADE, is_transfer,
)
from app.domains.users.models import User

_DEFAULT_CURRICULUM_YEAR = 2026

# 한 턴에 허용할 LLM 왕복 횟수. finish_response가 나오면 즉시 루프를 빠져나가므로
# 이 값은 **실제로 그만큼 일해야 하는 턴에만** 걸린다 — 평범한 "다음 학기 뭐 들을까"는
# 예전대로 3~5회에 끝난다(2026-08-20 실측). 8이던 값을 12로 올린 이유는 "졸업까지
# 남은 학기 전부" 요청 때문이다: 요건 조회 + 로드맵 조회 + 학기·이수구분별 search_courses
# 여러 번 + propose_term_plan + (미배정분 보충 검색 + 2차 propose_term_plan) + finish
# 까지 하면 8로는 마지막 보충 라운드가 잘린다.
MAX_TOOL_ITERATIONS = 12

# 미배정 학점이 남았다고 finish_response를 되돌리려면, 그 뒤에 최소 이만큼의 왕복이
# 남아 있어야 한다(보충 search_courses + 2차 propose_term_plan + finish_response).
# 예산이 모자란데도 되돌리면 finish_response를 아예 못 받고 폴백 요약으로 떨어진다 —
# 실제로 그랬다(2026-08-20: 게이트를 넣자 12회를 다 쓰고 "죄송해요, 답변을 정리하지
# 못했어요"가 나갔다. 제안은 19건이나 쌓여 있었는데도).
_FINISH_GATE_RESERVE = 4

# "교양선택" 세부영역 8개(2021교육과정 구체계 — graduation_progress.BALANCED_LIBERAL_AREAS
# 참고). portal_sync._refine_liberal_area_categories가 One-Stop
# 졸업예정정보 판정을 근거로 student_course_records.category를 상위값('교양선택')에서
# 이 세부영역명으로 override 한다. 여기 목록은 One-Stop 원문("N영역 : 이름"에서 이름만)과
# 일치해야 한다 — 목록에 없는 이름이 들어오면 컨텍스트 요약에서 조용히 빠져 LLM이
# 미이수로 오인할 수 있다.
# 단일 출처는 academics 쪽이다 — 판정 엔진이 이 값들을 '교양선택'으로 롤업해야 해서
# (graduation_progress._CATEGORY_ROLLUP) 두 곳에 따로 두면 한쪽만 고쳐져 집계가 어긋난다.
from app.domains.academics.graduation_progress import (
    BALANCED_LIBERAL_AREAS,
    requirement_category_for_course,
)
from app.domains.academics.program_status import (
    ACTIVE_PROGRAM_STATUSES, is_active_program_status,
)

_BALANCED_LIBERAL_AREAS = BALANCED_LIBERAL_AREAS


# program_type → 사용자에게 보여줄 한글 명칭. 컨텍스트 블록과 도구 응답이 같은 값을 써야
# LLM이 한쪽 표기만 보고 다른 이름으로 부르지 않는다.
# `UserAcademicProgram.program_type`의 실제 값과 정확히 맞춘다 (auth._VALID_PROGRAM_TYPES).
_PROGRAM_TYPE_LABELS: dict[str, str] = {
    "primary": "주전공",
    "dual": "복수전공",
    "minor": "부전공",
    "interdisciplinary": "융합·연계전공",
}


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


def _curriculum_semester_for(
    db: Session, user_id: int, planned_year: str | None, planned_semester: str | None
) -> str | None:
    """달력 학기를 커리큘럼 학기로 환산한다. 환산 불가면 None.

    LLM은 propose_change에 달력 학기를 넣는다(프롬프트 규약). 로드맵 화면은
    커리큘럼 학기로 슬롯을 잡으므로, 반영 시점에 나머지 축을 채워 준다.
    """
    if not planned_year or not planned_semester:
        return None
    from app.domains.planning.history import project_curriculum_term

    _, curriculum_semester = project_curriculum_term(db, user_id, planned_year, planned_semester)
    return curriculum_semester


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


# 졸업까지 남은 학기를 세는 상한. 커리큘럼 학년이 4를 넘으면 project_curriculum_term이
# (None, None)을 돌려줘서 자연히 멈추지만, 데이터가 이상할 때 무한 루프가 되지 않도록.
_MAX_PLAN_HORIZON_TERMS = 8

# 학기에 이만큼도 여유가 없으면 "더 채울 수 있다"고 보지 않는다. 부산대 최소 학점
# 과목이 1학점이지만, 1~2학점 남았다고 다시 검색시키면 왕복만 늘고 결과가 안 는다.
_MIN_USEFUL_TERM_ROOM = 3.0


def _remaining_terms_until_graduation(db: Session, user_id: int) -> list[dict]:
    """다음 배치 가능 학기부터 졸업 예정 학기까지의 정규 학기 목록.

    "졸업까지 로드맵 짜줘"에 LLM이 다음 한 학기만 제안하고 끝내던 원인 중 하나가,
    **남은 학기가 몇 개인지 알려주는 값이 어디에도 없었다는 것**이다(2026-08-20 실계정
    관측: 3회 요청 전부 3학년 2학기만 제안, 4-1/4-2는 0건). 달력 학기 → 커리큘럼
    학년/학기 환산은 `project_curriculum_term`이 이미 하고 있고, 4학년을 넘으면
    (None, None)을 돌려준다 — 그 지점이 졸업 예정 시점이다.

    편입생이면 첫 재학 학기가 3학년이라 자연히 남은 학기가 짧게 나온다(3-2 → 4-1 → 4-2).

    **이수기록이 없으면 빈 목록을 돌려준다.** `project_curriculum_term`은 이수기록이
    하나도 없을 때 매 호출마다 "이번이 첫 학기"(rank=1)로 답한다 — 학년이 전진하지
    않으므로 `_MAX_PLAN_HORIZON_TERMS`가 잘라줄 때까지 **같은 학기가 8개** 쌓인다.
    성적표 미업로드·포털 동기화 실패 사용자에게 "2030년 1학기(1학년)"를 계획하라고
    시키는 꼴이라, 근거가 없으면 아무것도 주장하지 않는다.
    """
    from app.domains.planning.history import project_curriculum_term

    cy, cs = _current_academic_term()
    year, semester = _next_term(cy, cs)
    out: list[dict] = []
    seen: set[tuple[int, str | None]] = set()
    for _ in range(_MAX_PLAN_HORIZON_TERMS):
        grade, curriculum_semester = project_curriculum_term(
            db, user_id, str(year), f"{semester}학기"
        )
        if grade is None:
            break
        if (grade, curriculum_semester) in seen:
            # 커리큘럼 학년/학기가 전진하지 않는다 = 기준점이 없다는 뜻.
            return []
        seen.add((grade, curriculum_semester))
        out.append({
            "planned_year": str(year),
            "planned_semester": f"{semester}학기",
            "planned_grade": grade,
            "curriculum_semester": curriculum_semester,
        })
        year, semester = _next_term(year, semester)
    return out


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


# Core prompt = 모든 대화에 항상 실리는 규칙만. 상황별 규칙은 아래 `_CONDITIONAL_RULES`
# 에서 관리하고 `_build_system_prompt` 가 학생 상태를 probe해 필요한 것만 append한다.
# 목적: 프롬프트 fatigue 완화 — 대다수 학생에게 무관한 규칙을 매 턴 노출하지 않는다.
# (2026-08-12 관찰: 프롬프트 300+줄일 때 case 08 부전공이 3/3→1/3로 흔들리는 신호)
_CORE_PROMPT = """너는 부산대학교 학생의 4년 학사 로드맵을 함께 짜주는 상담 AI다.

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
  필터로 좁혀서 호출해라. 이때 `grade` 필터는 걸지 마라.** 요청 학기가 4-1이든
  3-2든, 학생이 아직 못 들은 과목이 이전 학년(1·2학년)에도 남아 있을 수 있다.
  그 개설 학기(1·2학기·전학기)만 맞으면 학년이 낮은 과목도 후보로 유효하다 —
  grade 필터로 좁히면 이런 미이수분이 아예 후보에서 빠진다. 특정 키워드가 있으면 query에
  그 키워드를, 없으면 query를 비워두고 필터만으로 목록을 받아 그중 학생 상황에
  맞는 과목을 골라 propose_change 해라. 한 번 검색해서 결과가 부족하면 필터/키워드를
  바꿔서 다시 검색해라 — 첫 검색 결과가 애매하다고 "추천할 과목이 없다"고 답하지 마라.
- **다음 학기 추천 시 `get_graduation_progress`에서 `remaining_credits > 0`인 모든
  이수구분에 대해 각각 `search_courses`를 호출해라.** 전공만 훑고 교양은 건너뛰지
  마라. **효원핵심교양(category="교양필수")·기초교양(category="교양선택") 같은 교양도 졸업요건이라
  남은 학점 있으면 전공과 나란히 추천해라.**
- **미이수 전공기초·전공필수는 finish_response의 첫 번째 추천 항목으로 무조건 배치해라.**
  대상은 `get_roadmap_items.missing_required_available`에 그대로 담겨 온다 — 도구가
  "미이수 + 그 학기 개설" 조건을 이미 확인한 목록이니 네가 따로 대조하지 마라. 목록에
  과목이 있으면 그게 진로와 무관해 보여도 **다른 진로 관련 전공선택보다 반드시 먼저**
  추천하고, 각 항목의 `program_label`로 어느 전공 요건인지(주전공/부전공/복수전공) 밝혀라.
  **목록이 비어 있으면 미이수 필수가 없다는 뜻이니 그 얘기를 꺼내지 마라** — 목록에 없는
  과목을 미이수라고 하면 이미 이수한 과목을 다시 들으라고 하는 셈이 된다. 이 순서를
  뒤집으면(진로 관련 전공선택 먼저 나열하고 전공기초는 뒤에 언급) 사용자가 우선순위를
  잘못 잡아 다음 학기 필수 이수 부담이 커진다.
  **단 이 목록은 우선순위만 정한다 — 답변 범위를 여기로 좁히지 마라.** 목록에 안 나온
  프로그램(특히 주전공)과 남은 이수구분도 평소대로 빠짐없이 함께 안내해라. 목록에 뜬
  전공만 다루고 나머지를 빠뜨리면 학생이 다른 전공은 다 됐다고 오해한다.
- search_courses 결과에 description(교과목개요)이 있으면 과목명만 보고 판단하지 말고
  그 내용을 실제로 읽고 학생의 진로/관심사와 맞는지 확인해라. 과목명에 키워드가 없어도
  description 내용상 관련 있는 과목일 수 있다.
- **이미 로드맵에 있는 과목(get_roadmap_items 결과의 course_id 목록)은 다시 create로 제안하지 마라 — 같은 과목이 두 번 만들어지는 걸 도구 단에서 거절한다.** 학기/학년만 옮기고 싶으면 그 항목의 `id`로 action='update'를 호출해라.
- **이미 이수한 과목(get_roadmap_items 결과의 `completed_courses`)은 다시 추천하지 마라.** 성적표에서 파싱된 이수내역은 `course_id` 매핑이 대부분 안 돼 있어 로드맵 중복 가드로는 잡히지 않는다. finish_response에서 언급하는 과목명이 `completed_courses`에 있는 이름과 겹치는지 반드시 이름 기준으로 재확인해라. 이수기록과 이름이 정확히 일치하는 create는 도구 단에서도 거절한다.
- **성적표 표기와 교육과정 표기가 다르게 보이는 유사명 과목은 네가 임의로 "같은 과목"이라고 판정하지 마라.** 예를 들어 이수기록의 표기와 교육과정 표기가 한 글자만 다른 경우가 있는데, 부산대에서 실제로 같은 과목인지 확인할 방법이 우리 데이터엔 없다. 이런 경우 자동으로 제외/포함시키지 말고, finish_response에서 사용자에게 되물어서 답을 받은 뒤 다음 턴에 그 과목을 제외해라. 사용자가 "다르다/모르겠다"고 하면 그대로 후보에 유지해라 — 우리가 대신 판단하지 않는다.
- 기존 항목의 학기/학년을 바꾸고 싶으면 propose_change(action="update", item_id=...)를,
  항목을 빼고 싶으면 propose_change(action="delete", item_id=...)를 써라.
- **두 학기 이상을 한 번에 계획해야 하는 요청("졸업까지", "남은 학기 전부", "4학년
  2학기까지")에는 `propose_change` 대신 `propose_term_plan`을 써라.** 과목마다
  propose_change를 부르면 도구 호출 횟수가 모자라 뒤쪽 학기가 통째로 빠진다.
  남은 학기 목록은 `get_roadmap_items`의 `remaining_terms`에 그대로 온다.
- **너는 실제로 아무것도 저장하지 않는다.** propose_change는 "제안"만 만든다.
  finish_response 메시지 마지막에는 반드시 "이 변경을 반영할까요?"처럼 사용자 확인을
  구하는 문장을 넣고, 사용자가 승인해야만 실제로 반영된다는 걸 분명히 말해라.
- 학생이 이미 만족한 이수구분에는 무리하게 과목을 더 넣지 말고, 부족한 이수구분 위주로
  추천해라.
- **학기 배치 규칙 (필수 준수)**:
  - `planned_semester`는 반드시 `"1학기"` 또는 `"2학기"` 문자열로 넘겨라. `"1"`, `"2"`,
    영문/숫자만은 저장 포맷과 어긋난다.
  - `planned_year`는 실제 달력 연도(예: `"2027"`), `planned_grade`는 학생 커리큘럼 기준
    학년(1~4). 두 값이 어긋나면 로드맵이 꼬인다.
  - **`planned_grade`/`planned_semester`는 학생이 실제로 그 과목을 이수할 학기다** —
    사용자가 요청한 배치 학기(예: "4학년 1학기 추천"이면 4·1학기)를 그대로 써라.
    `search_courses` 결과의 `grade`(교육과정표 권장 학년)는 참고용이다. 개설 학기가
    요청 학기와 맞지 않는 과목은 뺀다. `semester`가 `"1학기 또는 2학기"` 또는
    `"전학기"`인 과목은 학생 상황에 맞는 정규 학기 하나를 골라라.
  - **계절수업/도약수업 전용 과목은 정규 학기 추천에서 제외해라.** `search_courses`
    결과의 `semester`가 `"여름계절수업"`, `"겨울계절수업"` 등 방학 세션이면 정규
    1·2학기 개설이 아니다. 사용자가 "다음 학기", "N학년 M학기" 같은 정규 학기 추천을
    요청했다면 이런 과목은 finish_response에서 아예 언급하지 말고, propose_change도
    하지 마라. 사용자가 명시적으로 "계절수업 뭐 들을까"라고 물었을 때만 planned_semester
    를 원문 그대로(예: `"여름계절수업"`) 넣어서 제안해라.
  - **과거 학기에는 새 항목을 만들지 마라.** `get_roadmap_items`의 `next_plannable_term`
    이전 학기로 create 제안은 도구가 거부한다.
  - **학기당 학점 상한(term_credit_cap)을 넘기지 마라.** 새 과목을 정규 학기에 추가하면
    그 학기 합이 상한을 넘지 않도록 조정. 상한 초과 create/update는 도구가 거절하고
    에러 응답에 `current_items_in_term`(그 학기 항목 목록), `course_semester`, `hint`
    가 같이 온다. 그 목록 중 새 과목과 **역할 겹치거나 우선순위 낮은 것**을 골라
    `propose_change(action='delete' 또는 'update')`로 먼저 빼거나 다른 학기로 옮긴 뒤,
    새 과목을 다시 create 하는 **대체(swap) 조합**을 사용자에게 제안해라.
  - **대체 후보가 없을 때 "다음 학기로 미루자"고 아무렇게나 말하지 마라.** 학기 전용
    과목을 미뤄야 하면 **같은 학기의 다음 연도**(예: 3-2 → 4-2)로 제안해라. 계절수업은
    정규 상한과 별개.
- **finish_response 첫 문장에 커리큘럼상 학년·학기를 자연어로 명시해라.** "다음 학기"
  라고만 두루뭉술 말하지 말고 `next_plannable_term`을 근거로 "**N학년 M학기**" 형태
  (예: "다음 학기는 3학년 2학기입니다. 이 학기 추천은..."). **주의**: 변수명
  (`next_plannable_term`, `offered_this_term`, `in_catalog`, `is_enrolled` 등 도구가
  돌려준 필드명 전부)이나 "커리큘럼 좌표:" 같은 기술 라벨을 답변에 노출하지 마라.
  뜻을 우리말로 풀어 써라 — `offered_this_term=false`가 아니라 "이번 학기에는 개설되지
  않았어요".
- **사용자가 요청한 범위를 벗어나 제안을 남발하지 마라.** 사용자가 "이 과목을
  몇 학기로 옮겨줘"처럼 기존 항목 하나를 콕 집어 요청했으면 그 항목에 대한
  propose_change 하나만 호출하고 끝내라 — 물어보지도 않은 다른 과목을 추가로
  추천하지 마라. "수강계획 추천해줘"처럼 범위가 넓은 요청일 때만 여러 과목을
  한 번에 제안해라.
- 한국어로, 간결하게 답해라.
"""


# 상황별 규칙 — 학생 상태 probe로 필요한 것만 시스템 프롬프트에 붙는다.
# key = 상황 식별자, value = 프롬프트에 append될 규칙 텍스트.
# _select_applicable_rules가 학생 데이터로 어떤 키가 활성화될지 결정.
_CONDITIONAL_RULES: dict[str, str] = {

    "non_primary_programs": """
- **부전공·복수전공·SW융합트랙(program_type != 'primary') 챙기기**: 학생이 그런 프로그램에
  등록돼 있다. 주전공만 챙기지 마라:
  1. `get_program_evaluations`를 호출해 각 프로그램의 그룹별 완료·부족 정보를 확인한다
     (특히 부전공 필수과목 몇 개 남았는지, SW융합트랙 학점 그룹별 진행률).
  2. 부족한 그룹의 인정 과목을 검색할 때는 `search_courses`에 `program_type` 파라미터를
     넘겨라(예: `program_type="minor"`). 주전공 학과 필터로만 검색하면 부전공 필수과목이
     아예 결과에 안 나온다.
  3. propose_change의 `program_type` 필드에 해당 프로그램 값(minor/dual/interdisciplinary)을
     넘겨 어느 프로그램용 항목인지 명확히 태깅해라.
  4. 부전공 필수과목이 남아 있으면 사용자에게 그걸 우선 언급해라 — 필수과목을 안 채우면
     선택과목 학점만 21학점 채워도 부전공 완료로 인정 안 된다.""",

    "career_dept_mismatch": """
- **진로-전공 mismatch 감지 시 부·복수전공 옵션 제안**: 학생 프로필의 진로 목표와
  주전공 학과가 명백히 다른 도메인이라 판단된다. `finish_response`에서 **부전공/복수전공
  옵션을 능동적으로 제안해라**. 문구 예: "국문학과 커리큘럼만으로는 백엔드 실무 역량
  쌓기 어려워요. 정보컴퓨터공학부 **부전공(21학점)** 또는 **복수전공(36학점)** 을
  고려해보시는 게 좋습니다 — 프로필 '학적 관리'에서 등록 가능합니다."
  이 안내를 안 하면 사용자는 자기 진로에 맞는 경로를 놓친다.""",

    "transfer_student": """
- **편입생 대응**: `earliest_recorded_grade`가 있는 편입생이다. 그 학년 미만(예: 3이면
  1·2학년)으로 propose_change를 호출하지 마라 — 도구 단에서 거절된다. finish_response
  에서 "편입생은 3학년부터 시작합니다"처럼 최저 학년을 명시해라.""",

    "staggered_semester": """
- **엇학기 학생 대응 — 달력 학기 ≠ 커리큘럼 학기**: `get_roadmap_items`가 돌려주는
  `next_plannable_term`(달력)과 `next_curriculum_term`(커리큘럼 학년/학기)이 다를 수
  있다. 예: 한 학기 휴학한 학생의 다음 달력 학기가 2026-1이라도 커리큘럼 상으로는
  4-2일 수 있다.
  - **`search_courses`의 `semester` 필터는 `next_plannable_term.semester`(달력)를 써라.**
  - **요건·학년 판단은 `next_curriculum_term.grade/semester`(커리큘럼)를 기준으로.**
  - `propose_change`의 `planned_year`는 달력, `planned_semester`는 달력, `planned_grade`
    는 커리큘럼으로 넣어라.""",

    "critical_missing": """
- **필수 미이수 + 개설학기 어긋남 = 졸업 위험, 반드시 경고**: `get_roadmap_items` 응답의
  `critical_missing_required`에 항목이 있다. finish_response 첫 부분에서 이 사실을
  명시적으로 알려라 — "졸업 필수인 OO(X학기 전용 개설)가 미이수인데 다음 학기가 Y학기라
  이번엔 못 듣습니다, 다음 학년도 X학기에 반드시 들어야 졸업 가능합니다"처럼 위험 +
  대안(같은 학기의 다음 연도)을 함께.""",

    "prereq_blocked": """
- **선수과목 부족 과목은 후보에서 제외**: `get_roadmap_items`의 `prereq_blocked`에
  항목이 있다. 이 목록의 course_id는 **propose_change로 create하지 마라**. 학생이
  명시적으로 "이거 이번에 담고 싶다"고 물으면 "선수과목인 X가 아직 미이수라 X를 먼저
  들으시고 다음 학기에"라고 안내. description 파싱 기반이라 100% 정확하진 않으니 학생이
  "선수 이미 들었어" 반박하면 그대로 받아들이고 진행해라.""",

    "retake_candidates": """
- **재수강 안내는 권유만, 명시 요청 시 create 가능**: `get_roadmap_items`의
  `retake_candidates`에 C+ 이하 성적 이수 과목이 있다. 사용자가 (a) GPA 개선을
  명시적으로 언급하거나 (b) "재수강 뭐 하는 게 좋아?"처럼 직접 물으면 그때만 후보를
  제시해라. **매 대화마다 "재수강 어때?"라고 들이대지 마라** — 사용자 침해.
  **사용자가 특정 과목을 콕 집어 "이거 재수강 넣어줘"라고 명시 요청**하면 그 과목이
  retake_candidates에 있는지 확인 후 `propose_change(action="create", course_id=...,
  is_retake=True, reason="사용자 재수강 요청")` 로 로드맵에 넣어라. is_retake=True
  없이는 도구가 이수 완료 재추천으로 거절한다. 자격 없는 과목(retake_candidates에
  없음 = B- 이상)에 억지로 is_retake 넘기면 도구가 거절.""",

    "narrow_scope_request": """
- **이번 요청은 범위가 좁다 — 요청한 것 하나만 처리해라**: 사용자가 대상을 콕 집고
  "그것만"류 표현으로 범위를 못박았다. 그 항목에 대한 `propose_change` **딱 하나만**
  호출하고 바로 `finish_response`로 끝내라.
  - 같은 학기에 다른 항목이 보여도 건드리지 마라. 묶어서 옮기지 마라.
  - 물어보지도 않은 과목 추천·재수강 권유·졸업요건 브리핑을 덧붙이지 마라.
  - 관련 조언이 떠오르면 제안(propose_change) 대신 finish_response 문장 한 줄로만 언급해라.
  실제 관측: 한 과목만 옮겨달라는 요청에 같은 학기의 다른 과목까지 함께 옮겨서, 사용자가
  요청하지 않은 변경이 승인 대기에 올라갔다.""",

    "full_horizon_request": """
- **이번 요청은 "졸업까지 남은 학기 전부"다 — 한 학기만 하고 끝내지 마라**:
  0. **목표는 "학기를 꽉 채우기"가 아니라 "졸업요건을 채우기"다.** 남은 이수구분을 다
     채웠으면 거기서 멈춰라 — 학기에 여유 학점이 남아도, 어떤 학기가 통째로 비어도
     졸업에 필요 없는 과목을 억지로 넣지 마라. 그 판단은 네가 하지 말고
     `propose_term_plan` 응답의 `unmet_categories_after_plan`(비어 있으면 요건 충족)과
     `next_action`을 따라라.
  1. `get_roadmap_items` 응답의 `remaining_terms`가 다음 배치 가능 학기부터 졸업 예정
     학기까지의 목록이다(각 항목에 달력 연도/학기, 커리큘럼 학년, 그 학기에 이미
     계획된 학점, 남은 여유 학점이 들어 있다). **요건이 남아 있는 한** 그 목록의
     학기를 순서대로 채워라.
  2. `search_courses`를 **1학기용·2학기용으로 각각**, 남은 이수구분(전공기초/전공필수/
     전공선택/교양필수 등)별로 호출해 후보 풀을 먼저 모아라. 한 과목을 두 학기에
     겹쳐 배치하지 마라.
  3. 후보가 모이면 **`propose_term_plan`을 호출해 남은 학기를 통째로 제안해라.**
     과목마다 `propose_change`를 부르면 도구 반복 횟수가 모자라 중간에 끊긴다.
  4. 응답의 `rejected`에 걸린 과목은 사유(학점 상한 초과/중복/이미 이수/계절수업 전용)
     를 보고 학기를 바꿔 **한 번 더** `propose_term_plan`을 호출해라. 재시도는 한 번까지.
  5. `finish_response`는 학기별로 나눠 써라 — 각 학기에 어떤 과목 몇 학점인지, 학기
     합계가 얼마인지. **마지막 `propose_term_plan` 응답의 `plan_so_far`를 그대로 옮겨
     적어라** (이번 턴에 제안된 전부가 학기별로 들어 있다). 마지막 호출의 `accepted`만
     보고 쓰면 앞선 호출에서 성공한 학기를 "확정 없음"이라고 적게 된다.
     **학기 제목의 학년은 네가 추측하지 말고 `term_totals_after`(또는 `remaining_terms`)의
     `planned_grade`를 그대로 써라** — 예: planned_grade=3, planned_semester="2학기",
     planned_year="2026" → "3학년 2학기(2026년 2학기)". 사용자가 "4학년 2학기까지"라고
     말했다고 해서 첫 학기를 4학년이라고 부르지 마라(2026-08-20 실측: 3학년 2학기를
     "4학년 2학기(2026년 2학기)"라고 적었다). 그리고 응답의 `requirement_coverage`를 근거로 이 계획을 다 이수하면 어느
     이수구분이 채워지고 어디가 얼마나 남는지 밝혀라.
  6. 배치 규칙은 평소와 같다: 1학기 전용 개설 과목은 1학기 슬롯, 2학기 전용은 2학기
     슬롯, 계절수업 전용은 정규 학기에 넣지 마라.
  7. 남은 이수구분을 다 채울 만큼 후보를 못 찾았으면 "몇 학점이 아직 미배정"인지
     솔직히 적어라. 다 채운 척하지 마라. 반대로 **요건이 다 채워졌으면 그렇다고 밝히고,
     남은 학기가 가벼운 이유(더 들을 필요가 없다)를 한 줄로 설명해라** — 빈 학기를
     설명 없이 두면 학생은 계획이 덜 짜였다고 읽는다. 단 `requirement_coverage`에
     잔여 학점이 `null`로만 나오면 학과 요건 기준이 DB에 없다는 뜻이니, 충족됐다고
     말하지 말고 **확인할 수 없다고 그대로 적어라.**
  8. **"지금 짜드릴까요?"라고 먼저 되묻지 마라.** 제안은 사용자가 승인해야만 저장되니
     되묻는 건 한 턴을 통째로 버리는 것이다. 제안부터 만들고, 확인은 finish_response
     마지막의 "이 변경을 반영할까요?" 한 문장으로 받아라.
  9. 학기 합계 학점을 네가 더하지 마라. **마지막 `propose_term_plan` 응답의
     `term_totals_after`**를 그대로 적어라 — 직접 더하다가 실제 배치와 다른 숫자를
     답변에 쓴 적이 있다(2026-08-20: 실제 19학점인 학기를 "15학점"이라고 적었다).""",

    "liberal_area_partial": """
- **균형교양 세부영역별 판정**: get_graduation_progress의 '교양선택'에 남은 학점이 있고,
  이미 이수한 세부영역과 미이수 세부영역이 프로필 블록에 노출돼 있다. **미이수 세부영역
  을 우선 채우는 방향**으로 search_courses 후보를 고르고 finish_response에서 그 근거
  ("네가 아직 안 든 XX영역 보강용")를 밝혀라. 세부영역 정보가 프로필 블록에 없으면
  (포털 미동기화) 그 사실을 알리고 우선 동기화 안내.""",
}


def _career_looks_mismatched(db: Session, user: User) -> bool:
    """진로 목표가 주전공 학과 커리큘럼과 동떨어져 보이는지 판정하는 cheap probe.

    판정: 진로 문구가 알려진 진로군(`CAREER_ALIASES`)에 걸리면, 그 진로군 키워드에
    해당하는 과목이 학생의 주전공 학과 개설과목에 **하나도 없을 때만** mismatch로 본다.
    진로군에 안 걸리면(예: "재무분석가", "자동차 엔지니어") 판단 근거가 없으므로 False —
    모르는 걸 mismatch로 단정하지 않는다.

    이전 구현은 "진로 목표가 있고 부·복수전공이 없으면" 무조건 mismatch 규칙을 붙였다.
    그래서 정컴 학생 + "백엔드 개발자"처럼 완벽히 일치하는 경우에도 매 대화마다 "부전공/
    복수전공을 제안해라"는 강한 지시가 시스템 프롬프트에 실렸다 — 불필요한 부전공 권유를
    유발하고, 프롬프트 fatigue로 다른 규칙의 준수도까지 떨어뜨린다
    (`docs/backend/...`/골든 하니스 2026-08 관측).
    """
    if user.department_id is None or not user.career_goal:
        return False

    from app.ai.rag.career_keywords import CAREER_KEYWORDS, career_alias_groups

    career = user.career_goal.strip()
    groups = career_alias_groups(career)
    if not groups:
        return False

    rows = db.execute(
        select(Course.course_name, Course.description).where(
            Course.department_id == user.department_id
        )
    ).all()
    if not rows:
        # 학과 개설과목 데이터가 없으면 아무것도 판정할 수 없다. 데이터 공백을
        # mismatch로 오인해서 엉뚱한 부전공 권유를 하지 않는다.
        return False

    haystack = " ".join(f"{name or ''} {desc or ''}" for name, desc in rows).lower()

    # 신호 1 — 진로군 키워드가 학과 개설과목에 등장하는가
    if any(kw.lower() in haystack for kw in {k for g in groups for k in CAREER_KEYWORDS[g]}):
        return False

    # 신호 2 — 진로 문구 자체가 과목명과 겹치는가 (2글자 단위).
    # alias가 느슨해서 생기는 오탐을 잡는다: "재무분석가"는 '분석' 때문에 data 진로군에
    # 걸리지만, 경영학과에 '재무관리'·'기업재무'가 있으므로 mismatch가 아니다.
    bigrams = {career[i:i + 2] for i in range(len(career) - 1) if not career[i:i + 2].isspace()}
    if any(bg.lower() in haystack for bg in bigrams if len(bg.strip()) == 2):
        return False

    return True


# "이것만 해줘"류 범위 한정 표현. 조사·어미 변형까지 다 잡으려 하지 않고, 오탐이 거의
# 없는 명확한 표현만 둔다 — 넓은 요청에 이 규칙이 잘못 붙으면 정상적인 다중 추천이 막힌다.
_NARROW_SCOPE_MARKERS = (
    "그것만", "그거만", "이것만", "이거만", "하나만", "한 개만", "딱 하나",
    "그 과목만", "이 과목만", "다른 건 건드리지", "다른건 건드리지",
    "다른 건 그대로", "추가 추천은 필요 없", "추천은 안 해도",
)


def _looks_like_narrow_scope_request(message: str | None) -> bool:
    """사용자 메시지가 "이것만 처리해줘"라고 범위를 못박았는지.

    학생 DB 상태가 아니라 이번 턴 메시지로만 판정하는 유일한 조건부 규칙이다.
    CORE에도 같은 취지의 규칙이 있지만 긴 프롬프트 뒤쪽에 묻혀 준수도가 낮았다
    (골든 케이스 26에서 N=3 중 2회 위반: "데이터베이스만 옮겨줘"에 컴퓨터네트워크까지
    같이 이동). 신호가 명확할 때만 프롬프트 끝에 짧고 강한 규칙을 덧붙인다.
    """
    if not message:
        return False
    compact = message.replace(" ", "")
    return any(marker.replace(" ", "") in compact for marker in _NARROW_SCOPE_MARKERS)


# "남은 학기 전부"를 가리키는 범위 표현. 이것만으로는 부족하다 — "졸업까지 뭐가
# 남았는지 정리해줘"처럼 **조회**를 요청하는 문장에도 들어간다.
_FULL_HORIZON_SCOPE_MARKERS = (
    "졸업까지", "졸업 까지", "졸업할 때까지", "졸업 때까지", "졸업 전까지",
    "졸업까지의", "졸업 로드맵", "졸업 시점까지",
    "남은 학기 전부", "남은 학기 모두", "남은 학기 다", "남은 학기를 전부",
    "남은 학기 계획", "남은 학기 싹", "앞으로 남은 학기", "남은 학기 동안",
    "전체 로드맵", "전체 학기", "모든 학기",
    "4학년 2학기까지", "4-2까지", "4학년까지",
)

# 이미 지난 일이나 현재 상태를 **묻는** 신호.
# "졸업 로드맵 지금 어떻게 돼 있어?"에 3개 학기 제안이 쌓이면 안 된다.
#
# 단 아래 `_BUILD_VERB_MARKERS`가 같이 있으면 veto하지 않는다 — "졸업까지 짜서 알려줘"는
# 조회가 아니라 계획 요청이고, 이걸 죽이면 이 기능이 고치려던 증상(다음 한 학기만
# 제안하고 끝냄)으로 그대로 돌아간다.
_QUERY_ONLY_MARKERS = (
    "알려줘", "알려 줘", "알려주", "보여줘", "보여 줘", "보여주",
    "정리해줘", "정리해 줘", "정리해주", "확인만", "확인해줘", "확인해 줘",
    "어떻게 돼", "어떻게 됐", "어떻게 되어", "어떻게 되었",
    "들었는지", "이수했는지", "남았는지", "세워져 있는지", "세워졌는지",
)

# "만들어 달라"가 명시적인 동사. 조회 표현과 같이 나와도 이쪽이 이긴다
# ("졸업까지 로드맵 짜서 보여줘").
# 어간(`채워`/`편성`/`설계`)이 아니라 **요청형**으로 둔다. 어간이면 수동·서술형에도
# 걸려서 "졸업 로드맵 어떻게 채워져 있는지 보여줘"가 계획 요청으로 잡힌다 — veto를
# 뚫는 예외라 오탐이 곧 "조회 요청에 학기 제안이 쌓인다"가 된다.
_BUILD_VERB_MARKERS = (
    "짜줘", "짜 줘", "짜주", "짜서", "짜봐", "짜자",
    "편성해", "설계해", "배치해", "만들어",
    "채워줘", "채워 줘", "채워라", "채워주", "채워서",
    "계획해줘", "계획해 줘", "계획해주", "계획해라", "계획해서",
    "계획 세워줘", "계획 세워 줘", "계획 세워서", "계획을 세워",
)

# 실제로 **계획을 만들어 달라**는 신호. 위 범위 표현과 같이 나와야 full-horizon 요청이다.
_PLANNING_INTENT_MARKERS = (
    "로드맵", "계획", "짜줘", "짜 줘", "짜주", "짜서", "짜봐", "짜자", "설계", "세워",
    "배치", "편성", "채워", "채우", "수강계획", "커리큘럼 짜",
    "들어야", "들으면", "뭘 들", "무엇을 들", "어떻게 들", "수강 순서",
)


def _looks_like_full_horizon_request(message: str | None) -> bool:
    """"졸업까지 전부 짜줘"처럼 남은 학기 **전체 계획**을 요구한 요청인지.

    `_looks_like_narrow_scope_request`와 짝이 되는 반대 방향 판정이다. 둘 다 학생 DB가
    아니라 이번 턴 문장으로만 판정한다.

    범위 표현과 계획 의도를 **둘 다** 요구한다. "졸업까지"만 보면 "졸업까지 뭐가
    남았는지 정리해줘" 같은 단순 조회 요청까지 걸려서, 묻지도 않은 3개 학기 제안이
    승인 대기에 쌓인다.

    2026-08-20 실계정(편입 3학년, 남은 학기 3개) 관측: "졸업까지 로드맵 짜줘",
    "남은 학기 전부 계획해줘", "4학년 2학기까지 어떻게 들어야 해?" 세 요청 모두
    **다음 한 학기(3-2)만** 제안하고 "승인해주시면 4-1, 4-2도 이어서"로 끝냈다.
    도구 반복 상한 문제가 아니었다 — 8회 중 3/5/4회만 쓰고 스스로 끝냈다.
    """
    if not message:
        return False
    compact = message.replace(" ", "")

    if any(m.replace(" ", "") in compact for m in _QUERY_ONLY_MARKERS) and not any(
        m.replace(" ", "") in compact for m in _BUILD_VERB_MARKERS
    ):
        return False

    matched = [m.replace(" ", "") for m in _FULL_HORIZON_SCOPE_MARKERS
               if m.replace(" ", "") in compact]
    if not matched:
        return False

    # 계획 의도는 **범위 표현 바깥에서** 찾는다. `졸업 로드맵`·`전체 로드맵`·
    # `남은 학기 계획`처럼 범위 표현 자체가 의도 단어(`로드맵`/`계획`)를 품고 있어서,
    # 그냥 문장 전체에서 찾으면 "둘 다 있어야 한다"는 조건이 그 마커들에 대해
    # 무의미해진다 — "졸업 로드맵 지금 어떻게 돼 있어?"가 계획 요청으로 잡혔다.
    #
    # 매칭된 마커를 **하나씩** 지워보고 그중 하나라도 의도가 남으면 참이다. 겹치는
    # 마커를(`남은 학기 계획` ⊗ `앞으로 남은 학기`) 한꺼번에 지우면 그 사이의 의도
    # 단어까지 사라져서, 결과가 마커 선언 순서에 좌우된다.
    return any(
        any(intent.replace(" ", "") in compact.replace(m, " ")
            for intent in _PLANNING_INTENT_MARKERS)
        for m in matched
    )


def _has_term_gap(db: Session, user: User) -> bool:
    """마지막 이수 학기와 현재 학기 사이에 공백이 있으면 True (= 엇학기).

    현재 학기가 2026-2라면:
      마지막 이수 2026-1 → 간격 1학기 = 정상 (직전 학기까지 이수)
      마지막 이수 2026-2 → 간격 0     = 정상 (이번 학기 기록이 벌써 들어온 경우)
      마지막 이수 2024-1 → 간격 5학기 = 휴학 이력 → 엇학기

    이수 기록이 없으면(신입·편입·미동기화) 판정하지 않는다 — 근거가 없다.
    '입학전성적'처럼 학기를 특정할 수 없는 lump-sum 기록도 제외한다.
    """
    rows = db.execute(
        select(StudentCourseRecord.year, StudentCourseRecord.semester).where(
            StudentCourseRecord.user_id == user.id,
            StudentCourseRecord.year.is_not(None),
            StudentCourseRecord.semester.not_in(list(PRE_ADMISSION_SEMESTERS)),
        )
    ).all()

    absolute_terms = []
    for year, semester in rows:
        sem_int = _semester_str_to_int(semester)
        if sem_int is None or not str(year).isdigit():
            continue  # 계절수업·전학기 등은 순번을 매길 수 없다
        absolute_terms.append(int(year) * 2 + sem_int)
    if not absolute_terms:
        return False

    cy, cs = _current_academic_term()
    return (cy * 2 + cs) - max(absolute_terms) >= 2


def _select_applicable_rules(db: Session, user: User, message: str | None = None) -> list[str]:
    """학생 상태를 cheap probe로 확인해 활성화할 조건부 규칙 키 목록 반환.

    각 probe는 SQL COUNT 등 가벼운 쿼리만. 이미 계산 완료된 값(예: critical_missing)
    은 안 그리고 존재 여부만 판정 — 프롬프트 assembly 오버헤드가 대화 latency에 크게
    잡히지 않도록.
    """
    applicable: list[str] = []

    # 1. non-primary program (부·복수·융합) 존재 여부
    non_primary_count = db.scalar(
        select(func.count(UserAcademicProgram.id)).where(
            UserAcademicProgram.user_id == user.id,
            UserAcademicProgram.program_type != "primary",
            UserAcademicProgram.status.in_(ACTIVE_PROGRAM_STATUSES),
        )
    )
    has_non_primary = bool(non_primary_count)
    if has_non_primary:
        applicable.append("non_primary_programs")
    elif _career_looks_mismatched(db, user):
        # 진로군 키워드에 맞는 과목이 주전공 학과에 하나도 없을 때만 (probe 주석 참고).
        applicable.append("career_dept_mismatch")

    # 2. 편입생 (admission_type)
    if is_transfer(user.admission_type):
        applicable.append("transfer_student")

    # 3. 엇학기 — 마지막 이수 학기와 현재 학기 사이에 공백이 있는가.
    #
    #    옛 판정은 "최신 SCR 연도 - curriculum_year >= 4"였는데, 이건 엇학기가 아니라
    #    "입학한 지 오래됐나"를 재는 것이라 정작 대상인 한 학기 휴학생이 안 걸렸다
    #    (골든 케이스 10이 규칙을 한 번도 못 받고 3/3 실패).
    #
    #    "이수한 학기 수 < 경과 학기 수"도 안 된다 — 포털 미동기화나 부분 동기화로 기록이
    #    비어 있는 학생이 전부 걸린다. **마지막 이수 학기**만 보는 게 맞다:
    #    정상 재학생은 직전 학기까지 이수해 있고, 휴학했다면 그 지점에서 끊긴다.
    if _has_term_gap(db, user):
        applicable.append("staggered_semester")

    # 4. 자동 판정 필드들 — 실제 계산해서 비어있지 않은 경우만 규칙 추가
    #    (get_roadmap_items가 매 대화 첫 턴에 어차피 이 값들을 다시 계산하니 double-compute
    #    비용 감수. 로드맵은 사용자당 1개.)
    roadmap = db.scalars(
        select(CourseRoadmap).where(CourseRoadmap.user_id == user.id)
    ).first()
    roadmap_id = roadmap.id if roadmap else None

    # next_plannable_term.semester 계산
    cy_cal, cs_cal = _current_academic_term()
    ny_cal, ns_cal = _next_term(cy_cal, cs_cal)
    next_sem_str = f"{ns_cal}학기"

    if _compute_critical_missing_required(db, user, roadmap_id, next_sem_str):
        applicable.append("critical_missing")
    if _compute_prereq_blocked(db, user, roadmap_id):
        applicable.append("prereq_blocked")
    if _compute_retake_candidates(db, user):
        applicable.append("retake_candidates")

    # 5. 균형교양 세부영역 활성화 — SCR에 category='교양선택'이 있으면 일단 규칙 노출
    #    (세부영역 override 유무는 LLM이 프로필 블록 보고 판단)
    has_liberal = db.scalar(
        select(func.count(StudentCourseRecord.id)).where(
            StudentCourseRecord.user_id == user.id,
            StudentCourseRecord.category.in_(["교양선택"] + list(_BALANCED_LIBERAL_AREAS)),
        )
    )
    if has_liberal:
        applicable.append("liberal_area_partial")

    # 6. 범위 한정 요청 — 유일하게 DB가 아니라 이번 턴 메시지로 판정한다.
    #    맨 끝에 붙여서 프롬프트 마지막 줄이 되게 한다 (recency).
    #    full_horizon과 동시에 걸리면 좁은 쪽이 이긴다 — "그것만"이라고 못박은 요청에
    #    남은 학기 전부를 채우는 건 명백한 범위 초과다.
    if _looks_like_narrow_scope_request(message):
        applicable.append("narrow_scope_request")
    elif _looks_like_full_horizon_request(message):
        applicable.append("full_horizon_request")

    return applicable


def _build_system_prompt(
    db: Session, user: User, message: str | None = None
) -> tuple[str, list[str]]:
    """core + applicable conditional rules + student context block 결합한 최종 시스템
    프롬프트. 두 번째 리턴은 적용된 rule 키 목록 (관측·디버깅용, 프롬프트 안 실림).
    """
    rules = _select_applicable_rules(db, user, message)
    conditional_text = "".join(_CONDITIONAL_RULES[k] for k in rules)
    return _CORE_PROMPT + conditional_text, rules


# 하위 호환: 기존 코드에서 _SYSTEM_PROMPT를 참조하는 곳이 있으면 core만 반환.
# 신규 코드는 _build_system_prompt(db, user) 를 써야 한다.
_SYSTEM_PROMPT = _CORE_PROMPT

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_graduation_progress",
            "description": (
                "학생의 활성 프로그램(주전공/부전공/복수전공/융합) 전부의 이수구분별 남은 학점을 조회한다. "
                "programs 리스트에 program_type='primary' 외에 minor/dual/interdisciplinary가 함께 나올 수 있다. "
                "부전공·SW융합 등의 세부 그룹 규칙(택N/M·필수과목·exclude)까지 판정하려면 "
                "get_program_evaluations를 추가로 호출해라."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_program_evaluations",
            "description": (
                "부전공·복수전공·SW융합트랙(program_type != 'primary') 프로그램의 그룹별 규칙 판정 결과를 조회한다. "
                "각 프로그램의 special_rules(그룹별 all/min_courses/min_credits) 기준으로 이수 여부와 부족분을 "
                "돌려준다. 학생이 부전공 이수 중이면 필수과목 몇 개 남았는지, 총학점 얼마 남았는지 "
                "여기서 확인해라. get_graduation_progress가 학점 총계만 준다면 이 도구는 세부 그룹 규칙까지 준다."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_available_tracks",
            "description": (
                "이 학생의 학과에서 이수 가능한 AI융합트랙(SW융합트랙) 목록과 등록 여부를 조회한다. "
                "졸업요건이 **아니라** 이수 시 졸업증명서에 과정명이 표기되는 인증 프로그램이다 "
                "(학과 전공 12~15학점 + AI융합 공통 6~9학점 = 총 21학점). "
                "학생이 로드맵·진로·'들을 만한 프로그램'을 물으면 이걸 확인해라. "
                "AI융합 공통교과목 목록(모듈1/모듈2, 개설 확인 여부, 온라인 개설 여부)도 함께 "
                "돌려주므로 '무엇을 담으면 되는지'까지 구체적으로 답할 수 있다. "
                "tracks가 빈 배열이면 대상 학과가 아니니 트랙을 아예 언급하지 마라."
            ),
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
                "성적표 기반 이수기록(completed_courses), **critical_missing_required**"
                "(학과 필수인데 미이수 + 개설 학기가 다음 학기와 어긋난 목록 = 졸업 위험), "
                "**retake_candidates**(C+ 이하 성적 이수 과목 목록 = 재수강 권유 후보), "
                "**prereq_blocked**(선수과목 미이수라 지금 담기 부적절한 학과 과목 목록), "
                "**remaining_terms**(다음 배치 가능 학기부터 졸업 예정 학기까지 남은 정규 학기 "
                "목록 — 각 학기의 달력 연도/학기, 커리큘럼 학년, 이미 계획된 학점, 남은 여유 학점. "
                "'졸업까지 계획해줘' 같은 요청은 이 목록의 학기를 전부 채워야 한다)"
                "를 돌려준다. 새 항목 제안 전에 반드시 이걸 확인해라 — 특히 학점 상한 "
                "초과, 이미 이수한 과목 중복, 졸업 위험 필수 미이수, 선수과목 부족."
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
                "category='전공선택'로 호출해라. **grade 필터는 웬만하면 걸지 마라** — "
                "'4학년 1학기 추천'처럼 특정 학기 배치를 위한 검색이라도, 이전 학년에 못 들은 "
                "과목이 후보에서 빠지지 않도록 학년은 열어두고 semester/category만 걸어라. "
                "결과의 grade(교육과정 권장 학년)와 semester(권장 학기)는 참고용이다: "
                "학생이 그 과목을 실제로 이수할 학기(propose_change의 planned_grade/"
                "planned_semester)는 이 결과 그대로가 아니라 배치 대상 학기다. 결과의 "
                "description 필드에 교과목개요(있는 과목만)가 같이 온다."
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
                        "description": (
                            "이수구분 필터. 학생 자연어를 그대로 넘기면 백엔드가 매핑한다 "
                            "(예: '핵심교양' → 효원핵심교양, '교양필수' → 효원핵심교양, "
                            "'교양선택' → 효원균형교양+효원창의교양+기초교양). "
                            "학생이 '균형교양만 더 채우고 싶다'처럼 세부 영역을 콕 집으면 '효원균형교양'으로, "
                            "그냥 '교양선택 뭐 있냐'면 '교양선택'으로 넓게. "
                            "빈 결과 오면 응답의 `available_categories`를 보고 다른 값으로 재시도 — "
                            "같은 인수로 재호출하지 마라."
                        ),
                    },
                    "program_type": {
                        "type": "string",
                        "enum": ["primary", "minor", "dual", "interdisciplinary"],
                        "description": (
                            "검색 스코프를 어느 프로그램의 학과로 잡을지. 지정하지 않거나 'primary'면 "
                            "주전공 학과에서 검색. 'minor'/'dual'/'interdisciplinary'를 넘기면 학생 학적에서 "
                            "해당 program_type의 학과·전공을 조회해 그 학과 개설과목 + 그 프로그램의 "
                            "인정과목(program_courses)까지 후보로 뜬다. 부전공 필수과목 추천할 때는 "
                            "반드시 program_type='minor'로 호출해라 — 안 그러면 주전공 학과만 검색해서 "
                            "부전공 학과 과목이 결과에 안 나온다."
                        ),
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
                    "program_type": {
                        "type": "string",
                        "enum": ["primary", "minor", "dual", "interdisciplinary"],
                        "description": (
                            "이 항목이 어느 프로그램용인지 태깅. 기본 NULL=주전공/미지정. "
                            "부전공 필수과목을 create할 때는 반드시 'minor'로 넘겨야 판정 로직이 "
                            "그 항목을 부전공 이수 항목으로 취급한다."
                        ),
                    },
                    "is_retake": {
                        "type": "boolean",
                        "description": (
                            "재수강 create 우회 플래그. 기본 false. **사용자가 명시적으로 "
                            "'이 과목을 재수강하고 싶다'고 요청했고 그 과목이 "
                            "get_roadmap_items의 retake_candidates에 올라 있는 (=성적 C+ 이하) "
                            "경우에만 true**로 넘겨라. true여야 이수 완료 재추천 가드를 "
                            "우회한다. 자격 없는 과목(B- 이상)에 true 넘기면 도구가 거절."
                        ),
                    },
                },
                "required": ["action", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_term_plan",
            "description": (
                "**여러 학기 분량의 수강 계획을 한 번에 제안한다.** '졸업까지 로드맵 짜줘', "
                "'남은 학기 전부 계획해줘'처럼 두 학기 이상을 계획해야 하는 요청에는 "
                "propose_change를 과목마다 부르지 말고 반드시 이 도구를 써라 — 과목별 호출은 "
                "도구 반복 횟수를 다 써버려서 뒤쪽 학기가 통째로 빠진다. "
                "검증은 propose_change와 완전히 동일하다(과거 학기·이수 완료·중복·선수과목 "
                "학년 하한·계절수업 전용·학기당 학점 상한). 한 과목이 거절돼도 나머지는 그대로 "
                "제안되고, 거절된 과목은 사유와 함께 rejected에 담겨 돌아온다. "
                "학점 상한은 **이 호출 안에서 앞서 담긴 과목까지 누적해서** 검사하므로, "
                "빈 학기에 과목을 몰아넣으면 상한 초과분이 rejected로 떨어진다. "
                "응답의 `plan_so_far`가 이번 턴에 제안된 전부를 학기별로 모은 최종 상태다 — "
                "여러 번 호출했으면 답변은 마지막 호출의 accepted가 아니라 이걸 보고 써라. "
                "이미 제안한 과목을 다시 넘기면 실패가 아니라 already_in_plan으로 돌아온다. "
                "주전공 이수구분별 requirement_coverage(이 제안을 다 이수하면 얼마가 남는지)도 "
                "함께 온다. **`unmet_categories_after_plan`이 비어 있으면 졸업요건이 다 "
                "채워졌다는 뜻이니 더 넣지 마라** — 학기에 여유 학점이 남아도, 어떤 학기가 "
                "비어 있어도 졸업에 필요 없는 과목을 억지로 채울 이유가 없다. 다음에 무엇을 "
                "할지는 `next_action`에 그대로 적혀 있다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "terms": {
                        "type": "array",
                        "description": (
                            "학기별 계획. get_roadmap_items의 remaining_terms 순서대로 넣어라."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "planned_year": {
                                    "type": "string",
                                    "description": "달력 연도(예: '2027').",
                                },
                                "planned_semester": {
                                    "type": "string",
                                    "description": "'1학기' 또는 '2학기'.",
                                },
                                "planned_grade": {
                                    "type": "integer",
                                    "description": "커리큘럼 기준 학년(1~4). remaining_terms의 값을 그대로.",
                                },
                                "course_ids": {
                                    "type": "array",
                                    "items": {"type": "integer"},
                                    "description": "이 학기에 넣을 과목 id 목록(search_courses로 확인한 값).",
                                },
                                "reason": {
                                    "type": "string",
                                    "description": "이 학기 배치의 근거. 생략하면 공통 reason을 쓴다.",
                                },
                            },
                            "required": ["planned_year", "planned_semester", "course_ids"],
                        },
                    },
                    "reason": {
                        "type": "string",
                        "description": "전체 계획의 근거(학기별 reason이 없을 때 쓰인다).",
                    },
                    "program_type": {
                        "type": "string",
                        "enum": ["primary", "minor", "dual", "interdisciplinary"],
                        "description": "이 계획 항목들이 어느 프로그램용인지. 기본 NULL=주전공/미지정.",
                    },
                },
                "required": ["terms"],
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


def _safe_call(handler, tool_input: dict) -> dict:
    """`handler(**tool_input)` 방어 래퍼.

    LLM(gpt-4o-mini 관측)이 종종 잘못된 kwarg 이름을 낸다 — 예: `{"query=": "..."}`
    처럼 등호가 붙거나, 스키마에 없는 필드를 추가한다. 기본 `handler(**tool_input)`은
    `TypeError`로 죽고, 그 위를 감싼 langfuse span context가 `generator didn't stop
    after throw()`로 재폭발해서 대화 전체가 크래시된다.

    대응: handler 시그니처에 없는 키는 조용히 드롭하되, 응답에 `_dropped_args`로 실어
    LLM이 다음 턴에 올바른 이름으로 재호출할 수 있게 한다. 알 수 없는 예외는 문자열로
    감싸 error 필드로 돌려준다 — 도구 하나 실패로 전체 세션이 죽지 않도록.
    """
    import inspect

    try:
        sig = inspect.signature(handler)
    except (TypeError, ValueError):
        sig = None

    dropped: list[str] = []
    if sig is not None and tool_input:
        allowed = {
            n for n, p in sig.parameters.items()
            if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        }
        has_var_keyword = any(
            p.kind == p.VAR_KEYWORD for p in sig.parameters.values()
        )
        if not has_var_keyword:
            filtered = {k: v for k, v in tool_input.items() if k in allowed}
            dropped = [k for k in tool_input if k not in allowed]
            tool_input = filtered

    try:
        result = handler(**tool_input)
    except TypeError as e:
        return {"error": f"도구 호출 실패(잘못된 인자): {e}", "_dropped_args": dropped}
    except Exception as e:  # noqa: BLE001 - 도구 하나 실패로 세션 전체를 죽이지 않는다
        return {"error": f"도구 실행 오류: {type(e).__name__}: {e}"}

    if dropped and isinstance(result, dict):
        result.setdefault("_dropped_args", dropped)
    return result


def _compute_critical_missing_required(
    db: Session,
    user: User,
    roadmap_id: int | None,
    reference_semester: str,
) -> list[dict]:
    """학과 필수·기초 과목 중 (a) 미이수 (b) courses.semester가 단일 학기 전용
    ('1' 또는 '2') (c) 그 개설 학기가 `reference_semester`와 다름 — 조건을 모두
    만족하는 과목 목록.

    졸업 위험 감지용. 예: 4학년 2학기 학생이 컴퓨터구조(전공필수, 2학기 전용)를
    미이수면, 다음 학기(1학기)엔 못 듣는다는 사실을 LLM이 도구 결과로 즉시 인지해서
    finish_response에 위험 경고를 붙일 수 있게 한다. 이 정보 없이는 LLM이
    courses.semester를 스스로 크로스체크하지 않고 무해한 추천만 나열해 사용자가
    졸업 실패 위험을 모른 채로 넘어간다 (case 13 관측).

    - **roadmap 챗**: `reference_semester = next_plannable_term.semester` (다음 학기)
      → "다음 학기에 못 듣는 필수" 목록
    - **timetable 챗**: `reference_semester = target_term.semester` (이번 학기)
      → "이번 학기 시간표에 넣을 수 없는 필수" 목록

    `1,2` / `전학기` / 계절수업 개설 과목은 어느 학기든 미룰 수 있어 제외.
    `roadmap_id=None`이면 status='completed' 로드맵 항목은 이수 세트에서 빠지고
    student_course_records만 본다 (timetable 챗은 로드맵 없이도 호출 가능).
    """
    if user.department_id is None:
        return []

    def _norm(n: str | None) -> str:
        """propose_change의 _norm과 동일 규칙: 유니코드 로마자 정규화 + 괄호·공백 제거."""
        if not n:
            return ""
        roman = {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV"}
        s = "".join(roman.get(ch, ch) for ch in n)
        return s.replace("(", "").replace(")", "").replace(" ", "").strip()

    # 이수 완료 세트: student_course_records + 로드맵의 status='completed' (있으면)
    completed_norms: set[str] = set()
    for r in db.scalars(
        select(StudentCourseRecord).where(StudentCourseRecord.user_id == user.id)
    ).all():
        completed_norms.add(_norm(r.raw_course_name))
    # 편입생이 "전적대 데이터구조가 PNU 자료구조를 대체했다"고 직접 등록해 뒀으면
    # 성적표에 없는 PNU 과목명도 이수 완료로 본다 (course_substitution 참고).
    for name in substituted_course_names(db, user.id):
        completed_norms.add(_norm(name))
    if roadmap_id is not None:
        for it in db.scalars(
            select(CourseRoadmapItem).where(
                CourseRoadmapItem.roadmap_id == roadmap_id,
                CourseRoadmapItem.status == "completed",
            )
        ).all():
            completed_norms.add(_norm(it.course_name))

    ref_char = str(reference_semester).replace("학기", "").strip()
    if ref_char not in ("1", "2"):
        return []  # 계절수업 등 정규 학기 아니면 위험 판정 불가

    q = select(Course).where(
        Course.department_id == user.department_id,
        # 부산대 AIS 시드 표준 표기. 카테고리 값이 학과별로 다르게 도입되면
        # (예: "학과기초", "기초선택") 이 리스트에 추가해야 한다. 향후 스키마에
        # `category_kind` enum이 생기면 그걸 우선 사용.
        Course.category.in_(["전공필수", "전공기초"]),
        Course.semester.in_(["1", "2"]),  # 단일 학기 전용만 (전학기·1,2·계절수업은 미룰 수 있음)
    )
    if user.major_id is not None:
        q = q.where(or_(Course.major_id == user.major_id, Course.major_id.is_(None)))

    critical: list[dict] = []
    for c in db.scalars(q).all():
        if _norm(c.course_name) in completed_norms:
            continue
        if c.semester == ref_char:
            continue  # 그 학기에 개설 — 위험 아님
        critical.append({
            "course_id": c.id,
            "course_name": c.course_name,
            "category": c.category,
            "offered_semester": c.semester,
            "reason": (
                f"학과 필수인데 {c.semester}학기 전용 개설이라 대상 학기"
                f"({reference_semester})에는 수강 불가"
            ),
        })
    return critical


def _compute_missing_required_available(
    db: Session, user: User, roadmap_id: int | None, reference_semester: str
) -> list[dict]:
    """미이수 전공기초·전공필수 중 **대상 학기에 실제로 담을 수 있는** 과목 목록.

    `_compute_critical_missing_required`의 짝이다:
      - critical  = 미이수 + 그 학기에 개설 **안 됨** → 졸업 위험 경고
      - 이 함수   = 미이수 + 그 학기에 개설 **됨**   → 이번 학기 최우선 추천 대상

    왜 도구가 주는가: 예전엔 프롬프트가 "get_graduation_progress의 전공기초 remaining과
    completed_courses와 학과 커리큘럼을 대조해서 누락된 저학년 필수를 먼저 추천해라"라고
    시켰다. LLM이 세 소스를 크로스체크해야 해서 자주 놓쳤고, 그걸 보완하려고 넣은 구체적
    예시("이산수학 미이수면...")는 **이미 이수한 학생에게도 그대로 복사**되는 환각을 낳았다.
    예시를 빼자 이번엔 규칙 준수가 무너졌다(케이스 12가 0/3).
    → 크로스체크를 도구로 내리고 프롬프트는 "이 목록을 먼저 추천해라"만 말하게 한다.
    """
    critical_ids = {
        c["course_id"] for c in
        _compute_critical_missing_required(db, user, roadmap_id, reference_semester)
    }

    def _norm(n: str | None) -> str:
        if not n:
            return ""
        roman = {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV"}
        t = "".join(roman.get(ch, ch) for ch in n)
        return t.replace("(", "").replace(")", "").replace(" ", "").strip()

    completed_norms: set[str] = set()
    for r in db.scalars(
        select(StudentCourseRecord).where(StudentCourseRecord.user_id == user.id)
    ).all():
        completed_norms.add(_norm(r.raw_course_name))
    # 편입생이 "전적대 데이터구조가 PNU 자료구조를 대체했다"고 직접 등록해 뒀으면
    # 성적표에 없는 PNU 과목명도 이수 완료로 본다 (course_substitution 참고).
    for name in substituted_course_names(db, user.id):
        completed_norms.add(_norm(name))
    if roadmap_id is not None:
        for it in db.scalars(
            select(CourseRoadmapItem).where(
                CourseRoadmapItem.roadmap_id == roadmap_id,
                CourseRoadmapItem.status == "completed",
            )
        ).all():
            completed_norms.add(_norm(it.course_name))

    ref_char = str(reference_semester).replace("학기", "").strip()

    # **활성 프로그램 전부**를 훑는다. 주전공만 보면 복수·부전공 학생의 목록에 그 프로그램
    # 과목이 하나도 안 들어가고, 규칙이 "이 목록을 앞에 배치해라"라고 시키는 탓에 답변이
    # 주전공으로만 채워져 **사용자가 물어본 프로그램이 통째로 빠진다**
    # (골든 케이스 09: "복수전공 수학과 뭐부터?"에 정컴 과목만 답해서 3/3 → 1/3).
    programs = db.scalars(
        select(UserAcademicProgram).where(
            UserAcademicProgram.user_id == user.id,
            UserAcademicProgram.status.in_(ACTIVE_PROGRAM_STATUSES),
        )
    ).all()
    scopes = [(p.department_id, p.major_id, p.program_type) for p in programs if p.department_id]
    if not scopes:
        scopes = [(user.department_id, user.major_id, "primary")]

    available: list[dict] = []
    seen_ids: set[int] = set()
    for dept_id, major_id, program_type in scopes:
        q = select(Course).where(
            Course.department_id == dept_id,
            Course.category.in_(["전공필수", "전공기초"]),
        )
        if major_id is not None:
            q = q.where(or_(Course.major_id == major_id, Course.major_id.is_(None)))
        for c in db.scalars(q).all():
            if c.id in critical_ids or c.id in seen_ids:
                continue
            if _norm(c.course_name) in completed_norms:
                continue
            # 그 학기에 열리는 것만: 해당 학기 전용이거나 학기 무관 개설.
            if not (c.semester == ref_char or c.semester in ("1,2", "전학기")):
                continue
            seen_ids.add(c.id)
            available.append({
                "course_id": c.id,
                "course_name": c.course_name,
                "category": c.category,
                "credits": float(c.credits) if c.credits is not None else None,
                "grade": c.year,
                # 어느 프로그램 요건인지 밝힌다 — 안 밝히면 LLM이 전부 주전공으로 뭉뚱그린다.
                "program_type": program_type,
                "program_label": _PROGRAM_TYPE_LABELS.get(program_type, program_type),
            })
    return available


# 부산대 재수강 규정 상 C+(2.5) 이하만 재수강 가능. 학사 규정이 바뀌면 이 값만 수정.
# 실제 규정 근거: 학사관리규정 재수강 조항 (기준은 대학·연도별 조금씩 다를 수 있음).
_RETAKE_GRADE_POINT_THRESHOLD = 2.5


def _best_grade_point_for_norm(db: Session, user_id: int, norm_key: str, norm_fn) -> float | None:
    """정규화된 이름 키로 학생의 그 과목 최고 grade_point 조회. None이면 판단 불가.

    propose_change의 재수강 가드 우회 검증에 사용. `_compute_retake_candidates`와 같은
    "최고치 유지" 규칙 (재수강해서 이미 개선된 성적을 반영)을 재사용한다.
    """
    records = db.scalars(
        select(StudentCourseRecord).where(StudentCourseRecord.user_id == user_id)
    ).all()
    best: float | None = None
    for r in records:
        if r.grade_point is None:
            continue
        if norm_fn(r.raw_course_name) != norm_key:
            continue
        gp = float(r.grade_point)
        if best is None or gp > best:
            best = gp
    return best


def _compute_retake_candidates(db: Session, user: User) -> list[dict]:
    """성적표(SCR)에서 성적이 낮아 재수강 후보가 되는 과목 목록.

    로직:
    - 이름 정규화 후 최고 grade_point만 유지 (재수강해서 이미 개선했으면 최신치가 반영됨)
    - 최고 grade_point가 `_RETAKE_GRADE_POINT_THRESHOLD`(C+ = 2.5) 이하면 후보
    - grade_point가 없는 rows(=포털 동기화 전, 학점 미매핑)는 판단 불가로 제외
    - is_retake 플래그는 참조만 하고 필터에 쓰지 않음 — 정규화 후 최고치 기준이 더 안정적

    LLM에게는 **권유 후보**로 노출한다. 학생이 명시적으로 GPA 개선/재수강 관심을
    표할 때만 이 목록에서 후보를 제시하고, 그렇지 않으면 매번 강권하지 마라.
    사용자가 특정 과목을 콕 집어 재수강을 요청하면 `propose_change(..., is_retake=True)`로
    로드맵에 넣을 수 있다 — 그 플래그가 있어야만 completed_courses_guard를 우회하고,
    이 목록에 없는 과목(B- 이상)에 넘기면 도구가 거절한다. 골든 케이스 22가 이 흐름을 지킨다.
    """

    def _norm(n: str | None) -> str:
        if not n:
            return ""
        roman = {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV"}
        s = "".join(roman.get(ch, ch) for ch in n)
        return s.replace("(", "").replace(")", "").replace(" ", "").strip()

    records = db.scalars(
        select(StudentCourseRecord).where(StudentCourseRecord.user_id == user.id)
    ).all()

    # 이름별 최고 grade_point 집계 (재수강 후 개선된 성적을 반영하기 위해).
    # grade_point가 None인 row는 집계 제외.
    best_by_name: dict[str, tuple[float, StudentCourseRecord]] = {}
    for r in records:
        if r.grade_point is None:
            continue
        key = _norm(r.raw_course_name)
        if not key:
            continue
        gp = float(r.grade_point)
        cur = best_by_name.get(key)
        if cur is None or gp > cur[0]:
            best_by_name[key] = (gp, r)

    candidates: list[dict] = []
    for key, (gp, r) in best_by_name.items():
        if gp > _RETAKE_GRADE_POINT_THRESHOLD:
            continue
        candidates.append({
            "course_name": r.raw_course_name,
            "category": r.category,
            "credits": float(r.credits) if r.credits is not None else None,
            "current_grade": r.grade,
            "current_grade_point": gp,
            "year_taken": r.year,
            "semester_taken": r.semester,
            "reason": (
                f"현재 최고 성적 {r.grade or f'GPA {gp:.1f}'} — "
                f"재수강 가능 (기준: 최고 {_RETAKE_GRADE_POINT_THRESHOLD:.1f} 이하)"
            ),
        })
    # 성적 낮은 순 정렬 — LLM이 우선순위 짐작에 도움.
    # `0.0 or 999`는 999로 falsy 처리되니 명시적 None 체크.
    candidates.sort(key=lambda c: (999 if c["current_grade_point"] is None
                                    else c["current_grade_point"]))
    return candidates


# 선수과목을 courses.description 본문에서 추출할 때 인식하는 라벨. 부산대
# 학과별로 표기가 조금씩 다르지만 이 세 개면 대부분 커버 (관측 기준).
_PREREQ_LABELS = (
    "선수과목", "선이수과목", "선이수 과목", "선수 과목", "선수",
)


def _extract_prereqs_from_description(desc: str | None) -> list[str]:
    """courses.description 텍스트에서 선수과목명을 최선노력(best-effort)으로 추출.

    지원 패턴 (모두 라벨 뒤 콜론/전각콜론 필요):
    - "선수과목: 자료구조, 알고리즘"
    - "선이수 과목: 컴퓨터프로그래밍(I)"
    - "선수: X 및 Y"

    구분자: `,` `;` `·` `、` ` 및 ` ` 또는 ` ` 그리고 `

    라벨 없는 자유서술("자료구조를 미리 이수한 학생 대상") 같은 것은 잡지 않는다 —
    false positive 방지가 우선. 이런 경우엔 LLM의 check_prereqs 도구가 대안.

    **파싱 한계**: 라벨이 문장 중간에 있고 뒤에 서술이 이어지는 경우
    ("선수과목: 자료구조 를 요구한다") false positive 위험. 조사·서술어 꼬리를
    스트립으로 완화하지만 완벽하진 않음. 실사용 관측되면 구조적 prereq 스키마
    도입으로 근본 해결 (별도 스코프).
    """
    if not desc:
        return []
    import re

    label_re = "|".join(re.escape(lbl) for lbl in _PREREQ_LABELS)
    # 라벨 뒤 문장 끝까지 greedy 캡처 → 아래에서 구분자로 split + 서술어 tail trim.
    # greedy 유지 이유: `선수과목: A, B, C` 를 한 번에 잡아야 comma split이 성립.
    pattern = re.compile(rf"(?:{label_re})\s*[:：]\s*([^.。\n]+)")

    # 과목명 뒤에 붙는 조사·서술어 시작 마커. 이 단어들이 whitespace 뒤 별개 토큰으로
    # 나타나면 그 위치에서 잘라낸다 ("자료구조 를 요구한다" → "자료구조").
    _PARTICLE_OR_VERB_MARKERS = frozenset({
        "은", "는", "이", "가", "을", "를", "과", "와", "에", "로",
        "은데", "인데", "인", "이며", "이수", "필요", "요구", "권장",
        "및",  # 이미 splitter가 처리하지만 여기서도 안전장치
    })

    def _trim_tail(name: str) -> str:
        """공백으로 토큰화 후 첫 조사·서술어 마커 이전까지만 유지 (multi-word 과목명 보존)."""
        tokens = name.split()
        keep: list[str] = []
        for tok in tokens:
            if tok in _PARTICLE_OR_VERB_MARKERS:
                break
            # 어절이 "을...", "를...", "이수...", 같이 시작하면 서술 시작으로 간주
            if any(tok.startswith(m) for m in ("을", "를", "이수", "필요", "요구", "권장")):
                break
            keep.append(tok)
        return " ".join(keep)

    names: list[str] = []
    seen: set[str] = set()
    for m in pattern.findall(desc):
        # 구분자 splitter (콤마, 세미콜론, 중점, ' 및 ', ' 또는 ', ' 그리고 ')
        parts = re.split(r"[,;·、]|\s*(?:및|또는|그리고)\s*", m)
        for p in parts:
            p = _trim_tail(p.strip())
            # 남은 미세 잔여물 (구두점·조사 단글자) 제거
            while p and p[-1] in "은는이가을를와과 등,.":
                p = p[:-1].rstrip()
            if p and p not in seen:
                seen.add(p)
                names.append(p)
    return names


def _compute_prereq_blocked(
    db: Session,
    user: User,
    roadmap_id: int | None,
) -> list[dict]:
    """학과 개설 과목 중 (a) 아직 이수 안 함 (b) description에서 뽑아낸 선수과목 중
    하나 이상이 이수 완료 세트에 없음 — 조건을 만족하는 과목 목록.

    이 리스트에 있는 과목은 이번 학기든 다음 학기든 **선수과목 부족으로 지금 담기
    부적절**. LLM이 자동 추천에서 제외하거나, 학생이 문의 시 "선수과목 X부터 들어야
    한다"고 안내해야 한다. courses.description 파싱 기반이라 best-effort — 학과 문서
    라벨링이 애매하면 false positive/negative 있을 수 있다 (LLM check_prereqs로 보완).

    `roadmap_id=None`이면 이수 세트는 SCR만 참조 (timetable 챗).
    """
    if user.department_id is None:
        return []

    def _norm(n: str | None) -> str:
        if not n:
            return ""
        roman = {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV"}
        s = "".join(roman.get(ch, ch) for ch in n)
        return s.replace("(", "").replace(")", "").replace(" ", "").strip()

    completed_norms: set[str] = set()
    for r in db.scalars(
        select(StudentCourseRecord).where(StudentCourseRecord.user_id == user.id)
    ).all():
        completed_norms.add(_norm(r.raw_course_name))
    # 편입생이 "전적대 데이터구조가 PNU 자료구조를 대체했다"고 직접 등록해 뒀으면
    # 성적표에 없는 PNU 과목명도 이수 완료로 본다 (course_substitution 참고).
    for name in substituted_course_names(db, user.id):
        completed_norms.add(_norm(name))
    if roadmap_id is not None:
        for it in db.scalars(
            select(CourseRoadmapItem).where(
                CourseRoadmapItem.roadmap_id == roadmap_id,
                CourseRoadmapItem.status == "completed",
            )
        ).all():
            completed_norms.add(_norm(it.course_name))

    q = select(Course).where(
        Course.department_id == user.department_id,
        Course.description.is_not(None),
    )
    if user.major_id is not None:
        q = q.where(or_(Course.major_id == user.major_id, Course.major_id.is_(None)))

    blocked: list[dict] = []
    for c in db.scalars(q).all():
        if _norm(c.course_name) in completed_norms:
            continue  # 이미 이수 — 판단 대상 아님
        prereq_names = _extract_prereqs_from_description(c.description)
        if not prereq_names:
            continue  # 선수과목 라벨 없음
        missing = [p for p in prereq_names if _norm(p) not in completed_norms]
        if not missing:
            continue  # 다 이수했으니 blocked 아님
        blocked.append({
            "course_id": c.id,
            "course_name": c.course_name,
            "category": c.category,
            "missing_prerequisites": missing,
            "reason": (
                f"description상 선수과목 '{', '.join(missing)}' 미이수 — "
                f"지금 이 과목 담기 전에 선수부터 이수 권장"
            ),
        })
    return blocked


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
        # 졸업요건을 숫자로 알 수 있는 학생인가. `_requirement_coverage()`가 채운다.
        # 요건 행이 없으면 "다 채웠다"고 말할 근거가 없다.
        self.requirements_known = False
        # 총 이수학점 기준 잔여(이번 턴 제안 반영 후). None이면 기준을 모른다는 뜻.
        self.remaining_total_after_plan: float | None = None
        # 턴 안에서 안 변하는 값들. 매 호출 재계산이 이수기록 전체 스캔·과목 조회로
        # 이어져 도구 한 번에 수백 건의 SELECT가 나갔다.
        self._remaining_terms_cache: list[dict] | None = None
        self._course_credits_cache: dict[int, float] = {}
        # propose_term_plan이 "아직 미배정 학점이 남았고 학기 여유도 있다"고 판정하면
        # 그 요약이 여기 담긴다. run_roadmap_chat이 이 값을 보고 첫 finish_response를
        # 한 번만 되돌린다 (아래 _finish_gate_blocked 참고).
        self.plan_gap: dict | None = None
        # propose_term_plan을 이 턴에 한 번이라도 불렀는지. "졸업까지" 요청인데 제안을
        # 하나도 안 만들고 되묻기만 하고 끝내는 걸 막는 게이트가 이 값을 본다.
        self.term_plan_called = False

    def get_graduation_progress(self) -> dict:
        # 부전공/복수전공/융합전공까지 모두 진도 계산해 LLM에 노출
        progresses = compute_graduation_progress(
            self.db, self.user.id, program_types={"primary", "minor", "dual", "interdisciplinary"}
        )
        return {
            "programs": [
                {
                    "program_type": p.program_type,
                    # 한글 명칭을 같이 준다. 영문 코드만 주면 LLM이 추측해서 연계전공(48학점)을
                    # "부전공"이라 부르는 일이 있었다 — 부전공은 21학점이라 학생이 요구 학점을
                    # 오해한다 (골든 케이스 06에서 관측).
                    "program_label": _PROGRAM_TYPE_LABELS.get(p.program_type, p.program_type),
                    "department_id": p.department_id,
                    "major_id": p.major_id,
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

    def get_available_tracks(self) -> dict:
        """이 학생의 학과에서 이수 가능한 AI융합트랙(SW융합트랙) 목록.

        졸업요건이 **아니다** — 이수하면 졸업증명서에 과정명이 표기되는 인증
        프로그램이다. 학과 전공과목 12~15학점 + AI융합 공통교과목 6~9학점 = 총
        21학점.

        프로필 블록(텍스트)에도 같은 정보가 실리지만, 도구로도 조회할 수 있어야
        한다 — 실측(2026-08-19)에서 심리학과 학생이 "내가 들을 수 있는 특별한
        프로그램 있어?"라고 물었을 때, 프롬프트에 트랙이 적혀 있는데도 LLM이
        "확인된 항목이 없습니다"라고 답했다. 도구로 사실을 확인하는 구조라
        조회 수단이 없는 정보는 "없는 것"으로 기울었다.

        대상 학과가 아니면 `tracks: []`. 그때는 트랙 얘기를 꺼내면 안 된다.
        """
        department_id = self.user.department_id
        if department_id is None:
            return {"tracks": [], "note": "학과 정보가 없어 트랙을 판단할 수 없다."}

        grs = find_ai_tracks_for_department(self.db, department_id)
        if not grs:
            return {
                "tracks": [],
                "note": "이 학과는 AI융합트랙 대상 학과가 아니다. 트랙을 언급하지 마라.",
            }

        enrolled_major_ids = {
            p.major_id
            for p in self.db.scalars(
                select(UserAcademicProgram).where(
                    UserAcademicProgram.user_id == self.user.id,
                    UserAcademicProgram.program_type == "interdisciplinary",
                    UserAcademicProgram.status.in_(ACTIVE_PROGRAM_STATUSES),
                )
            ).all()
        }

        tracks = []
        for gr in grs:
            major = self.db.get(_Major, gr.major_id) if gr.major_id else None
            rules = gr.special_rules or {}
            tracks.append({
                "track_name": major.name if major else "?",
                "major_id": gr.major_id,
                "total_credits": gr.required_total_credits,
                "dept_credits": rules.get("dept_credits"),
                "ai_common_credits": rules.get("ai_common_credits"),
                "is_enrolled": gr.major_id in enrolled_major_ids,
            })
        # 다음 배치 가능 학기 기준으로 실제 개설 여부까지 붙인다. 카탈로그에 있는 것과
        # 이번 학기에 담을 수 있는 것은 다르다 — 2026-2학기 실측에서 카탈로그 8/10인데
        # 실제 개설은 3개뿐이었다. 구분 없이 안내하면 담을 수 없는 과목을 권하게 된다.
        cy, cs = _current_academic_term()
        ny, ns = _next_term(cy, cs)
        common = list_ai_common_courses(self.db, year=str(ny), semester=f"{ns}학기")
        # **개설 상태별로 배열을 나눠서 준다.** 한 배열에 플래그로 담아 주면 LLM이
        # 섞는다 — 실측(2026-08-19)에서 "이번 학기 담을 수 있는 과목" 목록 안에
        # 미개설 과목을 넣고, 정작 개설된 과목은 "학기마다 다르다"로 분류했다.
        return {
            "tracks": tracks,
            # 트랙 학점의 절반 가까이가 이 공통교과목에서 나온다. 목록 없이 "AI융합 공통
            # 6~9학점"만 알려주면 학생은 무엇을 담아야 할지 모른다.
            "ai_common_term": {"year": str(ny), "semester": f"{ns}학기"},
            "ai_common_can_take_now": [c for c in common if c.get("offered_this_term")],
            "ai_common_not_offered_this_term": [
                c for c in common if c["in_catalog"] and not c.get("offered_this_term")
            ],
            "ai_common_not_in_catalog": [c for c in common if not c["in_catalog"]],
            "ai_common_scheduling": AI_COMMON_SCHEDULING_NOTE,
            "note": (
                "졸업요건이 아니라 선택 인증 프로그램이다. 미이수해도 졸업에 영향 없다는 점을 "
                "반드시 함께 말해라. 미등록 상태면 '프로필의 AI융합트랙 등록에서 시작할 수 있다'고 "
                "안내하고, 이미 등록했으면 get_program_evaluations로 진도를 확인해라. "
                "AI융합 공통교과목(전부 일반선택)은 개설 상태별로 세 배열로 나눠서 준다. "
                "**배열을 섞지 마라.** ai_common_can_take_now = ai_common_term 학기에 실제로 "
                "담을 수 있는 것(이것만 이번 학기 추천에 넣어라). "
                "ai_common_not_offered_this_term = 과정에는 있으나 이번 학기 미개설(나중 학기에 "
                "노려야 한다고만 말해라). ai_common_not_in_catalog = 우리 수강편람에서 확인되지 "
                "않음(AI융합교육원 공지를 확인하라고 덧붙여라). "
                "listed_as가 있으면 수강편람에 그 이름으로 올라와 있다는 뜻이다."
            ),
        }

    def get_program_evaluations(self) -> dict:
        """부전공·SW융합트랙 등 program_type != 'primary' 프로그램의 규칙 기반 판정.

        graduation_requirements.special_rules(JSONB)에 담긴 그룹별 규칙
        (all/min_courses/min_credits/min_distinct_departments)을 학생 이수내역과
        대조해 각 그룹 완료 여부·부족분을 반환한다. 부전공 필수과목 남은 개수,
        SW융합트랙 학점 그룹별 진행률 등에 사용.
        """
        # 학생의 non-primary 프로그램 순회
        programs = self.db.scalars(
            select(UserAcademicProgram)
            .where(UserAcademicProgram.user_id == self.user.id,
                   UserAcademicProgram.status.in_(ACTIVE_PROGRAM_STATUSES))
            .where(UserAcademicProgram.program_type != "primary")
        ).all()

        results = []
        for prog in programs:
            if prog.department_id is None:
                continue
            r = evaluate_program(
                self.db,
                user_id=self.user.id,
                department_id=prog.department_id,
                major_id=prog.major_id,
                program_type=prog.program_type,
                curriculum_year=prog.curriculum_year,
            )
            if r is None:
                results.append({
                    "program_type": prog.program_type,
                    "department_id": prog.department_id,
                    "major_id": prog.major_id,
                    "curriculum_year": prog.curriculum_year,
                    "requirement_found": False,
                    "note": "special_rules 요건 데이터가 없습니다 (학과사무실 문의 or 후속 시드 대상).",
                })
                continue
            results.append({
                "program_type": r.program_type,
                "department_id": r.department_id,
                "major_id": r.major_id,
                "curriculum_year": r.curriculum_year,
                "requirement_found": True,
                "completed": r.completed,
                "total_credits_required": r.total_credits_required,
                "total_credits_earned": float(r.total_credits_earned),
                "total_credits_ok": r.total_credits_ok,
                "exclude_categories": r.excluded_categories,
                "notes": r.notes,
                "groups": [
                    {
                        "label": g.label,
                        "rule_type": g.rule_type,
                        "required_n": g.required_n,
                        "required_credits": g.required_credits,
                        "matched_courses": g.matched_courses or [],
                        "completed": g.completed,
                        "shortage": g.shortage,
                    }
                    for g in r.groups
                ],
            })
        return {"evaluations": results}

    def _min_completed_grade(self) -> int | None:
        """편입생에게 1·2학년 과목을 새로 추천하지 않도록 하기 위한 "학생이 실제로
        밟아온 최저 학년"을 계산한다. propose_change의 planned_grade 하한으로 쓴다.

        결정 순서:
        1. 편입생이면(users.admission_type='transfer') 편입 학년을 그대로 쓴다.
           이수 기록이 아직 없는 편입 직후 상태에서도 확실하게 판정된다.
        2. 아니면 로드맵에 status='completed' + planned_grade IS NOT NULL 인 항목의
           min(planned_grade)를 쓴다. (일반 재학생이 이미 학기를 밟았을 때)
        3. 그것도 없으면 None — 일반 신입생 또는 커리큘럼 미확정 상태. 1학년부터
           자유롭게 create 가능.

        admission_type이 생기기 전에는 StudentCourseRecord에 semester='입학전성적'
        행이 있는지로 편입을 추론했다. 포털 동기화 전인 편입생은 판정할 수 없었고,
        조기이수 인정 학점이 있는 신입생은 편입생으로 잘못 걸렸다.
        """
        if is_transfer(self.user.admission_type):
            return TRANSFER_ENTRY_GRADE
        return self.db.scalar(
            select(func.min(CourseRoadmapItem.planned_grade)).where(
                CourseRoadmapItem.roadmap_id == self.roadmap.id,
                CourseRoadmapItem.status == "completed",
                CourseRoadmapItem.planned_grade.is_not(None),
            )
        )

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

        **이번 턴에 이미 제안(propose)된 미승인 변경도 함께 센다.** 예전에는 DB의
        CourseRoadmapItem만 셌는데, 그러면 아직 아무것도 없는 미래 학기(예: 4학년 1학기)에
        과목을 몇 개를 밀어넣든 합계가 계속 0이라 학기당 상한 가드가 한 번도 걸리지 않았다.
        승인하면 그대로 저장되는 값이므로 계획 시점에 같이 세는 게 맞다.
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

        # 같은 항목에 대한 변경은 **첫 건만** 반영한다. 델타 누적 방식이라 같은 item을
        # 두 번 delete하면 학점이 두 번 빠져서, 21학점이 찬 학기에 6학점이 더 들어간다
        # (실측). 중복 가드는 create에만 있어서 delete/update는 그대로 쌓인다.
        seen_items: set[int] = set()
        for ch in self.pending_changes:
            if exclude_item_id is not None and ch.item_id == exclude_item_id:
                continue
            if ch.action != "create" and ch.item_id is not None:
                if ch.item_id in seen_items:
                    continue
                seen_items.add(ch.item_id)
            if ch.action == "create":
                if ch.course_id is None:
                    continue
                # 과목 학점은 안 변하므로 턴 안에서 캐시한다. `db.get`이 이 세션 설정에서는
                # identity map을 타지 않고 매번 SQL을 내서, 제안이 쌓일수록 이 루프가
                # O(n²)로 커졌다(3학기×6과목 배치에서 SELECT courses가 308회).
                if ch.course_id in self._course_credits_cache:
                    credits = self._course_credits_cache[ch.course_id]
                else:
                    course = self.db.get(Course, ch.course_id)
                    credits = (
                        float(course.credits)
                        if course is not None and course.credits is not None
                        else 0.0
                    )
                    self._course_credits_cache[ch.course_id] = credits
                key = (ch.planned_year, ch.planned_semester)
                out[key] = out.get(key, 0.0) + credits
            elif ch.item_id is not None:
                item = self.db.get(CourseRoadmapItem, ch.item_id)
                if item is None:
                    continue
                credits = float(item.credits or 0)
                old_key = (item.planned_year, item.planned_semester)
                if ch.action == "delete":
                    out[old_key] = out.get(old_key, 0.0) - credits
                elif ch.action == "update" and ch.planned_year:
                    # 학기를 옮기는 update만 학점이 이동한다.
                    new_key = (ch.planned_year, ch.planned_semester or item.planned_semester)
                    if new_key != old_key:
                        out[old_key] = out.get(old_key, 0.0) - credits
                        out[new_key] = out.get(new_key, 0.0) + credits
                # `planned_year` 없는 update(예: planned_grade만 교정)는 학기가 그대로다.
                # 예전엔 여기서도 옛 학기 학점을 빼기만 하고 다시 더하지 않아서, 그런 제안
                # 하나가 그 학기 학점을 통째로 증발시켰다 — 상한 가드가 오히려 느슨해졌다.
        return out

    def _remaining_terms(self) -> list[dict]:
        """졸업까지 남은 학기 + 학기별 이미 계획된 학점/여유 학점.

        학기 목록 자체(`_remaining_terms_until_graduation`)는 턴 안에서 안 변하는데
        계산에 이수기록 전체 스캔이 학기 수만큼 들어간다. `get_roadmap_items`가 매 턴
        부르고 `propose_term_plan` 하나 안에서도 두 번 더 부르므로 캐시한다.
        계획 학점은 제안이 쌓이면서 바뀌므로 매번 다시 센다.
        """
        if self._remaining_terms_cache is None:
            self._remaining_terms_cache = _remaining_terms_until_graduation(
                self.db, self.user.id
            )
        cap = self._term_credit_cap()
        planned = self._planned_credits_by_term()
        out = []
        for term in self._remaining_terms_cache:
            used = planned.get((term["planned_year"], term["planned_semester"]), 0.0)
            out.append({
                **term,
                "already_planned_credits": used,
                "credits_left_in_term": max(cap - used, 0.0),
            })
        return out

    def _critical_missing_required(self, next_planned_semester: str) -> list[dict]:
        """`_compute_critical_missing_required` 얇은 wrapper. 로드맵 챗이 self.roadmap.id를
        자동으로 넘긴다. 실제 로직·시맨틱은 module-level 함수 docstring 참고.
        """
        return _compute_critical_missing_required(
            self.db, self.user, self.roadmap.id, next_planned_semester
        )

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
        # 커리큘럼 학기 매핑 — 엇학기(휴학 이력) 학생은 달력 학기와 커리큘럼 학년/학기가
        # 어긋난다. 예: 한 학기 휴학한 학생의 커리큘럼 4-1이 실제로는 달력 2학기.
        # 이 정보를 명시적으로 노출해서 LLM이 (a) 스케줄 필터는 next_plannable_term
        # (달력), (b) 요건·학년 판단은 next_curriculum_term (커리큘럼) 순으로 쓸 수
        # 있게 한다.
        from app.domains.planning.history import project_curriculum_term
        cur_grade, cur_sem = project_curriculum_term(
            self.db, self.user.id, str(cy), f"{cs}학기"
        )
        next_grade, next_sem = project_curriculum_term(
            self.db, self.user.id, str(ny), f"{ns}학기"
        )
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
            # 엇학기 대응: 커리큘럼 상 지금·다음 학기가 달력과 어긋날 수 있음.
            "current_curriculum_term": {"grade": cur_grade, "semester": cur_sem},
            "next_curriculum_term": {"grade": next_grade, "semester": next_sem},
            "term_credit_cap": credit_cap,
            # 다음 배치 가능 학기 ~ 졸업 예정 학기. "졸업까지 계획해줘"에 이 목록의
            # 학기를 전부 채워야 한다 (2026-08-20까지는 이 값이 없어서 LLM이 다음
            # 한 학기만 제안하고 끝냈다).
            "remaining_terms": self._remaining_terms(),
            "planned_credits_by_term": [
                {"planned_year": y, "planned_semester": s, "credits": c}
                for (y, s), c in sorted(planned.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or ""))
            ],
            "completed_courses": self._completed_courses(),
            # 졸업 위험 감지: 학과 필수인데 미이수 + 개설학기가 다음 학기와 어긋난 목록.
            # 비어있지 않으면 LLM이 finish_response에서 사용자에게 위험을 반드시 알려야 한다.
            "critical_missing_required": self._critical_missing_required(f"{ns}학기"),
            "missing_required_available": _compute_missing_required_available(
                self.db, self.user, self.roadmap.id, f"{ns}학기"
            ),
            # 재수강 후보 (성적 낮은 이수 과목). **권유 정보**로 노출 — 학생이 GPA 개선
            # 관심 표하거나 명시적으로 재수강 물을 때만 제시. 물어보지 않았는데 매번
            # 강권하지 마라.
            "retake_candidates": _compute_retake_candidates(self.db, self.user),
            # 선수과목 부족으로 담기 부적절한 학과 개설 과목. courses.description 파싱
            # 기반이라 best-effort — LLM이 이 목록에 있는 course_id는 propose_change
            # (create) 하지 말고, 학생이 물어보면 "선수과목 X부터 들어야" 안내해라.
            "prereq_blocked": _compute_prereq_blocked(
                self.db, self.user, roadmap_id=self.roadmap.id,
            ),
        }

    def search_courses(
        self,
        query: str = "",
        semester: str | None = None,
        grade: str | int | None = None,
        category: str | None = None,
        program_type: str | None = None,
    ) -> dict:
        """과목 후보 검색.

        program_type: None(기본, 주전공 학과) | "minor" | "dual" | "interdisciplinary"
        지정 시 UserAcademicProgram에서 해당 program_type의 department/major 조회 후
        그 학과 개설과목 + program_courses 인정과목을 검색 대상으로 사용한다.
        """
        query = (query or "").strip()

        # 검색 스코프 결정: program_type 지정되면 해당 프로그램의 dept/major, 아니면 주전공
        if program_type and program_type != "primary":
            target_prog = self.db.scalars(
                select(UserAcademicProgram).filter_by(
                    user_id=self.user.id, program_type=program_type,
                ).where(UserAcademicProgram.status.in_(ACTIVE_PROGRAM_STATUSES))
            ).first()
            if target_prog is None or target_prog.department_id is None:
                return {"results": [], "note": f"{program_type} 프로그램이 학적에 없거나 학과 정보 부족."}
            search_dept_id = target_prog.department_id
            search_major_id = target_prog.major_id
            curriculum_year = target_prog.curriculum_year or _DEFAULT_CURRICULUM_YEAR
        else:
            if self.user.department_id is None:
                return {"results": []}
            search_dept_id = self.user.department_id
            search_major_id = self.user.major_id
            primary_prog = self.db.scalars(
                select(UserAcademicProgram).filter_by(user_id=self.user.id, program_type="primary")
            ).first()
            curriculum_year = (
                primary_prog.curriculum_year if primary_prog and primary_prog.curriculum_year
                else _DEFAULT_CURRICULUM_YEAR
            )

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
            department_id=search_dept_id,
            major_id=search_major_id,
            curriculum_year=curriculum_year,
            filters=filters,
        )

        # program_type이 minor/interdisciplinary면 program_courses 인정과목도 병행 후보로 추가.
        # 부전공은 개설학과 과목 뿐 아니라 program_courses에 명시된 필수과목을 우선 노출해야
        # LLM이 부전공 필수과목을 놓치지 않는다.
        if program_type and program_type != "primary":
            extra_ids = {r["course_id"] for r in results if r.get("course_id")}
            pc_rows = self.db.scalars(
                select(ProgramCourse).where(
                    ProgramCourse.department_id == search_dept_id,
                    ProgramCourse.major_id == search_major_id,
                )
            ).all()
            for pc in pc_rows:
                if pc.course_id in extra_ids:
                    continue
                c = self.db.get(Course, pc.course_id)
                if not c:
                    continue
                results.append({
                    "course_id": c.id,
                    "course_name": c.course_name,
                    "category": c.category,
                    "credits": float(c.credits) if c.credits is not None else None,
                    "grade": c.year,
                    "semester": c.semester,
                    "evidence": f"program_courses.requirement_group='{pc.requirement_group}'",
                    "description": c.description,
                })
        payload: dict = {
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
        # 빈 결과에는 hint 부착 — LLM이 같은 인수로 반복 호출하지 않도록.
        if not payload["results"]:
            from app.ai.rag.curriculum_retriever import available_categories_for_scope
            cats = available_categories_for_scope(
                self.db,
                department_id=search_dept_id,
                major_id=search_major_id,
                semester=semester,
            )
            payload["available_categories"] = cats
            reason_parts = []
            if category and category not in cats:
                reason_parts.append(f"category={category!r}는 이 스코프 개설 목록에 없음")
            if query:
                reason_parts.append(f"query={query!r}로 매치 없음")
            if grade:
                reason_parts.append(f"grade={grade!r}로 좁힘 (제거 시 결과 있을 수 있음)")
            payload["note"] = (
                (" · ".join(reason_parts) or "결과 없음")
                + ". available_categories 참고해 다른 값으로 재시도하거나, "
                  "정말 매치 없으면 finish_response로 사용자에게 알려라."
            )
        return payload

    def propose_change(
        self,
        action: str,
        reason: str,
        item_id: int | None = None,
        course_id: int | None = None,
        planned_year: str | None = None,
        planned_semester: str | None = None,
        planned_grade: int | None = None,
        program_type: str | None = None,
        is_retake: bool = False,
    ) -> dict:
        if action not in ("create", "update", "delete"):
            return {"error": f"알 수 없는 action: {action}"}
        if program_type is not None and program_type not in ("primary", "minor", "dual", "interdisciplinary"):
            return {"error": f"program_type은 primary/minor/dual/interdisciplinary 중 하나여야 합니다: {program_type}"}

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
                match = next(
                    (r for r in completed if _norm(r.raw_course_name) == new_norm), None
                )
                # 편입생이 "이 PNU 과목은 전적대 과목으로 대체했다"고 직접 등록한 경우도
                # 이미 이수한 것으로 본다. 성적표에는 전적대 과목명('데이터구조')만 있어서
                # 이름 매칭으로는 안 잡힌다 (course_substitution 참고).
                #
                # **대체한 바로 그 행**을 가져온다. "대체됐나?"만 보고 아무 전적대 행이나
                # match로 쓰면 아래 에러 메시지가 엉뚱한 과목을 근거로 인용한다.
                if match is None:
                    match = substituting_record(self.db, self.user.id, course_obj.id)
                if match is not None:
                    # is_retake=True + 재수강 자격(=최고 grade_point ≤ 2.5) 확인되면 가드 우회.
                    # LLM이 사용자 명시적 재수강 요청 시에만 이 플래그를 걸도록 프롬프트에서 지시.
                    # 자격 없는 과목(B- 이상) 재수강 시도는 통과 안 함 — 부산대 규정 C+ 이하만 가능.
                    if is_retake:
                        best_gp = _best_grade_point_for_norm(self.db, self.user.id, new_norm, _norm)
                        if best_gp is not None and best_gp <= _RETAKE_GRADE_POINT_THRESHOLD:
                            # 재수강으로 정당하게 통과 — pending change 생성 시 reason에 자동 표기.
                            reason = f"[재수강] {reason}"
                        else:
                            return {
                                "error": (
                                    f"{course_obj.course_name!r}은(는) 재수강 대상이 아닙니다 "
                                    f"(현재 최고 성적 GP={best_gp}). 부산대 규정상 C+(2.5) 이하만 "
                                    f"재수강 가능합니다. is_retake=True 사용은 retake_candidates에 "
                                    f"올라온 과목에 한합니다."
                                )
                            }
                    else:
                        return {
                            "error": (
                                f"{course_obj.course_name!r}은(는) 이미 이수한 과목입니다"
                                f"(성적표 원문 '{match.raw_course_name}', {match.year} {match.semester}). "
                                f"재수강이면 is_retake=True를 넘겨주세요. 아니면 로드맵에 다시 넣지 마세요."
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

        if action == "create" and course_id is None:
            # 마지막 관문. course_id 없는 create는 항상 빈 항목을 만든다: 이 도구는
            # course_name을 받지 않고 PendingRoadmapChange에도 그 컬럼이 없어서,
            # apply_pending_changes가 이름·학점·이수구분을 전부 Course에서 가져온다
            # (`course_name=course.course_name if course else None`). 승인하면 과목명도
            # 학점도 없는 로드맵 행이 생기고 요건 집계에도 안 잡힌다.
            #
            # 더 나쁜 건, 이수·중복·재수강·계절수업 가드가 전부 `course_obj is not None`
            # 분기 안에 있어서 통째로 우회된다는 점이다 — 골든 케이스 22에서 실제로
            # `is_retake=True, course_id=None`이 모든 검증을 지나쳐 빈 항목을 만들었다.
            #
            # 위치가 마지막인 이유: 과거 학기·학년·학점 상한처럼 더 구체적인 위반이
            # 있으면 그 에러를 먼저 보여주는 게 LLM이 고치기 쉽다.
            return {
                "error": (
                    "create에는 course_id가 필요합니다. search_courses로 대상 과목을 먼저 "
                    "찾아 course_id를 확인한 뒤 다시 호출하세요. 이미 이수한 과목을 재수강 "
                    "제안하는 경우에도 마찬가지입니다 — retake_candidates의 과목명으로 "
                    "search_courses를 호출해 course_id를 얻은 뒤 is_retake=True와 함께 넘기세요."
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
            program_type=program_type,
        )
        self.db.add(change)
        self.db.flush()
        self.pending_changes.append(change)
        return {"change_id": change.id, "action": action}

    def propose_term_plan(
        self,
        terms: list[dict] | None = None,
        reason: str = "",
        program_type: str | None = None,
    ) -> dict:
        """여러 학기 계획을 한 번의 도구 호출로 제안한다.

        왜 별도 도구인가: "졸업까지 로드맵 짜줘"에 필요한 propose_change 호출 수는
        (남은 학기 수 × 학기당 5~7과목)이라 15~20회다. MAX_TOOL_ITERATIONS가 8이라
        구조적으로 불가능하고, 실제로 LLM은 시도조차 하지 않고 다음 한 학기만 제안한 뒤
        "승인해주시면 이어서 하겠다"로 끝냈다(2026-08-20 실계정 3회 전부).
        프롬프트로 "전부 계획해라"라고만 시키면 이번엔 반복 상한에 걸려 끊길 뿐이라,
        도구 쪽에서 한 번에 받을 수 있게 만드는 게 맞다.

        검증은 propose_change를 그대로 재사용한다 — 가드를 복제하면 한쪽만 고쳐지는
        일이 반드시 생긴다. 한 과목이 거절돼도 나머지는 계속 제안하고, 거절 사유는
        rejected에 담아 LLM이 다른 학기로 옮겨 재시도할 수 있게 한다.
        """
        if not terms:
            return {"error": "terms가 비어 있습니다. 학기별 course_ids를 넣어 다시 호출하세요."}
        if program_type is not None and program_type not in (
            "primary", "minor", "dual", "interdisciplinary"
        ):
            return {"error": f"program_type은 primary/minor/dual/interdisciplinary 중 하나여야 합니다: {program_type}"}

        self.term_plan_called = True
        cap = self._term_credit_cap()
        term_results: list[dict] = []
        accepted_count = 0
        rejected_count = 0

        for term in terms:
            if not isinstance(term, dict):
                continue
            planned_year = term.get("planned_year")
            planned_semester = term.get("planned_semester")
            planned_grade = term.get("planned_grade")
            course_ids = term.get("course_ids") or []
            term_reason = term.get("reason") or reason or "졸업까지 남은 학기 일괄 계획"

            accepted: list[dict] = []
            rejected: list[dict] = []
            already: list[dict] = []
            for course_id in course_ids:
                course = self.db.get(Course, course_id) if course_id is not None else None
                entry = {
                    "course_id": course_id,
                    "course_name": course.course_name if course is not None else None,
                    "category": course.category if course is not None else None,
                    "credits": float(course.credits) if course is not None and course.credits is not None else None,
                }
                # 이번 턴에 이미 제안한 과목을 다시 넘긴 경우는 **실패가 아니다**.
                # propose_change는 중복 create를 error로 돌려주는데, 벌크 경로에서
                # 그걸 rejected에 섞으면 LLM이 "다 반려됐다"고 읽고 앞서 성공한 제안까지
                # 없던 일처럼 답변한다(2026-08-20 실측: 실제로 accepted된 4학년 1학기
                # 3과목을 "확정 없음"이라고 답했다).
                # 이번 턴 제안뿐 아니라 **이미 승인돼 저장된 로드맵 항목**도 마찬가지다.
                # "1턴에 승인 → 2턴에 '졸업까지 마저 짜줘'"가 이 기능의 주 시나리오인데,
                # 그때 DB 항목과의 중복은 여전히 rejected로 떨어져서 같은 오독이 났다.
                if course_id is not None and (
                    any(
                        c.action == "create" and c.course_id == course_id
                        for c in self.pending_changes
                    )
                    or self.db.scalar(
                        select(CourseRoadmapItem.id).where(
                            CourseRoadmapItem.roadmap_id == self.roadmap.id,
                            CourseRoadmapItem.course_id == course_id,
                        )
                    )
                    is not None
                ):
                    already.append({
                        **entry,
                        # 안내가 없으면 "다른 학기로 옮겨달라"는 요청이 조용한 no-op이
                        # 된다 — 요청한 학기는 빈 채로 남는데 rejected도 아니라 LLM이
                        # 뭘 해야 할지 모른다.
                        "note": (
                            "이미 로드맵에 있는 과목이라 새로 만들지 않았다. 학기를 옮기려면 "
                            "propose_change(action='update', item_id=…)를 써라."
                        ),
                    })
                    continue
                result = self.propose_change(
                    action="create",
                    reason=term_reason,
                    course_id=course_id,
                    planned_year=planned_year,
                    planned_semester=planned_semester,
                    planned_grade=planned_grade,
                    program_type=program_type,
                )
                if "error" in result:
                    rejected.append({**entry, "error": result["error"]})
                    rejected_count += 1
                else:
                    accepted.append({**entry, "change_id": result.get("change_id")})
                    accepted_count += 1

            planned_after = self._planned_credits_by_term().get(
                (planned_year, planned_semester), 0.0
            )
            term_results.append({
                "planned_year": planned_year,
                "planned_semester": planned_semester,
                "planned_grade": planned_grade,
                "accepted": accepted,
                "already_in_plan": already,
                "rejected": rejected,
                "term_credits_after": planned_after,
                "term_credit_cap": cap,
            })

        # 계획이 덜 찼는지 도구가 직접 판정한다. 프롬프트로 "꽉 채워라"라고만 시켰을 때
        # LLM은 전공필수만 넣고 전공선택 29학점을 남긴 채 "추가 탐색이 필요합니다"로
        # 끝냈다(2026-08-20 실측). 남은 이수구분과 학기 여유 학점을 계산해서 돌려주면
        # 다음 턴에 무엇을 얼마나 더 찾아야 하는지가 명시적 지시가 된다.
        coverage = self._requirement_coverage()
        unmet = [
            {
                "category_name": c["category_name"],
                "remaining_credits": c["remaining_after_plan"],
            }
            for c in coverage
            if c["remaining_after_plan"] is not None and c["remaining_after_plan"] > 0
        ]
        room = [
            {
                "planned_year": t["planned_year"],
                "planned_semester": t["planned_semester"],
                "credits_left_in_term": round(t["term_credit_cap"] - t["term_credits_after"], 1),
            }
            for t in term_results
            if t["term_credit_cap"] - t["term_credits_after"] >= _MIN_USEFUL_TERM_ROOM
        ]
        total_room = sum(r["credits_left_in_term"] for r in room)
        total_unmet = sum(u["remaining_credits"] for u in unmet)
        # 총 이수학점이 남았으면 카테고리를 다 채웠어도 졸업요건 미충족이다.
        total_short = self.remaining_total_after_plan or 0.0
        # 요건을 숫자로 모르면(요건 행 없음) "채울 필요 없다"고 말할 근거도 없다.
        # 그 경우엔 빈 학기가 남아 있는 한 계속 채우게 둔다 — 예전 동작이다.
        still_to_fill = bool(unmet) or total_short > 0 or not self.requirements_known

        if rejected_count:
            next_action = (
                "rejected 과목의 사유를 보고 배치 가능한 다른 학기로 옮겨 "
                "propose_term_plan을 한 번 더 호출해라."
            )
        elif unmet and room:
            next_action = (
                f"아직 {total_unmet:g}학점이 미배정이고 학기 여유가 {total_room:g}학점 남았다. "
                f"미배정 이수구분({', '.join(u['category_name'] for u in unmet)})으로 "
                "search_courses를 여유 있는 학기별로 다시 호출해 후보를 더 모은 뒤, "
                "**추가로 넣을 과목만** 담아 propose_term_plan을 한 번 더 호출해라. "
                "이미 accepted된 과목은 다시 넣지 마라(중복으로 거절된다). "
                "그러고도 남는 학점이 있으면 finish_response에서 몇 학점이 미배정인지 밝혀라."
            )
        elif unmet:
            next_action = (
                f"{total_unmet:g}학점이 미배정인데 남은 학기에 여유 학점이 없다. "
                "더 넣지 말고, finish_response에서 졸업까지 학점이 모자란다는 사실과 "
                "부족한 이수구분·학점을 그대로 알려라."
            )
        elif total_short > 0:
            next_action = (
                f"이수구분별 잔여는 없지만 졸업 총 이수학점이 {total_short:g}학점 남았다"
                "(학과 요건의 이수구분 합보다 총요구학점이 큰 경우다 — 사범대 교직학점 등). "
                "여유 있는 학기에 과목을 더 담아 propose_term_plan을 한 번 더 호출해라. "
                "후보를 더 못 찾겠으면 몇 학점이 남는지 finish_response에서 밝혀라."
            )
        elif self.requirements_known:
            next_action = (
                "졸업요건이 모두 충족됐다(이수구분별 잔여 0 + 총 이수학점 충족). "
                "**학기를 더 채우지 마라** — 남은 학기에 여유 학점이 있어도 졸업에 필요 "
                "없는 과목을 억지로 넣을 이유가 없다. finish_response에서 학기별 계획을 "
                "정리하고, 요건이 다 채워진다는 것과 각 학기가 몇 학점인지 알려라. "
                "더 듣고 싶으면 말해달라고 덧붙여라."
            )
        else:
            next_action = (
                "이 학생의 졸업요건 기준을 숫자로 확인할 수 없다(학과 요건 행이 없거나 "
                "활성 학적이 등록되지 않았다). 남은 학기가 비어 있으면 계속 채우되, "
                "지금까지 제안한 계획을 finish_response에서 정리할 때 **요건 충족 여부는 "
                "확인할 수 없다는 것을 그대로 밝혀라.** 채워졌다고 말하지 마라."
            )

        # 되돌림 게이트용 상태.
        #
        # **기준은 "학기가 꽉 찼는가"가 아니라 "졸업요건이 남았는가"다.** 요건을 다
        # 채웠으면 남은 학기에 여유가 있어도, 심지어 한 학기가 통째로 비어 있어도
        # 되돌리지 않는다 — 졸업에 필요 없는 과목을 억지로 채우게 만들 이유가 없다.
        # (예전에는 `empty_terms`만으로도 발동해서, 요건이 다 충족된 학생에게도
        #  "2027년 2학기가 비어 있으니 채워라"라고 밀어붙였다.)
        #
        # 빈 학기 목록은 그대로 들고 간다. 요건이 남아 있을 때 "N학점 미배정"보다
        # "2027년 1학기가 비어 있다"가 훨씬 구체적인 지시라 후속 호출에서 실제로
        # 채워지기 때문이다(실측에서 LLM이 `course_ids: []`인 빈 학기를 넣고 넘어간
        # 적이 있다).
        empty_terms = [
            f"{t['planned_year']}년 {t['planned_semester']}({t['planned_grade']}학년)"
            for t in self._remaining_terms()
            if t["already_planned_credits"] <= 0
        ]
        self.plan_gap = (
            {
                "unmet_credits": round(total_unmet, 1),
                "unmet_categories": [u["category_name"] for u in unmet],
                "remaining_total_credits_after_plan": self.remaining_total_after_plan,
                "terms_with_room": room,
                "empty_terms": empty_terms,
            }
            if still_to_fill and (room or empty_terms)
            else None
        )

        return {
            "terms": term_results,
            # 이번 턴에 제안된 **전부**를 학기별로 모은 최종 상태. terms의 accepted는
            # 이번 호출분만 담기니, 여러 번 호출한 뒤 답변을 쓸 때는 이걸 그대로 옮겨라.
            "plan_so_far": self._plan_so_far(),
            # 남은 학기 **전부**의 최신 합계. terms에는 이번 호출에서 건드린 학기만 담기니,
            # 2차 호출 뒤에 답변을 쓸 때는 이 값을 봐야 학기별 총 학점이 맞는다.
            "term_totals_after": [
                {
                    "planned_year": t["planned_year"],
                    "planned_semester": t["planned_semester"],
                    "planned_grade": t["planned_grade"],
                    "total_credits": t["already_planned_credits"],
                }
                for t in self._remaining_terms()
            ],
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "requirement_coverage": coverage,
            "unmet_categories_after_plan": unmet,
            # 이수구분별 잔여가 0이어도 총 이수학점이 남을 수 있다(요건 행의 이수구분
            # 합 < 총요구학점인 학과). `unmet_categories_after_plan`만 보고 "다 채웠다"고
            # 판단하지 마라. None이면 기준을 몰라서 계산 못 한 것이다.
            "remaining_total_credits_after_plan": self.remaining_total_after_plan,
            "terms_with_room": room,
            "next_action": next_action,
            "hint": (
                "finish_response에는 accepted 과목만 적고, requirement_coverage의 "
                "remaining_after_plan이 0이 아닌 이수구분은 아직 남았다고 밝혀라. "
                "먼저 next_action을 따라라."
            ),
        }

    def _plan_so_far(self) -> list[dict]:
        """이번 턴에 제안된 create를 학기별로 모은 최종 상태.

        propose_term_plan을 여러 번 부르면 각 호출의 `accepted`는 그 호출분만 담는다.
        LLM이 마지막 호출 결과만 보고 답변을 쓰면 앞서 성공한 학기를 "확정 없음"이라고
        적는다(2026-08-20 실측). 답변에 옮겨 적을 단일 출처를 준다.
        """
        by_term: dict[tuple[str | None, str | None], dict] = {}
        for change in self.pending_changes:
            if change.action != "create" or change.course_id is None:
                continue
            course = self.db.get(Course, change.course_id)
            if course is None:
                continue
            key = (change.planned_year, change.planned_semester)
            slot = by_term.setdefault(key, {
                "planned_year": change.planned_year,
                "planned_semester": change.planned_semester,
                "planned_grade": change.planned_grade,
                "courses": [],
                "total_credits": 0.0,
            })
            credits = float(course.credits) if course.credits is not None else 0.0
            slot["courses"].append({
                "course_id": course.id,
                "course_name": course.course_name,
                "category": course.category,
                "credits": credits,
            })
            slot["total_credits"] += credits
        return [by_term[k] for k in sorted(by_term, key=lambda k: (k[0] or "", k[1] or ""))]

    def _requirement_coverage(self) -> list[dict]:
        """이번 턴에 제안한 과목들을 다 이수하면 주전공 이수구분별로 얼마가 남는지.

        판정은 전부 규칙 기반이다 — LLM은 이 숫자를 받아 설명만 한다.
        (compute_graduation_progress의 잔여 학점 - 이번 턴 제안 과목의 이수구분별 학점)
        """
        progresses = compute_graduation_progress(
            self.db, self.user.id, program_types={"primary"}
        )
        if not progresses:
            self.requirements_known = False
            self.remaining_total_after_plan = None
            return []
        program = progresses[0]
        # 학과 요건 행이 없으면(`requirement_found=False`) 잔여 학점이 전부 None이라
        # "미충족 0"과 "판단 불가"가 구분되지 않는다. 그 둘을 섞으면 요건을 모르는
        # 학생에게 "요건을 다 채웠다"고 말하게 된다.
        # 총요구학점을 모르면 "모두 충족"을 주장할 수 없다 — 이수구분 잔여가 0이어도
        # 총학점 축이 통째로 빠진 채 판정하게 된다(사범대처럼 그 축에만 남는 학점이 있다).
        # 운영 DB의 primary 요건 126행은 전부 총요구학점이 있지만, 없는 행이 들어오면
        # 조용히 "다 채웠다"가 되는 게 아니라 "확인할 수 없다"로 떨어져야 한다.
        self.requirements_known = program.required_total_credits is not None
        proposed: dict[str, float] = {}
        proposed_total = 0.0
        for ch in self.pending_changes:
            if ch.action != "create" or ch.course_id is None:
                continue
            course = self.db.get(Course, ch.course_id)
            if course is None:
                continue
            # 요건 라벨(성적표 어휘)과 `courses.category`(수강편람 어휘)가 교양에서
            # 겹치지 않는다 — 정규화 없이 이름으로 맞추면 교양 과목을 아무리 계획해도
            # 교양 잔여가 1학점도 안 줄어들어, "요건 충족" 상태에 영영 도달하지 못한다.
            key = requirement_category_for_course(course.category) or "미분류"
            credits = float(course.credits or 0)
            proposed[key] = proposed.get(key, 0.0) + credits
            proposed_total += credits

        # 총 이수학점 요건. **카테고리 합만 보면 안 된다** — 운영 DB의 primary 요건
        # 126행 중 17행(사범대 전체)이 카테고리 합 < 총요구학점이고, 그 차이 22학점이
        # 교직이다. 카테고리를 다 채워도 총학점이 남는데 "다 충족됐다"고 말하게 된다
        # (엔진은 같은 호출에서 satisfied=False라고 판정하고 있다).
        remaining_total = (
            float(program.remaining_total_credits)
            if program.remaining_total_credits is not None
            else None
        )
        self.remaining_total_after_plan = (
            round(max(remaining_total - proposed_total, 0.0), 1)
            if remaining_total is not None
            else None
        )

        out = []
        for category in program.categories:
            remaining = (
                float(category.remaining_credits)
                if category.remaining_credits is not None
                else None
            )
            planned = proposed.get(category.category_name, 0.0)
            out.append({
                "category_name": category.category_name,
                "remaining_before_plan": remaining,
                "planned_in_this_turn": planned,
                "remaining_after_plan": (
                    round(max(remaining - planned, 0.0), 1) if remaining is not None else None
                ),
            })
        # 요건 카테고리에 없는데 제안된 이수구분(예: 학과 카탈로그 태그가 다른 경우)도 노출
        known = {c.category_name for c in program.categories}
        for key, planned in proposed.items():
            if key not in known:
                out.append({
                    "category_name": key,
                    "remaining_before_plan": None,
                    "planned_in_this_turn": planned,
                    "remaining_after_plan": None,
                })
        return out

    def dispatch(self, name: str, tool_input: dict) -> dict:
        handler = getattr(self, name, None)
        if handler is None:
            return {"error": f"알 수 없는 도구: {name}"}
        return _safe_call(handler, tool_input)


# LLM 컨텍스트로 실을 최근 대화 턴 수. DB에는 전부 저장하고 유저는 UI에서 다 볼
# 수 있지만, LLM에 매 요청마다 다 실으면 오래된 실패 컨텍스트(예: "공학작문 못 찾음")가
# 남아 후속 응답을 오염시킨다(2026-08-10 관찰). 최근 N턴만 유지해서 참조 해석
# ("아까 그거", "다른 걸로") 은 살리면서 오래된 오염은 잘라낸다.
# N=6이면 대략 3 exchange(user+assistant × 3).
_LLM_HISTORY_WINDOW = 6


def _load_history(db: Session, session_id: int) -> list[CourseRoadmapChatMessage]:
    """LLM 프롬프트에 실을 최근 N턴. DB 전체를 순회하지 않고 desc + limit 후 뒤집는다."""
    latest = db.scalars(
        select(CourseRoadmapChatMessage)
        .where(CourseRoadmapChatMessage.session_id == session_id)
        .order_by(CourseRoadmapChatMessage.id.desc())
        .limit(_LLM_HISTORY_WINDOW)
    ).all()
    return list(reversed(latest))


def _program_required_credits(db: Session, program: UserAcademicProgram) -> int | None:
    """이 학적 프로그램의 졸업 요구 총학점. 없으면 None.

    프로필 블록에 실어 LLM이 프로그램 유형만 보고 학점을 추측하지 않게 한다 —
    융합·연계전공은 21(SW융합트랙)·36(복수전공)·42·48(정식 연계전공)로 갈리는데,
    이름만으로는 구분이 안 돼 실제로 오인이 관측됐다.
    """
    from app.domains.academics.graduation_progress import _find_requirement

    requirement = _find_requirement(db, program)
    return requirement.required_total_credits if requirement else None


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
        # 키는 UserAcademicProgram.program_type의 실제 값과 정확히 맞춰야 한다
        # (auth._VALID_PROGRAM_TYPES). 예전엔 "double"/"teaching"처럼 존재하지 않는
        # 키가 적혀 있어서 복수전공 학생이 LLM에게 "dual: OO학과"로 전달됐다.
        # SW융합트랙·연계전공·융합전공은 전부 interdisciplinary로 들어온다.
        label = _PROGRAM_TYPE_LABELS.get(p.program_type or "", p.program_type or "unknown")
        line = f"  - {label}: {dept_name}"
        if major_name:
            line += f" / {major_name}"
        if p.curriculum_year:
            line += f" ({p.curriculum_year} 교육과정)"
        # 요구 학점을 여기 같이 실어준다. 이게 없으면 LLM이 도구를 호출하고도 "48학점
        # 연계전공"을 21학점 SW융합트랙으로 오인하는 일이 있었다 (골든 케이스 06).
        # 프로그램 유형만으로는 21/36/42/48이 구분되지 않기 때문이다.
        required = _program_required_credits(db, p)
        if required is not None:
            line += f" — 요구 {required}학점"
        program_lines.append(line)
    if not program_lines:
        program_lines.append("  - (등록된 학적 프로그램 없음)")

    completed = db.scalars(
        select(StudentCourseRecord).where(StudentCourseRecord.user_id == user.id)
    ).all()
    completed_by_cat: dict[str | None, list[StudentCourseRecord]] = {}
    for r in completed:
        completed_by_cat.setdefault(r.category, []).append(r)
    completed_lines: list[str] = []
    for cat in ["전공기초", "전공필수", "전공선택", "교양필수", "교양선택", "일반선택"]:
        recs = completed_by_cat.get(cat)
        if recs:
            names = sorted({r.raw_course_name for r in recs})
            completed_lines.append(f"  - {cat}: {', '.join(names)}")
    if not completed_lines:
        completed_lines.append("  - (성적표 이수기록 없음 — 신입 또는 미동기화)")

    # 균형교양 세부영역별 이수/미이수 요약. portal_sync가 One-Stop 판정으로 category를
    # 세부영역명으로 override 한 rows만 집계된다 — 미이수 rows는 여전히 '교양선택'이라
    # 여기서는 안 잡히고, 아래 "미이수 영역" 목록에 자동으로 남는다.
    balanced_lines: list[str] = []
    missing_areas: list[str] = []
    for area in _BALANCED_LIBERAL_AREAS:
        recs = completed_by_cat.get(area)
        if recs:
            total_credits = sum(float(r.credits) for r in recs if r.credits is not None)
            names = sorted({r.raw_course_name for r in recs})
            credit_str = f"{total_credits:g}학점" if total_credits else "학점 미상"
            balanced_lines.append(f"  - {area}: {credit_str} 이수 ({', '.join(names)})")
        else:
            missing_areas.append(area)
    if balanced_lines:
        balanced_block = "\n".join(balanced_lines)
    else:
        balanced_block = "  - (이수한 균형교양 세부영역 없음 — 또는 포털 동기화 전이라 세부영역이 붙지 않은 상태)"
    if missing_areas:
        missing_block = ", ".join(missing_areas)
        # 예시 문구용: 실제 미이수 영역 앞 2개만 슬래시로 이어 붙인다.
        # 상수 앞 3개를 하드코딩하던 옛 버전은 이미 이수한 영역을 예시로 드는 어색함이 있었다.
        missing_example = "'" + "/".join(missing_areas[:2]) + "'"
    else:
        missing_block = f"(없음 — {len(_BALANCED_LIBERAL_AREAS)}개 세부영역 모두 최소 1과목 이수)"
        missing_example = "'미이수 영역'"

    career = user.career_goal.strip() if user.career_goal else ""
    career_line = career if career else "(등록된 진로 목표 없음 — 프로필에서 입력하면 반영된다)"

    # AI융합트랙 안내 — 학생 학과가 14개 대상 학과 중 하나면 이수 가능. 이미 등록한
    # 트랙이 있으면 진도 요약, 없고 대상 학과면 "이수 가능하다" 안내.
    ai_track_block = ""
    if user.department_id is not None:
        track_grs = find_ai_tracks_for_department(db, user.department_id)
        if track_grs:
            enrolled_major_ids = {
                p.major_id for p in programs
                if p.program_type == "interdisciplinary"
                and is_active_program_status(p.status)
            }
            lines = []
            for g in track_grs:
                m = db.get(_Major, g.major_id) if g.major_id else None
                tname = m.name if m else "?"
                enrolled = g.major_id in enrolled_major_ids
                lines.append(f"  - {tname}: {'[이수 등록됨]' if enrolled else '[미등록]'}")
            ai_track_block = f"""

- **AI융합트랙 (졸업요건 아님, 인증 프로그램)**:
{chr(10).join(lines)}
  → 학과 전공과목 12~15학점 + AI융합 공통교과목 6~9학점 = 총 21학점 이수 시
    졸업증명서에 이수 과정명 표기.
    **이 학생은 대상 학과다. 로드맵을 처음 짜주거나 진로 방향을 이야기할 때 한 번은
    먼저 알려줘라** — 학생이 물어볼 때까지 기다리지 마라. 트랙이 있는 줄 모르는 학생이
    대부분이다. 다만 매 턴 반복하지는 말고, 졸업요건 안내를 밀어내지도 마라(졸업요건이
    우선이다).
    "들을 만한 프로그램 있냐"류 질문에는 **반드시 `get_available_tracks`를 호출해서**
    답해라 — 위 목록만 보고 "없다"고 답한 사고가 있었다.
    미등록 상태면 "프로필의 AI융합트랙 등록에서 시작할 수 있다"고 안내하고, 이미
    등록됐으면 `get_program_evaluations`로 진도를 알려줘라.
    **트랙 미이수는 졸업에 영향 없다는 점을 항상 함께 명시해라.**"""

    return f"""[이 학생 프로필 — 매 추천 판단 시 이 정보를 함께 고려해라]

- **진로 목표**: {career_line}
  → 전공선택·교양선택 후보가 여러 개일 때 이 방향에 맞는 과목(예: 진로가 "시스템 프로그래밍"이면
    운영체제·컴퓨터네트워크·임베디드 계열, "AI"면 머신러닝·딥러닝·데이터 계열)을 우선해라.
    다만 부족한 이수구분을 채우는 게 최우선이고, 진로 정합성은 후보 사이 우선순위 지표다.

- **학적 프로그램(전공/부전공 등)**:
{chr(10).join(program_lines)}
  → 복수전공/부전공/연계전공이 있으면 **그 프로그램의 요구 학점도 반드시 함께 안내해라**.
    위에 학점이 적혀 있으면 그게 그 프로그램의 졸업 요구 학점이다 — 주전공 요건만 답하고
    넘어가면 학생이 다전공 이수 계획을 통째로 놓친다.
    `get_graduation_progress`는 **활성 프로그램 전부**(주전공·부전공·복수전공·융합)의 남은
    학점을 함께 돌려준다. 그룹별 세부 규칙까지 필요하면 `get_program_evaluations`를 더 불러라.

- **이수 완료 과목(성적표 원문 표기, 학과 커리큘럼 표기와 차이 있을 수 있음)**:
{chr(10).join(completed_lines)}
  → 이 목록에 있는 과목명과 정확히 일치하는 create는 도구 단에서 거절된다. 표기가
    다르게 보이는 유사명(예: 성적표 "데이터구조" ↔ 교육과정 "자료구조")은 네가 임의로
    같은 과목이라 단정하지 말고, 후보에 뜨면 사용자에게 "같은 과목인가요?"라고 되물어
    확인 후 다음 턴에 제외해라. 우리 데이터로 동치 여부를 확인할 방법이 없다.

- **균형교양 세부영역 이수 현황(One-Stop 학교 판정 결과 기반, {len(_BALANCED_LIBERAL_AREAS)}개 영역 중)**:
{balanced_block}
  → 미이수 세부영역: {missing_block}
  → 균형교양은 총 학점만 채우는 게 아니라 **세부영역 골고루** 이수해야 졸업요건이 인정된다.
    총 학점(get_graduation_progress의 '교양선택')이 남아 있으면 우선 **미이수 세부영역**을
    채우는 방향으로 추천해라. 이미 이수한 영역에 또 몰아넣지 마라. search_courses로
    후보를 찾을 때 그 세부영역에 속하는 과목인지 description·과목명으로 판단하고,
    finish_response에서도 "네가 아직 안 든 {missing_example} 영역 보강 차원에서 이
    과목을 추천한다"처럼 근거를 밝혀라. 세부영역 판정 자체는 학교 판정 결과라 네가
    뒤집지 말고 그대로 신뢰해라.
{ai_track_block}
"""


def _generate_session_title(message: str) -> str:
    """첫 메시지에서 화면에 보일 짧은 제목을 만든다.

    별도 LLM 호출을 피하려 규칙 기반으로 앞부분을 뽑는다: 개행/불필요 공백 제거 후
    앞 20자를 자르고, 잘렸으면 말줄임표를 붙인다. 실제 사용성 데이터가 쌓이면
    첫 응답의 요약을 title로 승격시키는 식으로 확장 가능.
    """
    stripped = " ".join(message.strip().split())
    if not stripped:
        return "새 대화"
    return stripped[:20] + ("…" if len(stripped) > 20 else "")


def _get_or_create_default_session(
    db: Session, roadmap: CourseRoadmap, message: str
) -> "CourseRoadmapChatSession":
    """session_id가 오지 않은 요청을 위해 기본 세션을 확보한다.

    로드맵에 세션이 하나도 없으면 첫 메시지 기반으로 새 세션을 만든다. 이미
    있으면 가장 최근 세션을 이어 쓴다 — 세션 도입 이전에 만들어진 대화 흐름의
    호환성을 위한 폴백이다.
    """
    latest = db.scalars(
        select(CourseRoadmapChatSession)
        .where(CourseRoadmapChatSession.roadmap_id == roadmap.id)
        .order_by(CourseRoadmapChatSession.id.desc())
    ).first()
    if latest is not None:
        return latest
    session = CourseRoadmapChatSession(roadmap_id=roadmap.id, title=_generate_session_title(message))
    db.add(session)
    db.flush()
    return session


def create_chat_session(db: Session, roadmap: CourseRoadmap, title: str | None = None) -> "CourseRoadmapChatSession":
    session = CourseRoadmapChatSession(roadmap_id=roadmap.id, title=(title or "새 대화"))
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def list_chat_sessions(db: Session, roadmap: CourseRoadmap) -> list["CourseRoadmapChatSession"]:
    return db.scalars(
        select(CourseRoadmapChatSession)
        .where(CourseRoadmapChatSession.roadmap_id == roadmap.id)
        .order_by(CourseRoadmapChatSession.id.desc())
    ).all()


def delete_chat_session(db: Session, roadmap: CourseRoadmap, session_id: int) -> bool:
    session = db.get(CourseRoadmapChatSession, session_id)
    if session is None or session.roadmap_id != roadmap.id:
        return False
    # 세션에 속한 메시지 먼저 삭제(FK 제약). pending_changes는 로드맵 전역이라 건드리지 않는다.
    db.query(CourseRoadmapChatMessage).filter(
        CourseRoadmapChatMessage.session_id == session_id
    ).delete(synchronize_session=False)
    db.delete(session)
    db.commit()
    return True


def _fallback_summary(db: Session, pending: list[PendingRoadmapChange]) -> str:
    """LLM이 finish_response도, 마무리 요약도 못 낸 턴의 최후 폴백.

    쌓인 제안을 학기별로 나열하기만 한다 — 판정도 추천 문장도 없다.
    """
    if not pending:
        return "죄송해요, 답변을 정리하지 못했어요. 다시 한 번 말씀해 주세요."

    by_term: dict[tuple[str | None, str | None], list[str]] = {}
    for change in pending:
        if change.action != "create" or change.course_id is None:
            continue
        course = db.get(Course, change.course_id)
        if course is None:
            continue
        credits = f"{float(course.credits):g}학점" if course.credits is not None else "학점 미상"
        by_term.setdefault((change.planned_year, change.planned_semester), []).append(
            f"{course.course_name}({credits}, {course.category or '이수구분 미상'})"
        )
    if not by_term:
        return "죄송해요, 답변을 정리하지 못했어요. 다시 한 번 말씀해 주세요."

    lines = ["답변 정리 중 문제가 있어 제안 내용만 그대로 보여드릴게요.", ""]
    for (year, semester), names in sorted(by_term.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or "")):
        lines.append(f"## {year}년 {semester}")
        lines.extend(f"- {name}" for name in names)
        lines.append("")
    lines.append("이 변경을 반영할까요?")
    return "\n".join(lines)


def run_roadmap_chat(
    db: Session,
    user: User,
    roadmap: CourseRoadmap,
    message: str,
    session_id: int | None = None,
) -> dict:
    """사용자 메시지를 처리하고, AI 답변 + 이번 턴에 만들어진 pending change 목록을 반환한다.

    session_id를 명시하지 않으면 로드맵의 가장 최근 세션을 이어 쓰거나, 세션이
    하나도 없으면 이번 메시지를 기반으로 새 세션을 만든다.

    이 함수는 course_roadmap_items를 절대 쓰지 않는다 — 실제 반영은
    apply_pending_changes()가 사용자 승인 후에 한다.
    """
    if session_id is not None:
        session = db.get(CourseRoadmapChatSession, session_id)
        if session is None or session.roadmap_id != roadmap.id:
            raise ValueError(f"session_id={session_id}는 이 로드맵의 세션이 아닙니다")
    else:
        session = _get_or_create_default_session(db, roadmap, message)

    # Langfuse trace: 이 대화 턴 전체(DB 작업 포함)를 하나의 agent-typed root observation으로
    # 감싼다. root 시점을 함수 초입으로 앞당겨야 UI latency가 실제 소요시간과 일치한다.
    from app.ai.llm.langfuse_callback import observe_agent_call

    with observe_agent_call(
        agent="roadmap_chat",
        user_id=user.id,
        session_id=session.id,
        user_message=message,
    ) as trace:
        # 페이즈 1: 사용자 메시지 저장 (DB write).
        with trace.span("persist_user_message"):
            db.add(
                CourseRoadmapChatMessage(
                    roadmap_id=roadmap.id,
                    session_id=session.id,
                    role="user",
                    content=message,
                )
            )
            db.flush()

        # 페이즈 2: 히스토리 로드 + 학생 컨텍스트 빌드 + 조건부 규칙 assembly (DB read heavy).
        with trace.span("load_history_and_context", as_type="retriever"):
            history = _load_history(db, session.id)
            context_block = _build_student_context_block(db, user)
            # message를 넘기는 이유: 범위 한정 요청("그것만요") 규칙은 학생 DB 상태가
            # 아니라 이번 턴 문장으로만 판정된다.
            base_prompt, applied_rules = _build_system_prompt(db, user, message)

        system_prompt = base_prompt + "\n\n" + context_block
        messages: list = [SystemMessage(content=system_prompt)]
        for m in history:
            if m.role == "user":
                messages.append(HumanMessage(content=m.content))
            else:
                messages.append(AIMessage(content=m.content))

        llm = _build_llm()
        ctx = _ToolContext(db, user, roadmap)

        # 대시보드 필터·breakdown용 metadata (개인정보 아님).
        primary_prog = db.scalars(
            select(UserAcademicProgram).filter_by(user_id=user.id, program_type="primary")
        ).first()
        has_non_primary = db.scalar(
            select(func.count(UserAcademicProgram.id)).where(
                UserAcademicProgram.user_id == user.id,
                UserAcademicProgram.program_type != "primary",
            )
        )
        trace.add_metadata({
            "roadmap_id": roadmap.id,
            "history_length": len(history),
            "admission_type": user.admission_type,
            "curriculum_year": primary_prog.curriculum_year if primary_prog else None,
            "has_non_primary_program": bool(has_non_primary),
            "model": settings.ROADMAP_AGENT_MODEL,
            # 조건부 규칙 assembly 관측용 — Langfuse UI에서 어떤 학생에게 어떤 규칙이
            # 얼마나 노출됐는지 breakdown 가능. fatigue vs coverage 트레이드오프 트래킹.
            "applied_conditional_rules": applied_rules,
            "system_prompt_chars": len(system_prompt),
        })

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
        iterations_used = 0
        non_finish_tool_calls = 0
        # 미배정 학점을 남긴 채 끝내려는 finish_response를 되돌리는 건 턴당 한 번뿐이다.
        finish_gate_used = False
        # "졸업까지 남은 학기 전부" 요청으로 판정된 턴인지 (조건부 규칙 판정 결과 재사용).
        expects_term_plan = "full_horizon_request" in applied_rules
        for _ in range(MAX_TOOL_ITERATIONS):
            iterations_used += 1
            ai_msg: AIMessage = llm_required.invoke(messages, config=trace.config)
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
                    gate_reason = None
                    if (
                        not finish_gate_used
                        and iterations_used <= MAX_TOOL_ITERATIONS - _FINISH_GATE_RESERVE
                    ):
                        if (
                            expects_term_plan
                            and not ctx.term_plan_called
                            # 남은 학기가 없으면 "remaining_terms에 있는 학기별로
                            # 채워라"가 실행 불가능한 지시다. 성적표 미업로드 사용자는
                            # 목록이 비므로(근거가 없으면 지어내지 않는다) 여기 걸린다.
                            and ctx._remaining_terms()
                        ):
                            # "4학년 2학기까지 어떻게 들어야 해?"에 제안을 하나도 만들지
                            # 않고 "바로 편성 들어갈까요?"라고 되묻고 끝낸 실측이 있다
                            # (2026-08-20). 제안은 승인 전까지 저장되지 않으므로 미리
                            # 되묻는 건 한 턴을 통째로 버리는 것이다.
                            gate_reason = (
                                "사용자는 남은 학기 전부를 계획해 달라고 했는데 이번 턴에 "
                                "propose_term_plan을 한 번도 부르지 않았다. 먼저 하겠냐고 "
                                "되묻지 마라 — 제안은 사용자가 승인해야만 저장되니 되묻는 건 "
                                "한 턴을 버리는 것이다. get_roadmap_items의 remaining_terms에 "
                                "있는 학기별로 search_courses로 후보를 모아 propose_term_plan을 "
                                "호출한 뒤에 finish_response 해라."
                            )
                        elif expects_term_plan and ctx.plan_gap is not None:
                            # propose_term_plan은 불렀는데 채울 수 있는 학기 여유를 남겨둔
                            # 채 끝내려는 경우다. 도구 응답의 next_action으로 "한 번 더
                            # 채워라"라고 지시해도 LLM은 그 지시를 사용자에게 **설명만 하고**
                            # 끝냈다(2026-08-20 실측: 전공선택 23학점을 남긴 채 "다음 단계로
                            # 더 채우는 플랜을 만들게요"로 종료). 그래서 프롬프트가 아니라
                            # 루프에서 첫 종료를 되돌린다. 되돌림은 턴당 한 번뿐이다 —
                            # 후보가 정말 없을 때 무한 루프가 되면 안 된다.
                            #
                            # `expects_term_plan`으로 가드한다. plan_gap의 empty_terms는
                            # 사용자가 요청한 학기가 아니라 **남은 학기 전부**를 보므로,
                            # 이 조건이 없으면 "다음 학기만 짜줘"에도 "나머지 학기도
                            # 채워라"라고 되돌린다 — narrow_scope가 full_horizon을 이기게
                            # 만든 프롬프트 쪽 결정이 여기서 뚫린다.
                            gap = ctx.plan_gap
                            if gap["empty_terms"]:
                                gate_reason = (
                                    f"{', '.join(gap['empty_terms'])}에 계획된 과목이 "
                                    "하나도 없다. 사용자는 남은 학기 **전부**를 계획해 "
                                    "달라고 했다. 그 학기의 개설 학기에 맞는 과목을 "
                                    "search_courses로 찾아(1학기 슬롯이면 semester='1학기', "
                                    "2학기 슬롯이면 '2학기') `course_ids`를 채운 뒤 "
                                    "propose_term_plan을 한 번 더 호출해라. "
                                    "`course_ids`가 빈 학기를 넣는 건 계획한 게 아니다. "
                                    "그 다음에 finish_response 해라."
                                )
                            elif not gap["unmet_categories"]:
                                # 이수구분 잔여는 0인데 게이트가 걸린 경우다. 총 이수학점이
                                # 남았거나(요건 행의 이수구분 합 < 총요구학점) 요건 기준
                                # 자체를 모른다. 아래 문구를 그대로 쓰면 "아직 0학점이
                                # 미배정이다()"라는 자가당착 지시가 나간다.
                                total_left = gap.get("remaining_total_credits_after_plan")
                                gate_reason = (
                                    (
                                        f"이수구분별 잔여는 없지만 졸업 총 이수학점이 "
                                        f"{total_left:g}학점 남았다."
                                        if total_left
                                        else "이 학생의 졸업요건 기준을 숫자로 확인할 수 없어 "
                                        "무엇이 남았는지 계산하지 못했다."
                                    )
                                    + f" 여유 있는 학기: "
                                    f"{json.dumps(gap['terms_with_room'], ensure_ascii=False)}. "
                                    "지금 끝내지 말고 그 학기에 담을 과목을 search_courses로 "
                                    "찾아 propose_term_plan을 한 번 더 호출해라. 그 다음에 "
                                    "finish_response 해라. 후보를 더 못 찾겠으면 그대로 다시 "
                                    "finish_response 하되, 요건 충족 여부에 대해 확인된 것만 "
                                    "적어라."
                                )
                            else:
                                gate_reason = (
                                    f"아직 {gap['unmet_credits']:g}학점이 미배정이다"
                                    f"({', '.join(gap['unmet_categories'])}). "
                                    f"여유 있는 학기: "
                                    f"{json.dumps(gap['terms_with_room'], ensure_ascii=False)}. "
                                    "지금 끝내지 말고 그 이수구분으로 search_courses를 다시 "
                                    "호출해 후보를 모은 뒤, **추가로 넣을 과목만** 담아 "
                                    "propose_term_plan을 한 번 더 호출해라. 그 다음에 "
                                    "finish_response 해라. 후보를 더 못 찾겠으면 그대로 다시 "
                                    "finish_response 하되, 몇 학점이 미배정으로 남는지 "
                                    "답변에 명시해라."
                                )
                    if gate_reason is not None:
                        finish_gate_used = True
                        result = {"delivered": False, "error": gate_reason}
                    else:
                        final_text = arguments.get("message", "")
                        result = {"delivered": True}
                        finished = True
                else:
                    non_finish_tool_calls += 1
                    with trace.span(f"tool:{name}", as_type="tool", input=arguments) as tool_span:
                        result = ctx.dispatch(name, arguments)
                        if tool_span is not None:
                            tool_span.update(output=result)
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
                    ],
                    config=trace.config,
                )
                final_text = wrapup.content if isinstance(wrapup.content, str) else ""
            except Exception:  # noqa: BLE001 - 마무리 요약 실패는 폴백 문구로 넘어간다
                final_text = ""
            if not final_text:
                # LLM 요약까지 실패해도, 이번 턴에 실제로 쌓인 제안이 있으면 그것만은
                # 사실 그대로 보여준다. 19건을 제안해놓고 "죄송해요"만 내보내면 사용자는
                # 승인 대기에 뭐가 올라왔는지 알 수 없다.
                final_text = _fallback_summary(db, ctx.pending_changes)

        # 페이즈 3: assistant 메시지 저장 (DB write + commit).
        with trace.span("persist_assistant_message"):
            db.add(
                CourseRoadmapChatMessage(
                    roadmap_id=roadmap.id,
                    session_id=session.id,
                    role="assistant",
                    content=final_text,
                )
            )
            db.commit()

        trace.set_output({
            "reply": final_text,
            "pending_changes_count": len(ctx.pending_changes),
        })
        # 대시보드 시계열/분포 차트용 정량 스코어.
        trace.score("finished_with_tool", finished)  # finish_response 정상 호출률
        trace.score("iterations_used", iterations_used)  # 평균/분포
        trace.score(
            "iteration_efficiency",
            round(1 - (iterations_used - 1) / max(MAX_TOOL_ITERATIONS - 1, 1), 3),
        )  # 0~1, 높을수록 짧게 끝남
        trace.score("tool_calls", non_finish_tool_calls)
        trace.score("pending_changes", len(ctx.pending_changes))

    return {
        "reply": final_text,
        "pending_changes": ctx.pending_changes,
        "session_id": session.id,
        # 아래 둘은 API 응답에는 안 쓰이고 평가 하니스(tests/eval)가 읽는다. timetable_chat의
        # 반환 형태와 맞춰 두 에이전트를 같은 기준으로 채점할 수 있게 한다.
        "finished": finished,          # finish_response로 정상 종료했는지 (폴백 요약이면 False)
        "iterations": iterations_used,  # LLM 왕복 횟수 (도구 호출 수 아님)
    }


def apply_pending_changes(
    db: Session, roadmap: CourseRoadmap, approved_ids: list[int], rejected_ids: list[int]
) -> dict:
    """사용자가 승인/거절한 pending change를 실제로 반영한다.

    승인된 항목만 course_roadmap_items에 create/update/delete로 반영하고,
    is_confirmed=true로 저장한다(승인 자체가 확정 행위라 이중 확정을 요구하지 않는다).
    거절된 항목은 그냥 status="rejected"로 남기고 버린다.
    """
    def _owned_item(db: Session, item_id: int | None, roadmap_id: int) -> CourseRoadmapItem | None:
        """이 로드맵에 속한 항목일 때만 돌려준다. 아니면 None.

        `change` 자체는 위에서 `change.roadmap_id != roadmap.id`로 걸러지지만,
        `change.item_id`는 그 검사에 포함되지 않는다. 지금은 propose_change가 제안을
        만들 때 항목 소유권을 확인하므로 남의 item_id가 담긴 행이 생기지 않지만,
        **승인은 남의 로드맵 항목을 수정/삭제하는 경로**라 한 겹 위에서만 지키기엔
        위험하다. 반영 직전에 다시 확인한다 (defense in depth).
        """
        if item_id is None:
            return None
        item = db.get(CourseRoadmapItem, item_id)
        if item is None or item.roadmap_id != roadmap_id:
            return None
        return item

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
                curriculum_semester=_curriculum_semester_for(
                    db, roadmap.user_id, change.planned_year, change.planned_semester
                ),
                planned_grade=change.planned_grade,
                reason=change.reason,
                source="ai",
                is_confirmed=True,
                program_type=change.program_type,
            )
            db.add(item)
        elif change.action == "update":
            item = _owned_item(db, change.item_id, roadmap.id)
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
                if change.planned_year is not None or change.planned_semester is not None:
                    # 달력 학기가 바뀌면 커리큘럼 학기도 다시 환산해야 한다.
                    item.curriculum_semester = _curriculum_semester_for(
                        db, roadmap.user_id, item.planned_year, item.planned_semester
                    )
                if change.planned_grade is not None:
                    item.planned_grade = change.planned_grade
                if change.program_type is not None:
                    item.program_type = change.program_type
                item.reason = change.reason
                item.source = "ai"
                item.is_confirmed = True
        elif change.action == "delete":
            item = _owned_item(db, change.item_id, roadmap.id)
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
