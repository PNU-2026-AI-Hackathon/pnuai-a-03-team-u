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

import json

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.rag.curriculum_retriever import CurriculumRetriever
from app.core.config import settings
from app.domains.academics.graduation_progress import compute_graduation_progress
from app.domains.courses.models import Course
from app.domains.academics.models import UserAcademicProgram
from app.domains.planning.models import (
    CourseRoadmap,
    CourseRoadmapChatMessage,
    CourseRoadmapItem,
    PendingRoadmapChange,
)
from app.domains.users.models import User

_DEFAULT_CURRICULUM_YEAR = 2026

MAX_TOOL_ITERATIONS = 8

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
- search_courses 결과에 description(교과목개요)이 있으면 과목명만 보고 판단하지 말고
  그 내용을 실제로 읽고 학생의 진로/관심사와 맞는지 확인해라. 과목명에 키워드가 없어도
  description 내용상 관련 있는 과목일 수 있다(반대의 경우도 있다 — description이 없다고
  관련 없다고 단정하지는 마라, 그냥 참고 정보가 없는 것뿐이다).
- 이미 로드맵에 있거나(get_roadmap_items) 이미 이수한 과목은 다시 추천하지 마라.
- 기존 항목의 학기/학년을 바꾸고 싶으면 propose_change(action="update", item_id=...)를,
  항목을 빼고 싶으면 propose_change(action="delete", item_id=...)를 써라. 절대
  course_roadmap_items를 직접 바꿀 수 있는 방법은 없다 — 항상 이 제안 도구를 거친다.
- **너는 실제로 아무것도 저장하지 않는다.** propose_change는 "제안"만 만든다.
  finish_response 메시지 마지막에는 반드시 "이 변경을 반영할까요?"처럼 사용자 확인을
  구하는 문장을 넣고, 사용자가 승인해야만 실제로 반영된다는 걸 분명히 말해라.
- 학생이 이미 만족한 이수구분에는 무리하게 과목을 더 넣지 말고, 부족한 이수구분 위주로
  추천해라.
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
            "description": "현재 로드맵에 들어있는 모든 항목(학년/학기/과목/상태/출처)을 조회한다.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_courses",
            "description": "과목명/키워드로 학생 학과·교육과정연도에 맞는 교육과정표를 검색한다(RAG). course_id를 얻으려면 반드시 이걸 먼저 호출해야 한다. 결과의 description 필드에 교과목개요(있는 과목만)가 같이 온다.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "검색할 과목명 키워드"}},
                "required": ["query"],
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
                    "planned_year": {"type": "string"},
                    "planned_semester": {"type": "string", "description": "예: '1학기', '2학기'"},
                    "planned_grade": {"type": "integer"},
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

    def get_roadmap_items(self) -> dict:
        items = self.db.scalars(
            select(CourseRoadmapItem)
            .where(CourseRoadmapItem.roadmap_id == self.roadmap.id)
            .order_by(CourseRoadmapItem.planned_year, CourseRoadmapItem.planned_semester)
        ).all()
        return {
            "items": [
                {
                    "id": item.id,
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
            ]
        }

    def search_courses(self, query: str) -> dict:
        query = (query or "").strip()
        if not query or self.user.department_id is None:
            return {"results": []}

        program = self.db.scalars(
            select(UserAcademicProgram).filter_by(user_id=self.user.id, program_type="primary")
        ).first()
        curriculum_year = program.curriculum_year if program and program.curriculum_year else _DEFAULT_CURRICULUM_YEAR

        retriever = CurriculumRetriever(self.db)
        results = retriever.search(
            query=query,
            department_id=self.user.department_id,
            major_id=self.user.major_id,
            curriculum_year=curriculum_year,
            filters={"limit": 10},
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

        if action in ("create", "update") and course_id is not None:
            course = self.db.get(Course, course_id)
            if course is None:
                return {"error": f"course_id {course_id}는 존재하지 않는 과목입니다"}

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


def run_roadmap_chat(db: Session, user: User, roadmap: CourseRoadmap, message: str) -> dict:
    """사용자 메시지를 처리하고, AI 답변 + 이번 턴에 만들어진 pending change 목록을 반환한다.

    이 함수는 course_roadmap_items를 절대 쓰지 않는다 — 실제 반영은
    apply_pending_changes()가 사용자 승인 후에 한다.
    """
    db.add(CourseRoadmapChatMessage(roadmap_id=roadmap.id, role="user", content=message))
    db.flush()

    history = _load_history(db, roadmap.id)
    messages: list = [SystemMessage(content=_SYSTEM_PROMPT)]
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
