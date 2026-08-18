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
    CoursePlan, CoursePlanItem, CourseRoadmap, CourseRoadmapItem, PendingRoadmapChange,
    TimetableChatMessage, TimetableChatSession,
)
from app.domains.planning.timetable_chat import (
    _TimeTableToolContext, clear_chat_messages, run_timetable_chat,
)
from app.domains.users.models import User


_TABLES = [
    School.__table__, College.__table__, Department.__table__, Major.__table__,
    User.__table__, Course.__table__, CourseOffering.__table__, CourseTime.__table__,
    CourseRoadmap.__table__, CourseRoadmapItem.__table__, PendingRoadmapChange.__table__,
    UserAcademicProgram.__table__, GraduationRequirement.__table__,
    StudentCourseRecord.__table__,
    TimetableChatSession.__table__, TimetableChatMessage.__table__,
    # 시간표 챗이 "사용자가 UI에서 직접 담아둔 강좌"를 읽는다 — 없으면 run_timetable_chat이
    # 테이블 부재로 죽는다.
    CoursePlan.__table__, CoursePlanItem.__table__,
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


def _add_section(db, *, course_id, offering_id, section, day, start, end,
                 year="2026", semester="2학기"):
    """이미 있는 과목에 분반을 하나 더 붙인다 (같은 course_id, 다른 offering)."""
    db.add(CourseOffering(
        id=offering_id, course_id=course_id, year=year, semester=semester,
        section=section, professor="교수",
    ))
    db.add(CourseTime(
        offering_id=offering_id, day_of_week=day,
        start_time=datetime.time.fromisoformat(start),
        end_time=datetime.time.fromisoformat(end),
    ))


class ValidateTimetableRejectsInvalidCombosTest(unittest.TestCase):
    """검증기가 조용히 통과시키던 두 가지 — 실계정 재현으로 발견 (2026-08-16)."""

    def test_same_course_two_sections_rejected(self):
        """같은 과목의 다른 분반을 함께 담으면 거절해야 한다.

        시간이 안 겹치면 충돌 검사에 안 걸려서 예전엔 `ok: true`로 통과했다. 실제로
        확률및통계 140분반+141분반 조합이 '6학점'으로 집계돼, 한 과목을 두 번 듣는
        시간표가 목표 학점을 채운 것처럼 보였다.
        """
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="확률및통계",
                                  credits=3.0, day="화", start="09:00", end="10:15")
        _add_section(db, course_id=1, offering_id=102, section="141",
                     day="화", start="10:30", end="11:45")
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        result = ctx.validate_timetable(offering_ids=[101, 102])

        self.assertFalse(result["ok"])
        self.assertEqual("duplicate_course", result["reason"])
        self.assertEqual([101, 102], result["duplicates"][0]["offering_ids"])

    def test_already_completed_course_rejected(self):
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="자료구조",
                                  credits=3.0, day="월", start="09:00", end="10:15")
        db.add(StudentCourseRecord(
            user_id=user.id, raw_course_name="자료구조", credits=3.0,
            year=2024, semester="1학기",
        ))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        result = ctx.validate_timetable(offering_ids=[101])

        self.assertFalse(result["ok"])
        self.assertEqual("already_completed", result["reason"])


class BuildTimetableTest(unittest.TestCase):
    """조합 구성을 LLM이 아니라 규칙 엔진이 한다 (2026-08-17)."""

    def test_prefers_filling_credits_over_fewer_days(self):
        """학점을 채우는 조합이 과목 1개짜리보다 위에 와야 한다.

        `timetable._rank_schedules`(요일 수 1순위)를 그대로 쓰면 1과목(1일) 조합이
        4과목(3일) 조합을 제친다 — 실측에서 12학점이 가능한 후보 풀에 3학점짜리
        단과목이 1·2위로 나왔다.
        """
        db = _make_db()
        user = _make_student(db)
        for i, day in enumerate(["월", "화", "수", "목"]):
            _add_course_with_offering(
                db, course_id=i + 1, offering_id=101 + i, name=f"과목{i}", credits=3.0,
                day=day, start="09:00", end="10:15",
            )
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        result = ctx.build_timetable(offering_ids=[101, 102, 103, 104], target_credits=12)

        self.assertTrue(result["ok"])
        top = result["schedules"][0]
        self.assertEqual([101, 102, 103, 104], top["offering_ids"])
        self.assertEqual(12.0, top["total_credits"])
        self.assertTrue(top["reaches_target_credits"])

    def test_picks_one_section_per_course(self):
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="확률및통계",
                                  credits=3.0, day="화", start="09:00", end="10:15")
        _add_section(db, course_id=1, offering_id=102, section="141",
                     day="화", start="10:30", end="11:45")
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        result = ctx.build_timetable(offering_ids=[101, 102], target_credits=6)

        self.assertTrue(result["ok"])
        for schedule in result["schedules"]:
            self.assertEqual(1, len(schedule["offering_ids"]))
            self.assertEqual(3.0, schedule["total_credits"])

    def test_builds_on_top_of_user_placed_timetable(self):
        """사용자가 시간표 UI에서 직접 담아둔 강좌를 고정하고 그 위에 얹는다."""
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="이미담은과목",
                                  credits=3.0, day="월", start="09:00", end="10:15")
        # 담아둔 강의와 시간이 겹치는 후보 → 제외돼야 한다.
        _add_course_with_offering(db, course_id=2, offering_id=102, name="겹치는과목",
                                  credits=3.0, day="월", start="09:30", end="10:45")
        _add_course_with_offering(db, course_id=3, offering_id=103, name="안겹치는과목",
                                  credits=3.0, day="화", start="09:00", end="10:15")
        plan = CoursePlan(id=7, user_id=user.id, year="2026", semester="2학기", title="내 시간표")
        db.add(plan)
        db.add(CoursePlanItem(plan_id=7, offering_id=101, source="manual"))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기", plan_id=7)

        result = ctx.build_timetable(offering_ids=[102, 103], target_credits=6)

        self.assertTrue(result["ok"])
        top = result["schedules"][0]
        # 고정분 + 새로 담을 것이 모두 offering_ids에 있고, 겹치는 후보는 빠진다.
        self.assertEqual([101, 103], top["offering_ids"])
        self.assertEqual([101], top["locked_offering_ids"])
        self.assertEqual([103], top["added_offering_ids"])
        self.assertNotIn(102, top["offering_ids"])
        self.assertTrue(
            any("겹침" in d["reason"] for d in result["dropped"]),
            msg=f"겹쳐서 빠졌다는 사유가 있어야 한다: {result['dropped']}",
        )

    def test_ignores_placed_timetable_when_asked(self):
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="이미담은과목",
                                  credits=3.0, day="월", start="09:00", end="10:15")
        _add_course_with_offering(db, course_id=2, offering_id=102, name="겹치는과목",
                                  credits=3.0, day="월", start="09:30", end="10:45")
        db.add(CoursePlan(id=7, user_id=user.id, year="2026", semester="2학기"))
        db.add(CoursePlanItem(plan_id=7, offering_id=101, source="manual"))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기", plan_id=7)

        result = ctx.build_timetable(
            offering_ids=[102], target_credits=3, ignore_current_timetable=True,
        )

        self.assertTrue(result["ok"])
        self.assertEqual([102], result["schedules"][0]["offering_ids"])
        self.assertEqual([], result["schedules"][0]["locked_offering_ids"])


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
        # roadmap 챗과 동일한 critical_missing_required 필드가 timetable에도 노출됨
        self.assertIn("critical_missing_required", result)

    def test_critical_missing_flags_required_not_open_this_semester(self):
        """target_term=2학기인데 필수과목이 1학기 전용 개설이고 미이수면 critical.
        roadmap 챗의 동일 헬퍼를 재사용하므로 로직 자체는 roadmap 테스트가 커버 —
        여기선 timetable 파이프라인이 값을 실제로 노출하는지만 확인."""
        db = _make_db()
        user = _make_student(db)
        db.add(GraduationRequirement(
            department_id=100, program_type="primary", curriculum_year="2024",
            required_total_credits=133,
        ))
        # 1학기 전용 전공필수, 학생 미이수 → target_term=2학기와 어긋남 → critical
        db.add(Course(
            id=901, course_name="자료구조", department_id=100,
            category="전공필수", credits=3.0, year="2", semester="1",
        ))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")
        result = ctx.get_student_context()
        names = [c["course_name"] for c in result["critical_missing_required"]]
        self.assertIn("자료구조", names)

    def test_critical_missing_skips_course_open_this_semester(self):
        """2학기 전용 필수 미이수 + target_term=2학기면 이번에 들 수 있어 critical 아님."""
        db = _make_db()
        user = _make_student(db)
        db.add(GraduationRequirement(
            department_id=100, program_type="primary", curriculum_year="2024",
            required_total_credits=133,
        ))
        db.add(Course(
            id=902, course_name="컴퓨터구조", department_id=100,
            category="전공필수", credits=3.0, year="2", semester="2",
        ))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")
        result = ctx.get_student_context()
        names = [c["course_name"] for c in result["critical_missing_required"]]
        self.assertNotIn("컴퓨터구조", names)

    def test_retake_candidates_exposed(self):
        """retake_candidates 필드가 로드맵 챗과 동일 스키마로 노출된다."""
        db = _make_db()
        user = _make_student(db)
        db.add(StudentCourseRecord(
            user_id=user.id, raw_course_name="이산수학",
            credits=3.0, year="2024", grade="D+", grade_point=1.5,
        ))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")
        result = ctx.get_student_context()
        self.assertIn("retake_candidates", result)
        names = [c["course_name"] for c in result["retake_candidates"]]
        self.assertIn("이산수학", names)

    def test_conditional_prompt_baseline_shorter_than_complex(self):
        """조건부 규칙 assembly — 상태 없는 학생은 CORE만, 복잡한 학생은 규칙 추가로 길어짐."""
        from app.domains.planning.timetable_chat import _build_timetable_system_prompt
        # Baseline: 성적 없고 필수 미이수 없음
        db = _make_db()
        user = _make_student(db)
        db.commit()
        baseline_prompt, baseline_rules = _build_timetable_system_prompt(db, user, "2학기")
        self.assertEqual([], baseline_rules)

        # 복잡한 학생: 저성적 SCR + 미이수 필수 (1학기 전용, target=2학기)
        db2 = _make_db()
        user2 = _make_student(db2)
        db2.add(GraduationRequirement(
            department_id=100, program_type="primary", curriculum_year="2024",
            required_total_credits=133,
        ))
        db2.add(StudentCourseRecord(user_id=user2.id, raw_course_name="이산수학",
                                     credits=3.0, grade="D+", grade_point=1.5, year="2024"))
        db2.add(Course(id=990, course_name="자료구조", department_id=100,
                       category="전공필수", credits=3.0, year="2", semester="1"))
        db2.commit()
        complex_prompt, complex_rules = _build_timetable_system_prompt(db2, user2, "2학기")

        self.assertIn("retake_candidates", complex_rules)
        self.assertIn("critical_missing", complex_rules)
        self.assertLess(len(baseline_prompt), len(complex_prompt))

    def test_prereq_blocked_exposed(self):
        """prereq_blocked 필드로 선수 미이수 과목이 노출된다."""
        db = _make_db()
        user = _make_student(db)
        db.add(Course(
            id=910, course_name="운영체제", department_id=100,
            category="전공선택", credits=3.0, year="3", semester="2",
            description="선수과목: 자료구조",
        ))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")
        result = ctx.get_student_context()
        self.assertIn("prereq_blocked", result)
        blocked = {b["course_name"]: b["missing_prerequisites"]
                    for b in result["prereq_blocked"]}
        self.assertIn("운영체제", blocked)
        self.assertEqual(["자료구조"], blocked["운영체제"])


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

        # 응답 = LLM이 쓴 설명 + 서버가 DB 값으로 붙인 과목 목록.
        # 목록을 LLM에게 맡기면 과목명·학점을 지어내서 화면의 시간표와 어긋난다
        # (_render_schedule_summary 참고). 대화 기록에는 텍스트만 남으므로 이 목록이
        # 새로고침 후 "무엇을 추천받았는지"의 유일한 기록이기도 하다.
        self.assertTrue(result["reply"].startswith("백엔드 진로에 맞춰 두 과목을 짜봤어요."))
        self.assertIn("📋 총 6학점", result["reply"])
        self.assertIn("백엔드시스템 (전공선택, 3학점) — 월 09:00-10:15", result["reply"])
        self.assertIn("서버프로그래밍 (전공선택, 3학점) — 화 09:00-10:15", result["reply"])
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
        # 저장되는 내용도 화면에 나간 응답과 같아야 한다 (목록 포함).
        self.assertEqual(result["reply"], messages[1].content)


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


class ClearChatMessagesTest(unittest.TestCase):
    """'이 대화 비우기' — 세션(제목·학기 맥락)은 남기고 메시지만 지운다."""

    def test_clears_messages_but_keeps_session(self):
        db = _make_db()
        db.add(School(id=1, name="테스트")); db.flush()
        db.add(College(id=1, school_id=1, name="테스트대학")); db.flush()
        db.add(Department(id=100, college_id=1, name="테스트학과")); db.flush()
        user = _make_student(db, department_id=100)
        sess = TimetableChatSession(user_id=user.id, year="2026", semester="2학기", title="스레드")
        db.add(sess); db.flush()
        db.add(TimetableChatMessage(session_id=sess.id, role="user", content="안녕"))
        db.add(TimetableChatMessage(session_id=sess.id, role="assistant", content="네"))
        db.commit()

        deleted = clear_chat_messages(db, user, sess.id)

        self.assertEqual(2, deleted)
        self.assertIsNotNone(db.get(TimetableChatSession, sess.id))
        self.assertEqual(0, db.query(TimetableChatMessage).filter_by(session_id=sess.id).count())

    def test_other_users_session_returns_none(self):
        db = _make_db()
        db.add(School(id=1, name="테스트")); db.flush()
        db.add(College(id=1, school_id=1, name="테스트대학")); db.flush()
        db.add(Department(id=100, college_id=1, name="테스트학과")); db.flush()
        user = _make_student(db, department_id=100)
        other = TimetableChatSession(user_id=999, year="2026", semester="2학기", title="남의 것")
        db.add(other); db.commit()

        self.assertIsNone(clear_chat_messages(db, user, other.id))


class OfferingLookupTest(unittest.TestCase):
    """개설 조회가 `courses` 행 하나가 아니라 실제 `course_offerings`를 근거로 하는지.

    실측 배경 (2026-08, 운영 DB): 같은 과목이 여러 course 행으로 중복돼 있고(506개 과목명),
    개설이 그 행들에 흩어져 붙는다. '공학작문및발표'는 5개 행 중 1326에 2026-2학기 분반이
    24개 달려 있는데 그 행의 카탈로그 semester가 '1'이라 2학기 검색에서 빠지고, 살아남은
    6166은 개설 0이라 "이번 학기 미개설"로 답했다. 실제로는 28개 분반이 열려 있었다.
    """

    def _seed_duplicate_course(self, db):
        # 같은 교양 과목이 두 행으로 중복 (department_id=None). 개설은 '1학기' 행에만 달림.
        db.add(Course(id=1326, course_name="공학작문및발표", category="효원핵심교양",
                      credits=3.0, year="2", semester="1", department_id=None))
        db.add(Course(id=6166, course_name="공학작문및발표", category="효원핵심교양",
                      credits=3.0, year="3", semester="2", department_id=None))
        db.add(CourseOffering(id=6675, course_id=1326, year="2026", semester="2학기",
                              section="001", professor="교수"))
        db.add(CourseTime(offering_id=6675, day_of_week="월",
                          start_time=datetime.time(9, 0), end_time=datetime.time(10, 30)))
        db.flush()

    def test_offerings_found_across_duplicate_course_rows(self):
        db = _make_db()
        user = _make_student(db, department_id=100)
        self._seed_duplicate_course(db)
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")
        # 검색이 6166(개설 0)을 집어와도 형제 행 1326의 분반을 찾아야 한다.
        attached = ctx._attach_offerings({"course_id": 6166, "course_name": "공학작문및발표"})
        self.assertEqual([6675], [s["offering_id"] for s in attached["offered_sections"]])

    def test_sibling_merge_does_not_cross_categories(self):
        """이수구분이 다르면 같은 과목명·전공이라도 합치지 않는다.

        실제 사례: 컴퓨터공학전공(major=36) 안에 이산수학이 두 항목이다 —
        CB1501027(1-1, 전공기초) / CB2001104(2-2, 전공선택). 분반을 합쳐 보여주면
        학생이 어느 요건을 채우는지 오인한다(졸업요건 집계가 이수구분 기준).
        """
        db = _make_db()
        _make_student(db, department_id=108, major_id=36)
        db.add(Course(id=6445, course_name="이산수학", category="전공기초", credits=3.0,
                      year="1", semester="1", department_id=108, major_id=36))
        db.add(Course(id=6469, course_name="이산수학", category="전공선택", credits=3.0,
                      year="2", semester="2", department_id=108, major_id=36))
        db.add(CourseOffering(id=7001, course_id=6469, year="2026", semester="2학기",
                              section="001"))
        db.flush()
        user = db.get(User, 1)
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        # 전공기초 쪽을 조회했는데 전공선택 쪽 분반이 딸려오면 안 된다.
        attached = ctx._attach_offerings({"course_id": 6445, "course_name": "이산수학"})
        self.assertEqual([], attached["offered_sections"])
        # 전공선택 쪽은 자기 분반을 그대로 본다.
        attached2 = ctx._attach_offerings({"course_id": 6469, "course_name": "이산수학"})
        self.assertEqual([7001], [s["offering_id"] for s in attached2["offered_sections"]])

    def test_sibling_merge_does_not_cross_departments(self):
        """학과가 다른 동명 과목의 분반까지 합치면 남의 시간표를 보여주게 된다."""
        db = _make_db()
        _make_student(db, department_id=100)
        db.add(Course(id=201, course_name="자료구조", category="전공필수", credits=3.0,
                      year="2", semester="1", department_id=100))
        db.add(Course(id=202, course_name="자료구조", category="전공필수", credits=3.0,
                      year="2", semester="1", department_id=999))
        db.add(CourseOffering(id=301, course_id=202, year="2026", semester="2학기",
                              section="001"))
        db.flush()
        user = db.get(User, 1)
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")
        attached = ctx._attach_offerings({"course_id": 201, "course_name": "자료구조"})
        self.assertEqual([], attached["offered_sections"])


class NotOfferedSeparationTest(unittest.TestCase):
    """미개설 과목이 `results`에 섞이지 않고 별도 필드로 나오는지.

    골든 케이스 21: `offered_sections: []`를 LLM이 "존재하는 과목"으로 읽고 미개설 사실을
    안 알리거나(관측), 심지어 시간표에 넣었다고 거짓 주장했다.
    """

    def test_not_offered_course_is_separated_and_flagged(self):
        db = _make_db()
        user = _make_student(db, department_id=100)
        # 개설 있는 과목 1개 + 카탈로그에만 있는 과목 1개(다른 학기 표기 → semester 필터로 숨음)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="데이터베이스",
                                  credits=3.0, day="월", start="09:00", end="10:30")
        db.add(Course(id=9001, course_name="공학작문", category="교양필수", credits=2.0,
                      year="2", semester="1", department_id=100))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        r = ctx.list_offered_courses(query="공학작문")

        self.assertNotIn("공학작문", [x["course_name"] for x in r["results"]])
        self.assertIn("공학작문",
                      [x["course_name"] for x in r["matched_but_not_offered_this_term"]])
        self.assertIn("개설되지 않았습니다", r["not_offered_note"])


class TimeConstraintParseTest(unittest.TestCase):
    """사용자 메시지에서 요일·시간대 제약 파싱.

    오탐(제약이 없는데 있다고 판단)은 정상 후보를 지워버리므로 놓치는 것보다 나쁘다 —
    확신이 높은 표현만 잡고 나머지는 제약 없음으로 둔다.
    """

    def parse(self, msg):
        return timetable_chat_mod._parse_time_constraint(msg)

    def test_day_and_period(self):
        c = self.parse("이번 학기 시간표 짜주세요. 조건 있어요 — 월수 오전에만 수업 넣어주세요.")
        self.assertEqual({"월", "수"}, c["days"])
        self.assertEqual("morning", c["period"])

    def test_period_only(self):
        self.assertEqual("afternoon", self.parse("오후에만 수업 듣고 싶어요")["period"])

    def test_days_only(self):
        self.assertEqual({"화", "목"}, self.parse("화목만 넣어주세요")["days"])

    def test_plain_request_has_no_constraint(self):
        for msg in ["이번 학기 시간표 짜주세요", "정컴 3학년인데 추천해줘", "월요일에 뭐 열려요?", None, ""]:
            self.assertIsNone(self.parse(msg), msg)

    def test_negative_form_is_not_guessed(self):
        """"화요일 빼고"는 의미가 반대라 지금은 제약으로 잡지 않는다 (오파싱 위험)."""
        self.assertIsNone(self.parse("화요일 빼고 짜주세요"))

    def test_day_letters_inside_ordinary_words_are_not_days(self):
        """'과목'·'필수'의 목·수를 요일로 읽으면 안 된다.

        실제로 그렇게 동작했다. '만'/'위주'만 있으면 문장 전체에서 요일 글자를 긁어서
        '전공필수과목만 넣어줘' → {수, 목}이 됐고, 그 제약이 후보 필터·검증·최종 응답
        세 군데에서 강제돼 사용자는 이유 없이 수·목 수업만 받거나 빈 시간표를 받았다.
        '만'은 한국어 요청에 워낙 흔해서 사실상 상시 발동하는 상태였다.
        """
        for msg in [
            "전공 과목만 3개 추천해줘",
            "전공필수만 추천해주세요",
            "전공필수과목만 넣어줘",
            "가볍게 3과목만 듣고 싶어요",
            "졸업요건에 필요한 과목만 넣어줘",
            "교양과목만 추천",
            "수업만 3개 넣어줘",
        ]:
            parsed = self.parse(msg)
            self.assertIsNone(
                (parsed or {}).get("days"),
                f"낱말 속 글자를 요일로 읽었다: {msg!r} -> {parsed}",
            )

    def test_yoil_suffix_does_not_add_sunday(self):
        """'수요일'의 '일'이 일요일로 잡히면 안 된다.

        예전에는 매치 문자열 전체를 훑어서 '…요일'을 언급하는 거의 모든 요청에
        일요일이 섞여 들어갔다.
        """
        self.assertEqual({"월", "수"}, self.parse("월요일과 수요일만 넣어주세요")["days"])
        self.assertEqual({"월", "수"}, self.parse("월/수요일에만 수업 넣어줘")["days"])
        self.assertEqual({"금"}, self.parse("금요일 위주로 짜줘")["days"])

    def test_explicit_single_day_still_works(self):
        """한 글자짜리를 무시하되, '요일'이 붙으면 하루짜리 제약도 살아 있어야 한다."""
        self.assertEqual({"월"}, self.parse("월요일만 수업 넣어줘")["days"])
        self.assertEqual({"월", "수", "금"}, self.parse("월수금만 듣게 해줘")["days"])


class TimeConstraintEnforcementTest(unittest.TestCase):
    """제약 위반 분반이 후보·검증·최종 응답 어디서도 통과하지 못하는지.

    골든 케이스 18에서 3/3 재현된 실패를 막는 가드다: LLM이 화·목 14:00 분반을 조합에
    넣고 rationale에는 "월수 오전에 진행되는"이라고 거짓 설명을 붙였다.
    """

    def setup_ctx(self, constraint):
        db = _make_db()
        user = _make_student(db)
        # 월수 오전 (제약 부합) / 화목 오후 (위반)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="데이터베이스",
                                  credits=3.0, day="월", start="09:00", end="10:30")
        _add_course_with_offering(db, course_id=2, offering_id=103, name="머신러닝",
                                  credits=3.0, day="화", start="14:00", end="15:30")
        db.flush()
        return _TimeTableToolContext(db, user, year="2026", semester="2학기",
                                     time_constraint=constraint)

    def test_validate_rejects_violating_offering(self):
        ctx = self.setup_ctx({"days": {"월", "수"}, "period": "morning"})
        result = ctx.validate_timetable(offering_ids=[101, 103])
        self.assertFalse(result["ok"])
        self.assertEqual("time_constraint_violation", result["reason"])
        self.assertEqual([103], [v["offering_id"] for v in result["violations"]])

    def test_validate_accepts_conforming_offering(self):
        ctx = self.setup_ctx({"days": {"월", "수"}, "period": "morning"})
        self.assertTrue(ctx.validate_timetable(offering_ids=[101])["ok"])

    def test_no_constraint_keeps_old_behaviour(self):
        ctx = self.setup_ctx(None)
        self.assertTrue(ctx.validate_timetable(offering_ids=[101, 103])["ok"])

    def test_finish_response_schedules_are_screened(self):
        ctx = self.setup_ctx({"days": {"월", "수"}, "period": "morning"})
        bad = ctx.schedules_violating_constraint(
            [{"offering_ids": [101, 103], "rationale": "월수 오전에 진행되는 과목입니다"}]
        )
        self.assertEqual([103], [b["offering_id"] for b in bad])

    def test_finish_response_screening_is_noop_without_constraint(self):
        ctx = self.setup_ctx(None)
        self.assertEqual([], ctx.schedules_violating_constraint(
            [{"offering_ids": [101, 103]}]
        ))


if __name__ == "__main__":
    unittest.main()
