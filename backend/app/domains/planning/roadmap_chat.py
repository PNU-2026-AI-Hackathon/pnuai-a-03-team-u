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
from app.domains.academics.graduation_progress import compute_graduation_progress
from app.domains.academics.program_evaluator import evaluate_program
from app.domains.academics.models import GraduationRequirement, ProgramCourse, StudentCourseRecord, UserAcademicProgram
from app.domains.courses.models import Course
from app.domains.planning.models import (
    CourseRoadmap,
    CourseRoadmapChatMessage,
    CourseRoadmapChatSession,
    CourseRoadmapItem,
    PendingRoadmapChange,
)
from app.domains.users.admission import TRANSFER_ENTRY_GRADE, is_transfer
from app.domains.users.models import User

_DEFAULT_CURRICULUM_YEAR = 2026

MAX_TOOL_ITERATIONS = 8

# 균형교양 7개 세부영역. portal_sync._refine_liberal_area_categories가 One-Stop
# 졸업예정정보 판정을 근거로 student_course_records.category를 상위값('교양선택')에서
# 이 세부영역명으로 override 한다. 여기 목록은 One-Stop 원문("N영역 : 이름"에서 이름만)과
# 일치해야 한다 — 목록에 없는 이름이 들어오면 컨텍스트 요약에서 조용히 빠져 LLM이
# 미이수로 오인할 수 있다.
_BALANCED_LIBERAL_AREAS: tuple[str, ...] = (
    "사상과역사",
    "사회와문화",
    "문학과예술",
    "과학과기술",
    "건강과레포츠",
    "외국어",
    "융복합",
)


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
  필터로 좁혀서 호출해라. 이때 `grade` 필터는 걸지 마라.** 요청 학기가 4-1이든
  3-2든, 학생이 아직 못 들은 과목이 이전 학년(1·2학년)에도 남아 있을 수 있다.
  그 개설 학기(1·2학기·전학기)만 맞으면 학년이 낮은 과목도 후보로 유효하다 —
  grade 필터로 좁히면 이런 미이수분이 아예 후보에서 빠진다. 예: 다음 학기가
  3학년 2학기이면 `search_courses(query="", semester="2학기", category="전공선택")`
  처럼 학년은 열어두고 이수구분·학기만 걸어서 훑어라. 특정 키워드가 있으면 query에
  그 키워드를, 없으면 query를 비워두고 필터만으로 목록을 받아 그중 학생 상황에
  맞는 과목을 골라 propose_change 해라. 한 번 검색해서 결과가 부족하면 필터/키워드를
  바꿔서 다시 검색해라 — 첫 검색 결과가 애매하다고 "추천할 과목이 없다"고 답하지 마라.
- **다음 학기 추천 시 `get_graduation_progress`에서 `remaining_credits > 0`인 모든
  이수구분에 대해 각각 `search_courses`를 호출해라.** 전공만 훑고 교양은 건너뛰지
  마라. 예: 조회 결과 전공필수·전공선택·교양필수 세 곳에 남은 학점이 있다면 세 번
  다 호출해라:
  - `search_courses(query="", semester="2학기", category="전공필수")`
  - `search_courses(query="", semester="2학기", category="전공선택")`
  - `search_courses(query="", semester="2학기", category="교양필수")`
  결과에는 학생 학과의 모든 학년 개설 과목이 섞여 나온다. **아직 이수하지 않은 과목
  중에 이전 학년 권장 과목이 있으면 이번 학기로 배치하는 걸 우선순위에 둬라** —
  특히 전공필수/전공기초처럼 반드시 이수해야 하는 카테고리에서 미이수분이 남아 있으면
  요청 학기 권장 과목보다 먼저 채워라. 특히 **효원핵심교양·기초교양 같은 학과 지정
  교양(category="교양필수" 필터로 잡힌다)은 졸업요건이라 반드시 이수해야 하니 남은
  학점이 있으면 전공과 나란히 추천해라.** 전공선택 남은 학점이 훨씬 많더라도 교양필수
  3학점을 이번 학기에 안 넣으면 다음 학기 부담이 커진다.
- **균형교양은 총학점만이 아니라 세부영역별로 판단해라.** get_graduation_progress의
  '교양선택'에 남은 학점이 있어도, 이미 이수한 세부영역(사상과역사·사회와문화·문학과예술·
  과학과기술·건강과레포츠·외국어·융복합)에 또 몰아넣으면 졸업요건에서 인정 안 되는 학점이
  쌓인다. 시스템 프롬프트 뒤에 붙는 [이 학생 프로필] 블록의 "균형교양 세부영역 이수 현황"과
  "미이수 세부영역" 목록을 먼저 확인해서, **미이수 세부영역을 우선 채우는 방향**으로
  search_courses 후보를 고르고 finish_response에서 그 근거("네가 아직 안 든 XX영역 보강용")를
  밝혀라. 세부영역 판정은 학교 One-Stop 판정 결과라 신뢰하고 뒤집지 마라. 프로필 블록에
  세부영역 정보가 하나도 없으면(포털 미동기화) 그 사실을 알리고 우선 동기화를 안내해라 —
  세부영역 없이는 어느 영역이 부족한지 확정할 수 없다.
- search_courses 결과에 description(교과목개요)이 있으면 과목명만 보고 판단하지 말고
  그 내용을 실제로 읽고 학생의 진로/관심사와 맞는지 확인해라. 과목명에 키워드가 없어도
  description 내용상 관련 있는 과목일 수 있다(반대의 경우도 있다 — description이 없다고
  관련 없다고 단정하지는 마라, 그냥 참고 정보가 없는 것뿐이다).
- **이미 로드맵에 있는 과목(get_roadmap_items 결과의 course_id 목록)은 다시 create로 제안하지 마라 — 같은 과목이 두 번 만들어지는 걸 도구 단에서 거절한다.** 학기/학년만 옮기고 싶으면 그 항목의 `id`로 action='update'를 호출해라.
- **이미 이수한 과목(get_roadmap_items 결과의 `completed_courses`)은 다시 추천하지 마라.** 성적표에서 파싱된 이수내역은 `course_id` 매핑이 대부분 안 돼 있어 로드맵 중복 가드로는 잡히지 않는다. finish_response에서 언급하는 과목명이 `completed_courses`에 있는 이름과 겹치는지 반드시 이름 기준으로 재확인해라. 이수기록과 이름이 정확히 일치하는 create는 도구 단에서도 거절한다.
- **성적표 표기와 교육과정 표기가 다르게 보이는 유사명 과목은 네가 임의로 "같은 과목"이라고 판정하지 마라.** 예: 이수기록에 '데이터구조'가 있고 후보에 '자료구조'가 있을 때, 부산대에서 실제로 같은 과목인지 확인할 방법이 우리 데이터엔 없다. 이런 경우 자동으로 제외/포함시키지 말고, finish_response에서 사용자에게 **"성적표의 '데이터구조'가 교육과정표의 '자료구조'와 같은 과목이 맞나요? 맞으면 제외할게요"**처럼 되물어서 답을 받은 뒤 다음 턴에 그 과목을 제외해라. 사용자가 "같다"고 답한 유사명 짝은 이후 답변에서도 계속 제외 목록에 유지해라. 사용자가 "다르다/모르겠다"고 하면 그대로 후보에 유지해라 — 우리가 대신 판단하지 않는다.
- 기존 항목의 학기/학년을 바꾸고 싶으면 propose_change(action="update", item_id=...)를,
  항목을 빼고 싶으면 propose_change(action="delete", item_id=...)를 써라. 절대
  course_roadmap_items를 직접 바꿀 수 있는 방법은 없다 — 항상 이 제안 도구를 거친다.
- **너는 실제로 아무것도 저장하지 않는다.** propose_change는 "제안"만 만든다.
  finish_response 메시지 마지막에는 반드시 "이 변경을 반영할까요?"처럼 사용자 확인을
  구하는 문장을 넣고, 사용자가 승인해야만 실제로 반영된다는 걸 분명히 말해라.
- 학생이 이미 만족한 이수구분에는 무리하게 과목을 더 넣지 말고, 부족한 이수구분 위주로
  추천해라.
- **부전공·복수전공·SW융합트랙(program_type != 'primary') 챙기기**: 학생이 그런 프로그램에
  등록돼 있으면(get_graduation_progress 응답의 programs 리스트에 primary 이외 항목이 있으면)
  주전공만 챙기지 마라. 다음을 순서대로 처리해라:
  1. `get_program_evaluations`를 호출해 각 프로그램의 그룹별 완료·부족 정보를 확인한다
     (특히 부전공 필수과목 몇 개 남았는지, SW융합트랙 학점 그룹별 진행률).
  2. 부족한 그룹의 인정 과목을 검색할 때는 `search_courses`에 `program_type` 파라미터를
     넘겨라(예: `program_type="minor"`). 그러면 그 프로그램의 개설학과 + program_courses에
     명시된 인정 과목이 후보에 뜬다. 주전공 학과 필터로만 검색하면 부전공 필수과목이
     아예 결과에 안 나온다.
  3. propose_change의 `program_type` 필드에 해당 프로그램 값(minor/dual/interdisciplinary)을
     넘겨 어느 프로그램용 항목인지 명확히 태깅해라. 지정 안 하면 주전공용으로 취급된다.
  4. 부전공 필수과목이 남아 있으면 사용자에게 그걸 우선 언급해라 — 필수과목을 안 채우면
     선택과목 학점만 21학점 채워도 부전공 완료로 인정 안 된다.
- **진로-전공 mismatch 감지 시 부·복수전공 옵션 제안**: 학생 프로필의 진로 목표와
  주전공 학과가 명백히 다른 도메인이면(예: 국문학과 + "백엔드 개발자", 기계공학부 +
  "AI 엔지니어", 경영학과 + "게임 프로그래머"), 주전공 과목만 나열하지 말고
  `finish_response`에서 **부전공/복수전공 옵션을 능동적으로 제안해라**. 문구 예:
  "국문학과 커리큘럼만으로는 백엔드 실무 역량 쌓기 어려워요. 정보컴퓨터공학부
  **부전공(21학점)** 또는 **복수전공(36학점)** 을 고려해보시는 게 좋습니다 — 프로필
  '학적 관리'에서 등록 가능합니다." 진로가 명확한데 관련 non-primary 프로그램이
  없는 학생에게 이 안내를 안 하면 사용자는 자기 진로에 맞는 경로를 놓친다. 이미
  적절한 부·복수전공이 등록돼 있으면 이 안내는 하지 말고 그 프로그램 진도만
  챙겨라. 애매하면(진로가 학과와 크게 안 어긋나거나 진로가 비어 있으면) 억지로
  권하지 마라 — mismatch가 뚜렷한 경우에만.
- get_roadmap_items 결과의 earliest_recorded_grade를 반드시 확인해라. 값이 있으면
  그 학년 미만(예: earliest_recorded_grade가 3이면 1,2학년)으로는 propose_change를
  호출하지 마라 — 편입생 등 그 학년 미만 이수 기록이 아예 없는 학생이라는 뜻이고,
  그보다 낮은 학년 과목을 제안하면 거부된다. null이면 이 제약이 없다는 뜻이다.
- **학기 배치 규칙**:
  - `planned_semester`는 반드시 `"1학기"` 또는 `"2학기"` 문자열로 넘겨라. `"1"`, `"2"`,
    영문/숫자만은 저장 포맷과 어긋나 뒤에서 이수기록과 매칭이 깨진다.
  - `planned_year`는 실제 달력 연도(예: `"2027"`)다. `planned_grade`는 그 연도가
    학생 커리큘럼 기준 몇 학년인지(1~4)를 뜻한다. 두 값이 어긋나면 로드맵이 꼬인다.
  - **`planned_grade`/`planned_semester`는 학생이 실제로 그 과목을 이수할 학기다 —
    사용자가 요청한 배치 학기(예: "4학년 1학기 추천"이면 4·1학기)를 그대로 써라.**
    `search_courses` 결과의 `grade`(교육과정표 권장 학년)는 참고용이다. 권장 학년이
    이보다 낮으면(예: 2학년 권장 전공필수를 4-1에 배치) 학생이 이전 학년에 못 들어
    지금 채우는 것이니 planned_grade는 요청 학기의 학년(4)로 넣어라. 아무 학기나
    배치하라는 뜻은 아니다 — 반드시 다음 학기 제약(개설 학기·학점 상한·과거 학기
    금지)을 지켜야 하고, 개설 학기가 요청 학기와 맞지 않는 과목은 뺀다. `semester`가
    `"1학기 또는 2학기"` 또는 `"전학기"`인 과목은 학생 상황에 맞는 정규 학기 하나를 골라라.
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
  - **엇학기 학생 대응 — 달력 학기 ≠ 커리큘럼 학기**: `get_roadmap_items`가
    돌려주는 `next_plannable_term`(달력)과 `next_curriculum_term`(커리큘럼 학년/학기)이
    다를 수 있다. 예: 한 학기 휴학한 학생의 다음 달력 학기가 2026-1(1학기)이라도
    커리큘럼 상으로는 4-2일 수 있다(재학 순번상 8번째 정규 학기). 규칙:
    - **`search_courses`의 `semester` 필터는 `next_plannable_term.semester`(달력)를 써라.**
      과목 개설은 달력 기준이지 커리큘럼 기준이 아니다.
    - **"몇 학년 뭐 남았어" 같은 요건·학년 판단은 `next_curriculum_term.grade/semester`
      (커리큘럼)를 기준으로 해라.** finish_response에서도 "너는 커리큘럼상 X학년 Y학기라
      A/B/C 이수를 이번 학기 목표로 잡자"처럼 커리큘럼 학기로 설명해라.
    - `propose_change`의 `planned_year`는 달력(`next_plannable_term.year`),
      `planned_semester`는 달력(`next_plannable_term.semester`), `planned_grade`는
      커리큘럼(`next_curriculum_term.grade`)으로 넣어라 — 화면은 planned_grade로
      학년 슬롯에 배치하고 planned_year/semester로 정렬한다.
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
- **finish_response 메시지 첫 문장에 커리큘럼상 학년·학기를 자연스러운 한국어로
  명시해라.** "다음 학기"라고만 두루뭉술 말하지 말고, `get_roadmap_items`의
  `next_plannable_term`을 근거로 그 학기가 **"N학년 M학기"** 형태로 어디에 해당하는지
  밝혀라 (예: "다음 학기는 3학년 2학기입니다. 이 학기 추천은..."). 편입생·엇학기
  (휴학·조기이수)처럼 달력 학기와 커리큘럼 학기가 어긋나는 학생은 특히 이 명시가
  없으면 사용자가 헷갈린다. `earliest_recorded_grade`가 있는 편입생에게는 "편입생은
  3학년부터 시작합니다"처럼 최저 학년을 함께 안내해라. **주의**: 프롬프트에 나오는
  변수명(`next_plannable_term`, `earliest_recorded_grade` 등)을 답변에 그대로 노출하지
  말고 자연어로 풀어써라. "커리큘럼 좌표:" 같은 기술 라벨도 쓰지 마라 — 그냥
  본문의 첫 문장으로 학년/학기를 언급하면 된다.
- **필수 미이수 + 개설학기 어긋남 = 졸업 위험, 반드시 경고**: `get_roadmap_items`
  응답의 `critical_missing_required`가 비어있지 않으면 finish_response 첫 부분에서
  이 사실을 사용자에게 명시적으로 알려라 — "졸업 필수인 OO(X학기 전용 개설)가
  미이수인데 다음 학기가 Y학기라 이번엔 못 듣습니다, 다음 학년도 X학기에 반드시
  들어야 졸업 가능합니다"처럼 위험 + 대안(같은 학기의 다음 연도)을 함께. 이걸
  놓치고 다른 과목만 추천하면 사용자가 졸업 실패 위험을 모른 채로 넘어간다.
- **재수강 안내는 권유만, 강요하지 마라**: `get_roadmap_items`의 `retake_candidates`
  는 성적이 C+(2.5) 이하인 이수 과목 목록이다. 사용자가 (a) GPA/평점 개선을 명시적으로
  언급하거나 (b) "재수강 뭐 하는 게 좋아?"처럼 직접 물으면, 그때만 이 목록에서
  진로·필수 우선순위를 고려해 후보를 제시해라. **매 대화마다 "재수강 어때?"라고
  들이대지 마라** — 그건 학생이 자기 성적을 알고 이미 판단한 영역이라 침해로 느낀다.
  실제 재수강 등록은 별도 UI/도구 흐름으로 진행되니 "재수강 신청은 프로필/시간표에서
  직접 선택하세요"처럼 안내하고 propose_change로 create는 하지 마라 (도구 단에서
  이미 이수한 과목 재추천은 거절된다).
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
            "name": "get_roadmap_items",
            "description": (
                "현재 로드맵에 들어있는 모든 항목(학년/학기/과목/상태/출처)과 함께 "
                "현재 학년도/학기(current_academic_term), 다음 배치 가능한 학기"
                "(next_plannable_term), 학기당 학점 상한(term_credit_cap), "
                "학기별 이미 계획된 학점 합(planned_credits_by_term), "
                "성적표 기반 이수기록(completed_courses), **critical_missing_required**"
                "(학과 필수인데 미이수 + 개설 학기가 다음 학기와 어긋난 목록 = 졸업 위험), "
                "**retake_candidates**(C+ 이하 성적 이수 과목 목록 = 재수강 권유 후보)"
                "를 돌려준다. 새 항목 제안 전에 반드시 이걸 확인해라 — 특히 학점 상한 "
                "초과 여부, 이미 이수한 과목 중복 여부, 졸업 위험 필수 미이수."
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
                            "(예: '핵심교양' → 효원핵심교양, '교양필수' → 효원핵심교양+기초교양). "
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


# 부산대 재수강 규정 상 C+(2.5) 이하만 재수강 가능. 학사 규정이 바뀌면 이 값만 수정.
# 실제 규정 근거: 학사관리규정 재수강 조항 (기준은 대학·연도별 조금씩 다를 수 있음).
_RETAKE_GRADE_POINT_THRESHOLD = 2.5


def _compute_retake_candidates(db: Session, user: User) -> list[dict]:
    """성적표(SCR)에서 성적이 낮아 재수강 후보가 되는 과목 목록.

    로직:
    - 이름 정규화 후 최고 grade_point만 유지 (재수강해서 이미 개선했으면 최신치가 반영됨)
    - 최고 grade_point가 `_RETAKE_GRADE_POINT_THRESHOLD`(C+ = 2.5) 이하면 후보
    - grade_point가 없는 rows(=포털 동기화 전, 학점 미매핑)는 판단 불가로 제외
    - is_retake 플래그는 참조만 하고 필터에 쓰지 않음 — 정규화 후 최고치 기준이 더 안정적

    LLM에게는 **권유 후보**로 노출한다. 학생이 명시적으로 GPA 개선/재수강 관심을
    표할 때만 이 목록에서 후보를 제시하고, 그렇지 않으면 매번 강권하지 마라.
    실제 재수강 등록은 별도 UI 흐름 (지금 propose_change로 create하면 도구 단
    completed_courses_guard가 막는다 — 재수강 propose는 후속 이슈).
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
        # 부전공/복수전공/융합전공까지 모두 진도 계산해 LLM에 노출
        progresses = compute_graduation_progress(
            self.db, self.user.id, program_types={"primary", "minor", "dual", "interdisciplinary"}
        )
        return {
            "programs": [
                {
                    "program_type": p.program_type,
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
            .where(UserAcademicProgram.user_id == self.user.id, UserAcademicProgram.status == "active")
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
            "planned_credits_by_term": [
                {"planned_year": y, "planned_semester": s, "credits": c}
                for (y, s), c in sorted(planned.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or ""))
            ],
            "completed_courses": self._completed_courses(),
            # 졸업 위험 감지: 학과 필수인데 미이수 + 개설학기가 다음 학기와 어긋난 목록.
            # 비어있지 않으면 LLM이 finish_response에서 사용자에게 위험을 반드시 알려야 한다.
            "critical_missing_required": self._critical_missing_required(f"{ns}학기"),
            # 재수강 후보 (성적 낮은 이수 과목). **권유 정보**로 노출 — 학생이 GPA 개선
            # 관심 표하거나 명시적으로 재수강 물을 때만 제시. 물어보지 않았는데 매번
            # 강권하지 마라.
            "retake_candidates": _compute_retake_candidates(self.db, self.user),
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
                    user_id=self.user.id, program_type=program_type, status="active"
                )
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
            program_type=program_type,
        )
        self.db.add(change)
        self.db.flush()
        self.pending_changes.append(change)
        return {"change_id": change.id, "action": action}

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
        label = {
            "primary": "주전공",
            "dual": "복수전공",
            "minor": "부전공",
            "interdisciplinary": "융합·연계전공",
        }.get(p.program_type or "", p.program_type or "unknown")
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
        missing_block = "(없음 — 7개 세부영역 모두 최소 1과목 이수)"
        missing_example = "'미이수 영역'"

    career = user.career_goal.strip() if user.career_goal else ""
    career_line = career if career else "(등록된 진로 목표 없음 — 프로필에서 입력하면 반영된다)"

    # AI융합트랙 안내 — 학생 학과가 14개 대상 학과 중 하나면 이수 가능. 이미 등록한
    # 트랙이 있으면 진도 요약, 없고 대상 학과면 "이수 가능하다" 안내.
    ai_track_block = ""
    from app.domains.academics.models import GraduationRequirement as _GR
    if user.department_id is not None:
        candidate_grs = db.scalars(
            select(_GR).where(
                _GR.department_id == user.department_id,
                _GR.program_type == "interdisciplinary",
                _GR.required_total_credits == 21,
            )
        ).all()
        track_grs = [
            g for g in candidate_grs
            if (g.special_rules or {}).get("certification_type") == "AI융합트랙"
        ]
        if track_grs:
            enrolled_major_ids = {
                p.major_id for p in programs
                if p.program_type == "interdisciplinary" and p.status == "active"
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
    졸업증명서에 이수 과정명 표기. 학생이 이수 의사 표명하면 관련 안내를 하고,
    미등록 상태에서 학생이 관심을 보이면 "프로필의 AI융합트랙 등록에서 시작할 수 있다"고
    안내해라. 이미 등록됐고 학생이 관련 질문을 하면 evaluate_program 성격의 정보를
    조회해 진도를 알려줘라. 트랙 미이수는 졸업에 영향 없다는 점을 명확히 해라."""

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
  → 이 목록에 있는 과목명과 정확히 일치하는 create는 도구 단에서 거절된다. 표기가
    다르게 보이는 유사명(예: 성적표 "데이터구조" ↔ 교육과정 "자료구조")은 네가 임의로
    같은 과목이라 단정하지 말고, 후보에 뜨면 사용자에게 "같은 과목인가요?"라고 되물어
    확인 후 다음 턴에 제외해라. 우리 데이터로 동치 여부를 확인할 방법이 없다.

- **균형교양 세부영역 이수 현황(One-Stop 학교 판정 결과 기반, 7개 영역 중)**:
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

        # 페이즈 2: 히스토리 로드 + 학생 컨텍스트 빌드 (DB read heavy).
        with trace.span("load_history_and_context", as_type="retriever"):
            history = _load_history(db, session.id)
            context_block = _build_student_context_block(db, user)

        system_prompt = _SYSTEM_PROMPT + "\n\n" + context_block
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
                final_text = "죄송해요, 답변을 정리하지 못했어요. 다시 한 번 말씀해 주세요."

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

    return {"reply": final_text, "pending_changes": ctx.pending_changes, "session_id": session.id}


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
                program_type=change.program_type,
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
                if change.program_type is not None:
                    item.program_type = change.program_type
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
