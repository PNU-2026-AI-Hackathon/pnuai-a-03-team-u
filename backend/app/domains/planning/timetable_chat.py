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
from app.domains.academics.models import StudentCourseRecord
from app.domains.courses.models import Course, CourseOffering, CourseTime
from app.domains.planning.models import CourseRoadmap, CourseRoadmapItem
from app.domains.planning.roadmap_chat import _build_llm
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


_SYSTEM_PROMPT = """너는 부산대 학생의 이번 학기 시간표를 함께 짜주는 상담 AI다.

**사용자에게 보이는 모든 응답은 finish_response 도구로만 전달한다.** 일반 텍스트로
직접 답하면 사용자에게 아무것도 안 보인다.

**너는 시간표를 직접 만들지 않는다.** 시간이 겹치는 시간표를 내놓으면 수강신청이
막힌다. 대신:
1. `get_student_context`로 학생 수강기록·진로·학과·학점상한을 먼저 본다.
2. `list_offered_courses`나 `search_by_career`로 이번 학기 실제 개설 과목을 찾는다.
3. 후보 과목 조합을 골라 `validate_timetable`에 넘긴다 — 규칙 코드가 시간 충돌·학점
   상한을 검증해 유효한 조합만 되돌려준다.
4. 유효 조합을 얻으면 `finish_response`에 후보 시간표(section_ids 배열들)와 사용자에게
   보여줄 설명 메시지를 담아 넘긴다.

**우선순위**:
- 학생이 이미 이수한 과목은 다시 추천하지 않는다 (`get_student_context.completed_courses`).
- 학생이 "이번 학기는 가볍게 듣고 싶어" 같은 학점/과목수 선호를 말하면 그 방향으로
  조합을 좁힌다.
- 진로 관련 과목을 우선 후보로 올린다 (`search_by_career` 사용).
- 사용자가 로드맵을 언급하거나 "내 계획대로" 같은 표현을 쓰면 그때만 `get_roadmap_hint`를
  호출한다. 그 외엔 로드맵을 조회하지 않는다.

**저장 흐름과의 관계**: 사용자가 UI에서 시간표를 저장하면 서버가 그 조합을 이번 학기
로드맵 항목으로 upsert 한다(같은 학기·같은 과목이면 조용히 스킵). 그래서 후보를 뽑을 때
사용자가 이미 이번 학기 로드맵에 등록해 둔 과목과 겹치면, 자동으로 걸러 넣지 말고
**finish_response에서 "OO는 이미 이번 학기 로드맵에 있어서 저장하면 스킵됩니다"라고
사용자에게 알려줘라.** 사용자가 "그래도 저장하겠다"고 하면 그대로 조합에 포함해라
(중복은 서버가 알아서 스킵함). 로드맵 조회는 이 경우에도 `get_roadmap_hint`를 써라 —
로드맵 언급이 없다면 굳이 물어보진 마라(같은 학기 중복 여부는 사용자가 저장 시점에 UI에서
스킵 안내로도 알 수 있으니 필수는 아니다).

**선수과목 확인**: `check_prereqs`로 학생이 필요한 사전 이수를 마쳤는지 확인한다. 선수과목
정보가 없으면 그냥 이수기록에 이름으로 대조한다.

한국어로, 간결하게 답해라.
"""


_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_student_context",
            "description": (
                "학생의 학과·진로·이수기록·이번 학기 학점 상한을 조회한다. "
                "새 후보를 뽑기 전에 반드시 먼저 호출해라."
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
                        "description": "이수구분 필터 ('전공필수', '전공선택', '교양선택' 등). 로드맵 채팅과 같은 어휘.",
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
        completed = _completed_course_norms(self.db, self.user.id)
        return {
            "student_id": self.user.id,
            "department_id": self.user.department_id,
            "major_id": self.user.major_id,
            "career_goal": self.user.career_goal,
            "term_credit_cap": _term_credit_cap(self.db, self.user),
            "target_term": {"year": self.year, "semester": self.semester},
            "completed_course_names": sorted(completed),
        }

    def list_offered_courses(
        self, query: str | None = None, category: str | None = None, limit: int | None = None
    ) -> dict:
        retriever = CurriculumRetriever(self.db)
        results = retriever.search(
            query=query or "",
            filters={
                "department_id": self.user.department_id,
                "major_id": self.user.major_id,
                "semester": self.semester,
                "category": category,
            },
            top_k=max(1, min(limit or 10, 30)),
        )
        return {"results": [self._attach_offerings(r) for r in results]}

    def search_by_career(self, career_hint: str | None = None, limit: int | None = None) -> dict:
        hint = career_hint or self.user.career_goal
        if not hint:
            return {"results": [], "note": "학생 career_goal이 비어 있고 career_hint도 없음."}
        keywords = expand_career_query(hint)
        retriever = CurriculumRetriever(self.db)
        seen: dict[int, dict] = {}
        for kw in keywords:
            results = retriever.search(
                query=kw,
                filters={
                    "department_id": self.user.department_id,
                    "major_id": self.user.major_id,
                    "semester": self.semester,
                },
                top_k=5,
            )
            for r in results:
                cid = r.get("course_id")
                if cid is not None and cid not in seen:
                    seen[cid] = self._attach_offerings(r)
                    if len(seen) >= (limit or 10):
                        break
            if len(seen) >= (limit or 10):
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
        if name == "get_student_context":
            return self.get_student_context()
        if name == "list_offered_courses":
            return self.list_offered_courses(**tool_input)
        if name == "search_by_career":
            return self.search_by_career(**tool_input)
        if name == "check_prereqs":
            return self.check_prereqs(**tool_input)
        if name == "validate_timetable":
            return self.validate_timetable(**tool_input)
        if name == "get_roadmap_hint":
            return self.get_roadmap_hint()
        return {"error": f"unknown_tool:{name}"}


def run_timetable_chat(
    db: Session,
    user: User,
    year: str,
    semester: str,
    message: str,
    history: list[dict] | None = None,
) -> dict:
    """스파이크 진입점. 스테이트리스: 대화 히스토리는 클라이언트가 관리.

    history: [{"role": "user"|"assistant", "content": "..."}, ...]
    반환: {"reply": str, "schedules": [{"offering_ids": [...], "rationale": "..."}, ...],
            "iterations": int, "tool_calls": [...]}
    """
    ctx = _TimeTableToolContext(db=db, user=user, year=year, semester=semester)
    llm = _build_llm().bind_tools(_TOOLS, tool_choice="any")

    messages: list = [SystemMessage(content=_SYSTEM_PROMPT)]
    for h in history or []:
        role = h.get("role")
        content = h.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=message))

    reply_text = ""
    schedules: list[dict] = []
    tool_call_log: list[dict] = []

    for iteration in range(MAX_TOOL_ITERATIONS):
        ai_msg = llm.invoke(messages)
        messages.append(ai_msg)
        tool_calls = getattr(ai_msg, "tool_calls", None) or []
        if not tool_calls:
            reply_text = ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
            break
        finished = False
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
            result = ctx.dispatch(name, args or {})
            messages.append(
                ToolMessage(
                    content=json.dumps(result, ensure_ascii=False, default=str),
                    tool_call_id=call_id or "",
                )
            )
        if finished:
            break

    return {
        "reply": reply_text,
        "schedules": schedules,
        "iterations": iteration + 1,
        "tool_calls": tool_call_log,
    }
