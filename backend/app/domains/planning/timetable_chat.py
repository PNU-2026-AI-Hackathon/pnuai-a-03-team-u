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

import datetime
import json
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.ai.rag.career_keywords import expand_career_query
from app.ai.rag.curriculum_retriever import CurriculumRetriever
from app.core.config import settings
from app.domains.academics.course_substitution import liberal_area_completions
from app.domains.academics.models import StudentCourseRecord
from app.domains.academics.program_status import ACTIVE_PROGRAM_STATUSES
from app.domains.courses.models import Course, CourseOffering, CourseTime
from app.domains.planning.models import (
    CoursePlan,
    CoursePlanItem,
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
    _completed_course_norms,
    _normalize_course_name,
    _schedule_shape,
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
   (`remaining_by_category`)**·균형교양 이수/미이수 영역을 먼저 본다.
2. **`remaining_by_category`가 비어있지 않으면 각 카테고리별로 `list_offered_courses`를
   반드시 호출해라.** 예: `remaining_by_category=[{전공필수: 12}, {교양필수: 3}]` 이면
   `list_offered_courses(category="전공필수")` 와 `list_offered_courses(category="교양필수")`
   두 번은 최소로 호출한다. career 관련 소수 과목만 뽑고 부족한 요건 못 채우는 걸 방지.
3. 진로 관련 심화 후보가 필요하면 `list_offered_courses(query=...)` 로 토픽 검색 병행.
   career 검색은 카테고리 훑기의 보조지 대체가 아니다.
4. 모은 후보 분반을 **`build_timetable`에 한꺼번에 넘긴다** — 규칙 엔진이 시간 충돌 없는
   조합을 직접 만들어 돌려준다. **조합을 네가 손으로 고르려 하지 마라.** 분반 시간을
   눈으로 맞춰보는 건 네가 잘 못하는 일이고, 엔진이 정확히 그걸 하려고 있다.
   후보는 넉넉히(10~25개 분반) 넘겨라 — 적게 넘기면 조합이 안 나온다.
   **매 대화 턴에서 finish_response 전에 build_timetable을 최소 1회 반드시 호출**해라.
   (`validate_timetable`은 사용자가 특정 조합을 콕 집어 "이거 되냐"고 물을 때만 쓴다.)
5. `build_timetable`이 돌려준 `schedules`의 `offering_ids`를 **그대로** `finish_response`에
   담고, 사용자에게 보여줄 설명 메시지를 함께 넘긴다. offering_id를 직접 고쳐 넣거나
   엔진이 안 준 조합을 지어내지 마라 — 검증이 깨진다.
   조합이 안 나오면(`ok: false`) 후보를 더 넓혀 다시 호출하고, 그래도 안 되면
   무엇을 시도했고 왜 안 되는지 finish_response에서 설명해라.
   **message에 과목 목록을 나열하지 마라.** 어떤 과목이 몇 학점에 무슨 요일인지는 서버가
   정확한 값으로 답변 끝에 자동으로 붙인다. 네가 목록을 다시 쓰면 기억으로 쓰다가 과목명·
   학점을 틀리고, 화면의 시간표와 어긋난 설명이 나간다(실측된 실패다).
   너는 **왜 이 조합인지, 무엇이 부족한지, 다음에 뭘 하면 좋은지**만 2~4문장으로 써라.
   특정 과목을 콕 집어 언급해야 할 때만 `course_lines`의 이름을 그대로 옮겨 적어라.

**사용자가 이미 담아둔 시간표를 존중해라 (중요)**:
`get_student_context.current_timetable`은 사용자가 시간표 화면에서 **직접 선택해 담은**
강좌들이다. 백지가 아니라 여기서 이어서 짜는 것이다.
- 이미 담긴 과목을 다시 추천하지 마라. 그것과 시간이 겹치는 분반도 추천하지 마라.
  (`build_timetable`이 자동으로 고정·제외하니 후보 풀에 다시 넣을 필요 없다.)
- 남은 학점은 `current_timetable.remaining_credits_to_cap`을 기준으로 본다.
- 이미 담긴 강좌가 있을 때만 그 사실을 언급해라 ("이미 담으신 3과목에 이어서…").
  `offering_count`가 0이면 아예 언급하지 마라 — "이미 담으신 0과목"은 이상한 문장이다.
- 사용자가 "지금 담은 거 빼고 처음부터 다시" 라고 명시할 때만
  `build_timetable(ignore_current_timetable=true)`를 쓴다.
- 대화 도중 "지금 뭐 담겨 있지?" / 시간표를 바꾼 뒤 다시 확인해야 할 때는
  `get_current_timetable`을 쓴다 — `get_student_context`를 통째로 다시 받을 필요 없다.
  `occupied_slots`로 이미 찬 요일·시간대도 함께 온다.

**학점 목표**: `get_student_context.target_credit_floor` (상한의 80%) 학점 **이상** 채우는
조합을 만들어라. 사용자가 "가볍게 듣고 싶다"고 명시한 경우에만 이 하한을 무시한다.
- **사용자가 학점을 숫자로 말하면**("18학점으로 짜줘", "딱 15학점") 그 숫자를
  `build_timetable(target_credits=18, credit_mode="exact")`로 그대로 넘겨라. 자동 목표를
  쓰거나 네가 숫자를 바꾸지 마라 — 18을 요청했는데 21학점 시간표를 내미는 건 오답이다.
- exact인데 딱 맞는 조합이 없으면 `reaches_target_credits`가 false로 오고
  `below_target_note`가 붙는다. 그때는 **몇 학점으로 짰고 왜 요청대로 못 했는지를
  답변 첫 부분에서 먼저 밝혀라.** 요청한 학점인 것처럼 넘어가면 안 된다.
- **자동 목표 학점(`target_credit_floor`, 상한의 80%)은 우리 내부 계산값이다. 사용자에게
  그 숫자를 말하지 마라.** 사용자가 말한 적 없는 "목표 16학점" 같은 문구가 답변에 나오면
  자기가 정한 기준을 사용자 요청인 것처럼 말하는 셈이다(실측된 실패). 사용자가 학점을
  직접 말한 경우에만 그 숫자를 언급해라.
- `build_timetable` 응답에 `credit_intent_note`가 있으면 그 지시를 그대로 따라라 —
  사용자가 메시지에서 말한 학점 요청을 서버가 확정한 것이다.

**답변 본문에 내부 용어를 쓰지 마라**: `offering_id` / `course_id` / `target_credits` /
`build_timetable` 같은 필드·도구 이름은 사용자 화면에 아무 의미가 없다. "아래 조합의
offering_id를 그대로 수강신청에 담으면 됩니다" 같은 문장은 안내가 아니라 혼란이다
(실측). 과목명·요일·시간으로만 말해라.
학점을 최대한 채우는 건 `build_timetable`이 알아서 한다 — 같은 후보로 반복 호출해도
결과는 안 바뀐다. 학점이 모자라면 **후보 과목을 늘려서** 한 번 더 부르고, 그래도 안 늘면
그 사실을 사용자에게 설명하고 끝내라 (무한 재시도 금지).

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
- 교양선택 과목을 추천할 때는 `missing_liberal_areas`를 우선 채우고,
  `completed_liberal_areas`에 있는 영역을 이미 충족한 것으로 취급해라. 영역 정보는
  One-Stop의 학교 판정을 DB에 저장한 값이므로 과목명만 보고 영역을 추측하지 마라 —
  `list_offered_courses(liberal_area="XX영역")`로 직접 필터해서 후보를 찾아라. 단
  '외국어'/'융복합'은 이 필터로 안 잡히니 그 두 영역이 미이수면 query/category로
  따로 찾는다.
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
사용자가 "월수금만", "화목 빼고", "오전만", "오전 수업은 빼줘" 같은 제약을 명시하면
**위반하는 분반은 조합에 절대 넣지 마라**. "빼줘/제외해줘"는 한정("~만")과 방향만
반대일 뿐 똑같이 강한 요청이다 — 지킨 척 문장만 쓰고 실제로는 그 시간대 수업을 담는
답변이 실측됐다. `validate_timetable`은 시간 충돌·학점 상한만 판정하지 사용자
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
  있다. finish_response 앞부분에서 **그 과목의 실제 이름과 개설 학기를 직접 써서**,
  이번 학기에는 못 담는다는 사실과 다음에 언제 들어야 졸업 가능한지를 함께 알려라.
  ⚠️ 과목명·학기는 `critical_missing_required`에 **실제로 들어 있는 값만** 써라. 시간표 후보에는 넣지 마라 (이번 학기 개설 안 됨).
  ⚠️ `missing_required_offered_this_term`은 **정반대 목록**이다 — 미이수 필수인데 이번
  학기에 분반이 열려 있는 과목이다. 여기 있는 과목을 "개설되지 않았다"고 말하면 바로
  아래 시간표에 그 과목이 들어 있는 자기모순 답변이 된다(실측). 우선 후보로 담아라.""",

    "prereq_blocked": """
- **선수과목 부족 과목 이번 시간표 제외**: `prereq_blocked`에 항목이 있다. 이 course_id는
  시간표 조합에 넘기지 마라. `list_offered_courses` 결과에 있어도 걸러라. description
  파싱 기반이라 오탐 가능성 있으니 학생 "선수 이미 들었어" 반박하면 그대로 수용. 명시적
  요청 시 "선수 X가 미이수라 X부터 이수 권장"이라고 안내.""",

    "non_primary_programs": """
- **부전공·복수전공 과목도 후보에 넣어라**: 이 학생은 주전공 외 프로그램을 이수 중이다.
  `list_offered_courses`를 **주전공용 한 번, 해당 프로그램용 한 번**(`program_type="minor"`
  등) 최소 두 번 호출해라. 주전공 스코프로만 검색하면 부전공 학과 개설과목이 결과에
  아예 안 나와서, 담을 수 있는 과목이 몇 개 없는 것처럼 보인다.""",

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

    from app.domains.academics.models import UserAcademicProgram
    from sqlalchemy import func as _func

    # 부·복수·융합전공 보유 → 그 학과 개설과목도 따로 검색해야 후보가 제대로 모인다.
    if db.scalar(
        select(_func.count(UserAcademicProgram.id)).where(
            UserAcademicProgram.user_id == user.id,
            UserAcademicProgram.program_type != "primary",
            UserAcademicProgram.status.in_(ACTIVE_PROGRAM_STATUSES),
        )
    ):
        applicable.append("non_primary_programs")

    # 엇학기 — 로드맵 챗과 같은 판정을 쓴다 (마지막 이수 학기와 현재 학기 사이 공백).
    # 예전엔 "최신 SCR 연도 - curriculum_year >= 4"라는 다른 식이 여기 복제돼 있었고,
    # 그 식은 정작 한 학기 휴학생을 못 잡았다. 판정이 두 곳에 갈리면 로드맵과 시간표가
    # 서로 다른 안내를 하게 되므로 단일 출처로 모은다.
    from app.domains.planning.roadmap_chat import _has_term_gap
    if _has_term_gap(db, user):
        applicable.append("staggered_semester")

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
                "**completed_liberal_areas / missing_liberal_areas**(균형교양 영역 현황), "
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
                "offered_sections의 offering_id를 모아 build_timetable에 넘기면 조합을 만들어준다. "
                "**`results`에는 이번 학기 분반이 실제로 있는 과목만 들어온다.** 교육과정에는 "
                "있지만 이번 학기 미개설인 과목은 `matched_but_not_offered_this_term`으로 따로 "
                "온다 — 시간표에 넣을 수 없고, 사용자가 그 과목을 콕 집어 요청했다면 "
                "'이번 학기에는 개설되지 않았습니다'라고 명시적으로 알려야 한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "과목명·토픽 키워드. 비워두면 필터로만 훑는다."},
                    "category": {
                        "type": "string",
                        "description": (
                            "이수구분 필터. 학생이 말한 자연어를 그대로 넘기면 백엔드가 매핑한다 "
                            "(예: '핵심교양' → 효원핵심교양, '교양필수' → 효원핵심교양, "
                            "'교양선택' → 효원균형교양+효원창의교양+기초교양). "
                            "빈 결과가 오면 응답의 `available_categories`를 보고 다른 값으로 재시도해라 — "
                            "같은 인수로 재호출하지 마라."
                        ),
                    },
                    "liberal_area": {
                        "type": "string",
                        "description": (
                            "균형교양 세부영역 필터. `get_student_context`의 `missing_liberal_areas` "
                            "값을 그대로 넘겨라(예: '사상과역사') — 결과의 `general_education_area`가 "
                            "그 값과 일치하는 과목만 온다. 과목명만 보고 영역을 추측하지 말고 이 "
                            "필터로 확인해라. **'외국어'/'융복합'은 이 필터로 안 잡힌다** — 그 두 "
                            "영역은 query나 category로 따로 찾아라(응답 note가 안내한다)."
                        ),
                    },
                    "limit": {"type": "integer", "description": "결과 상한 (기본 10)"},
                    "program_type": {
                        "type": "string",
                        "enum": ["primary", "minor", "dual", "interdisciplinary"],
                        "description": (
                            "검색 스코프를 어느 프로그램의 학과로 잡을지. 미지정이면 주전공 학과. "
                            "학생이 부전공·복수전공을 이수 중이면 그 프로그램 과목도 시간표에 넣어야 "
                            "하므로 `program_type='minor'` 처럼 지정해 **따로 한 번 더 호출**해라 — "
                            "주전공 학과 스코프로만 검색하면 부전공 학과 개설과목이 결과에 아예 안 나온다."
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
            "name": "get_current_timetable",
            "description": (
                "사용자가 시간표 화면에서 **직접 담아둔 강좌**의 현재 상태를 조회한다. "
                "`get_student_context`에도 같은 값이 들어 있지만, 시간표를 바꾼 뒤 다시 "
                "확인하거나 대화 중간에 '지금 뭐 담겨 있지?'를 물었을 때는 이걸 쓴다 — "
                "전체 컨텍스트를 다시 받을 필요가 없다. "
                "담긴 강좌·학점·남은 학점과, 그것들이 차지한 요일/시간대를 돌려준다."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_timetable",
            "description": (
                "**시간표를 짜는 기본 도구.** 후보 분반 목록을 넘기면 규칙 엔진이 시간 충돌 없는 "
                "조합을 직접 만들어 최대 3개 돌려준다. 같은 과목 중복·학점 상한·이수 완료 과목·"
                "사용자 시간 제약은 엔진이 알아서 거른다. "
                "**조합을 직접 손으로 고르지 말고 이 도구를 써라** — 후보를 넉넉히(10~25개 분반) "
                "넘길수록 좋은 조합이 나온다. 반환된 offering_ids를 그대로 finish_response에 담으면 된다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "offering_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": (
                            "후보 분반 풀. list_offered_courses/search_by_career에서 모은 "
                            "offering_id를 우선순위 높은 순으로 넣어라 (앞쪽이 우선 채택된다)."
                        ),
                    },
                    "must_include_offering_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": (
                            "반드시 포함해야 하는 **분반**(offering) — 과목이 아니라 분반 단위다. "
                            "여기 넣은 분반은 그대로 들어가고, 같은 과목의 다른 분반은 후보에서 "
                            "빠진다. 쓸 수 없는 분반이면 조합을 만들지 않고 사유를 돌려준다."
                        ),
                    },
                    "target_credits": {
                        "type": "number",
                        "description": (
                            "목표 학점. 미지정이면 학점 상한의 80%. 사용자가 '가볍게'라고 하면 "
                            "낮춰서 넘겨라. 사용자가 이미 담아둔 강좌 학점까지 포함한 최종 목표다. "
                            "**사용자가 '18학점으로', '15학점 정도'처럼 숫자를 말하면 그 숫자를 "
                            "그대로 넣어라** — 네가 임의로 올리거나 내리지 마라."
                        ),
                    },
                    "credit_mode": {
                        "type": "string",
                        "enum": ["at_least", "exact"],
                        "description": (
                            "기본 at_least — target_credits '이상'으로 최대한 채운다. "
                            "사용자가 학점을 **콕 집어 말했으면**('18학점으로 짜줘', '딱 15학점') "
                            "exact를 넣어라. exact는 그 학점을 넘지 않고, 정확히 못 맞추면 "
                            "이하 최대로 내려가면서 reaches_target_credits=false로 알려준다. "
                            "'가볍게'·'많이 듣고 싶어'처럼 방향만 말한 경우는 at_least 그대로 두고 "
                            "target_credits만 조절해라."
                        ),
                    },
                    "ignore_current_timetable": {
                        "type": "boolean",
                        "description": (
                            "기본 false — 사용자가 시간표 화면에서 이미 담아둔 강좌를 고정한 채 "
                            "그 위에 얹는다. 사용자가 '처음부터 다시 짜줘', '지금 거 무시하고' 처럼 "
                            "명시적으로 백지에서 새로 짜달라고 할 때만 true."
                        ),
                    },
                },
                "required": ["offering_ids"],
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
                "사용자에게 보여줄 최종 답변을 제출한다. schedules 배열에는 "
                "**build_timetable이 돌려준 offering_ids를 그대로** 넣어라 — 직접 고르거나 "
                "고쳐 넣으면 시간 충돌·학점 상한이 확인되지 않은 조합이 사용자에게 나간다."
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


# --- 사용자 시간 제약 -------------------------------------------------------
#
# "월수 오전에만 넣어주세요" 같은 제약은 _CORE_PROMPT에도 규칙이 있지만 LLM이 지키지 않는다:
# 골든 케이스 18에서 3/3 재현으로, 화·목 14:00 분반(6003)을 조합에 넣고서 rationale에는
# "월수 오전에 진행되는 데이터베이스와 머신러닝"이라고 **거짓 설명**까지 붙였다.
# 제약 위반과 설명 불일치가 동시에 일어나므로 사용자는 잘못된 시간표를 그대로 믿게 된다.
#
# 그래서 판정을 LLM에 맡기지 않는다. 메시지에서 제약을 파싱해 도구 계층이 (a) 후보에서
# 아예 빼고 (b) 검증에서 거절한다 — 로드맵 챗의 가드들과 같은 방식이다.

_DAY_TOKENS = {"월": "월", "화": "화", "수": "수", "목": "목", "금": "금", "토": "토", "일": "일"}

# 요일 표기 추출. 예전 정규식 `(?:[월화수목금토일](?:요일)?)+` 은 두 가지로 고장나 있었다.
#
# ① **평범한 낱말 속 글자를 요일로 읽었다.** 공백을 지운 문장 전체를 훑기 때문에
#    '전공필수과목만' → 필'수'·과'목' → {수, 목}이 됐다. 이 제약은 이후
#    `_attach_offerings`(후보에서 분반 제거) → `validate_timetable`
#    (`time_constraint_violation`) → `finish_response`(시간표 삭제) 세 군데에서
#    강제되므로, 사용자는 "왜 수·목 수업만 나오지" 또는 빈 시간표를 이유도 모르고 받는다.
#    → 요일로 인정하는 조건: (a) '요일'이 명시됐거나, (b) 요일 글자가 2자 이상
#      연달아 나올 때('월수', '화목'). 한 글자만 있는 건 무시한다.
#
# ② **'수요일'의 '일'을 일요일로 셌다.** 매치된 문자열 전체를 훑어서
#    '월요일과 수요일만' → {월, 수, 일}이 됐다. 즉 '…요일'을 언급하는 거의 모든
#    요청에 일요일이 섞여 들어갔다.
#    → '요일' 접미사는 별도 그룹으로 빼서 글자 수집 대상에서 제외한다.
#
# 구분자에 '과'/'와'는 넣지 않는다. 넣으면 '필수과목'이 수-과-목으로 이어져 ①이 재발한다.
# '월요일과 수요일'처럼 '과'로 이어진 표현은 각각 '요일'이 붙어 있어 따로 잡히므로 문제없다.
_DAY_MENTION_RE = re.compile(
    r"(?P<days>[월화수목금토일](?:[,/·~]?[월화수목금토일])*)(?P<explicit>요일)?"
)

# 오전/오후 경계. 12:00에 걸치는 수업은 어느 쪽으로도 단정하지 않고 통과시킨다(보수적).
_NOON = datetime.time(12, 0)

# **배제형 제약**("오전 수업은 빼줘", "화목 빼고"). 예전에는 '빼고'/'제외'가 보이면
# 통째로 `return None` — 즉 제약 없음으로 처리했다. 그런데 LLM은 그 요청을 봤으므로
# "오전 수업은 제외해서 짰어요"라고 **말은 한다.** 2026-08-20 실계정 실측:
# "오전 수업은 빼줘" → 확률통계 월 09:00-12:00, 일반물리학 화 09:00-10:15이 담긴
# 시간표를 내놓고 답변은 "오전(09:00 이전) 수업은 제외해서…"였다(오전의 정의까지
# 자기에게 유리하게 바꿨다). 파싱을 포기하면 제약이 사라지는 게 아니라 **거짓 설명만
# 남는다.** 그래서 배제형도 규칙으로 잡아 도구 계층에서 강제한다.
#
# '빼줘'는 '빼고'를 포함하지 않는다 — 예전 게이트 키워드("만","에만","위주","빼고",
# "제외")로는 애초에 걸리지도 않았다. 어간까지 내려서 잡는다.
_EXCLUDE_MARKER = r"(?:빼|제외|피하|피해|말고|없이|싫|안돼|안됨|불가)"

_PERIOD_EXCLUDE_RE = re.compile(
    r"(?P<period>오전|오후)(?:수업|강의|타임|시간대|시간|것|거)?(?:은|는|을|를|만|에|이|가)?"
    + _EXCLUDE_MARKER
)

# 요일 배제. 요일 인정 조건은 `_DAY_MENTION_RE`와 같다 — '요일'이 명시됐거나 요일 글자가
# 2자 이상 연달아 나올 때만. 안 그러면 '전공필수 빼고'의 '수'가 수요일이 된다.
_DAY_EXCLUDE_RE = re.compile(
    r"(?P<days>[월화수목금토일](?:[,/·~]?[월화수목금토일])*)(?P<explicit>요일)?"
    r"(?:수업|강의)?(?:은|는|을|를|에|만)?" + _EXCLUDE_MARKER
)


def _collect_days(match: re.Match) -> list[str]:
    """요일 매치에서 실제 요일 글자만. '요일' 접미사 없는 한 글자는 낱말의 일부로 본다."""
    chars = [ch for ch in match.group("days") if ch in _DAY_TOKENS]
    if not match.group("explicit") and len(chars) < 2:
        return []
    return chars


def _parse_time_constraint(message: str | None) -> dict | None:
    """사용자 메시지에서 요일·시간대 제약을 뽑는다. 없으면 None.

    확신이 높은 표현만 잡는다 — 오탐으로 정상 후보를 지우는 게 놓치는 것보다 나쁘다.
    잡히지 않으면 기존 동작 그대로(제약 없음)다.

    - 한정형 요일: "월수 오전만", "월/수요일에만"
    - 한정형 시간대: "오전만" / "오후에만"
    - 배제형 요일: "화목 빼고", "금요일은 제외"      → `exclude_days`
    - 배제형 시간대: "오전 수업은 빼줘", "오후 말고"  → `exclude_period`

    배제형을 먼저 잡고 그 부분을 텍스트에서 지운 뒤 한정형을 본다. 안 그러면
    "오전 수업은 빼줘"가 한정형 `period="morning"`으로 뒤집혀 정반대 제약이 된다.
    """
    if not message:
        return None
    text = message.replace(" ", "")

    constraint: dict = {}
    spans: list[tuple[int, int]] = []

    exclude_days: set[str] = set()
    for match in _DAY_EXCLUDE_RE.finditer(text):
        chars = _collect_days(match)
        if not chars:
            continue
        exclude_days.update(chars)
        spans.append(match.span())
    if exclude_days:
        constraint["exclude_days"] = exclude_days

    for match in _PERIOD_EXCLUDE_RE.finditer(text):
        constraint["exclude_period"] = (
            "morning" if match.group("period") == "오전" else "afternoon"
        )
        spans.append(match.span())

    # 배제형으로 소비한 구간을 지운 나머지에서만 한정형을 찾는다.
    rest = text
    for start, end in sorted(spans, reverse=True):
        rest = rest[:start] + rest[end:]

    # 한정 표현이 없으면 단순 언급일 수 있다("월요일에 뭐 열려?") — 제약으로 보지 않는다.
    if any(k in rest for k in ("만", "에만", "위주")):
        days: set[str] = set()
        for match in _DAY_MENTION_RE.finditer(rest):
            days.update(_collect_days(match))
        if days:
            constraint["days"] = days
        if "오전" in rest:
            constraint["period"] = "morning"
        elif "오후" in rest:
            constraint["period"] = "afternoon"

    return constraint or None


def _describe_constraint(constraint: dict) -> str:
    parts = []
    if constraint.get("days"):
        parts.append("".join(sorted(constraint["days"], key="월화수목금토일".index)) + "요일")
    period = constraint.get("period")
    if period == "morning":
        parts.append("오전")
    elif period == "afternoon":
        parts.append("오후")
    if constraint.get("exclude_days"):
        parts.append(
            "".join(sorted(constraint["exclude_days"], key="월화수목금토일".index))
            + "요일 제외"
        )
    exclude_period = constraint.get("exclude_period")
    if exclude_period == "morning":
        parts.append("오전 제외")
    elif exclude_period == "afternoon":
        parts.append("오후 제외")
    return " ".join(parts) or "(제약 없음)"


def _times_violate_constraint(times, constraint: dict | None) -> str | None:
    """이 분반의 강의시간이 제약을 어기면 사유 문자열, 아니면 None.

    한정형(`period`)과 배제형(`exclude_period`)의 경계 판정이 일부러 다르다:
      - `period="morning"`("오전만")은 **시작이 정오 이후**면 위반 — 11:00~13:00처럼
        걸치는 수업은 통과시킨다(보수적, 정상 후보를 함부로 지우지 않는다).
      - `exclude_period="morning"`("오전 빼줘")은 **시작이 정오 이전**이면 위반 —
        09:00 시작 수업을 남겨두면 요청을 정면으로 어긴 시간표가 나간다.
    """
    if not constraint:
        return None
    for t in times:
        day = (t.day_of_week or "").strip()
        if constraint.get("days") and day and day not in constraint["days"]:
            return f"{day}요일 수업 — 요청한 요일({_describe_constraint(constraint)})이 아님"
        if constraint.get("exclude_days") and day and day in constraint["exclude_days"]:
            return f"{day}요일 수업 — 빼달라고 한 요일"
        period = constraint.get("period")
        if period == "morning" and t.start_time and t.start_time >= _NOON:
            return f"{day} {t.start_time.strftime('%H:%M')} 시작 — 오전 요청과 어긋남"
        if period == "afternoon" and t.end_time and t.end_time <= _NOON:
            return f"{day} {t.end_time.strftime('%H:%M')} 종료 — 오후 요청과 어긋남"
        exclude_period = constraint.get("exclude_period")
        if exclude_period == "morning" and t.start_time and t.start_time < _NOON:
            return f"{day} {t.start_time.strftime('%H:%M')} 시작 — 오전 수업을 빼달라는 요청과 어긋남"
        if exclude_period == "afternoon" and t.start_time and t.start_time >= _NOON:
            return f"{day} {t.start_time.strftime('%H:%M')} 시작 — 오후 수업을 빼달라는 요청과 어긋남"
    return None


# --- 사용자 학점 요청 -------------------------------------------------------
#
# 학점 목표도 시간 제약과 같은 이유로 LLM에 맡기지 않는다. "가볍게 듣고 싶어"에
# gpt-4o-mini는 `target_credits=16, credit_mode="at_least"`를 넘겨서 **17학점** 시간표를
# 내놨고(상한 21인 학생 기준으로 가볍지 않다), 답변에는 "'16학점(목표)'을 정확히
# 맞추기보다는 …총 17학점으로 잡혔습니다"라고 **사용자가 말한 적 없는 내부 목표 숫자**
# 까지 노출했다 (2026-08-20 실계정 실측). 요청이 명확한 표현만 규칙으로 뽑아 도구
# 계층에서 인자를 확정한다 — 모호하면 잡지 않고 기존대로 LLM 판단에 맡긴다.

# "가볍게 듣고 싶어" 계열. 낱말 하나('가볍게')만 보면 "가볍게 설명해줘" 같은 문장까지
# 걸리므로 학습 부담을 가리키는 표현만 모은다 (공백 제거 후 부분 일치).
_LIGHT_LOAD_PHRASES = (
    "가볍게듣", "가볍게들", "가볍게짜", "가볍게가", "가볍게수강", "가볍게만",
    "적게듣", "적게들", "조금만듣", "조금만들", "널널", "부담없", "부담이없",
    "빡세지않", "빡시지않", "쉬엄쉬엄", "최소학점", "여유롭게듣", "여유있게듣",
)
# "가볍게"의 목표 학점. 부산대 정규학기 최소 신청학점(통상 12학점) 수준으로 잡는다.
# 상한의 80%(=이 학생은 16.8)를 목표로 두면 '가볍게'가 사실상 무시되기 때문이다.
_LIGHT_LOAD_CREDITS = 12.0


def _parse_credit_intent(message: str | None) -> dict | None:
    """사용자 메시지에서 **"가볍게 듣고 싶다"**만 뽑는다. 아니면 None(= LLM 판단).

    반환: `{"target_credits": None, "credit_mode": "at_least", "style": "light"}`
    (목표 학점은 상한을 알아야 정해지므로 `build_timetable`에서 확정한다)

    ## 왜 숫자는 안 뽑는가 — 2026-08-20 설계 검토

    한때 `"18학점으로"` 같은 숫자도 정규식으로 뽑아 **LLM 인자를 덮어썼다.** 네 번의
    리뷰를 거치며 오탐이 계속 나왔고, 마지막에 그 구조가 수렴하지 않는다는 게 드러났다:

      - 오탐의 원인이 **요청 꼬리 화이트리스트 자체**였다. `만`은 조사(`12학점만`)이자
        `만점`의 첫 글자고, `신청`·`까지`·`정도`도 요청과 서술 양쪽에 쓰인다. 한국어는
        교착어라 꼬리에 형태소 경계가 없어 접두 검사로 둘을 가를 수 없다. 항목을 넣으면
        오탐, 빼면 미탐 — **배제 목록을 늘려도 못 고친다.**
      - `max` 우선 규칙이 그 오탐을 증폭했다. 과거 학점은 대개 큰 값(18~21)이라
        `"21학점까지 신청 가능하다던데 18학점으로 해줘"` → **21**이 됐다.
        **이 PR이 없애려던 실패("18 요청에 21을 내놓음")를 파서가 그대로 재생산했다.**

    그리고 원래 동기였던 "LLM이 사용자가 말한 숫자를 안 넘긴다"는 **관측된 적이 없다.**
    2026-08-19의 "18 요청 → 21" 사고는 LLM이 18을 제대로 넘겼는데 `target_credits`가
    하한으로만 쓰이던 랭킹 버그였고, 정렬 키 수정으로 해결됐다. 프롬프트와 도구 스키마
    양쪽에 "숫자를 말하면 그대로 넣어라"가 이미 있고 `credit_mode` enum도 생겼다.
    **근거 없는 보험이 실증된 손해를 내고 있었다.**

    반면 "가볍게"는 실측 근거가 있다 — mini가 없는 숫자(16)를 지어내 17학점을 내놨다.
    숫자가 없어 어휘 모호성도 거의 없다. 그래서 이 경로만 남긴다.
    """
    if not message:
        return None
    text = message.replace(" ", "")
    if any(p in text for p in _LIGHT_LOAD_PHRASES):
        return {"target_credits": None, "credit_mode": "at_least", "style": "light"}
    return None


# "공강 많게" = 학교 나가는 날을 줄이고 싶다는 요청(= 통학 요일 수 최소화). 랭킹에서
# 요일 수는 원래 4순위라 사실상 반영되지 않았고, LLM은 그런데도 "공강을 최대한 확보하는
# 쪽으로 잡았어요"라고 답했다(2026-08-20 실측, 실제로는 월화수목 4일짜리 20학점 조합).
# 요청이 명확할 때만 랭킹 기준을 바꾼다.
_FEWER_DAYS_PHRASES = (
    "공강많", "공강최대", "공강늘", "공강좀", "몰아서", "몰아듣", "몰아넣", "몰아서듣",
    "등교적게", "학교적게", "학교덜", "통학적게", "요일적게", "며칠만나",
)
_FEWER_DAYS_RE = re.compile(r"주[1-5]일")


def _prefers_fewer_days(message: str | None) -> bool:
    """"공강 많게"/"몰아서" 류 요청인지. 아니면 기존 랭킹 그대로."""
    if not message:
        return False
    text = message.replace(" ", "")
    return any(p in text for p in _FEWER_DAYS_PHRASES) or bool(_FEWER_DAYS_RE.search(text))


# --- 사용자 응답에서 내부 용어 제거 -----------------------------------------
#
# LLM이 도구 인자·필드명을 그대로 답변에 옮겨 적는다. 2026-08-20 실계정 실측:
# "아래 조합의 offering_id를 그대로 수강신청에 담으면 됩니다." — 사용자는 offering_id를
# 볼 수도 쓸 수도 없다(화면에 뜨는 건 과목명·시간표 블록이다). 프롬프트로만 막으면
# 새는 게 이미 여러 번 관측돼서, 마지막에 한 번 더 치환한다.
_INTERNAL_TERM_REPLACEMENTS: tuple[tuple[str, str], ...] = tuple(
    sorted(
        {
            "offering_ids": "과목", "offering_id": "과목",
            "course_ids": "과목", "course_id": "과목",
            "course_lines": "과목 목록",
            "target_credits": "목표 학점", "target_credit_floor": "목표 학점",
            "credit_mode": "학점 기준",
            "reaches_target_credits": "목표 학점 도달 여부",
            "below_target_note": "목표 학점 안내",
            "remaining_by_category": "이수구분별 남은 학점",
            "critical_missing_required": "미이수 필수 과목",
            "current_timetable": "현재 시간표",
            "build_timetable": "시간표 구성",
            "validate_timetable": "시간표 검증",
            "list_offered_courses": "개설 과목 조회",
            "search_by_career": "진로 기반 과목 검색",
            "get_student_context": "학생 정보 조회",
            "finish_response": "답변",
        }.items(),
        key=lambda kv: -len(kv[0]),  # 긴 것부터 — offering_ids가 offering_id보다 먼저
    )
)


# 치환 후 조사가 어긋나지 않게 함께 고쳐 쓴다 — 그냥 바꾸면 "offering_id를"이
# "과목를"이 되어 오히려 더 어색한 문장이 된다.
_JOSA_PAIRS = (("을", "를"), ("은", "는"), ("이", "가"), ("과", "와"), ("으로", "로"))
_JOSA_ALTERNATION = "|".join(
    sorted({j for pair in _JOSA_PAIRS for j in pair}, key=len, reverse=True)
)


def _has_final_consonant(word: str) -> bool:
    """마지막 글자에 받침이 있는지 (한글이 아니면 없는 것으로 본다)."""
    if not word:
        return False
    last = word[-1]
    if not ("가" <= last <= "힣"):
        return False
    return (ord(last) - 0xAC00) % 28 != 0


def _fit_josa(word: str, josa: str) -> str:
    """`word` 뒤에 붙일 조사를 받침에 맞춰 고른다. 목록에 없는 조사는 그대로."""
    for with_batchim, without in _JOSA_PAIRS:
        if josa in (with_batchim, without):
            return with_batchim if _has_final_consonant(word) else without
    return josa


def _name_matches_query(course_name: str | None, query: str | None) -> bool:
    """검색어가 이 과목 **이름을 가리키는지**. query가 없으면 항상 False.

    "이번 학기에 개설되지 않았습니다" 안내를 붙일 자격이 있는지 판단하는 데 쓴다 —
    의미 유사도로 딸려온 무관한 과목까지 안내하면 사용자는 묻지도 않은 과목의
    미개설 소식을 듣는다.
    """
    if not query or not course_name:
        return False
    q = _normalize_course_name(query)
    name = _normalize_course_name(course_name)
    if not q or not name:
        return False
    return q in name or name in q


def _scrub_internal_terms(text: str) -> str:
    """답변 본문에 샌 내부 식별자·도구 이름을 사용자가 읽을 수 있는 말로 바꾼다."""
    if not text:
        return text
    for term, replacement in _INTERNAL_TERM_REPLACEMENTS:
        if term not in text:
            continue
        text = re.sub(
            re.escape(term) + rf"(?P<josa>{_JOSA_ALTERNATION})?",
            lambda m: replacement + _fit_josa(replacement, m.group("josa") or ""),
            text,
        )
    return text


# --- 조합 탐색 (규칙 엔진) -------------------------------------------------
#
# 예전에는 조합 구성 자체를 LLM이 했다: `list_offered_courses`로 분반 목록을 받아
# 눈으로 시간을 맞춰보고 `validate_timetable`에 넣어보는 시행착오. 실계정·실DB
# (2026-2학기 3,599분반)로 재현해보니 gpt-4o-mini는 이걸 못 한다 — 한 턴에
# validate를 12번 호출해 **전부 실패**하고 결국 빈 시간표로 끝났다.
#
# 조합 탐색은 애초에 LLM이 할 일이 아니라 규칙 코드가 할 일이다(CLAUDE.md 절대원칙 #1과
# 같은 방향: 판정·구성은 규칙 엔진, LLM은 설명). 후보 풀만 LLM이 고르고, 시간 충돌 없는
# 조합을 실제로 짜는 건 여기서 한다.

_MAX_SEARCH_NODES = 30_000     # 탐색 폭주 방지 (후보가 많아도 응답 시간이 튀지 않게)
# 모아둔 조합이 이 수를 넘으면 학점 높은 순으로 잘라 메모리를 묶는다. **탐색은 멈추지
# 않는다.** 예전엔 "N개 모으면 return"이었는데, DFS가 include-first라 그 N개를 1순위 과목의
# 첫 분반 서브트리에서 다 써버리면 **그 과목의 다른 분반도, 그 과목을 빼는 가지도 영영
# 탐색되지 않았다.** 독립 리뷰 실측: 같은 후보 풀에서 18학점이 가능한데 9학점만 내놓고
# "최대 9학점"이라고 단언했다 — 이 변경이 없애려던 실패 유형 그대로다.
_COMBO_PRUNE_AT = 400
_COMBO_PRUNE_KEEP = 150
_MAX_COURSE_GROUPS = 14        # 탐색에 넣을 과목 수 상한 (우선순위 앞쪽부터)
_MAX_SCHEDULES_RETURNED = 3


def _format_section_line(section: _SectionInfo) -> str:
    """"응용통계학 (전공필수, 3학점) — 화 09:00-10:15, 목 09:00-10:15" 형태의 한 줄.

    LLM이 응답 본문에 그대로 옮겨 적으라고 주는 값이다.
    """
    meta = ", ".join(
        part for part in (
            section.category,
            f"{section.credits:g}학점" if section.credits is not None else None,
        ) if part
    )
    slots = ", ".join(
        f"{t.day_of_week or '?'} {t.start_time.strftime('%H:%M')}-{t.end_time.strftime('%H:%M')}"
        for t in section.times
        if t.start_time is not None and t.end_time is not None
    )
    line = section.course_name or f"분반 {section.offering_id}"
    if meta:
        line = f"{line} ({meta})"
    return f"{line} — {slots}" if slots else f"{line} — 시간 정보 없음"


def _rank_built_combos(
    combos: list[list[_SectionInfo]], target_credits: float,
    prefer_fewer_days: bool = False,
) -> list[list[_SectionInfo]]:
    """조합 랭킹. **학점을 먼저 채우고, 목표를 넘긴 뒤에는 촘촘한 시간표를 선호한다.**

    `timetable._rank_schedules`를 그대로 쓰면 안 된다 — 그건 "같은 과목 집합의 서로 다른
    분반 조합" 비교용이라 **요일 수가 1순위**다. 여기서는 과목 수가 다른 조합끼리 비교하는데,
    그 기준을 쓰면 과목 1개짜리(1일)가 4과목 조합(3일)보다 위로 올라온다. 실제로 그렇게
    나왔다(2026-08-17 실측: 12학점 조합이 가능한데 3학점짜리 단과목이 1·2위를 차지).

    `min(credits, target)`으로 묶는 게 요점이다:
      - 목표 미달 조합끼리는 학점이 많은 쪽이 위 (최대한 채운다)
      - 목표를 채운 조합끼리는 전부 동점 → **목표 초과가 적은 쪽**, 그다음 요일 수·공백이
        적은 쪽이 위 (더 채우려고 무리하게 늘리지 않는다)

    초과분(`over`)을 2순위에 두는 이유: target은 시스템 안에서 "이 학점 **이상**"이라는
    최소치로 쓰이는데(프롬프트의 `target_credit_floor`), 사용자가 "18학점으로 짜줘"라고
    명시했을 때까지 상한(21)을 꽉 채워 내놓으면 요청을 무시한 답이 된다. 실제로 18을
    요청했는데 21학점 조합만 3개 나왔다(2026-08-19 실측). 최소치 의미는 그대로 두고,
    이미 목표를 만족한 것들 중에서는 목표에 가까운 쪽을 고른다.

    `prefer_fewer_days=True`면 **요일 수를 초과분보다 먼저** 본다. 사용자가 "공강 많게",
    "몰아서 듣고 싶어"라고 말했을 때만 켠다. 기본값에서는 요일 수가 4순위라 사실상
    반영되지 않는다 — 2026-08-20 실계정 실측에서 "공강 많게 짜줘"에 월·화·수·목
    4일짜리 20학점 조합이 나왔는데 답변은 "공강을 최대한 확보하는 쪽으로 …잡았어요"였다.
    학점 목표(1순위)는 그대로 둔다. 요일 수를 학점보다 위에 두면 3학점 단과목 시간표가
    1위가 되는 옛 실패(2026-08-17)가 되살아난다.
    """
    def key(combo: list[_SectionInfo]) -> tuple:
        credits = sum(s.credits or 0.0 for s in combo)
        days, gap = _schedule_shape(combo)
        over = max(0.0, credits - target_credits)
        if prefer_fewer_days:
            return (-min(credits, target_credits), len(days), gap, over, -credits)
        return (-min(credits, target_credits), over, len(days), gap, -credits)

    return sorted(combos, key=key)


def _search_feasible_combos(
    groups: list[tuple[bool, list[_SectionInfo]]],
    credit_cap: float,
    target_credits: float,
    exact: bool = False,
) -> tuple[list[list[_SectionInfo]], bool]:
    """과목별 분반 후보에서 시간 충돌 없는 조합들을 찾는다.

    groups: (필수 포함 여부, 그 과목의 분반 후보들) 목록. 우선순위 높은 과목이 앞.
            한 과목에서는 분반을 **최대 하나만** 고른다 — 같은 과목 중복 수강 방지.

    탐색은 "넣어보기"를 먼저, "건너뛰기"를 나중에 해서 학점을 많이 채우는 조합이 먼저
    쌓이게 한다. 노드 예산(_MAX_SEARCH_NODES)으로 상한을 둔다.

    반환: (랭킹 전 조합 목록, 탐색이 예산에 걸려 잘렸는지).
    목표 학점(target_credits)을 넘긴 조합이 하나라도 있으면 그것들만, 하나도 없으면 찾은
    것 중 학점이 큰 순으로 돌려준다 — 목표에 못 미쳐도 "아무것도 못 만들었다"보다 낫다.

    `exact=True`면 target을 **넘지 않는다**: 탐색 예산 자체를 target으로 조인다. 그러면
    - target에 정확히 맞는 조합이 있으면 `reached`에 그것들만 남고,
    - 없으면 폴백이 target **이하 최대**를 돌려준다.
    "18학점으로 짜줘"에 19를 내놓지 않기 위한 것이다. 넘치는 쪽이 아니라 모자란 쪽으로
    비켜서는 이유: 학점 상한과 등록 부담은 위로만 위험하고, 사용자가 말한 숫자보다 많이
    담아주는 건 요청을 무시한 답으로 읽힌다. 정확히 못 맞췄다는 사실은 호출부가
    `reaches_target_credits`로 받아 사용자에게 밝힌다 — 조용히 다른 학점을 내밀지 않는다.

    두 번째 값이 True면 **"이게 최대다"라고 단언하면 안 된다** — 안 본 가지가 남아 있다.
    """
    if exact:
        credit_cap = min(credit_cap, target_credits)
    collected: list[tuple[list[_SectionInfo], float]] = []
    nodes = 0
    truncated = False

    def dfs(index: int, chosen: list[_SectionInfo], credits: float) -> None:
        nonlocal nodes, truncated
        if nodes >= _MAX_SEARCH_NODES:
            truncated = True
            return
        nodes += 1
        if index == len(groups):
            if chosen:
                collected.append((list(chosen), credits))
                if len(collected) > _COMBO_PRUNE_AT:
                    # 메모리만 묶는다. 여기서 return하면 트리가 굶는다.
                    collected.sort(key=lambda pair: -pair[1])
                    del collected[_COMBO_PRUNE_KEEP:]
            return

        required, sections = groups[index]
        for section in sections:
            section_credits = section.credits or 0.0
            if credits + section_credits > credit_cap:
                continue
            if any(_sections_conflict(section, other) for other in chosen):
                continue
            chosen.append(section)
            dfs(index + 1, chosen, credits + section_credits)
            chosen.pop()
        # 이 과목을 빼고 진행 — 필수 지정된 과목은 뺄 수 없다.
        if not required:
            dfs(index + 1, chosen, credits)

    dfs(0, [], 0.0)
    if not collected:
        return [], truncated

    reached = [combo for combo, credits in collected if credits >= target_credits]
    if reached:
        return reached, truncated
    collected.sort(key=lambda pair: -pair[1])
    return [combo for combo, _ in collected], truncated


class _TimeTableToolContext:
    """도구 실행 상태. LLM 대화 한 턴 동안 살아 있음."""

    def __init__(self, db: Session, user: User, year: str, semester: str,
                 time_constraint: dict | None = None, plan_id: int | None = None,
                 credit_intent: dict | None = None, prefer_fewer_days: bool = False):
        self.db = db
        self.user = user
        self.year = year
        self.semester = semester
        # 사용자가 시간표 UI에서 직접 담아둔 강좌들이 있는 수강계획(course_plans). 챗은
        # 이걸 **이미 확정된 부분**으로 보고 그 위에 얹는다 — 시간이 겹치는 분반을
        # 추천하거나 이미 담은 과목을 또 추천하면 안 되기 때문이다.
        self.plan_id = plan_id
        self._locked_sections_cache: list[_SectionInfo] | None = None
        # 사용자 메시지에서 파싱한 요일·시간대 제약. None이면 제약 없음(기존 동작).
        self.time_constraint = time_constraint
        # 사용자 메시지에서 파싱한 학점 목표(`_parse_credit_intent`). None이면 LLM이
        # 넘긴 target_credits/credit_mode를 그대로 쓴다(기존 동작).
        self.credit_intent = credit_intent
        # "공강 많게"/"몰아서" 요청이면 랭킹에서 요일 수를 앞세운다.
        self.prefer_fewer_days = prefer_fewer_days
        # 이번 학기에 실제 분반이 있는 과목명(정규화) 집합. 캐시 — 턴마다 한 번만 조회.
        self._offered_names_cache: set[str] | None = None
        # validate_timetable이 ok로 통과시킨 조합들 (finish 단계 가드가 참조).
        self.validated_ok_combos: list[list[int]] = []
        # build_timetable이 규칙 엔진으로 만들어낸 조합들. finish 단계에서 LLM이 빈
        # schedules로 끝내려 할 때 "엔진은 만들 수 있었다"는 근거로 되돌리는 데 쓴다.
        self.built_combos: list[list[int]] = []
        self._completed_norms_cache: set[str] | None = None
        self._prereq_blocked_cache: set[int] | None = None
        # build_timetable 재시도 억제용 — 후보를 바꿔도 최대 학점이 안 늘면 그만 시도하게 한다.
        self._build_calls = 0
        self._best_built_credits = 0.0
        # 이번 턴에 "개설됨"으로 이미 내보낸 과목명(정규화). 미개설 목록에서 같은 이름을
        # 빼는 데 쓴다 — 아래 `_filter_shadowed_not_offered` 참고.
        self._offered_names_this_turn: set[str] = set()

    # ------------ 도구 구현 ------------

    def offered_course_names_this_term(self) -> set[str]:
        """이번 학기(target_term)에 **실제 분반이 있는** 과목명(정규화) 집합.

        학생 학과 스코프로 좁힌다 (`department_id`가 학생 학과이거나 NULL = 교양,
        `major_id`가 학생 전공이거나 NULL). `_sibling_course_ids`와 달리 이수구분·학점은
        보지 않는다 — 여기서 답하려는 질문이 "이 **이름**의 과목을 이번 학기에 담을 수
        있나"이기 때문이다. 사용자에게 나가는 문장도 이름 단위다("일반물리학은 이번
        학기에 개설되지 않았습니다").

        개설 여부의 근거는 언제나 `course_offerings`이지 `courses.semester`(카탈로그의
        권장 학기)가 아니다. 이 구분을 놓쳐서 생긴 사고가 이 파일에만 두 번 있다.
        """
        if self._offered_names_cache is None:
            rows = self.db.execute(
                select(Course.course_name)
                .join(CourseOffering, CourseOffering.course_id == Course.id)
                .where(
                    CourseOffering.year == self.year,
                    CourseOffering.semester == self.semester,
                    or_(
                        Course.department_id == self.user.department_id,
                        Course.department_id.is_(None),
                    ),
                    or_(
                        Course.major_id == self.user.major_id,
                        Course.major_id.is_(None),
                    ),
                )
                .distinct()
            ).all()
            self._offered_names_cache = {
                _normalize_course_name(name) for (name,) in rows if name
            }
        return self._offered_names_cache

    def _filter_shadowed_not_offered(
        self, offered: list[dict], not_offered: list[dict]
    ) -> list[dict]:
        """미개설 목록에서 **같은 이름이 개설로도 나온 과목**을 뺀다.

        부산대는 같은 과목명에 개설 주체별로 다른 교과목코드를 발급한다. 그래서 한 이름의
        여러 행 중 일부만 이번 학기 분반을 갖는 일이 생기고, LLM이 둘 다 과목명으로만
        옮겨 적으면 한 답변 안에 "○○는 이번 학기 개설이 아니라 담을 수 없어요"와
        "○○ 3학점 — 월/수 15:00"이 같이 나온다. 사용자에겐 자기모순으로 읽힌다.

        ⚠️ **이 방어층이 처음 만들어진 계기(`일반물리학`)는 실제로는 데이터 버그였다.**
        시드 CSV 수기 입력에서 `일반물리학(I)`/`(II)`의 접미사가 잘려 둘 다 `일반물리학`이
        됐던 것이고, PR #191이 이름을 복원해 근본 원인을 없앴다. 지금 그 두 행은 이름이
        서로 다르다.

        그래도 남겨둔다: 진짜 동명 과목(alias 그룹)이 여전히 있고 — `공학작문및발표`,
        `인공지능과디지털사고`, `대학영어`, `약리학(I)` — 시드 데이터가 또 어긋나면
        사용자에게 자기모순 답변이 바로 나가는 경로이기 때문이다. 비용은 사실상 0이다.

        미개설 안내의 목적은 "네가 원한 그 과목을 못 담는다"를 알리는 것인데, 같은 이름을
        이미 담았다면 그 목적이 이미 충족돼 있다. 그래서 이름이 겹치면 침묵하는 쪽을
        고른다 — 틀린 경고를 하는 것보다 낫다.

        판정 근거를 **이번 학기 개설 목록 전체**(`offered_course_names_this_term`)로 둔다.
        예전에는 "같은 턴의 이전 호출에서 개설로 내보낸 이름"만 봐서 순서에 의존했다 —
        먼저 미개설로 나가고 나중 호출에서 개설이 발견되는 순서면 그대로 새어 나갔고,
        검색 결과에 그 과목이 아예 안 잡힌 턴에서는 항상 새어 나갔다. 개설 여부는 검색
        순서와 무관한 DB 사실이므로 DB에 직접 묻는다.
        """
        self._offered_names_this_turn.update(
            _normalize_course_name(r.get("course_name") or "")
            for r in offered
            if r.get("course_name")
        )
        shadowed = self._offered_names_this_turn | self.offered_course_names_this_term()
        return [
            {"course_id": r.get("course_id"), "course_name": r.get("course_name"),
             "category": r.get("category")}
            for r in not_offered
            if _normalize_course_name(r.get("course_name") or "") not in shadowed
        ]

    def _critical_missing_split(self) -> dict:
        """`critical_missing_required`를 **실제 개설 여부로 다시 갈라서** 돌려준다.

        `_compute_critical_missing_required`(roadmap_chat 공유)는 "이번 학기에 못 듣는
        필수"를 `courses.semester` — 카탈로그의 *권장* 학기 — 하나로만 판정한다.
        `course_offerings`를 보지 않으므로, 같은 과목명이 다른 교과목코드로 이번 학기에
        열려 있으면 **거짓 경고**가 된다.

        실제 사례: `공학작문및발표`는 카탈로그 `semester`가 `'1'`인데 2026-2학기에 24개
        분반이 열려 있다. 카탈로그만 보면 "2학기엔 개설되지 않아 넣을 수 없어요"라고
        써놓고 아래 시간표에는 그 과목이 들어가는 답변이 나간다.

        (이 교정이 처음 필요해진 계기였던 `일반물리학`은 실제로는 이름 잘림 버그였고
        PR #191이 뿌리를 뽑았다. 함께 적었던 `공학선형대수학`은 학생 스코프 안에서
        재현되지 않아 근거에서 뺀다 — 분반이 있는 행들이 전부 타 학과 소속이다.)

        그래서 이번 학기에 개설된 것은 경고에서 빼고 `missing_required_offered_this_term`
        으로 옮긴다 — 조용히 버리지 않는다. 그것들은 "미이수 필수인데 이번 학기에 담을 수
        있는 과목"이라 오히려 1순위 후보다.

        판정을 여기서 고치는 이유: `_compute_critical_missing_required`는 로드맵 챗과
        공유하는 함수라 이 세션에서 건드리지 않는다. 시간표 챗은 "이번 학기에 담을 수
        있나"만 필요하므로 소비 지점에서 개설 사실로 교정한다.
        """
        critical = _compute_critical_missing_required(
            self.db, self.user, roadmap_id=None, reference_semester=self.semester,
        )
        offered_names = self.offered_course_names_this_term()
        truly_missing: list[dict] = []
        actually_offered: list[dict] = []
        for item in critical:
            if _normalize_course_name(item.get("course_name") or "") in offered_names:
                actually_offered.append({
                    "course_id": item.get("course_id"),
                    "course_name": item.get("course_name"),
                    "category": item.get("category"),
                })
            else:
                truly_missing.append(item)
        payload: dict = {"critical_missing_required": truly_missing}
        if actually_offered:
            payload["missing_required_offered_this_term"] = actually_offered
            payload["missing_required_offered_note"] = (
                "카탈로그상 다른 학기 과목으로 표기돼 있지만 이번 학기에 **실제로 분반이 "
                "열려 있는** 미이수 필수 과목이다. 이번 학기에 담을 수 있으니 "
                "list_offered_courses로 분반을 찾아 우선 후보로 넣어라. "
                "절대 '이번 학기에 개설되지 않았다'고 말하지 마라 — 개설돼 있다."
            )
        return payload

    def get_student_context(self) -> dict:
        from app.domains.academics.graduation_progress import (
            compute_graduation_progress,
            liberal_areas_for_generation,
        )
        from app.domains.planning.history import project_curriculum_term

        # 균형교양 집계와 이수과목명 정규화가 둘 다 같은 user_id의 student_course_records를
        # 필요로 해서, 한 번만 조회해 양쪽에 넘긴다(중복 쿼리 방지).
        course_records = self.db.scalars(
            select(StudentCourseRecord).where(StudentCourseRecord.user_id == self.user.id)
        ).all()
        completed = _completed_course_norms(self.db, self.user.id, records=course_records)
        cap = _term_credit_cap(self.db, self.user)
        # 엇학기 대응 — target_term은 달력이고, 커리큘럼 상으로는 다른 학년/학기일 수 있다.
        target_grade, target_curr_sem = project_curriculum_term(
            self.db, self.user.id, self.year, self.semester
        )

        # 카테고리별 남은 학점을 노출 — LLM이 "전공필수 12학점 남음, 교양필수 3학점 남음"
        # 같은 breakdown을 보고 카테고리별로 훑도록 유도한다. 없으면 mini가 career_goal
        # 하나만 보고 좁게 검색해서 결국 소수 과목만 확정하는 문제가 있음(2026-08-10 관찰).
        remaining_by_category: list[dict] = []
        primary_curriculum_year: str | None = None
        try:
            progresses = compute_graduation_progress(
                self.db, self.user.id, program_types={"primary"}
            )
            if progresses:
                p = progresses[0]  # 주전공만 노출 (시간표는 로드맵 독립이라 부전공까진 안 봄)
                primary_curriculum_year = p.curriculum_year
                for c in p.categories:
                    if c.remaining_credits is None or c.remaining_credits <= 0:
                        continue
                    remaining_by_category.append({
                        "category": c.category_name,
                        "remaining_credits": float(c.remaining_credits),
                    })
        except Exception:  # noqa: BLE001 - 판정 실패 시 시간표 챗 자체가 죽으면 안 됨
            pass

        # One-Stop이 공식 판정한 영역과 입학 전 인정 학점에 학생이 직접 지정한 영역
        # 대체를 합쳐 시간표 LLM에도 구조화해 전달한다. 세대별(구/신체계) 부분집합만
        # 보여줘야 2021학번에게 "세계와 소통 미이수"처럼 해당 없는 영역을 들이밀지 않는다
        # (roadmap_chat.py의 같은 처리와 대칭).
        student_liberal_areas = liberal_areas_for_generation(primary_curriculum_year)
        liberal_completions = liberal_area_completions(
            self.db,
            self.user.id,
            student_liberal_areas,
            records=course_records,
        )

        completed_liberal_areas: list[dict] = []
        missing_liberal_areas: list[str] = []
        for area in student_liberal_areas:
            completion = liberal_completions[area]
            if not completion.completed:
                missing_liberal_areas.append(area)
                continue
            completed_liberal_areas.append({
                "area": area,
                # 묶음 입학 전 인정 학점은 영역별 배분을 알 수 없으므로 더하지 않는다.
                "credits": completion.direct_credits,
                "course_names": completion.course_names,
                "recognized_by_substitution": bool(completion.substituted_records),
            })

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
            # 학교 판정 기반 균형교양 현황. 시간표 추천 시 이미 채운 영역을 반복 추천하지
            # 않고 아직 비어 있는 영역을 우선하도록 시스템 프롬프트가 지시한다.
            "completed_liberal_areas": completed_liberal_areas,
            "missing_liberal_areas": missing_liberal_areas,
            # 카테고리별 부족분. 이 목록을 훑어 각 항목별로 list_offered_courses 호출해라.
            "remaining_by_category": remaining_by_category,
            # 이번 학기(target_term)에 개설 안 되는 미이수 필수 과목 목록. 비어있지
            # 않으면 finish_response에서 사용자에게 "이 필수 과목은 X학기 전용이라
            # 이번엔 못 담는다, 다음 학년도 X학기에 반드시" 라고 안내해라. 이 시간표
            # 조합에는 넣지 마라 (개설 안 됨). roadmap 챗의 동일 기능(critical_missing_
            # required)과 로직 공유. 로드맵이 없어도 SCR 기반으로 판정 가능.
            **self._critical_missing_split(),
            # 재수강 권유 후보 (성적 낮은 이수 과목). 사용자가 명시적으로 GPA 개선
            # 관심 표하거나 재수강 물을 때만 제시. 매번 강권 X. 로드맵 챗과 동일 로직.
            "retake_candidates": _compute_retake_candidates(self.db, self.user),
            # 선수과목 미이수라 이번 학기 시간표에 담기 부적절한 학과 과목. best-effort
            # description 파싱 기반. 이 목록의 course_id는 조합에 넣지 마라.
            "prereq_blocked": _compute_prereq_blocked(self.db, self.user, roadmap_id=None),
            # 사용자가 시간표 화면에서 직접 담아둔 강좌. **이미 확정된 부분**으로 보고
            # 그 위에 추가할 과목만 추천해라. build_timetable은 이걸 자동으로 고정해서
            # 조합을 짜므로 후보 풀에 다시 넣을 필요 없다.
            "current_timetable": self.current_timetable(),
        }

    def get_current_timetable(self) -> dict:
        """`get_current_timetable` 도구 본체. `current_timetable()`과 같은 값을 준다.

        `get_student_context` 안에도 같은 내용이 들어 있지만, 시간표를 바꾼 뒤 다시
        확인하려면 전체 컨텍스트(이수기록·요건·재수강 후보까지)를 통째로 다시 받아야
        했다. 대화 중간의 "지금 뭐 담겨 있지?"에는 이 도구 하나면 된다.
        """
        return self.current_timetable()

    def current_timetable(self) -> dict:
        """사용자가 시간표 UI에서 담아둔 현재 상태 요약."""
        locked = self.locked_sections()
        cap = _term_credit_cap(self.db, self.user)
        locked_credits = sum(s.credits or 0.0 for s in locked)
        # 이미 찬 요일·시간대. "월요일 오전은 이미 찼다" 같은 판단을 LLM이 바로 할 수 있게.
        occupied: dict[str, list[str]] = {}
        for section in locked:
            for time_slot in section.times:
                if not time_slot.day_of_week or time_slot.start_time is None:
                    continue
                occupied.setdefault(time_slot.day_of_week, []).append(
                    f"{time_slot.start_time.strftime('%H:%M')}-"
                    f"{time_slot.end_time.strftime('%H:%M')}"
                    if time_slot.end_time else time_slot.start_time.strftime("%H:%M")
                )
        return {
            "plan_id": self.plan_id,
            "offering_count": len(locked),
            "locked_credits": locked_credits,
            "credit_cap": cap,
            "remaining_credits_to_cap": max(0.0, cap - locked_credits),
            "occupied_slots": {day: sorted(slots) for day, slots in sorted(occupied.items())},
            "offerings": [
                {
                    "offering_id": s.offering_id,
                    "course_id": s.course_id,
                    "course_name": s.course_name,
                    "category": s.category,
                    "credits": s.credits,
                    "section": s.section,
                    "times": [
                        {
                            "day_of_week": t.day_of_week,
                            "start_time": t.start_time.strftime("%H:%M") if t.start_time else None,
                            "end_time": t.end_time.strftime("%H:%M") if t.end_time else None,
                        }
                        for t in s.times
                    ],
                }
                for s in locked
            ],
        }

    def _search_scope(self, program_type: str | None) -> tuple[int | None, int | None]:
        """검색 대상 학과·전공. program_type이 minor/dual/interdisciplinary면 그 프로그램의 학과.

        로드맵 챗 `search_courses`와 같은 규칙이다. 이게 없으면 부전공 학생의 시간표에
        부전공 학과 과목이 **아예 후보로 뜨지 않는다** — 골든 케이스 20(경영 주전공 +
        전자 부전공)에서 실제로 회로이론이 보이지 않아, 담을 수 있는 과목이 주전공
        1과목뿐인 상태로 매번 반복 상한까지 헤맸다.
        """
        if program_type and program_type != "primary":
            from app.domains.academics.models import UserAcademicProgram
            prog = self.db.scalars(
                select(UserAcademicProgram).filter_by(
                    user_id=self.user.id, program_type=program_type,
                ).where(UserAcademicProgram.status.in_(ACTIVE_PROGRAM_STATUSES))
            ).first()
            if prog is not None and prog.department_id is not None:
                return prog.department_id, prog.major_id
        return self.user.department_id, self.user.major_id

    def list_offered_courses(
        self, query: str | None = None, category: str | None = None,
        liberal_area: str | None = None,
        limit: int | None = None, program_type: str | None = None,
    ) -> dict:
        retriever = CurriculumRetriever(self.db)
        scope_dept_id, scope_major_id = self._search_scope(program_type)
        results = retriever.search(
            query=query or "",
            department_id=scope_dept_id,
            major_id=scope_major_id,
            curriculum_year=2026,
            filters={
                "semester": self.semester, "category": category,
                "general_education_area": liberal_area,
            },
        )
        cap = max(1, min(limit or 10, 30))
        candidates = list(results[:cap])

        # 과목명을 콕 집어 물은 경우(query 있음)에는 카탈로그 `semester` 필터를 한 번 더
        # 풀어서 이름으로 다시 찾는다. 이 필드는 "권장 학기"라 실제 개설과 자주 어긋나기
        # 때문이다 — 실측(2026-08): '공학작문및발표'는 2026-2학기 분반이 24개 열려 있는데
        # 그 행의 catalog semester가 '1'이라 2학기 검색에서 통째로 빠졌다. 개설 여부의
        # 진짜 근거는 `course_offerings`이지 `courses.semester`가 아니다.
        if query:
            seen_ids = {r.get("course_id") for r in candidates}
            unfiltered = retriever.search(
                query=query,
                department_id=scope_dept_id,
                major_id=scope_major_id,
                curriculum_year=2026,
                filters={"category": category, "general_education_area": liberal_area},
            )
            for r in unfiltered[:cap]:
                if r.get("course_id") not in seen_ids:
                    candidates.append(r)
                    seen_ids.add(r.get("course_id"))

        attached = [self._attach_offerings(r) for r in candidates]

        # 개설이 하나도 없는 과목을 `results`에 섞어두면 LLM이 `offered_sections: []`를
        # "일단 존재하는 과목"으로 읽고 시간표에 넣거나, 반대로 미개설 사실을 사용자에게
        # 안 알린다 (골든 케이스 21에서 관측: "공학작문 넣어줘"에 미개설을 명시하지 않고
        # 한 번은 시간표에 포함했다고 거짓 주장까지 했다). 담을 수 있는 것과 담을 수 없는
        # 것을 아예 다른 필드로 갈라서 오독의 여지를 없앤다.
        offered = [r for r in attached if r.get("offered_sections")]
        # **미개설 안내는 사용자가 이름을 콕 집어 물었을 때만 의미가 있다.**
        # 검색기는 의미 유사도로 뽑으므로, query='일반물리학'에도 '건강과레포츠',
        # '생명의료윤리' 같은 무관한 행이 딸려 온다(실 DB 확인). 카테고리만 걸고 훑는
        # 호출(`query` 없음)은 아예 "이 과목 담고 싶다"는 요청이 아니다. 그런 행까지
        # `matched_but_not_offered_this_term`에 넣으면 LLM이 사용자가 언급한 적도 없는
        # 과목을 붙잡고 "이번 학기에 개설되지 않았습니다"라고 알린다. 이 필드의 목적
        # ("네가 원한 그 과목을 못 담는다")에 맞게 이름이 실제로 매치되는 것만 남긴다.
        not_offered = self._filter_shadowed_not_offered(
            offered,
            [r for r in attached
             if not r.get("offered_sections") and _name_matches_query(r.get("course_name"), query)],
        )
        payload: dict = {"results": offered}
        if not_offered:
            payload["matched_but_not_offered_this_term"] = not_offered
            payload["not_offered_note"] = (
                f"위 과목들은 교육과정에는 있으나 {self.year}학년도 {self.semester}에 개설된 "
                "분반이 없다. 시간표에 넣을 수 없다. 사용자가 이 중 하나를 콕 집어 요청했다면 "
                "finish_response에서 '이번 학기에는 개설되지 않았습니다'라고 **명시적으로** "
                "알려라 — 넣었다고 하거나 조용히 빼면 안 된다."
            )

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
            if liberal_area:
                reason_parts.append(
                    f"liberal_area={liberal_area!r}로 매치 없음 — '외국어'/'융복합'은 "
                    "이 필터로 안 잡히니 category로 다시 찾아라"
                )
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

    def _sections_from_offering_ids(self, offering_ids: list[int]) -> list[_SectionInfo] | None:
        """offering_id 목록을 조합 탐색·검증이 공통으로 쓰는 _SectionInfo로 만든다.

        하나라도 존재하지 않으면 None (호출자가 사유를 정한다).
        """
        offerings = self.db.scalars(
            select(CourseOffering).where(CourseOffering.id.in_(offering_ids))
        ).all()
        if len(offerings) != len(set(offering_ids)):
            return None
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
        return sections

    def _completed_norms(self) -> set[str]:
        if self._completed_norms_cache is None:
            self._completed_norms_cache = _completed_course_norms(self.db, self.user.id)
        return self._completed_norms_cache

    def _prereq_blocked_course_ids(self) -> set[int]:
        """`prereq_blocked` 과목의 course_id 집합.

        기존엔 시스템 프롬프트로만 "이 목록은 후보에서 빼라"고 지시했는데, LLM이
        지시를 어기고 그대로 build_timetable에 넘기면 걸러낼 코드가 없어서 그대로
        시간표에 들어갔다(2026-08-23 live eval로 재현 — 선수과목 미이수 과목이
        조합에 포함됨). roadmap_chat.propose_change가 이미 이 목록을 코드 레벨에서
        강제 차단하는 것과 대칭을 맞춘다.
        """
        if self._prereq_blocked_cache is None:
            self._prereq_blocked_cache = {
                b["course_id"] for b in _compute_prereq_blocked(self.db, self.user, roadmap_id=None)
            }
        return self._prereq_blocked_cache

    def locked_sections(self) -> list[_SectionInfo]:
        """사용자가 시간표 UI에서 이미 담아둔 분반들.

        추천은 항상 이 위에 얹는다. 이걸 안 보면 (a) 이미 담은 과목을 또 추천하고
        (b) 담아둔 강의와 시간이 겹치는 분반을 추천해서, 사용자가 승인하는 순간
        깨진 시간표가 된다.
        """
        if self._locked_sections_cache is None:
            if self.plan_id is None:
                self._locked_sections_cache = []
            else:
                offering_ids = list(
                    self.db.scalars(
                        select(CoursePlanItem.offering_id)
                        .where(
                            CoursePlanItem.plan_id == self.plan_id,
                            CoursePlanItem.offering_id.is_not(None),
                        )
                        .order_by(CoursePlanItem.id)
                    )
                )
                self._locked_sections_cache = (
                    self._sections_from_offering_ids(offering_ids) or []
                ) if offering_ids else []
        return self._locked_sections_cache

    def validate_timetable(self, offering_ids: list[int]) -> dict:
        if not offering_ids:
            return {"ok": False, "reason": "empty_offering_ids"}
        sections = self._sections_from_offering_ids(offering_ids)
        if sections is None:
            return {"ok": False, "reason": "some_offerings_not_found"}
        times_by_offering = {s.offering_id: list(s.times) for s in sections}
        # 후보 목록에서 이미 걸렀더라도, LLM이 예전 턴의 offering_id를 기억해 다시 넣을 수
        # 있다. 검증 단계에서 한 번 더 막고 어떤 분반이 왜 안 되는지 알려준다.
        violations = [
            {"offering_id": s.offering_id,
             "reason": _times_violate_constraint(times_by_offering[s.offering_id], self.time_constraint)}
            for s in sections
            if _times_violate_constraint(times_by_offering[s.offering_id], self.time_constraint)
        ]
        if violations:
            return {
                "ok": False,
                "reason": "time_constraint_violation",
                "constraint": _describe_constraint(self.time_constraint or {}),
                "violations": violations,
                "hint": (
                    "사용자가 요청한 시간 제약을 어기는 분반이다. 이 offering_id들을 빼고 "
                    "다시 검증해라. 제약을 지키면 목표 학점에 못 미치면 억지로 채우지 말고 "
                    "finish_response에서 '제약을 지키면 최대 N학점까지 가능합니다'라고 설명해라."
                ),
            }

        # **같은 과목의 다른 분반을 동시에 담는 조합을 막는다.**
        # 예전엔 이 검사가 없어서 확률및통계 140분반(6612)+141분반(6613) 조합이
        # `ok: true, total_credits 6.0`으로 통과했다(2026-08-16 실계정 재현). 한 과목을
        # 두 번 수강하는 시간표인데 학점까지 이중 계산돼서, 목표 학점을 채운 것처럼
        # 보이는 가짜 조합이 그대로 사용자에게 나갔다. 시간이 안 겹치는 분반끼리는
        # 시간 충돌 검사로도 안 걸린다 — 과목 단위로 따로 봐야 한다.
        duplicates: list[dict] = []
        by_course: dict[int, list[_SectionInfo]] = {}
        for s in sections:
            by_course.setdefault(s.course_id, []).append(s)
        for course_id, group in by_course.items():
            if len(group) > 1:
                duplicates.append({
                    "course_id": course_id,
                    "course_name": group[0].course_name,
                    "offering_ids": [s.offering_id for s in group],
                    "sections": [s.section for s in group],
                })
        if duplicates:
            return {
                "ok": False,
                "reason": "duplicate_course",
                "duplicates": duplicates,
                "hint": (
                    "같은 과목의 서로 다른 분반을 한 시간표에 함께 넣었다. 한 과목은 분반 "
                    "하나만 수강한다. 각 과목마다 분반을 하나씩만 남기고 다시 검증해라."
                ),
            }

        # 이미 이수한 과목도 여기서 막는다. 프롬프트에만 적어둔 규칙이라 실제로 새고 있었다.
        completed = self._completed_norms()
        already = [
            {"offering_id": s.offering_id, "course_name": s.course_name}
            for s in sections
            if s.course_name and _normalize_course_name(s.course_name) in completed
        ]
        if already:
            return {
                "ok": False,
                "reason": "already_completed",
                "already_completed": already,
                "hint": (
                    "학생이 이미 이수한 과목이다. 재수강 목적이 아니면 시간표에서 빼고 "
                    "다시 검증해라."
                ),
            }

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

    def build_timetable(
        self,
        offering_ids: list[int],
        must_include_offering_ids: list[int] | None = None,
        target_credits: float | None = None,
        ignore_current_timetable: bool = False,
        credit_mode: str = "at_least",
    ) -> dict:
        """후보 분반 풀에서 시간 충돌 없는 시간표 조합을 **규칙 엔진이 직접 짜서** 돌려준다.

        LLM은 "어떤 과목을 후보로 볼지"만 정하고, 실제 조합 구성은 여기서 한다.
        걸러내는 것들(호출자가 몰라도 되게 여기서 처리):
          - 사용자가 시간표 UI에서 이미 담아둔 강좌 → 고정하고 그 위에 얹는다
          - 같은 과목의 여러 분반 → 과목당 하나만 선택
          - 사용자 요일·시간대 제약 위반 분반
          - 이미 이수한 과목
          - 선수과목 미이수(`prereq_blocked`)인 과목
          - 학점 상한 초과

        `credit_mode`:
          - `"at_least"`(기본) — `target_credits` **이상**을 목표로 최대한 채운다.
            자동 목표(상한의 80%)로 도는 평소 흐름이 이것이다.
          - `"exact"` — `target_credits`를 **넘지 않는다**. 사용자가 "18학점으로 짜줘"처럼
            숫자를 명시했을 때 쓴다. 정확히 못 맞추면 그 이하 최대로 내려가고,
            못 맞췄다는 사실을 `reaches_target_credits=false` + `below_target_note`로
            분명히 알린다 — 조용히 다른 학점을 내밀지 않는다.
            `target_credits` 없이 `"exact"`만 오면 맞출 기준이 없으므로 `at_least`로 되돌린다.
        """
        if not offering_ids:
            return {"ok": False, "reason": "empty_offering_ids"}
        must_include = set(must_include_offering_ids or [])
        pool_ids = list(dict.fromkeys([*offering_ids, *must_include]))
        sections = self._sections_from_offering_ids(pool_ids)
        if sections is None:
            return {"ok": False, "reason": "some_offerings_not_found"}
        # **호출자가 넘긴 순서로 되돌린다.** `_sections_from_offering_ids`는 `IN (...)`
        # 조회라 DB 행 순서(대개 offering_id 오름차순)로 돌아온다. 그대로 쓰면 도구
        # 설명("앞쪽이 우선 채택된다")과 실제 동작이 어긋나고, 아래 _MAX_COURSE_GROUPS
        # 절삭에서 LLM이 1순위로 넣은 과목이 잘려나간다(독립 리뷰 실측).
        pool_rank = {offering_id: index for index, offering_id in enumerate(pool_ids)}
        sections.sort(key=lambda s: pool_rank.get(s.offering_id, len(pool_ids)))

        # 사용자가 이미 담아둔 강좌를 고정 기반으로 깔고 시작한다. 그 학점만큼 상한이
        # 줄고, 그것과 시간이 겹치는 후보는 애초에 조합에 못 들어간다.
        locked = [] if ignore_current_timetable else self.locked_sections()
        locked_ids = {s.offering_id for s in locked}
        locked_course_ids = {s.course_id for s in locked}
        locked_credits = sum(s.credits or 0.0 for s in locked)

        cap = float(_term_credit_cap(self.db, self.user))

        # **"가볍게 듣고 싶어"만 LLM 인자를 덮어쓴다.** mini는 여기에 없는 숫자(16)를
        # 지어내 17학점을 내놨다(2026-08-20 실측). 숫자 목표는 LLM이 넘긴 값을 그대로
        # 쓴다 — 정규식으로 뽑던 것을 뺀 이유는 `_parse_credit_intent` 주석 참고.
        intent_note: str | None = None
        if self.credit_intent:
            intent = self.credit_intent
            if intent.get("style") == "light":
                light = min(_LIGHT_LOAD_CREDITS, cap)
                requested = light if target_credits is None else min(float(target_credits), light)
                intent_note = (
                    f"사용자가 '가볍게 듣고 싶다'고 했으므로 목표를 {requested:g}학점으로 "
                    "낮췄다(상한의 80% 자동 목표를 쓰지 않는다). 답변에서 자동 목표 숫자를 "
                    "언급하지 말고, 가볍게 짰다는 사실만 밝혀라."
                )
                target_credits = requested
                credit_mode = "at_least"

        # 기준 학점. at_least에서는 하한, exact에서는 넘지 말아야 할 정확한 목표다.
        target = float(target_credits) if target_credits is not None else max(1.0, cap * 0.8)
        # 기준 없이 exact만 오면 맞출 대상이 없다 — 자동 목표(상한의 80%)를 "정확히"로
        # 해석하면 사용자가 말한 적 없는 숫자에 시간표를 억지로 맞추게 된다.
        exact = credit_mode == "exact" and target_credits is not None
        completed = self._completed_norms()

        # 이미 담은 것만으로 상한이 찬 경우. 아래 탐색에 그냥 넘기면 조합을 못 만들고
        # "시간이 겹쳐서 성립하는 조합이 없다"는 엉뚱한 사유가 나간다.
        if locked and locked_credits >= cap:
            return {
                "ok": False,
                "reason": "credit_cap_already_reached",
                "credit_cap": cap,
                "locked_credits": locked_credits,
                "hint": (
                    f"사용자가 이미 담은 강좌만으로 학점 상한({cap:g})을 채웠다. 더 담을 수 "
                    "없다는 사실을 finish_response에서 알리고, 바꾸고 싶은 과목이 있는지 물어라."
                ),
            }

        dropped: list[dict] = []
        usable: list[_SectionInfo] = []
        for s in sections:
            if s.offering_id in locked_ids or s.course_id in locked_course_ids:
                dropped.append({"offering_id": s.offering_id, "course_name": s.course_name,
                                "reason": "이미 시간표에 담겨 있음"})
                continue
            reason = _times_violate_constraint(list(s.times), self.time_constraint)
            if reason:
                dropped.append({"offering_id": s.offering_id, "course_name": s.course_name,
                                "reason": reason})
                continue
            if s.course_name and _normalize_course_name(s.course_name) in completed:
                dropped.append({"offering_id": s.offering_id, "course_name": s.course_name,
                                "reason": "이미 이수한 과목"})
                continue
            if s.course_id in self._prereq_blocked_course_ids():
                dropped.append({"offering_id": s.offering_id, "course_name": s.course_name,
                                "reason": "선수과목 미이수로 이번 학기 담기 부적절"})
                continue
            conflict = next(
                (locked_section for locked_section in locked
                 if _sections_conflict(s, locked_section)),
                None,
            )
            if conflict is not None:
                dropped.append({
                    "offering_id": s.offering_id, "course_name": s.course_name,
                    "reason": f"이미 담은 '{conflict.course_name}'과 시간이 겹침",
                })
                continue
            usable.append(s)

        # 필수 지정 분반이 필터(이수 완료·고정분 충돌·시간 제약)에 걸려 사라졌으면
        # 조용히 무시하면 안 된다 — 사용자가 콕 집어 요청한 것이라 왜 못 넣는지 알려야 한다.
        usable_ids = {s.offering_id for s in usable}
        # **고정분은 이미 요구가 충족된 것이다.** `usable`에서는 "이미 시간표에 담겨 있음"
        # 으로 먼저 빠지므로, 빼주지 않으면 사용자가 담아둔 분반을 지정했을 때
        # "그 분반은 쓸 수 없습니다"라는 거짓 안내가 나간다. "140분반은 그대로 두고
        # 나머지 채워줘"는 아주 자연스러운 요청이다(독립 리뷰가 재현).
        # 같은 과목의 *다른* 분반을 지정한 경우는 locked_ids에 없으므로 계속 거절된다.
        missing_required = sorted(must_include - usable_ids - locked_ids)
        if missing_required:
            reasons = {d["offering_id"]: d["reason"] for d in dropped}
            return {
                "ok": False,
                "reason": "must_include_unavailable",
                "unavailable": [
                    {"offering_id": oid, "reason": reasons.get(oid, "후보에 없음")}
                    for oid in missing_required
                ],
                "hint": (
                    "반드시 포함하라고 지정한 분반을 쓸 수 없다. 위 사유를 사용자에게 그대로 "
                    "알리고, 같은 과목의 다른 분반을 넣을지 아니면 그 과목을 뺄지 물어라. "
                    "지정을 조용히 무시하고 다른 조합을 내지 마라."
                ),
            }

        if not usable:
            return {
                "ok": False,
                "reason": "no_usable_offerings",
                "dropped": dropped,
                "hint": (
                    "후보 분반이 제약·이수이력으로 전부 걸러졌다. list_offered_courses로 "
                    "다른 과목을 더 찾아 후보를 넓혀서 다시 호출하거나, 정말 담을 게 없으면 "
                    "finish_response에서 그 이유를 설명해라."
                ),
            }

        # 과목 단위로 묶는다. 그룹 순서 = LLM이 넘긴 offering_ids 순서(= 우선순위)이고,
        # must_include에 든 과목은 맨 앞 + 필수 표시. 그룹 안 분반은 시간 정보가 있는 것을
        # 앞세운다 — 시간 없는 분반은 어떤 조합과도 충돌하지 않아 먼저 뽑히는데, 그러면
        # 주간 시간표에 블록이 하나도 안 그려진다(timetable._sections_for_item과 같은 이유).
        order: list[int] = []
        grouped: dict[int, list[_SectionInfo]] = {}
        for s in usable:
            if s.course_id not in grouped:
                grouped[s.course_id] = []
                order.append(s.course_id)
            grouped[s.course_id].append(s)
        for group in grouped.values():
            group.sort(key=lambda s: 0 if s.has_time_info else 1)

        # **필수 지정은 분반 단위다.** 예전엔 course_id로 승격시켜서, "김교수님 140분반
        # 꼭 넣어줘"에 141분반을 담은 조합이 나왔다(도구 설명은 분반 단위라고 안내한다).
        # 그 과목 그룹에서 지정된 분반만 남긴다.
        required_course_ids = {s.course_id for s in usable if s.offering_id in must_include}
        for course_id in required_course_ids:
            pinned = [s for s in grouped[course_id] if s.offering_id in must_include]
            if pinned:
                grouped[course_id] = pinned
        order.sort(key=lambda cid: 0 if cid in required_course_ids else 1)
        kept, cut = order[:_MAX_COURSE_GROUPS], order[_MAX_COURSE_GROUPS:]
        # 절삭분을 조용히 버리면 "왜 그 과목이 안 들어갔는지"를 아무도 모른다.
        for cid in cut:
            for s in grouped[cid]:
                dropped.append({
                    "offering_id": s.offering_id, "course_name": s.course_name,
                    "reason": (
                        f"후보 과목이 많아 탐색에서 제외 (한 번에 최대 {_MAX_COURSE_GROUPS}과목). "
                        "꼭 넣어야 하면 must_include_offering_ids로 지정하거나 후보를 줄여 다시 호출해라."
                    ),
                })
        groups = [(cid in required_course_ids, grouped[cid]) for cid in kept]

        # 고정분을 뺀 나머지 예산 안에서만 새 과목을 찾는다.
        remaining_budget = cap - locked_credits
        combos, search_truncated = _search_feasible_combos(
            groups,
            credit_cap=remaining_budget,
            target_credits=max(0.0, target - locked_credits),
            exact=exact,
        )
        if not combos:
            # **왜 못 만들었는지를 구분한다.** 예전엔 전부 "시간이 겹쳐서"라고 답했는데,
            # 남은 학점 예산이 후보 중 제일 작은 과목보다도 적으면 시간과 무관하게
            # 아무것도 못 담는다. 그 경우 LLM이 헛되이 후보를 넓혀 재호출하고,
            # 사용자에게도 틀린 이유가 나간다(독립 리뷰 지적).
            cheapest = min((s.credits or 0.0 for s in usable), default=0.0)
            # exact인데 이미 담아둔 학점만으로 요청 학점을 채웠거나 넘긴 경우.
            # 학점 상한(cap) 기준으로만 보는 아래 분기는 이걸 못 잡아서, "후보 분반들이
            # 서로 시간이 겹쳐서 조합이 없다"는 엉뚱한 사유가 나간다 — 시간 문제가 아니다.
            if exact and target - locked_credits < cheapest:
                return {
                    "ok": False,
                    "reason": "exact_target_reached_by_locked",
                    "target_credits": target,
                    "locked_credits": locked_credits,
                    "cheapest_candidate_credits": cheapest,
                    "hint": (
                        f"사용자가 요청한 {target:g}학점 중 이미 담아둔 강좌가 "
                        f"{locked_credits:g}학점이라 남은 여유가 "
                        f"{max(0.0, target - locked_credits):g}학점뿐인데, 후보 중 가장 작은 "
                        f"과목이 {cheapest:g}학점이다. 시간이 겹쳐서가 아니다. "
                        "이미 담은 강좌만으로 요청 학점에 도달했다는 사실을 알리고, "
                        "바꾸고 싶은 과목이 있는지 물어라."
                    ),
                }
            if remaining_budget < cheapest:
                return {
                    "ok": False,
                    "reason": "credit_budget_exhausted",
                    "credit_cap": cap,
                    "locked_credits": locked_credits,
                    "remaining_budget": remaining_budget,
                    "cheapest_candidate_credits": cheapest,
                    "dropped": dropped,
                    "hint": (
                        f"시간 문제가 아니다. 학점 상한({cap:g})에서 이미 담은 "
                        f"{locked_credits:g}학점을 빼면 {remaining_budget:g}학점만 남는데, "
                        f"후보 중 가장 작은 과목이 {cheapest:g}학점이라 무엇도 못 담는다. "
                        "후보를 넓혀도 소용없다 — 사용자에게 학점 상한이 찼다는 사실과 "
                        "무엇을 빼야 하는지 물어라."
                    ),
                }
            return {
                "ok": False,
                "reason": "no_feasible_combination",
                "credit_cap": cap,
                "locked_credits": locked_credits,
                "target_credits": target,
                "dropped": dropped,
                "hint": (
                    "후보 분반들이 서로 시간이 겹쳐서 성립하는 조합이 없다"
                    + (" (필수 지정 과목을 반드시 포함하라는 조건 때문일 수 있다)."
                       if required_course_ids else ".")
                    + " list_offered_courses로 다른 시간대 과목을 더 찾아 후보를 넓혀서 "
                      "다시 호출해라."
                ),
            }

        # 랭킹은 고정분까지 합친 최종 시간표 모양으로 매긴다 — 사용자가 보는 건 합친 결과다.
        ranked = _rank_built_combos(
            [[*locked, *combo] for combo in combos], target_credits=target,
            prefer_fewer_days=self.prefer_fewer_days,
        )
        # 같은 분반 집합이 여러 번 나오면 하나만 남긴다.
        seen: set[tuple[int, ...]] = set()
        # **사용자 눈에 똑같아 보이는 조합도 하나만 남긴다.** offering_id만 다르고
        # 과목·이수구분·학점·요일·시간이 전부 같은 조합(= 같은 과목의 다른 분반이
        # 같은 시간대에 열린 경우)이 "후보 1/2/3"으로 나란히 나갔다. 2026-08-20 실계정
        # 실측: "12학점만 들을래"에 세 후보가 **글자 하나까지 동일하게** 렌더링됐다
        # (일반물리학·프로그래밍원리와실습·고전읽기와토론·인공지능과디지털사고).
        # 선택지를 셋 준 것처럼 보이지만 실제로는 하나다. 화면에 그려지는 값
        # (`_format_section_line` = `_render_schedule_summary`가 쓰는 것과 같은 함수)이
        # 같으면 같은 후보로 본다.
        seen_rendered: set[tuple[str, ...]] = set()
        schedules: list[dict] = []
        for combo in ranked:
            key = tuple(sorted(s.offering_id for s in combo))
            if key in seen:
                continue
            seen.add(key)
            course_lines = [_format_section_line(s) for s in combo]
            rendered = tuple(sorted(course_lines))
            if rendered in seen_rendered:
                continue
            seen_rendered.add(rendered)
            total = sum(s.credits or 0.0 for s in combo)
            days, gap = _schedule_shape(combo)
            schedules.append({
                # 고정분 + 추가분 전체. 시간표 담기 API가 멱등이라 그대로 적용해도 안전하다.
                "offering_ids": list(key),
                # 사용자에게 그대로 옮겨 적을 수 있는 과목 목록. 이게 없으면 LLM이 과목명을
                # 지어낸다 — 실측(2026-08-17)에서 '범주형 및 생존자료 분석'을
                # '데이터사이언스수학'으로 바꿔 써서, 화면의 시간표와 설명이 어긋났다.
                "course_lines": course_lines,
                "locked_offering_ids": sorted(locked_ids & set(key)),
                "added_offering_ids": sorted(set(key) - locked_ids),
                "total_credits": total,
                "distinct_days": len(days),
                "total_gap_minutes": gap,
                "reaches_target_credits": total >= target,
                "sections": [_serialize_section(s) for s in combo],
            })
            if len(schedules) >= _MAX_SCHEDULES_RETURNED:
                break

        for schedule in schedules:
            self.built_combos.append(list(schedule["offering_ids"]))

        payload: dict = {
            "ok": True,
            "credit_cap": cap,
            "target_credits": target,
            "credit_mode": "exact" if exact else "at_least",
            "schedules": schedules,
            "note": (
                "이 조합들은 규칙 엔진이 시간 충돌·학점 상한·과목 중복·시간 제약을 모두 "
                "확인해 만든 것이다. 그대로 finish_response의 schedules에 담아라 — "
                "offering_id를 직접 고쳐 넣지 마라(검증이 깨진다). "
                "**응답 본문의 과목명·학점·시간은 `course_lines`에 있는 값을 그대로 옮겨 적어라.** "
                "기억으로 쓰지 말고, 거기 없는 과목을 지어내지 마라 — 화면에 그려지는 시간표는 "
                "이 offering_ids라서 설명이 어긋나면 사용자가 잘못된 정보를 믿게 된다."
            ),
        }
        if intent_note:
            payload["credit_intent_note"] = intent_note
        if self.prefer_fewer_days:
            payload["shape_preference_note"] = (
                "사용자가 '공강 많게/몰아서'를 요청해서 **통학 요일 수가 적은 조합을 "
                "우선**해 랭킹했다. 답변에서는 '주 N일로 몰았다'처럼 요일 수로 설명해라 "
                "(각 조합의 실제 요일 수는 distinct_days에 있다)."
            )
        if locked:
            payload["locked_credits"] = locked_credits
            payload["locked_note"] = (
                f"사용자가 시간표에 이미 담아둔 {len(locked)}개 강좌를 고정한 채로 짠 조합이다. "
                "offering_ids에는 그 고정분도 포함돼 있고, 새로 추가되는 건 "
                "added_offering_ids다. 설명할 때 '기존 O개에 △△을 더했다'는 식으로 "
                "무엇이 새로 들어갔는지 밝혀라."
            )
        if dropped:
            payload["dropped"] = dropped
        if search_truncated:
            payload["search_truncated"] = True
        best_credits = max((s["total_credits"] for s in schedules), default=0.0)
        if not any(s["reaches_target_credits"] for s in schedules):
            # 후보를 넓혀도 학점이 안 늘면 그만 시도하라고 알려준다. 엔진이 이미 학점을
            # 최대화하므로 같은 후보로 다시 부르는 건 순수 낭비인데, 그냥 "더 넓혀라"라고만
            # 하면 mini가 상한(8 iterations)까지 계속 재시도한다(2026-08-17 관측).
            if exact:
                # exact는 "모자란다"가 아니라 "요청한 숫자에 안 떨어진다"는 얘기다.
                # 여기서 아래 at_least 문구를 그대로 쓰면 LLM이 "최대 N학점까지
                # 가능합니다"라고 답하는데, 사용자는 최대치를 물은 게 아니라 정확히
                # 그 학점을 요청한 것이라 동문서답이 된다.
                short = target - best_credits
                payload["below_target_note"] = (
                    f"사용자가 요청한 {target:g}학점에 **정확히 떨어지는 조합이 없다** "
                    f"(가능한 최선 {best_credits:g}학점, {short:g}학점 모자람). "
                    + ("후보가 많아 탐색을 끝까지 하지 못했으니 후보를 우선순위 높은 것 위주로 "
                       "줄여서 한 번 더 시도해볼 수 있다. "
                       if search_truncated else
                       "다른 학점 조합의 과목을 후보에 넣으면 맞을 수 있으니 "
                       "list_offered_courses로 **한 번만 더** 넓혀서 시도해라. ")
                    + "그래도 안 맞으면 finish_response에서 "
                    f"'{target:g}학점에 딱 맞는 조합이 없어서 {best_credits:g}학점으로 짰다'고 "
                    "**반드시 먼저 밝혀라** — 요청한 학점인 것처럼 넘어가지 마라."
                )
            elif search_truncated:
                # 예산에 걸려 안 본 가지가 남아 있다. 여기서 "최대 N학점"이라고 단언하면
                # 실제로는 가능한 조합을 두고 사용자에게 거짓말을 하게 된다.
                payload["below_target_note"] = (
                    f"목표 학점({target:g})에 도달하는 조합을 찾지 못했다(현재 최대 "
                    f"{best_credits:g}학점). 다만 **후보가 많아 탐색을 끝까지 하지 못했으므로 "
                    "'이게 최대'라고 단언하지 마라.** 후보를 좀 줄여서(우선순위 높은 과목 위주로) "
                    "다시 호출하면 더 나은 조합이 나올 수 있다."
                )
            elif self._build_calls and best_credits <= self._best_built_credits:
                payload["below_target_note"] = (
                    f"목표 학점({target:g})에 못 미치는데 후보를 바꿔도 최대 학점이 "
                    f"{self._best_built_credits:g}에서 늘지 않았다. **더 시도하지 말고** "
                    "지금 조합으로 finish_response 하면서 '이 조건으로는 최대 "
                    f"{best_credits:g}학점까지 가능합니다'라고 이유와 함께 설명해라."
                )
            else:
                payload["below_target_note"] = (
                    f"목표 학점({target:g})에 도달하는 조합이 없다(현재 최대 {best_credits:g}학점). "
                    "아직 안 훑은 이수구분이 있으면 list_offered_courses로 후보를 넓혀 "
                    "**한 번만 더** 시도하고, 그래도 안 늘면 finish_response에서 "
                    "'이 조건으로는 최대 N학점까지 가능합니다'라고 설명해라."
                )
        self._build_calls += 1
        self._best_built_credits = max(self._best_built_credits, best_credits)
        return payload

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

    def _sibling_course_ids(self, course_id: int) -> list[int]:
        """같은 과목의 중복 행들(id 집합)을 돌려준다.

        부산대는 같은 과목명에 개설 주체별로 **다른 교과목코드**를 발급한다 (ZE/DM/CB/MS
        접두사). 그래서 `courses`에 같은 (과목명, 학과, 전공)인데 course_code만 다른 행들이
        생긴다 — **2026-08-20 기준 4개 그룹 13행**(`공학작문및발표` 5, `인공지능과디지털사고` 4,
        `대학영어` 2, `약리학(I)` 2). 예전에 적혀 있던 "7개 그룹 19행"은 낡은 수치다.
        PR #191이 `일반물리학` 이름 잘림을 고치면서 한 그룹이 빠졌다(5개 15행 → 4개 13행).
        (같이 잘렸던 `이산수학`은 이수구분이 전공기초/전공선택으로 갈려 **애초에 이 그룹에
        든 적이 없다** — 그룹 키에 `category`가 들어가기 때문이다.)
        이건 적재 버그가 아니라 원본 데이터의 성질이고,
        코드는 수강신청에 필요하므로 **행을 합치면 안 된다**.

        문제는 개설(`course_offerings`)이 그 형제 행들에 흩어져 붙는다는 것이다:

            공학작문및발표  ZE1000043(1326): 24개  ← 카탈로그 semester가 '1'이라 2학기 검색에서 빠짐
                          ZE1000119(6166):  0개  ← 검색이 집어오던 행
            인공지능과디지털사고  1개 행에 65개, 나머지 3행에 0개
            대학영어            1개 행에 88개, 나머지 1행에 0개

        한 행만 보면 분반 0인 행을 집어 "이번 학기 미개설"이라고 오답한다(2026-08-13 실제
        사고). 그래서 개설 조회는 **검색이 집어온 행 하나가 아니라 같은 과목 전체**를 본다.

        판정 기준이 (과목명, 학과, 전공, **이수구분, 학점**)인 이유:

        - 학과·전공을 빼면 남의 학과 분반을 보여준다. 일반물리학(I)은 31개 학과에 각각
          존재하고, 정보컴퓨터공학부도 컴퓨터공학(36)·인공지능(35)·디자인테크놀로지(34)
          전공이 major_id로 나뉘어 각자 이산수학을 갖는다.
        - **이수구분·학점을 빼면 요건이 다른 과목을 합친다.** 컴퓨터공학전공 안에도
          이산수학이 두 항목이다: CB1501027(1-1, 전공기초)과 CB2001104(2-2, 전공선택).
          분반을 합쳐 보여주면 학생이 어느 요건을 채우는지 오인한다 — 졸업요건 집계가
          이수구분 기준이라 실제로 결과가 달라진다.

        현황 점검: `python scripts/report_course_alias_groups.py`
        """
        course = self.db.get(Course, course_id)
        if course is None:
            return [course_id]
        siblings = self.db.scalars(
            select(Course.id).where(
                Course.course_name == course.course_name,
                Course.department_id.is_(None) if course.department_id is None
                else Course.department_id == course.department_id,
                Course.major_id.is_(None) if course.major_id is None
                else Course.major_id == course.major_id,
                Course.category.is_(None) if course.category is None
                else Course.category == course.category,
                Course.credits.is_(None) if course.credits is None
                else Course.credits == course.credits,
            )
        ).all()
        return list(siblings) or [course_id]

    def _attach_offerings(self, retriever_result: dict) -> dict:
        """CurriculumRetriever 결과에 이번 학기 실제 offered_sections(offering_id·분반·시간)를 붙인다."""
        course_id = retriever_result.get("course_id")
        if course_id is None:
            return {**retriever_result, "offered_sections": []}
        offerings = self.db.scalars(
            select(CourseOffering).where(
                CourseOffering.course_id.in_(self._sibling_course_ids(course_id)),
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
        sections = []
        excluded = []
        for o in offerings:
            times = times_by_off.get(o.id, [])
            view = {
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
                    for t in times
                ],
            }
            # 사용자 제약을 어기는 분반은 후보에서 아예 뺀다. LLM이 "시간 보고 걸러라"를
            # 지키지 않는 게 관측됐으므로(케이스 18), 볼 수 없게 만드는 쪽이 확실하다.
            violation = _times_violate_constraint(times, self.time_constraint)
            if violation:
                excluded.append({**view, "excluded_reason": violation})
            else:
                sections.append(view)

        result = {**retriever_result, "offered_sections": sections}
        if excluded:
            # 왜 빠졌는지는 알려준다 — 제약을 지키면 학점이 모자란 상황을 LLM이
            # 사용자에게 설명할 수 있어야 한다.
            result["excluded_by_time_constraint"] = excluded
        return result

    def record_validated_ok(self, offering_ids: list[int]) -> None:
        """validate_timetable이 ok로 통과시킨 조합을 기억한다.

        LLM이 검증까지 해놓고 결과를 message 텍스트에만 적고 `schedules`는 비워서 내는
        일이 있다 — UI는 schedules를 렌더링하므로 사용자에겐 시간표가 안 보인다.
        되돌릴 때 "이 조합을 넣어라"라고 구체적으로 지목하기 위해 저장한다.
        """
        if offering_ids:
            self.validated_ok_combos.append(list(offering_ids))

    def engine_approved_sets(self) -> set[frozenset[int]]:
        """규칙 엔진이 승인한 분반 조합들. `build_timetable`이 만든 것 + `validate_timetable`이
        ok를 준 것.

        finish_response가 제출한 조합이 이 안에 없으면 LLM이 지어낸 조합이라는 뜻이다
        (실제로 관측되는 실패 — 엔진 결과에서 offering_id를 몇 개 바꿔 넣는다).
        """
        return {frozenset(combo) for combo in (*self.built_combos, *self.validated_ok_combos)}

    def has_any_offering(self) -> bool:
        """이번 학기에 개설 자체가 하나라도 있는지 (제약 필터 적용 후 기준).

        "조합을 만들 수 있었는데 안 만든 것"과 "정말 아무것도 없는 것"을 구분하는 데 쓴다.

        예전 구현은 해당 학기 **전교 개설 분반을 전부 객체로 적재**한 다음
        `CourseTime.offering_id.in_([...])`로 시간을 다시 긁었다. 두 가지가 문제였다:

        - 존재 여부만 알면 되는데 전수 적재를 챗 턴마다 했다.
        - `in_()`이 분반 하나당 bind 파라미터를 하나씩 만든다. 실제 수강편람은 학기당
          수천~수만 분반이라 PostgreSQL의 bind 파라미터 상한(65535)에 걸려 **쿼리가
          통째로 실패**할 수 있었다.

        제약이 없으면 존재 확인 한 방이면 끝이고, 있으면 조인 한 번으로 (분반, 시간)을
        받아 파이썬 판정 로직은 그대로 쓴다 — 판정 규칙을 SQL로 옮겨 적으면 후보 필터
        쪽 로직과 갈라질 위험이 있어서 그대로 둔다.
        """
        if not self.time_constraint:
            return (
                self.db.scalar(
                    select(CourseOffering.id)
                    .where(
                        CourseOffering.year == self.year,
                        CourseOffering.semester == self.semester,
                    )
                    .limit(1)
                )
                is not None
            )

        times_by_off: dict[int, list[CourseTime]] = {}
        rows = self.db.execute(
            select(CourseOffering.id, CourseTime)
            .outerjoin(CourseTime, CourseTime.offering_id == CourseOffering.id)
            .where(
                CourseOffering.year == self.year,
                CourseOffering.semester == self.semester,
            )
        ).all()
        for offering_id, course_time in rows:
            bucket = times_by_off.setdefault(offering_id, [])
            # outer join이라 시간표가 없는 분반은 course_time이 None으로 온다.
            # 그 경우도 "시간 정보 없음"으로 판정에 넘겨야 기존 동작과 같다.
            if course_time is not None:
                bucket.append(course_time)

        return any(
            _times_violate_constraint(times, self.time_constraint) is None
            for times in times_by_off.values()
        )

    def schedules_violating_constraint(self, schedules: list[dict]) -> list[dict]:
        """finish_response가 낸 조합 중 시간 제약을 어기는 offering 목록.

        제약이 없으면 항상 빈 리스트라 기존 동작에 영향이 없다.
        """
        if not self.time_constraint or not schedules:
            return []
        ids = {
            oid
            for s in schedules
            for oid in (s.get("offering_ids") or [])
            if isinstance(oid, int)
        }
        if not ids:
            return []
        times_by_offering: dict[int, list[CourseTime]] = {oid: [] for oid in ids}
        for t in self.db.scalars(
            select(CourseTime).where(CourseTime.offering_id.in_(ids))
        ).all():
            times_by_offering.setdefault(t.offering_id, []).append(t)
        bad = []
        for oid in sorted(ids):
            reason = _times_violate_constraint(times_by_offering.get(oid, []), self.time_constraint)
            if reason:
                bad.append({"offering_id": oid, "reason": reason})
        return bad

    # ------------ 디스패치 ------------

    def dispatch(self, name: str, tool_input: dict) -> dict:
        handler = {
            "get_student_context": self.get_student_context,
            "get_current_timetable": self.get_current_timetable,
            "list_offered_courses": self.list_offered_courses,
            "search_by_career": self.search_by_career,
            "check_prereqs": self.check_prereqs,
            "build_timetable": self.build_timetable,
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


def _render_schedule_summary(ctx: "_TimeTableToolContext", schedules: list[dict]) -> str:
    """제안된 시간표의 과목 목록을 **DB 값 그대로** 렌더링한다.

    LLM에게 목록을 맡기면 과목명과 학점을 지어낸다 — 2026-08-17 실측에서 '범주형 및
    생존자료 분석'을 '데이터사이언스수학'으로 바꿔 쓰고, 9학점 조합을 15학점이라고
    설명했다. 화면에 그려지는 시간표는 offering_ids라서 그 순간 설명과 시간표가 어긋난다.
    그래서 목록은 LLM이 쓰지 않고(프롬프트에서 금지) 여기서 붙인다.
    """
    locked_ids = {s.offering_id for s in ctx.locked_sections()}
    blocks: list[str] = []
    for index, schedule in enumerate(schedules, start=1):
        offering_ids = [oid for oid in (schedule.get("offering_ids") or []) if isinstance(oid, int)]
        if not offering_ids:
            continue
        sections = ctx._sections_from_offering_ids(offering_ids)
        if not sections:
            continue
        sections.sort(key=lambda s: (s.category or "", s.course_name or ""))
        total = sum(s.credits or 0.0 for s in sections)
        header = f"📋 후보 {index} — 총 {total:g}학점" if len(schedules) > 1 else f"📋 총 {total:g}학점"
        lines = [header]
        for section in sections:
            mark = " (이미 담김)" if section.offering_id in locked_ids else ""
            lines.append(f"- {_format_section_line(section)}{mark}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _resolve_plan_id(
    db: Session, user: User, year: str, semester: str, plan_id: int | None
) -> int | None:
    """추천의 기반이 될 시간표(course_plans) 하나를 고른다.

    프론트가 열어둔 시간표를 `plan_id`로 넘겨주면 그걸 쓰고, 안 넘어오면 그 학기의
    시간표 중 가장 최근에 수정한 것을 쓴다 — 사용자가 방금 과목을 담고 챗을 여는
    흐름에서 대개 그게 화면에 떠 있는 시간표다. 남의 시간표거나 학기가 다르면 무시한다
    (조용히 None으로 두고 백지에서 추천한다 — 여기서 예외를 던지면 챗 자체가 죽는다).
    """
    if plan_id is not None:
        plan = db.get(CoursePlan, plan_id)
        # 학기 검사를 빠뜨리면 지난 학기 시간표가 고정분으로 깔려 **학점 상한을 먹고
        # 시간대를 막는다.** 지금 UI는 학기로 필터해 목록을 주지만 엔드포인트는 공개다.
        if (
            plan is not None
            and plan.user_id == user.id
            and plan.year == year
            and plan.semester == semester
        ):
            return plan.id
        return None
    return db.scalar(
        select(CoursePlan.id)
        .where(
            CoursePlan.user_id == user.id,
            CoursePlan.year == year,
            CoursePlan.semester == semester,
        )
        .order_by(CoursePlan.updated_at.desc().nullslast(), CoursePlan.id.desc())
        .limit(1)
    )


def run_timetable_chat(
    db: Session,
    user: User,
    year: str,
    semester: str,
    message: str,
    session_id: int | None = None,
    plan_id: int | None = None,
) -> dict:
    """시간표 AI 상담 실행. session_id 없으면 (user, year, semester)의 최근 세션을
    이어 쓰거나 새로 만든다.

    `plan_id`는 사용자가 시간표 화면에서 직접 담아둔 강좌들이 있는 수강계획이다. 추천은
    그 위에 얹는다 (`_resolve_plan_id` 참고).

    반환: {"reply": str, "schedules": [{"offering_ids": [...], "rationale": "..."}, ...],
           "iterations": int, "tool_calls": [...], "session_id": int,
           "locked_offering_ids": [...]}
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
            # 시간 제약은 이번 턴 메시지에서 파싱한다. 파싱되면 도구 계층이 후보 필터링과
            # 검증 거절을 모두 담당하므로 LLM이 규칙을 어겨도 잘못된 조합이 안 나간다.
            time_constraint = _parse_time_constraint(message)
            # 학점 목표도 같은 이유로 이번 턴 메시지에서 규칙으로 뽑는다 — 잡히면
            # build_timetable이 LLM 인자 대신 이 값을 쓴다.
            credit_intent = _parse_credit_intent(message)
            resolved_plan_id = _resolve_plan_id(db, user, year, semester, plan_id)
            ctx = _TimeTableToolContext(db=db, user=user, year=year, semester=semester,
                                        time_constraint=time_constraint,
                                        plan_id=resolved_plan_id,
                                        credit_intent=credit_intent,
                                        prefer_fewer_days=_prefers_fewer_days(message))
            llm = _build_llm().bind_tools(_TOOLS, tool_choice="any")
            system_prompt, applied_rules = _build_timetable_system_prompt(db, user, semester)

        # 관측: 어떤 학생에게 어떤 조건부 규칙이 활성화됐는지 + 프롬프트 총 길이.
        trace.add_metadata({
            "applied_conditional_rules": applied_rules,
            "system_prompt_chars": len(system_prompt),
            # Langfuse에서 "제약이 걸린 대화에서 무슨 일이 있었나"를 필터링할 수 있게 남긴다.
            "time_constraint": _describe_constraint(time_constraint) if time_constraint else None,
            "credit_intent": credit_intent,
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
        # finish_response를 되돌린 적 있는지. 각각 한 번만 — 무한 왕복 방지.
        constraint_retry_used = False
        unvalidated_retry_used = False
        empty_schedules_retry_used = False

        # 가드가 finish_response를 되돌린 횟수. 이 반복은 탐색이 아니라 강제 교정이라
        # 탐색 예산(MAX_TOOL_ITERATIONS)에서 빼주지 않는다 — 안 그러면 가드 때문에 남은
        # 예산이 줄어 정작 시간표를 못 짜고 상한에 걸린다(케이스 20·21에서 8 iterations
        # 도달 관측). 되돌림은 종류별 1회씩이라 이 보정은 최대 3회로 묶여 있다.
        guard_retries = 0
        iteration = 0
        while iteration < MAX_TOOL_ITERATIONS + guard_retries:
            iteration += 1
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
                    proposed = args.get("schedules", []) or []
                    # 최종 관문. 여기까지 온 조합에 제약 위반이 남아 있으면 그대로 사용자에게
                    # 나간다 — 케이스 18에서 관측된 실패가 정확히 이 경로였다(위반 조합 +
                    # "월수 오전에 진행되는"이라는 거짓 rationale). 한 번은 되돌려 고치게 하고,
                    # 그래도 고쳐오지 않으면 위반 조합만 떨어뜨린다.
                    # validate_timetable을 한 번도 안 부르고 끝내려는 두 경로를 막는다.
                    # 케이스 18에서 둘 다 관측됐다:
                    #  (a) 조건에 맞는 분반이 2개(시간도 안 겹침) 있는데 빈 schedules로 종료
                    #  (b) 조합을 제출하면서 검증은 한 번도 안 함 — 충돌·학점 상한 미확인
                    # 프롬프트에 후퇴 문구를 넣으면 LLM이 그 경로를 선호한다는 게 이미
                    # 관측돼 있어(2026-08-12) 도구 계층에서 되돌린다. 한 번만.
                    # 예전 가드는 "validate_timetable을 한 번이라도 불렀나"만 봤다. 그래서
                    # 엔진 결과에서 offering_id를 몇 개 바꿔 끼운 조합은 그대로 통과했다.
                    # 지금은 **제출한 조합 자체가 엔진 승인 목록에 있는지**를 본다.
                    approved = ctx.engine_approved_sets()
                    unapproved = [
                        s for s in proposed
                        if frozenset(s.get("offering_ids") or []) not in approved
                    ]
                    never_built = not proposed and not approved and ctx.has_any_offering()
                    if not unvalidated_retry_used and (unapproved or never_built):
                        unvalidated_retry_used = True
                        guard_retries += 1
                        hint = (
                            "제출한 조합이 build_timetable/validate_timetable이 승인한 조합이 "
                            "아니다. 엔진이 만들지 않은 조합은 시간 충돌·학점 상한이 확인되지 "
                            "않은 것이라 사용자에게 낼 수 없다."
                            if unapproved else
                            "이번 학기 개설 과목이 있는데 build_timetable을 한 번도 호출하지 "
                            "않고 빈 시간표로 끝내려 했다."
                        )
                        messages.append(ToolMessage(
                            content=json.dumps({
                                "ok": False,
                                "reason": "schedule_not_engine_approved",
                                "engine_approved_schedules": [
                                    sorted(combo) for combo in approved
                                ],
                                "hint": (
                                    f"{hint} list_offered_courses로 후보 분반을 10~25개 모아 "
                                    "build_timetable에 넘기고, 돌아온 schedules의 offering_ids를 "
                                    "**그대로** schedules에 담아 다시 finish_response를 호출해라 "
                                    "(offering_id를 직접 고치지 마라). 정말 성립하는 조합이 "
                                    "없다면 무엇을 시도했고 왜 안 되는지 message에 설명해라."
                                ),
                            }, ensure_ascii=False),
                            tool_call_id=call_id or "",
                        ))
                        break

                    # 검증까지 해놓고 결과를 message 텍스트에만 적고 schedules는 비워서 내는
                    # 경우. UI가 렌더링하는 건 schedules라 사용자에겐 시간표가 안 보인다.
                    if not proposed and approved and not empty_schedules_retry_used:
                        empty_schedules_retry_used = True
                        guard_retries += 1
                        messages.append(ToolMessage(
                            content=json.dumps({
                                "ok": False,
                                "reason": "validated_combo_not_submitted",
                                "validated_ok_combos": [sorted(combo) for combo in approved],
                                "hint": (
                                    "validate_timetable로 ok를 받은 조합이 있는데 schedules를 "
                                    "비워서 finish_response를 호출했다. 사용자 화면에는 message "
                                    "본문이 아니라 schedules가 시간표로 렌더링되므로, 검증에 성공한 "
                                    "위 조합을 schedules에 담아 다시 호출해라."
                                ),
                            }, ensure_ascii=False),
                            tool_call_id=call_id or "",
                        ))
                        break

                    bad = ctx.schedules_violating_constraint(proposed)
                    if bad and not constraint_retry_used:
                        constraint_retry_used = True
                        guard_retries += 1
                        messages.append(ToolMessage(
                            content=json.dumps({
                                "ok": False,
                                "reason": "time_constraint_violation",
                                "constraint": _describe_constraint(time_constraint or {}),
                                "violations": bad,
                                "hint": (
                                    "위 offering들은 사용자가 요청한 시간 제약을 어긴다. 해당 분반을 "
                                    "빼고 finish_response를 다시 호출해라. message 본문에서도 그 과목·"
                                    "시간 언급을 지워라 — 조합에 없는 과목을 있는 것처럼 설명하면 안 된다. "
                                    "제약을 지키면 학점이 모자라면 그 사실을 그대로 설명해라."
                                ),
                            }, ensure_ascii=False),
                            tool_call_id=call_id or "",
                        ))
                        break  # 다음 iteration에서 LLM이 다시 finish_response를 부른다
                    reply_text = args.get("message", "")
                    if bad:
                        violating_ids = {v["offering_id"] for v in bad}
                        proposed = [
                            s for s in proposed
                            if not (set(s.get("offering_ids") or []) & violating_ids)
                        ]
                    schedules = proposed
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
                if name == "validate_timetable" and isinstance(result, dict) and result.get("ok"):
                    ctx.record_validated_ok(args.get("offering_ids") or [])
                messages.append(
                    ToolMessage(
                        content=json.dumps(result, ensure_ascii=False, default=str),
                        tool_call_id=call_id or "",
                    )
                )
            if finished:
                break

        # 반복 상한에 걸려 finish_response를 못 부르고 끝났는데, 규칙 엔진은 이미 성립하는
        # 조합을 만들어둔 경우가 있다. 그걸 버리고 "못 만들었어요"를 내보내면 사용자는
        # 있는 시간표를 못 받는다 — 엔진 결과를 그대로 쓴다(설명은 우리가 붙인다).
        if not schedules and ctx.built_combos:
            schedules = [{
                "offering_ids": ctx.built_combos[0],
                "rationale": "규칙 엔진이 시간 충돌 없이 구성한 조합",
            }]
            if not reply_text or not reply_text.strip():
                reply_text = (
                    "설명을 정리하다 중간에 멈췄지만, 시간 충돌 없이 성립하는 조합은 "
                    "찾았어요. 아래 후보를 확인해보시고 조정할 부분을 말씀해 주세요."
                )

        # 빈 응답 폴백. mini가 finish_response를 안 부르거나 message="" 로 부르면
        # 유저 화면에 아무것도 안 뜬다 — 최소한 무슨 상황인지 알려주는 문구로 대체.
        if not reply_text or not reply_text.strip():
            reply_text = (
                "죄송해요, 이번엔 시간표 후보를 정리하지 못했어요. "
                "요청을 조금 더 구체적으로 다시 말씀해 주세요 "
                "(예: '전공 필수 위주로', '월수금만', '오전 몰빵')."
            )

        # 내부 식별자·도구 이름이 답변에 섞여 나가는 걸 마지막에 한 번 더 막는다
        # (`_scrub_internal_terms` 참고 — "아래 조합의 offering_id를 …" 실측).
        reply_text = _scrub_internal_terms(reply_text)

        # 과목 목록은 LLM이 아니라 여기서 붙인다 (`_render_schedule_summary` 참고).
        if schedules:
            summary = _render_schedule_summary(ctx, schedules)
            if summary:
                reply_text = f"{reply_text.rstrip()}\n\n{summary}"

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
            "iterations": iteration,
        })
        # 대시보드용 정량 스코어.
        trace.score("finished_with_tool", finished)
        trace.score("iterations_used", iteration)
        trace.score(
            "iteration_efficiency",
            round(1 - (iteration - 1) / max(MAX_TOOL_ITERATIONS - 1, 1), 3),
        )
        trace.score("tool_calls", non_finish_tool_calls)
        trace.score("schedules_returned", len(schedules))

    return {
        "reply": reply_text,
        "schedules": schedules,
        "iterations": iteration,
        "tool_calls": tool_call_log,
        "session_id": session.id,
        # 사용자가 이미 담아둔 분반. 추천 조합에는 이것도 포함돼 있어서, 프론트가
        # "새로 추가되는 것"과 "원래 있던 것"을 구분해 보여줄 수 있어야 한다.
        "locked_offering_ids": [s.offering_id for s in ctx.locked_sections()],
        "plan_id": ctx.plan_id,
    }
