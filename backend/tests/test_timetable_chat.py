"""시간표 LLM 에이전트 스파이크 테스트.

목표: 도구가 시간 충돌·학점 상한을 정확히 판정하는지 검증. LLM 자체는 mock으로 대체해
스크립트된 tool_calls 시퀀스가 예상대로 흐르는지 확인한다.
"""

import datetime
import json
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.domains.academics.models import (
    College, Department, GraduationRequirement, Major, School, StudentCourseRecord,
    UserAcademicProgram,
)
from app.domains.courses.models import Course, CourseOffering, CourseTime
from app.domains.planning import timetable_chat as timetable_chat_mod
from app.domains.planning.models import (
    CourseRoadmap, CourseRoadmapItem, PendingRoadmapChange,
    TimetableChatMessage, TimetableChatSession,
)
from app.domains.planning.timetable_chat import _TimeTableToolContext, run_timetable_chat
from app.domains.users.models import User


_TABLES = [
    School.__table__, College.__table__, Department.__table__, Major.__table__,
    User.__table__, Course.__table__, CourseOffering.__table__, CourseTime.__table__,
    CourseRoadmap.__table__, CourseRoadmapItem.__table__, PendingRoadmapChange.__table__,
    UserAcademicProgram.__table__, GraduationRequirement.__table__,
    StudentCourseRecord.__table__,
    TimetableChatSession.__table__, TimetableChatMessage.__table__,
]


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=_TABLES)
    return sessionmaker(bind=engine)()


def _make_student(db, department_id=100, major_id=None):
    user = User(
        id=1, email="t@example.com", password_hash="x", name="테스트",
        department_id=department_id, major_id=major_id, career_goal="백엔드",
    )
    db.add(user)
    db.flush()
    return user


def _add_course_with_offering(
    db, *, course_id, offering_id, name, credits, day, start, end,
    year="2026", semester="2학기", category="전공선택",
):
    db.add(Course(
        id=course_id, course_name=name, category=category, credits=credits,
        department_id=100, year="3", semester="2",
    ))
    db.add(CourseOffering(
        id=offering_id, course_id=course_id, year=year, semester=semester,
        section="001", professor="교수",
    ))
    db.add(CourseTime(
        offering_id=offering_id, day_of_week=day,
        start_time=datetime.time.fromisoformat(start),
        end_time=datetime.time.fromisoformat(end),
    ))


class ValidateTimetableTest(unittest.TestCase):
    """validate_timetable이 실제 시간 충돌을 정확히 잡는지 — 스파이크의 핵심 안전장치."""

    def test_no_conflict_returns_ok(self):
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="A", credits=3.0,
                                  day="월", start="09:00", end="10:15")
        _add_course_with_offering(db, course_id=2, offering_id=102, name="B", credits=3.0,
                                  day="화", start="09:00", end="10:15")
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        result = ctx.validate_timetable(offering_ids=[101, 102])

        self.assertTrue(result["ok"])
        self.assertEqual(0, len(result["conflicts"]))
        self.assertEqual(6.0, result["total_credits"])

    def test_same_day_overlapping_time_detected_as_conflict(self):
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="A", credits=3.0,
                                  day="월", start="09:00", end="10:30")
        _add_course_with_offering(db, course_id=2, offering_id=102, name="B", credits=3.0,
                                  day="월", start="10:00", end="11:15")
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        result = ctx.validate_timetable(offering_ids=[101, 102])

        self.assertFalse(result["ok"])
        self.assertEqual(1, len(result["conflicts"]))

    def test_over_credit_cap_returns_not_ok(self):
        db = _make_db()
        user = _make_student(db)
        # 학점 상한이 이 학생은 19 (졸업요건 없으므로 기본값)
        for i in range(7):
            _add_course_with_offering(
                db, course_id=i + 1, offering_id=100 + i, name=f"과목{i}", credits=3.0,
                day="월화수목금토일"[i], start="09:00", end="10:15",
            )
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        result = ctx.validate_timetable(offering_ids=[100 + i for i in range(7)])

        self.assertEqual(21.0, result["total_credits"])
        self.assertEqual(19, result["credit_cap"])
        self.assertTrue(result["over_credit_cap"])
        self.assertFalse(result["ok"])


class StudentContextTest(unittest.TestCase):
    def test_get_student_context_includes_completed_courses_and_career(self):
        db = _make_db()
        user = _make_student(db)
        db.add_all([
            StudentCourseRecord(
                user_id=user.id, raw_course_name="자료구조", credits=3.0,
                year=2024, semester="1학기",
            ),
            StudentCourseRecord(
                user_id=user.id, raw_course_name="운영체제", credits=3.0,
                year=2024, semester="2학기",
            ),
        ])
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        result = ctx.get_student_context()

        self.assertEqual("백엔드", result["career_goal"])
        self.assertEqual({"year": "2026", "semester": "2학기"}, result["target_term"])
        self.assertIn("자료구조", result["completed_course_names"])
        self.assertIn("운영체제", result["completed_course_names"])
        self.assertIn("term_credit_cap", result)


class RunTimetableChatIntegrationTest(unittest.TestCase):
    """LLM을 스크립트된 tool_calls로 mock해 전체 루프가 도구를 실제로 호출하고
    finish_response에서 검증된 시간표를 반환하는지 검증한다.
    """

    def test_scripted_llm_flow_returns_validated_schedule(self):
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="백엔드시스템", credits=3.0,
                                  day="월", start="09:00", end="10:15")
        _add_course_with_offering(db, course_id=2, offering_id=102, name="서버프로그래밍", credits=3.0,
                                  day="화", start="09:00", end="10:15")
        db.flush()

        # 스크립트: get_student_context → validate_timetable → finish_response
        script = [
            [{"name": "get_student_context", "args": {}, "id": "c1"}],
            [{"name": "validate_timetable", "args": {"offering_ids": [101, 102]}, "id": "c2"}],
            [{
                "name": "finish_response",
                "args": {
                    "message": "백엔드 진로에 맞춰 두 과목을 짜봤어요.",
                    "schedules": [
                        {"offering_ids": [101, 102], "rationale": "월화 오전, 3+3학점."},
                    ],
                },
                "id": "c3",
            }],
        ]

        class _ScriptedLLM:
            def __init__(self, script):
                self._script = list(script)

            def bind_tools(self, tools, tool_choice=None):
                return self

            def invoke(self, messages, config=None):
                calls = self._script.pop(0)
                msg = MagicMock()
                msg.content = ""
                msg.tool_calls = calls
                return msg

        with patch.object(timetable_chat_mod, "_build_llm", return_value=_ScriptedLLM(script)):
            result = run_timetable_chat(
                db=db, user=user, year="2026", semester="2학기",
                message="백엔드 하고 싶은데 이번 학기 뭐 들으면 좋아요?",
            )

        self.assertEqual("백엔드 진로에 맞춰 두 과목을 짜봤어요.", result["reply"])
        self.assertEqual(1, len(result["schedules"]))
        self.assertEqual([101, 102], result["schedules"][0]["offering_ids"])
        # 도구 호출 순서 확인
        tool_names = [c["name"] for c in result["tool_calls"]]
        self.assertEqual(["get_student_context", "validate_timetable", "finish_response"], tool_names)
        # 세션 저장 확인: session_id가 응답에 있고, 메시지 2건(user+assistant) 저장됐음
        self.assertIn("session_id", result)
        session_id = result["session_id"]
        self.assertIsNotNone(session_id)
        messages = db.query(TimetableChatMessage).filter(
            TimetableChatMessage.session_id == session_id
        ).order_by(TimetableChatMessage.id).all()
        self.assertEqual(2, len(messages))
        self.assertEqual("user", messages[0].role)
        self.assertEqual("assistant", messages[1].role)
        self.assertEqual("백엔드 진로에 맞춰 두 과목을 짜봤어요.", messages[1].content)


class SessionPersistenceTest(unittest.TestCase):
    """(user, year, semester) 세션 CRUD + run_timetable_chat 세션 이어쓰기 검증."""

    def test_consecutive_calls_reuse_same_session(self):
        """session_id 명시 없이 연속 호출하면 같은 세션에 append. history도 DB에서 로딩."""
        db = _make_db()
        db.add(School(id=1, name="테스트")); db.flush()
        db.add(College(id=1, school_id=1, name="테스트대학")); db.flush()
        db.add(Department(id=100, college_id=1, name="테스트학과")); db.flush()
        user = _make_student(db, department_id=100)
        db.commit()

        class _AlwaysFinishLLM:
            def __init__(self):
                self.observed_message_counts: list[int] = []
            def bind_tools(self, tools, tool_choice=None): return self
            def invoke(self, messages, config=None):
                # human/AI 메시지 카운트 기록 (system 프롬프트 1개 제외)
                self.observed_message_counts.append(len(messages) - 1)
                msg = MagicMock()
                msg.content = ""
                msg.tool_calls = [{
                    "name": "finish_response", "id": "c",
                    "args": {"message": f"응답#{len(self.observed_message_counts)}", "schedules": []},
                }]
                return msg

        llm = _AlwaysFinishLLM()
        with patch.object(timetable_chat_mod, "_build_llm", return_value=llm):
            r1 = run_timetable_chat(db=db, user=user, year="2026", semester="2학기", message="첫 질문")
            r2 = run_timetable_chat(db=db, user=user, year="2026", semester="2학기", message="두 번째 질문")

        # 두 호출이 같은 세션 이어씀
        self.assertEqual(r1["session_id"], r2["session_id"])
        # 첫 호출은 히스토리 1(방금 저장한 유저 메시지), 두 번째 호출은 3(prev user+assistant + 이번 user)
        self.assertEqual([1, 3], llm.observed_message_counts)
        # DB에 4개 메시지 (user·assistant × 2)
        msgs = db.query(TimetableChatMessage).order_by(TimetableChatMessage.id).all()
        self.assertEqual(4, len(msgs))
        self.assertEqual(["user", "assistant", "user", "assistant"], [m.role for m in msgs])

    def test_wrong_user_session_id_rejected(self):
        db = _make_db()
        db.add(School(id=1, name="테스트")); db.flush()
        db.add(College(id=1, school_id=1, name="테스트대학")); db.flush()
        db.add(Department(id=100, college_id=1, name="테스트학과")); db.flush()
        user_a = _make_student(db, department_id=100)
        # 다른 유저의 세션
        other_session = TimetableChatSession(user_id=999, year="2026", semester="2학기", title="다른 유저")
        db.add(other_session); db.commit()

        class _FinishLLM:
            def bind_tools(self, tools, tool_choice=None): return self
            def invoke(self, messages, config=None): raise AssertionError("불려선 안 됨")

        with patch.object(timetable_chat_mod, "_build_llm", return_value=_FinishLLM()):
            with self.assertRaises(ValueError):
                run_timetable_chat(
                    db=db, user=user_a, year="2026", semester="2학기",
                    message="x", session_id=other_session.id,
                )

    def test_session_term_mismatch_rejected(self):
        """세션의 (year, semester)와 요청이 다르면 명시적으로 거절 — 컨텍스트 오염 방지."""
        db = _make_db()
        db.add(School(id=1, name="테스트")); db.flush()
        db.add(College(id=1, school_id=1, name="테스트대학")); db.flush()
        db.add(Department(id=100, college_id=1, name="테스트학과")); db.flush()
        user = _make_student(db, department_id=100)
        sess = TimetableChatSession(user_id=user.id, year="2026", semester="1학기", title="봄학기")
        db.add(sess); db.commit()

        class _FinishLLM:
            def bind_tools(self, tools, tool_choice=None): return self
            def invoke(self, messages, config=None): raise AssertionError("불려선 안 됨")

        with patch.object(timetable_chat_mod, "_build_llm", return_value=_FinishLLM()):
            with self.assertRaises(ValueError):
                run_timetable_chat(
                    db=db, user=user, year="2026", semester="2학기",  # 세션은 1학기인데 요청은 2학기
                    message="x", session_id=sess.id,
                )


if __name__ == "__main__":
    unittest.main()
