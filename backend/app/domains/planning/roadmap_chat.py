"""로드맵 AI 상담. Anthropic tool-calling으로 로드맵 변경안을 "제안"한다.

Agent는 course_roadmap_items를 절대 직접 쓰지 않는다 — 항상 pending_roadmap_changes에
제안만 쌓고, 사용자가 confirm 엔드포인트(POST /me/roadmaps/{id}/agent/confirm)로
승인한 항목만 실제로 반영된다(human-in-the-loop). 생성/수정/삭제 모두 이 절차를 거친다.

LangGraph 같은 그래프 오케스트레이션은 쓰지 않는다 — 단일 에이전트가 도구 몇 개를
반복 호출하다 최종 텍스트로 답하는 단순 루프라서 SDK의 tool loop만으로 충분하다.
대화 상태는 클라이언트가 매번 들고 있는 게 아니라 course_roadmap_chat_messages에
서버가 영속화한다(로드맵당 하나의 연속 대화).

과목 후보 검색(search_courses)은 RAG 담당자가 만든 CurriculumRetriever
(app/ai/rag/curriculum_retriever.py)를 그대로 쓴다 — pgvector 임베딩 검색이
가능하면 그걸 쓰고, 안 되면 courses 카탈로그 구조화 필터로 자동 폴백한다.
"""

from __future__ import annotations

import json

from anthropic import Anthropic
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

MODEL = "claude-sonnet-5"
MAX_TOOL_ITERATIONS = 6

_SYSTEM_PROMPT = """너는 부산대학교 학생의 4년 학사 로드맵을 함께 짜주는 상담 AI다.

- 학생의 졸업요건 남은 학점(get_graduation_progress)과 현재 로드맵(get_roadmap_items)을
  먼저 확인하고 답해라. 짐작으로 과목을 추천하지 마라.
- 과목을 추천할 때는 반드시 search_courses로 실재하는 과목을 찾아 course_id를 확인한 뒤
  propose_change(action="create")로 제안해라. 존재를 확인하지 않은 과목명을 답변에 넣지 마라.
- 이미 로드맵에 있거나(get_roadmap_items) 이미 이수한 과목은 다시 추천하지 마라.
- 기존 항목의 학기/학년을 바꾸고 싶으면 propose_change(action="update", item_id=...)를,
  항목을 빼고 싶으면 propose_change(action="delete", item_id=...)를 써라. 절대
  course_roadmap_items를 직접 바꿀 수 있는 방법은 없다 — 항상 이 제안 도구를 거친다.
- **너는 실제로 아무것도 저장하지 않는다.** propose_change는 "제안"만 만든다. 답변
  마지막에는 반드시 "이 변경을 반영할까요?"처럼 사용자 확인을 구하는 문장을 넣고,
  사용자가 승인해야만 실제로 반영된다는 걸 분명히 말해라.
- 학생이 이미 만족한 이수구분에는 무리하게 과목을 더 넣지 말고, 부족한 이수구분 위주로
  추천해라.
- 한국어로, 간결하게 답해라.
"""

_TOOLS = [
    {
        "name": "get_graduation_progress",
        "description": "학생의 주전공 졸업요건 대비 이수구분별 남은 학점을 조회한다.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_roadmap_items",
        "description": "현재 로드맵에 들어있는 모든 항목(학년/학기/과목/상태/출처)을 조회한다.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_courses",
        "description": "과목명/키워드로 학생 학과·교육과정연도에 맞는 교육과정표를 검색한다(RAG). course_id를 얻으려면 반드시 이걸 먼저 호출해야 한다.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "검색할 과목명 키워드"}},
            "required": ["query"],
        },
    },
    {
        "name": "propose_change",
        "description": "로드맵 변경(추가/수정/삭제)을 제안한다. 실제 저장은 사용자 승인 후에만 일어난다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "update", "delete"]},
                "item_id": {"type": "integer", "description": "update/delete일 때 대상 항목 id"},
                "course_id": {"type": "integer", "description": "create/update일 때 search_courses로 확인한 과목 id"},
                "planned_year": {"type": "string"},
                "planned_semester": {"type": "string", "description": "예: '1학기', '2학기'"},
                "planned_grade": {"type": "integer"},
                "reason": {"type": "string", "description": "이 변경을 제안하는 이유"},
            },
            "required": ["action", "reason"],
        },
    },
]


def _get_client() -> Anthropic:
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY가 설정되지 않았습니다 (.env 확인)")
    return Anthropic(api_key=settings.ANTHROPIC_API_KEY)


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
    messages = [{"role": m.role, "content": m.content} for m in history]

    client = _get_client()
    ctx = _ToolContext(db, user, roadmap)

    final_text = ""
    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=_SYSTEM_PROMPT,
            tools=_TOOLS,
            messages=messages,
        )

        tool_uses = [block for block in response.content if block.type == "tool_use"]
        text_blocks = [block.text for block in response.content if block.type == "text"]
        if text_blocks:
            final_text = "\n".join(text_blocks)

        if response.stop_reason != "tool_use" or not tool_uses:
            break

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for tool_use in tool_uses:
            result = ctx.dispatch(tool_use.name, tool_use.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
        messages.append({"role": "user", "content": tool_results})

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
