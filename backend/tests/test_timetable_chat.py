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
    College, Department, GraduationRequirement, Major, School, StudentCourseRecord, StudentCourseSubstitution,
    UserAcademicProgram,
)
from app.domains.courses.models import Course, CourseOffering, CourseTime
from app.domains.planning import timetable_chat as timetable_chat_mod
from app.domains.planning.models import (
    CoursePlan, CoursePlanItem, CourseRoadmap, CourseRoadmapItem, PendingRoadmapChange,
    TimetableChatMessage, TimetableChatSession,
)
from app.domains.planning.timetable import _SectionInfo
from app.domains.planning.timetable_chat import (
    _rank_built_combos, _TimeTableToolContext, clear_chat_messages, run_timetable_chat,
)
from app.domains.users.models import User


_TABLES = [
    School.__table__, College.__table__, Department.__table__, Major.__table__,
    User.__table__, Course.__table__, CourseOffering.__table__, CourseTime.__table__,
    CourseRoadmap.__table__, CourseRoadmapItem.__table__, PendingRoadmapChange.__table__,
    UserAcademicProgram.__table__, GraduationRequirement.__table__,
    StudentCourseRecord.__table__,
    StudentCourseSubstitution.__table__,  # 이수기록을 읽는 경로가 대체 관계를 함께 조회한다
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


class BuildTimetableReviewFindingsTest(unittest.TestCase):
    """독립 리뷰(2026-08-19)에서 나온 결함 3건의 회귀 테스트."""

    def test_search_does_not_starve_when_many_combos_exist(self):
        """조합 수집 상한이 백트래킹까지 끊어 탐색 트리를 굶기던 문제.

        예전 구현은 "조합 N개 모으면 return"이었는데 DFS가 include-first라, 1순위 과목의
        첫 분반 서브트리에서 N개를 다 써버리면 **그 과목의 다른 분반도, 그 과목을 빼는
        가지도 영영 탐색되지 않았다.** 결과적으로 18학점이 가능한 풀에서 9학점만 내놓고
        "이게 최대"라고 단언했다.

        여기서는 그 모양을 만든다: 1순위 과목이 고학점 과목들과 전부 충돌하고, 그것과
        양립하는 저학점 과목이 많아 조합 수가 폭발하는 상황.
        """
        db = _make_db()
        user = _make_student(db)
        # 1순위: 월 09~18시를 통째로 먹는 1학점짜리 (뒤의 월요일 과목들과 전부 충돌)
        _add_course_with_offering(db, course_id=1, offering_id=900, name="블로커",
                                  credits=1.0, day="월", start="09:00", end="18:00")
        # 이 블로커와 양립하는 저학점 과목 7개 (화요일) → 2^7 = 128가지 부분집합
        for i in range(7):
            _add_course_with_offering(
                db, course_id=10 + i, offering_id=910 + i, name=f"소액{i}", credits=1.0,
                day="화", start=f"{9 + i:02d}:00", end=f"{9 + i:02d}:45",
            )
        # 블로커를 빼야만 담을 수 있는 고학점 과목 3개 (월요일)
        for i in range(3):
            _add_course_with_offering(
                db, course_id=20 + i, offering_id=920 + i, name=f"고학점{i}", credits=3.0,
                day="월", start=f"{9 + i * 2:02d}:00", end=f"{10 + i * 2:02d}:15",
            )
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        pool = [900] + [910 + i for i in range(7)] + [920 + i for i in range(3)]
        result = ctx.build_timetable(offering_ids=pool, target_credits=15)

        self.assertTrue(result["ok"])
        best = max(s["total_credits"] for s in result["schedules"])
        # 블로커(1학점)를 버리고 고학점 3개(9) + 화요일 7개(7) = 16학점이 가능하다.
        self.assertGreaterEqual(
            best, 15.0,
            msg=f"탐색이 굶어서 최선을 못 찾았다: {[s['total_credits'] for s in result['schedules']]}",
        )

    def test_candidate_priority_order_is_respected(self):
        """호출자가 넘긴 순서 = 우선순위. DB 행 순서가 아니다.

        `_sections_from_offering_ids`가 `IN (...)` 조회라 offering_id 오름차순으로
        돌아오는데 그걸 그대로 쓰면, 도구 설명("앞쪽이 우선 채택된다")과 어긋나고
        과목 수 상한 절삭에서 LLM의 1순위가 잘려나간다.
        """
        db = _make_db()
        user = _make_student(db)
        # 전부 같은 시간 → 한 과목만 담을 수 있다. 누가 뽑히는지로 우선순위를 본다.
        for i in range(3):
            _add_course_with_offering(
                db, course_id=1 + i, offering_id=800 + i, name=f"과목{i}", credits=3.0,
                day="월", start="09:00", end="10:15",
            )
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        # 역순으로 넘긴다 — DB 행 순서(800,801,802)와 반대.
        result = ctx.build_timetable(offering_ids=[802, 801, 800], target_credits=3)

        self.assertTrue(result["ok"])
        self.assertEqual([802], result["schedules"][0]["offering_ids"])

    def test_dropped_records_courses_cut_by_group_cap(self):
        """과목 수 상한으로 잘린 후보는 사유가 남아야 한다 (조용히 사라지면 안 됨)."""
        db = _make_db()
        user = _make_student(db)
        count = 18  # _MAX_COURSE_GROUPS(14) 초과
        for i in range(count):
            _add_course_with_offering(
                db, course_id=1 + i, offering_id=700 + i, name=f"과목{i}", credits=1.0,
                day="월화수목금"[i % 5], start=f"{9 + i // 5:02d}:00", end=f"{9 + i // 5:02d}:45",
            )
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        result = ctx.build_timetable(offering_ids=[700 + i for i in range(count)])

        self.assertTrue(result["ok"])
        cut_reasons = [d for d in result.get("dropped", []) if "탐색에서 제외" in d["reason"]]
        self.assertEqual(count - 14, len(cut_reasons))


class TimetableChatFollowupsTest(unittest.TestCase):
    """#173 독립 리뷰의 후속 지적 + 담은 과목 확인 전용 도구."""

    def test_get_current_timetable_tool_reports_placed_courses(self):
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="담은과목",
                                  credits=3.0, day="월", start="09:00", end="10:15")
        db.add(CoursePlan(id=3, user_id=user.id, year="2026", semester="2학기"))
        db.add(CoursePlanItem(plan_id=3, offering_id=101, source="manual"))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기", plan_id=3)

        result = ctx.dispatch("get_current_timetable", {})

        self.assertEqual(1, result["offering_count"])
        self.assertEqual(3.0, result["locked_credits"])
        # 이미 찬 요일·시간대를 같이 줘야 "월요일 오전은 찼다"를 바로 판단할 수 있다.
        self.assertEqual({"월": ["09:00-10:15"]}, result["occupied_slots"])
        self.assertEqual("담은과목", result["offerings"][0]["course_name"])

    def test_get_current_timetable_is_safe_without_plan(self):
        db = _make_db()
        user = _make_student(db)
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        result = ctx.dispatch("get_current_timetable", {})

        self.assertEqual(0, result["offering_count"])
        self.assertEqual({}, result["occupied_slots"])

    def test_must_include_pins_the_exact_section(self):
        """필수 지정은 **분반 단위**다.

        예전엔 course_id로 승격시켜서, "140분반 꼭 넣어줘"에 141분반을 담은 조합이
        나왔다. 도구 설명은 분반 단위라고 안내하는데 구현이 달랐다.
        """
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=301, name="확률및통계",
                                  credits=3.0, day="화", start="09:00", end="10:15")
        _add_section(db, course_id=1, offering_id=302, section="141",
                     day="화", start="10:30", end="11:45")
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        result = ctx.build_timetable(
            offering_ids=[301, 302], must_include_offering_ids=[301], target_credits=3,
        )

        self.assertTrue(result["ok"])
        for schedule in result["schedules"]:
            self.assertIn(301, schedule["offering_ids"])
            self.assertNotIn(302, schedule["offering_ids"])

    def test_unusable_must_include_is_reported_not_ignored(self):
        """지정한 분반을 못 쓰면 조용히 다른 조합을 내면 안 된다."""
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=201, name="이미들은과목",
                                  credits=3.0, day="월", start="09:00", end="10:15")
        _add_course_with_offering(db, course_id=2, offering_id=202, name="다른과목",
                                  credits=3.0, day="화", start="09:00", end="10:15")
        db.add(StudentCourseRecord(user_id=user.id, raw_course_name="이미들은과목",
                                   credits=3.0, year=2024, semester="1학기"))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        result = ctx.build_timetable(
            offering_ids=[201, 202], must_include_offering_ids=[201], target_credits=3,
        )

        self.assertFalse(result["ok"])
        self.assertEqual("must_include_unavailable", result["reason"])
        self.assertEqual(201, result["unavailable"][0]["offering_id"])

    def test_must_include_of_already_placed_section_is_satisfied(self):
        """이미 담아둔 분반을 지정하면 **이미 충족된 것**이다.

        `usable`에서 고정분은 "이미 시간표에 담겨 있음"으로 먼저 빠지므로, 그대로 두면
        "140분반은 그대로 두고 나머지 채워줘"라는 자연스러운 요청에 **화면에 이미 들어있는
        분반을 두고 "쓸 수 없습니다"라고 답한다**(고치면서 만든 회귀, 독립 리뷰가 재현).
        """
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="이미담은과목",
                                  credits=3.0, day="월", start="09:00", end="10:15")
        _add_course_with_offering(db, course_id=2, offering_id=102, name="추가후보",
                                  credits=3.0, day="화", start="09:00", end="10:15")
        db.add(CoursePlan(id=1, user_id=user.id, year="2026", semester="2학기"))
        db.add(CoursePlanItem(plan_id=1, offering_id=101, source="manual"))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기", plan_id=1)

        result = ctx.build_timetable(
            offering_ids=[102], must_include_offering_ids=[101], target_credits=6,
        )

        self.assertTrue(result["ok"], msg=f"거부됨: {result.get('reason')}")
        self.assertIn(101, result["schedules"][0]["offering_ids"])

    def test_must_include_of_other_section_of_placed_course_is_still_rejected(self):
        """단, 같은 과목의 **다른** 분반을 지정하면 여전히 거절해야 한다."""
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="확률및통계",
                                  credits=3.0, day="월", start="09:00", end="10:15")
        _add_section(db, course_id=1, offering_id=102, section="141",
                     day="화", start="09:00", end="10:15")
        db.add(CoursePlan(id=1, user_id=user.id, year="2026", semester="2학기"))
        db.add(CoursePlanItem(plan_id=1, offering_id=101, source="manual"))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기", plan_id=1)

        result = ctx.build_timetable(
            offering_ids=[102], must_include_offering_ids=[102], target_credits=3,
        )

        self.assertFalse(result["ok"])
        self.assertEqual("must_include_unavailable", result["reason"])

    def test_exact_budget_fit_is_allowed(self):
        """남은 예산 == 후보 학점이면 담을 수 있다.

        (이 테스트로는 `<`/`<=` 변이를 못 잡는다 — 딱 맞는 조합이 실제로 만들어지면
        `if not combos:` 안으로 안 들어가기 때문이다. **다만 그 분기 자체는 도달 가능하다**
        — 처음엔 "도달 불가"라고 적었는데 독립 리뷰가 반례를 실증했다.
        `test_budget_boundary_with_unaffordable_required_course`가 그 경로를 덮는다.)
        """
        db = _make_db()
        user = _make_student(db)   # 학점 상한 19
        for i in range(6):
            _add_course_with_offering(
                db, course_id=1 + i, offering_id=400 + i, name=f"담은{i}", credits=3.0,
                day="월화수목금토"[i], start="09:00", end="10:15",
            )
        # 남은 예산 1학점, 후보도 정확히 1학점
        _add_course_with_offering(db, course_id=90, offering_id=490, name="딱맞는후보",
                                  credits=1.0, day="일", start="09:00", end="10:15")
        db.add(CoursePlan(id=9, user_id=user.id, year="2026", semester="2학기"))
        for i in range(6):
            db.add(CoursePlanItem(plan_id=9, offering_id=400 + i, source="manual"))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기", plan_id=9)

        result = ctx.build_timetable(offering_ids=[490])

        self.assertTrue(result["ok"], msg=f"경계에서 오거부: {result.get('reason')}")
        self.assertIn(490, result["schedules"][0]["offering_ids"])

    def test_budget_boundary_with_unaffordable_required_course(self):
        """남은 예산 == 최소 후보 학점인데 조합이 안 되는 경로.

        필수 지정 과목이 예산을 넘으면 조합이 비고, 그때 `remaining_budget < cheapest`
        분기에 **실제로 도달한다**(리뷰가 실증한 반례). `<=`로 바뀌면 "1학점 남는데
        가장 작은 과목이 1학점이라 무엇도 못 담는다"는 **자기모순 힌트**가 나간다 —
        1학점짜리는 담을 수 있는데도.
        """
        db = _make_db()
        user = _make_student(db)   # 상한 19
        for i in range(6):
            _add_course_with_offering(
                db, course_id=1 + i, offering_id=400 + i, name=f"담은{i}", credits=3.0,
                day="월화수목금토"[i], start="09:00", end="10:15",
            )
        _add_course_with_offering(db, course_id=90, offering_id=490, name="비싼필수",
                                  credits=3.0, day="일", start="09:00", end="10:15")
        _add_course_with_offering(db, course_id=91, offering_id=491, name="싼후보",
                                  credits=1.0, day="일", start="11:00", end="11:45")
        db.add(CoursePlan(id=9, user_id=user.id, year="2026", semester="2학기"))
        for i in range(6):
            db.add(CoursePlanItem(plan_id=9, offering_id=400 + i, source="manual"))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기", plan_id=9)

        result = ctx.build_timetable(
            offering_ids=[490, 491], must_include_offering_ids=[490],
        )

        self.assertFalse(result["ok"])
        # 예산 소진이 아니다 — 1학점짜리는 담을 수 있고, 못 담는 건 필수 지정 때문이다.
        self.assertEqual("no_feasible_combination", result["reason"])

    def test_must_include_violating_time_constraint_is_rejected(self):
        """시간 제약을 어기는 분반을 필수 지정하면 거절해야 한다.

        `locked_ids`를 차집합에서 빼면서 정상 거절 경로가 뚫리지 않았는지 고정한다.
        """
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=701, name="월요과목",
                                  credits=3.0, day="월", start="09:00", end="10:15")
        _add_course_with_offering(db, course_id=2, offering_id=702, name="화요과목",
                                  credits=3.0, day="화", start="09:00", end="10:15")
        db.flush()
        # 사용자가 "화요일만" 이라고 요청한 상황
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기",
                                    time_constraint={"days": {"화"}})

        result = ctx.build_timetable(
            offering_ids=[701, 702], must_include_offering_ids=[701],
        )

        self.assertFalse(result["ok"])
        self.assertEqual("must_include_unavailable", result["reason"])
        self.assertIn("요일", result["unavailable"][0]["reason"])

    def test_time_conflict_is_not_reported_as_budget_exhaustion(self):
        """예산은 남는데 시간이 겹쳐 못 만드는 경우 — 반대 방향 오답도 막는다."""
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=601, name="A",
                                  credits=3.0, day="월", start="09:00", end="12:00")
        _add_course_with_offering(db, course_id=2, offering_id=602, name="B",
                                  credits=3.0, day="월", start="10:00", end="13:00")
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        # 둘 다 필수 지정 → 시간이 겹쳐 조합 불가. 예산(19학점)은 충분하다.
        result = ctx.build_timetable(
            offering_ids=[601, 602], must_include_offering_ids=[601, 602],
        )

        self.assertFalse(result["ok"])
        self.assertEqual("no_feasible_combination", result["reason"])

    def test_occupied_slots_skips_sections_without_time_info(self):
        """시간 정보 없는 분반이 섞여도 깨지지 않아야 한다 — 실 DB엔 흔하다."""
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="시간있음",
                                  credits=3.0, day="월", start="09:00", end="10:15")
        # CourseTime 행은 있는데 요일/시작시각이 비어 있는 분반. 실 DB에 흔하고,
        # 가드가 없으면 여기서 터진다(크롤링이 아직 모든 분반의 시간을 못 채웠다).
        db.add(Course(id=2, course_name="시간미상", category="전공선택", credits=3.0,
                      department_id=100, year="3", semester="2"))
        db.add(CourseOffering(id=102, course_id=2, year="2026", semester="2학기",
                              section="001", professor="교수"))
        db.add(CourseTime(offering_id=102, day_of_week=None, start_time=None, end_time=None))
        db.add(CoursePlan(id=1, user_id=user.id, year="2026", semester="2학기"))
        db.add(CoursePlanItem(plan_id=1, offering_id=101, source="manual"))
        db.add(CoursePlanItem(plan_id=1, offering_id=102, source="manual"))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기", plan_id=1)

        result = ctx.dispatch("get_current_timetable", {})

        self.assertEqual(2, result["offering_count"])
        self.assertEqual({"월": ["09:00-10:15"]}, result["occupied_slots"])
        # 학점 상한도 함께 준다 (남은 학점 판단에 필요)
        self.assertEqual(19, result["credit_cap"])

    def test_credit_budget_exhaustion_is_not_reported_as_time_conflict(self):
        """학점이 모자란 건데 "시간이 겹쳐서"라고 답하면, LLM이 헛되이 후보를 넓혀
        재호출하고 사용자에게도 틀린 이유가 나간다."""
        db = _make_db()
        user = _make_student(db)   # 졸업요건 없음 → 학점 상한 19
        # 고정분으로 18학점을 채운다 (남은 예산 1학점)
        for i in range(6):
            _add_course_with_offering(
                db, course_id=1 + i, offering_id=400 + i, name=f"담은{i}", credits=3.0,
                day="월화수목금토"[i], start="09:00", end="10:15",
            )
        _add_course_with_offering(db, course_id=90, offering_id=490, name="후보",
                                  credits=3.0, day="일", start="09:00", end="10:15")
        db.add(CoursePlan(id=9, user_id=user.id, year="2026", semester="2학기"))
        for i in range(6):
            db.add(CoursePlanItem(plan_id=9, offering_id=400 + i, source="manual"))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기", plan_id=9)

        result = ctx.build_timetable(offering_ids=[490])

        self.assertFalse(result["ok"])
        self.assertEqual("credit_budget_exhausted", result["reason"])
        self.assertIn("시간 문제가 아니다", result["hint"])

    def test_tool_descriptions_do_not_point_at_validate_for_building(self):
        """코어 프롬프트는 build로 바꿨는데 스키마가 validate를 가리키면,
        스키마를 따르는 약한 모델이 옛 경로로 돌아간다."""
        by_name = {tool["function"]["name"]: tool["function"] for tool in timetable_chat_mod._TOOLS}
        self.assertNotIn("validate_timetable", by_name["list_offered_courses"]["description"])
        self.assertIn("build_timetable", by_name["list_offered_courses"]["description"])
        self.assertIn("build_timetable", by_name["finish_response"]["description"])
        # 앞 문장에 validate 참조가 남아 비문이 된 적이 있다 — 있으면 안 된다.
        self.assertNotIn("validate_timetable", by_name["finish_response"]["description"])


class ResolvePlanIdTest(unittest.TestCase):
    def test_explicit_plan_from_other_term_is_ignored(self):
        """학기가 다른 시간표를 고정분으로 깔면 학점 상한을 먹고 시간대를 막는다."""
        from app.domains.planning.timetable_chat import _resolve_plan_id

        db = _make_db()
        user = _make_student(db)
        db.add(CoursePlan(id=5, user_id=user.id, year="2025", semester="1학기"))
        db.add(CoursePlan(id=6, user_id=user.id, year="2026", semester="2학기"))
        db.flush()

        self.assertIsNone(_resolve_plan_id(db, user, "2026", "2학기", 5))
        self.assertEqual(6, _resolve_plan_id(db, user, "2026", "2학기", 6))

    def test_other_users_plan_is_ignored(self):
        from app.domains.planning.timetable_chat import _resolve_plan_id

        db = _make_db()
        user = _make_student(db)
        db.add(User(id=99, email="x@e.com", password_hash="x", name="남", department_id=100))
        db.flush()
        db.add(CoursePlan(id=7, user_id=99, year="2026", semester="2학기"))
        db.flush()

        self.assertIsNone(_resolve_plan_id(db, user, "2026", "2학기", 7))


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

    def test_같은_이름이_개설로도_나오면_미개설_목록에서_뺀다(self):
        """`일반물리학`처럼 학기별로 교과목코드가 다른 동명 과목 (2026-08-20 실계정 실측).

        컴퓨터공학전공 카탈로그에는 일반물리학이 두 행이다 — CB1501005(1학기 표기,
        2026-2학기 분반 0개)와 CB1501009(2학기 표기, 분반 2개). 엔진 분류는 맞지만
        LLM이 둘 다 과목명으로만 옮겨 적어서, 한 답변에 "일반물리학은 이번 학기
        개설이 아니라 담을 수 없어요"와 "일반물리학 3학점 — 월/수 15:00"이 같이 나왔다.
        """
        db = _make_db()
        user = _make_student(db, department_id=100)
        # 2학기 행 — 분반 있음
        _add_course_with_offering(db, course_id=1, offering_id=101, name="일반물리학",
                                  credits=3.0, day="월", start="15:00", end="16:15",
                                  category="전공기초")
        # 1학기 행 — 같은 이름, 다른 코드, 이번 학기 분반 없음
        db.add(Course(id=9002, course_name="일반물리학", category="전공기초", credits=3.0,
                      year="1", semester="1", department_id=100))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        r = ctx.list_offered_courses(query="일반물리학")

        self.assertIn("일반물리학", [x["course_name"] for x in r["results"]])
        self.assertNotIn(
            "일반물리학",
            [x["course_name"] for x in r.get("matched_but_not_offered_this_term", [])],
            "담을 수 있는 과목을 동시에 '못 담는다'고 알리면 사용자에겐 자기모순으로 읽힌다",
        )

    def test_이름이_안_겹치면_미개설_안내는_그대로_나간다(self):
        """겹칠 때만 침묵해야 한다 — 미개설 경고 자체를 죽이면 골든 케이스 21이 재발한다."""
        db = _make_db()
        user = _make_student(db, department_id=100)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="일반물리학",
                                  credits=3.0, day="월", start="15:00", end="16:15",
                                  category="전공기초")
        db.add(Course(id=9003, course_name="공학작문", category="전공기초", credits=2.0,
                      year="2", semester="1", department_id=100))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        # 같은 턴의 앞선 호출에서 일반물리학을 개설로 내보낸 뒤에도, 이름이 다른
        # 공학작문의 미개설 안내는 그대로 나가야 한다 (누적 집합이 과잉 억제하지 않는지).
        ctx.list_offered_courses(query="일반물리학")
        r = ctx.list_offered_courses(query="공학작문")

        self.assertIn("공학작문",
                      [x["course_name"] for x in r["matched_but_not_offered_this_term"]])


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

    def test_배제형_요일도_제약으로_잡는다(self):
        """예전엔 '빼고/제외'가 보이면 통째로 제약 없음(None)으로 처리했다.

        제약을 안 잡아도 **LLM은 그 요청을 봤으므로 지켰다고 말한다.** 파싱을 포기하면
        제약이 사라지는 게 아니라 거짓 설명만 남는다 (2026-08-20 실계정 실측 —
        아래 오전 배제 케이스 참고).
        """
        self.assertEqual({"화"}, self.parse("화요일 빼고 짜주세요")["exclude_days"])
        self.assertEqual({"화", "목"}, self.parse("화목 빼고 짜줘")["exclude_days"])
        self.assertEqual({"금"}, self.parse("금요일은 제외해줘")["exclude_days"])

    def test_오전_수업은_빼줘가_정반대로_뒤집히지_않는다(self):
        """2026-08-20 실계정 실측. "오전 수업은 빼줘"에 챗은

            "오전(09:00 이전) 수업은 제외해서, 가능한 분반 조합으로 16학점을 맞췄어요"

        라고 답하면서 확률통계 월 09:00-12:00, 일반물리학 화 09:00-10:15을 담았다.
        제약이 파싱되지 않았고('빼줘'는 옛 게이트 키워드 '빼고'에 안 걸린다), LLM은
        오전의 정의까지 자기에게 유리하게 바꿔서 지킨 척했다.

        또 하나의 함정: 배제형을 그냥 한정형 파서에 넘기면 '오전'이라는 글자 때문에
        `period="morning"`(= 오전에만)이 되어 **정확히 정반대 제약**이 걸린다.
        """
        for msg in ["오전 수업은 빼줘", "오전 빼줘", "오전 말고 오후로", "오전 수업 제외해주세요"]:
            parsed = self.parse(msg)
            self.assertEqual("morning", parsed.get("exclude_period"), msg)
            self.assertIsNone(parsed.get("period"), f"배제형이 한정형으로 뒤집혔다: {msg!r}")

    def test_배제형에서도_낱말_속_요일_글자는_무시한다(self):
        """'전공필수 빼고'의 '수'가 수요일이 되면 안 된다 (한정형과 같은 규칙)."""
        for msg in ["전공필수 빼고 추천해줘", "교양과목 말고 전공으로", "수업은 빼줘"]:
            parsed = self.parse(msg) or {}
            self.assertIsNone(parsed.get("exclude_days"), f"{msg!r} -> {parsed}")

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


class RankBuiltCombosOverTargetTest(unittest.TestCase):
    """목표 학점을 넘긴 조합끼리는 초과가 적은 쪽이 위여야 한다.

    `target_credits`는 시스템 안에서 "이 학점 **이상**"이라는 최소치로 쓰인다
    (프롬프트의 `target_credit_floor`). 그래서 예전에는 사용자가 "18학점으로
    짜줘"라고 명시해도 상한(21)까지 꽉 채운 조합만 내놓았다 — 2026-08-19 실계정
    실측에서 18을 요청했는데 21학점 조합 3개가 나왔다. 최소치 의미는 그대로 두고,
    이미 목표를 만족한 것들 중에서는 목표에 가까운 쪽을 고르게 한다.
    """

    @staticmethod
    def _section(offering_id: int, credits: float, day: str, start: int) -> _SectionInfo:
        return _SectionInfo(
            item_id=offering_id, course_id=offering_id, course_code=f"C{offering_id}",
            course_name=f"과목{offering_id}", category="전공선택", credits=credits,
            offering_id=offering_id, section="001", professor=None,
            times=(CourseTime(
                offering_id=offering_id, day_of_week=day,
                start_time=datetime.time(start, 0), end_time=datetime.time(start + 1, 15),
                classroom=None,
            ),),
        )

    def test_목표를_넘긴_조합끼리는_초과가_적은_쪽이_위(self):
        # 같은 요일 수(1일)·같은 공백이 되도록 맞춰서 초과분만 차이나게 한다.
        exactly_18 = [self._section(1, 9.0, "월", 9), self._section(2, 9.0, "월", 11)]
        over_21 = [self._section(3, 9.0, "화", 9), self._section(4, 12.0, "화", 11)]
        ranked = _rank_built_combos([over_21, exactly_18], target_credits=18.0)
        self.assertEqual(
            18.0, sum(s.credits for s in ranked[0]),
            "18학점을 요청했는데 21학점 조합이 1순위로 오면 요청을 무시한 답이 된다",
        )

    def test_목표_미달_조합은_여전히_많이_채운_쪽이_위(self):
        """초과 페널티가 '최대한 채운다'는 기존 동작을 되돌리면 안 된다."""
        small = [self._section(1, 6.0, "월", 9)]
        bigger = [self._section(2, 9.0, "화", 9), self._section(3, 6.0, "화", 11)]
        ranked = _rank_built_combos([small, bigger], target_credits=18.0)
        self.assertEqual(15.0, sum(s.credits for s in ranked[0]))


class ExactCreditModeTest(unittest.TestCase):
    """`credit_mode="exact"` — 사용자가 학점을 콕 집어 말한 경우.

    `target_credits`는 시스템 안에서 원래 "이 학점 **이상**"이라는 최소치다. 랭킹만
    고쳤을 때(2026-08-19)는 목표를 넘긴 것 중 초과가 적은 쪽을 골라 21 → 19가 됐지만,
    후보 풀에 정확히 18이 없으면 여전히 19를 내놓았다 — 18을 요청한 사용자에겐 오답이다.

    exact는 목표를 **넘지 않는다**. 정확히 맞으면 그것을, 안 맞으면 그 이하 최대를
    돌려주고 `reaches_target_credits=false`로 못 맞췄다는 사실을 알린다.
    """

    def _ctx(self, db, user):
        return _TimeTableToolContext(db, user, year="2026", semester="2학기")

    def test_정확히_맞는_조합이_있으면_그것을_고른다(self):
        db = _make_db()
        user = _make_student(db)
        # 3학점 6개 = 18. 여기에 1학점짜리를 더하면 19가 되는데, exact면 19를 만들면 안 된다.
        for i in range(6):
            _add_course_with_offering(
                db, course_id=i + 1, offering_id=101 + i, name=f"전공{i}", credits=3.0,
                day="월화수목금토"[i], start="09:00", end="10:15",
            )
        _add_course_with_offering(
            db, course_id=99, offering_id=199, name="1학점과목", credits=1.0,
            day="월", start="11:00", end="11:50",
        )
        db.flush()

        result = self._ctx(db, user).build_timetable(
            offering_ids=[101, 102, 103, 104, 105, 106, 199],
            target_credits=18, credit_mode="exact",
        )

        self.assertTrue(result["ok"])
        self.assertEqual("exact", result["credit_mode"])
        top = result["schedules"][0]
        self.assertEqual(18.0, top["total_credits"])
        self.assertTrue(top["reaches_target_credits"])
        self.assertNotIn(
            "below_target_note", result,
            "정확히 맞췄는데 '못 맞췄다' 안내가 붙으면 LLM이 사과부터 한다",
        )

    def test_어떤_조합도_목표를_넘지_않는다(self):
        """exact의 핵심 계약 — 돌려준 조합 중 단 하나도 target을 넘으면 안 된다."""
        db = _make_db()
        user = _make_student(db)
        for i in range(6):
            _add_course_with_offering(
                db, course_id=i + 1, offering_id=101 + i, name=f"전공{i}", credits=3.0,
                day="월화수목금토"[i], start="09:00", end="10:15",
            )
        _add_course_with_offering(
            db, course_id=99, offering_id=199, name="1학점과목", credits=1.0,
            day="월", start="11:00", end="11:50",
        )
        db.flush()

        result = self._ctx(db, user).build_timetable(
            offering_ids=[101, 102, 103, 104, 105, 106, 199],
            target_credits=18, credit_mode="exact",
        )

        self.assertTrue(result["ok"])
        for schedule in result["schedules"]:
            self.assertLessEqual(
                schedule["total_credits"], 18.0,
                f"exact인데 목표를 넘겼다: {schedule['total_credits']}학점",
            )

    def test_정확히_못_맞추면_이하_최대로_내려가고_사실을_알린다(self):
        """후보가 4학점짜리뿐이라 18이 불가능한 상황 — 16이 최선이다."""
        db = _make_db()
        user = _make_student(db)
        for i in range(5):
            _add_course_with_offering(
                db, course_id=i + 1, offering_id=201 + i, name=f"전공{i}", credits=4.0,
                day="월화수목금"[i], start="09:00", end="10:15",
            )
        db.flush()

        result = self._ctx(db, user).build_timetable(
            offering_ids=[201, 202, 203, 204, 205],
            target_credits=18, credit_mode="exact",
        )

        self.assertTrue(result["ok"])
        top = result["schedules"][0]
        self.assertEqual(16.0, top["total_credits"], "18 이하 최대는 4학점 4개 = 16이다")
        self.assertFalse(top["reaches_target_credits"])
        self.assertIn(
            "below_target_note", result,
            "못 맞췄으면 LLM에게 그 사실을 알려야 한다 — 조용히 16학점을 내밀면 안 된다",
        )
        note = result["below_target_note"]
        self.assertIn("18", note)
        self.assertIn("16", note)
        self.assertNotIn(
            "최대 N학점까지 가능합니다", note,
            "exact에 at_least용 '최대 몇 학점까지 가능' 문구가 나가면 동문서답이 된다",
        )

    def test_같은_후보에서_at_least와_exact가_반대로_갈린다(self):
        """3학점 5개 후보에 목표 13 — 13은 만들 수 없는 숫자다.

        at_least는 "13 **이상**"이라 위로 올라가 15를 잡고(기존 동작 유지),
        exact는 "13을 넘지 마라"라 아래로 내려가 12를 잡는다. 두 모드가 실제로
        반대 방향으로 움직이는지를 한 케이스에서 못박는다.
        """
        db = _make_db()
        user = _make_student(db)
        for i in range(5):
            _add_course_with_offering(
                db, course_id=i + 1, offering_id=301 + i, name=f"전공{i}", credits=3.0,
                day="월화수목금"[i], start="09:00", end="10:15",
            )
        db.flush()
        pool = [301, 302, 303, 304, 305]

        at_least = self._ctx(db, user).build_timetable(target_credits=13, offering_ids=pool)
        exact = self._ctx(db, user).build_timetable(
            target_credits=13, offering_ids=pool, credit_mode="exact",
        )

        self.assertEqual("at_least", at_least["credit_mode"])
        self.assertEqual(15.0, at_least["schedules"][0]["total_credits"])
        self.assertEqual("exact", exact["credit_mode"])
        self.assertEqual(12.0, exact["schedules"][0]["total_credits"])

    def test_target_없이_exact만_오면_at_least로_되돌린다(self):
        """맞출 기준이 없는데 자동 목표(상한의 80%)를 '정확히'로 해석하면,
        사용자가 말한 적 없는 숫자에 시간표를 억지로 맞추게 된다."""
        db = _make_db()
        user = _make_student(db)
        for i in range(5):
            _add_course_with_offering(
                db, course_id=i + 1, offering_id=401 + i, name=f"전공{i}", credits=3.0,
                day="월화수목금"[i], start="09:00", end="10:15",
            )
        db.flush()

        result = self._ctx(db, user).build_timetable(
            offering_ids=[401, 402, 403, 404, 405], credit_mode="exact",
        )

        self.assertTrue(result["ok"])
        self.assertEqual("at_least", result["credit_mode"])

    def test_도구_스키마와_프롬프트가_exact를_안내한다(self):
        """엔진만 고치고 LLM에게 안 알려주면 이 경로는 영영 안 쓰인다 —
        2026-08-19에 AI융합트랙이 프롬프트에만 있고 도구가 없어서 겪은 실패와 같은 형태다."""
        from app.domains.planning.timetable_chat import _TOOLS, _TIMETABLE_CORE_PROMPT

        build = next(
            t for t in _TOOLS if t["function"]["name"] == "build_timetable"
        )
        params = build["function"]["parameters"]["properties"]
        self.assertIn("credit_mode", params)
        self.assertEqual(["at_least", "exact"], params["credit_mode"]["enum"])
        self.assertIn("exact", _TIMETABLE_CORE_PROMPT)


class CreditIntentParseTest(unittest.TestCase):
    """사용자 메시지에서 학점 목표를 규칙으로 뽑는다.

    2026-08-20 실계정 실측: "가볍게 듣고 싶어"에 gpt-4o-mini는
    `target_credits=16, credit_mode="at_least"`를 넘겨 **17학점** 시간표를 냈다
    (상한 21인 학생 기준으로 가볍지 않다). 게다가 답변에는 "'16학점(목표)'을 정확히
    맞추기보다는 …총 17학점으로 잡혔습니다"라고 **사용자가 말한 적 없는 내부 목표
    숫자**까지 노출했다. 시간 제약과 같은 이유로 판정을 LLM에 맡기지 않는다.

    반대로 오탐은 정상 요청을 망가뜨리므로, 애매하면 None(= LLM 판단 유지)이다.
    """

    def parse(self, msg):
        return timetable_chat_mod._parse_credit_intent(msg)



    def test_가볍게는_light로_잡힌다(self):
        intent = self.parse("가볍게 듣고 싶어")
        self.assertEqual("light", intent["style"])
        self.assertIsNone(intent["target_credits"], "목표 학점은 상한을 아는 엔진이 정한다")

    def test_학점_목표가_아닌_숫자는_잡지_않는다(self):
        """"전공 12학점 남았는데"는 남은 요건 이야기지 목표가 아니다.

        꼬리 검사를 `in`으로 하면 "남았는데뭐들을까"의 '들'에 걸려 12학점 시간표가
        나간다 — 그래서 접두 검사만 한다.
        """
        for msg in [
            "전공 12학점 남았는데 뭐 들을까",
            "이번 학기 시간표 짜줘",
            "3학년인데 추천해줘",
            "최대한 많이 들을래",
            None,
            "",
        ]:
            self.assertIsNone(self.parse(msg), msg)


class CreditIntentEnforcementTest(unittest.TestCase):
    """파싱한 학점 요청이 `build_timetable`에서 LLM 인자를 실제로 덮어쓰는지.

    프롬프트에만 적어두면 새는 게 이미 여러 번 관측됐다. 시간 제약과 같은 방식으로
    도구 계층에서 확정한다.
    """

    def _db_with_courses(self):
        db = _make_db()
        user = _make_student(db)
        # 3학점 7개 = 최대 21 (기본 상한). 요일이 전부 달라 어떤 조합도 성립한다.
        for i in range(7):
            _add_course_with_offering(
                db, course_id=i + 1, offering_id=101 + i, name=f"전공{i}", credits=3.0,
                day="월화수목금토일"[i], start="09:00", end="10:15",
            )
        db.flush()
        return db, user


    def test_가볍게는_자동_목표_대신_낮은_목표를_쓴다(self):
        """"가볍게 듣고 싶어"에 17학점을 내놓던 실측 실패의 회귀 테스트."""
        db, user = self._db_with_courses()
        ctx = _TimeTableToolContext(
            db, user, year="2026", semester="2학기",
            credit_intent=timetable_chat_mod._parse_credit_intent("가볍게 듣고 싶어"),
        )

        result = ctx.build_timetable(
            offering_ids=[101, 102, 103, 104, 105, 106, 107],
            target_credits=16, credit_mode="at_least",
        )

        self.assertEqual(12.0, result["target_credits"])
        self.assertLessEqual(
            result["schedules"][0]["total_credits"], 13.0,
            "'가볍게'라고 했는데 상한 근처로 채우면 요청을 무시한 답이다",
        )

    def test_요청이_없으면_기존_동작_그대로(self):
        db, user = self._db_with_courses()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        result = ctx.build_timetable(
            offering_ids=[101, 102, 103, 104, 105, 106, 107],
            target_credits=18, credit_mode="at_least",
        )

        self.assertEqual(18.0, result["target_credits"])
        self.assertEqual("at_least", result["credit_mode"])
        self.assertNotIn("credit_intent_note", result)


class DuplicateRenderedScheduleTest(unittest.TestCase):
    """사용자 눈에 **똑같아 보이는** 후보가 여러 개 나가면 안 된다.

    2026-08-20 실계정 실측: "12학점만 들을래"에 후보 1/2/3이 글자 하나까지 동일하게
    렌더링됐다(같은 4과목, 같은 요일·시간). offering_id만 달랐다 — 같은 과목의 다른
    분반이 같은 시간대에 열려 있었기 때문이다. 선택지를 셋 준 것처럼 보이지만
    실제로는 하나고, 사용자는 뭐가 다른지 찾다가 시간을 버린다.
    """

    def test_같은_시간표로_보이는_조합은_하나만_돌려준다(self):
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="자료구조",
                                  credits=3.0, day="월", start="09:00", end="10:15")
        # 같은 과목의 다른 분반, **같은 요일·같은 시간** → 화면 표시가 완전히 동일하다.
        _add_section(db, course_id=1, offering_id=102, section="002",
                     day="월", start="09:00", end="10:15")
        _add_section(db, course_id=1, offering_id=103, section="003",
                     day="월", start="09:00", end="10:15")
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        result = ctx.build_timetable(offering_ids=[101, 102, 103], target_credits=3)

        self.assertTrue(result["ok"])
        self.assertEqual(
            1, len(result["schedules"]),
            "과목·요일·시간이 전부 같은 조합을 여러 후보로 내놓으면 선택지가 아니라 혼란이다",
        )

    def test_진짜로_다른_시간의_분반은_별도_후보로_남는다(self):
        """중복 제거가 과잉이면 정작 고를 게 없어진다 — 시간이 다르면 다른 후보다."""
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="자료구조",
                                  credits=3.0, day="월", start="09:00", end="10:15")
        _add_section(db, course_id=1, offering_id=102, section="002",
                     day="화", start="14:00", end="15:15")
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        result = ctx.build_timetable(offering_ids=[101, 102], target_credits=3)

        self.assertEqual(2, len(result["schedules"]))


class CriticalMissingOfferedThisTermTest(unittest.TestCase):
    """"이번 학기 개설 안 됨" 경고를 **실제 개설 사실**로 교정한다.

    `_compute_critical_missing_required`(roadmap_chat 공유)는 `courses.semester` —
    카탈로그의 *권장* 학기 — 만 보고 판정한다. `course_offerings`를 안 보므로 같은
    과목명이 다른 교과목코드로 이번 학기에 열려 있으면 거짓 경고가 된다.

    2026-08-20 실계정 실측(컴퓨터공학전공 2026-2학기): 7건 중 일반물리학·공학선형대수학
    2건은 실제로 2026-2학기 분반이 있었고, 그 결과 한 답변에

        "일반물리학 …이 2학기엔 개설되지 않아 시간표에 넣을 수 없어요"
        📋 후보 1 — 일반물리학 (전공기초, 3학점) — 월 15:00-16:15

    가 같이 나갔다. 사용자에겐 그냥 앞뒤가 안 맞는 답변이다.
    """

    def _student_with_two_rows(self):
        db = _make_db()
        user = _make_student(db, department_id=100)
        # 카탈로그 1학기 행 — 이번 학기 분반 0개. 여기서 critical 경고가 나온다.
        db.add(Course(id=9001, course_name="일반물리학", category="전공기초", credits=3.0,
                      year="1", semester="1", department_id=100))
        # 같은 이름의 2학기 행 — 이번 학기 분반 있음.
        _add_course_with_offering(db, course_id=9002, offering_id=201, name="일반물리학",
                                  credits=3.0, day="월", start="15:00", end="16:15",
                                  category="전공기초")
        # 진짜로 이번 학기에 없는 필수 과목 — 경고가 그대로 나가야 한다.
        db.add(Course(id=9003, course_name="논리회로및설계", category="전공필수", credits=3.0,
                      year="2", semester="1", department_id=100))
        db.flush()
        return db, user

    def test_이번_학기에_열린_과목은_미개설_경고에서_빠진다(self):
        db, user = self._student_with_two_rows()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        payload = ctx._critical_missing_split()

        self.assertNotIn(
            "일반물리학",
            [c["course_name"] for c in payload["critical_missing_required"]],
            "담을 수 있는 과목을 '못 담는다'고 알리면 같은 답변 안에서 자기모순이 된다",
        )
        self.assertIn(
            "일반물리학",
            [c["course_name"] for c in payload["missing_required_offered_this_term"]],
            "조용히 버리면 안 된다 — 미이수 필수인데 담을 수 있으니 오히려 1순위 후보다",
        )

    def test_정말_미개설인_필수는_경고가_그대로_나간다(self):
        db, user = self._student_with_two_rows()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        payload = ctx._critical_missing_split()

        self.assertIn(
            "논리회로및설계",
            [c["course_name"] for c in payload["critical_missing_required"]],
            "경고 자체를 죽이면 졸업 지연 위험을 아무도 안 알려준다",
        )


class NotOfferedShadowIsOrderIndependentTest(unittest.TestCase):
    """미개설 안내 억제가 **호출 순서에 의존하지 않아야** 한다.

    예전 `_filter_shadowed_not_offered`는 "같은 턴의 이전 호출에서 개설로 내보낸 이름"만
    봤다. 그래서 먼저 미개설로 나가고 나중 호출에서 개설이 발견되는 순서면 그대로
    새어 나갔다. 개설 여부는 검색 순서와 무관한 DB 사실이므로 DB에 직접 묻는다.
    """

    def test_개설_과목을_먼저_보지_않아도_미개설_목록에서_빠진다(self):
        db = _make_db()
        user = _make_student(db, department_id=100)
        # 이번 학기 분반이 있는 2학기 행
        _add_course_with_offering(db, course_id=1, offering_id=101, name="일반물리학",
                                  credits=3.0, day="월", start="15:00", end="16:15",
                                  category="전공기초")
        # 같은 이름의 1학기 행 — 분반 없음. 이수구분·학점이 달라 형제 조회에도 안 걸린다.
        db.add(Course(id=9002, course_name="일반물리학", category="전공선택", credits=2.0,
                      year="1", semester="1", department_id=100))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        # 개설된 쪽을 한 번도 안 본 상태에서 미개설 행만 집어오는 검색.
        r = ctx.list_offered_courses(query="일반물리학", category="전공선택")

        self.assertNotIn(
            "일반물리학",
            [x["course_name"] for x in r.get("matched_but_not_offered_this_term", [])],
        )


class ScrubInternalTermsTest(unittest.TestCase):
    """답변 본문에 샌 내부 식별자·도구 이름을 사용자 말로 바꾼다.

    2026-08-20 실계정 실측: "아래 조합의 offering_id를 그대로 수강신청에 담으면 됩니다."
    사용자는 offering_id를 볼 수도 쓸 수도 없다 — 화면에 뜨는 건 과목명과 시간표 블록이다.
    """

    def scrub(self, text):
        return timetable_chat_mod._scrub_internal_terms(text)

    def test_내부_식별자가_사용자_말로_바뀐다(self):
        self.assertEqual(
            "아래 조합의 과목을 그대로 수강신청에 담으면 됩니다.",
            self.scrub("아래 조합의 offering_id를 그대로 수강신청에 담으면 됩니다."),
        )

    def test_조사도_함께_고친다(self):
        """그냥 치환하면 '과목를'이 되어 원문보다 더 어색해진다."""
        self.assertEqual("과목을 담으세요", self.scrub("offering_ids를 담으세요"))
        self.assertEqual("시간표 구성으로 만들었어요", self.scrub("build_timetable로 만들었어요"))

    def test_평범한_문장은_건드리지_않는다(self):
        text = "전공필수 위주로 18학점 맞췄어요. 월·수 오전은 비워뒀습니다."
        self.assertEqual(text, self.scrub(text))

    def test_최종_답변에_적용된다(self):
        """치환을 함수만 만들어두고 파이프라인에 안 꽂으면 아무 효과가 없다."""
        import inspect
        source = inspect.getsource(timetable_chat_mod.run_timetable_chat)
        self.assertIn("_scrub_internal_terms(reply_text)", source)



class FewerDaysPreferenceTest(unittest.TestCase):
    """"공강 많게" / "몰아서" 요청이 실제 랭킹에 반영되는지.

    2026-08-20 실계정 실측: "공강 많게 짜줘"에 월·화·수·목 4일짜리 20학점 조합이 나왔고
    답변은 "공강을 최대한 확보하는 쪽으로 …잡았어요"였다. 요일 수는 랭킹에서 4순위라
    사실상 반영되지 않았는데 LLM은 반영했다고 말한 것이다.

    다만 학점 목표(1순위)까지 뒤집으면 안 된다 — 요일 수를 학점 위에 두면 3학점
    단과목 시간표가 1위가 되는 옛 실패(2026-08-17)가 되살아난다.
    """

    @staticmethod
    def _section(offering_id: int, credits: float, day: str, start: int) -> _SectionInfo:
        return _SectionInfo(
            item_id=offering_id, course_id=offering_id, course_code=f"C{offering_id}",
            course_name=f"과목{offering_id}", category="전공선택", credits=credits,
            offering_id=offering_id, section="001", professor=None,
            times=(CourseTime(
                offering_id=offering_id, day_of_week=day,
                start_time=datetime.time(start, 0), end_time=datetime.time(start + 1, 15),
                classroom=None,
            ),),
        )

    def test_요청이_있으면_요일_적은_쪽이_초과학점보다_먼저다(self):
        # 둘 다 목표(12) 이상. 하루에 몰린 12학점 vs 사흘에 흩어진 12학점.
        one_day = [self._section(1, 6.0, "월", 9), self._section(2, 6.0, "월", 11)]
        three_days = [self._section(3, 6.0, "화", 9), self._section(4, 6.0, "수", 9)]
        ranked = _rank_built_combos([three_days, one_day], target_credits=12.0,
                                    prefer_fewer_days=True)
        self.assertEqual({"월"}, {t.day_of_week for s in ranked[0] for t in s.times})

    def test_요청이_없으면_기존_랭킹_그대로(self):
        """기본 동작을 바꾸면 안 된다 — 요일 수는 여전히 초과학점보다 아래다."""
        one_day_over = [self._section(1, 9.0, "월", 9), self._section(2, 9.0, "월", 11)]
        two_days_exact = [self._section(3, 6.0, "화", 9), self._section(4, 6.0, "수", 9)]
        ranked = _rank_built_combos([one_day_over, two_days_exact], target_credits=12.0)
        self.assertEqual(12.0, sum(s.credits for s in ranked[0]))

    def test_요청_문구_판정(self):
        parse = timetable_chat_mod._prefers_fewer_days
        for msg in ["공강 많게 짜줘", "몰아서 듣고 싶어", "주 3일만 나가고 싶어", "학교 적게 나가게"]:
            self.assertTrue(parse(msg), msg)
        for msg in ["이번 학기 시간표 짜줘", "18학점으로 짜줘", None, ""]:
            self.assertFalse(parse(msg), msg)

    def test_학점_목표는_여전히_1순위(self):
        """요일 수를 학점보다 위에 두면 단과목 시간표가 1위가 된다 (2026-08-17 실패)."""
        single_course = [self._section(1, 3.0, "월", 9)]
        full_load = [
            self._section(2, 3.0, "화", 9), self._section(3, 3.0, "화", 11),
            self._section(4, 3.0, "수", 9), self._section(5, 3.0, "수", 11),
        ]
        ranked = _rank_built_combos([single_course, full_load], target_credits=12.0,
                                    prefer_fewer_days=True)
        self.assertEqual(12.0, sum(s.credits for s in ranked[0]))



class ExactTargetAlreadyMetByLockedTest(unittest.TestCase):
    """이미 담아둔 강좌만으로 요청 학점을 채운 경우의 사유가 정확한지.

    "12학점만"인데 시간표에 이미 12학점이 담겨 있으면 더 담을 게 없다. 예전에는
    학점 상한(21) 기준으로만 봐서 이 상황이 `no_feasible_combination`("후보 분반들이
    서로 시간이 겹쳐서 성립하는 조합이 없다")으로 나갔다 — 시간 문제가 아닌데 시간
    탓을 하면 LLM은 후보를 넓혀 재호출하고 사용자에겐 틀린 이유가 나간다.
    """

    def test_사유가_시간충돌이_아니라_학점으로_나온다(self):
        db = _make_db()
        user = _make_student(db)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="이미담김A",
                                  credits=3.0, day="월", start="09:00", end="10:15")
        _add_course_with_offering(db, course_id=2, offering_id=102, name="이미담김B",
                                  credits=3.0, day="화", start="09:00", end="10:15")
        _add_course_with_offering(db, course_id=3, offering_id=103, name="후보",
                                  credits=3.0, day="수", start="09:00", end="10:15")
        plan = CoursePlan(id=1, user_id=user.id, year="2026", semester="2학기", title="내 시간표")
        db.add(plan)
        db.flush()
        db.add(CoursePlanItem(plan_id=1, offering_id=101, source="manual"))
        db.add(CoursePlanItem(plan_id=1, offering_id=102, source="manual"))
        db.flush()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기", plan_id=1)

        result = ctx.build_timetable(
            offering_ids=[103], target_credits=6, credit_mode="exact",
        )

        self.assertFalse(result["ok"])
        self.assertEqual("exact_target_reached_by_locked", result["reason"])
        self.assertIn("시간이 겹쳐서가 아니다", result["hint"])



class NotOfferedNoticeOnlyForNamedCoursesTest(unittest.TestCase):
    """미개설 안내는 사용자가 **이름을 콕 집어 물은 과목**에만 붙어야 한다.

    검색기는 의미 유사도로 뽑는다. 실 DB 확인(2026-08-20): query='일반물리학'인데
    `matched_but_not_offered_this_term`에 '건강과레포츠', '생명의료윤리', '수학(I)'가
    함께 들어왔다. 카테고리만 걸고 훑는 호출(query 없음)은 아예 "이 과목 담고 싶다"는
    요청이 아닌데도 미개설 목록이 붙었다. 그대로 두면 LLM이 사용자가 언급한 적도 없는
    과목을 붙잡고 "이번 학기에 개설되지 않았습니다"라고 알린다.
    """

    def _db(self):
        db = _make_db()
        user = _make_student(db, department_id=100)
        _add_course_with_offering(db, course_id=1, offering_id=101, name="데이터베이스",
                                  credits=3.0, day="월", start="09:00", end="10:30",
                                  category="전공선택")
        db.add(Course(id=9001, course_name="건강과레포츠", category="전공선택", credits=1.0,
                      year="1", semester="1", department_id=100))
        db.flush()
        return db, user

    def test_카테고리만_훑는_호출에는_미개설_목록이_안_붙는다(self):
        db, user = self._db()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        r = ctx.list_offered_courses(category="전공선택")

        self.assertNotIn("matched_but_not_offered_this_term", r)

    def test_검색어와_이름이_안_맞으면_미개설_안내에서_빠진다(self):
        db, user = self._db()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        r = ctx.list_offered_courses(query="데이터베이스")

        self.assertNotIn(
            "건강과레포츠",
            [x["course_name"] for x in r.get("matched_but_not_offered_this_term", [])],
        )

    def test_이름이_맞으면_그대로_안내한다(self):
        """골든 케이스 21의 보호막을 약화시키면 안 된다."""
        db, user = self._db()
        ctx = _TimeTableToolContext(db, user, year="2026", semester="2학기")

        r = ctx.list_offered_courses(query="건강과레포츠")

        self.assertIn(
            "건강과레포츠",
            [x["course_name"] for x in r.get("matched_but_not_offered_this_term", [])],
        )



if __name__ == "__main__":
    unittest.main()


class ExclusionBeforeRestrictionTest(unittest.TestCase):
    """배제형을 먼저 잡고 **그 구간을 지운 뒤** 한정형을 봐야 한다.

    독립 리뷰(2026-08-20)가 잡았다 — 이 순서를 지키는 테스트가 없어서, 구간 삭제
    3줄을 없애도 92건이 전부 통과했다. 삭제가 없으면 한정형이 배제 표현까지 다시
    읽어 **자기모순 제약**이 나온다:

        "오전만 빼줘"    → {exclude_period: morning, period: morning}
        "화목만 빼고 짜줘" → {exclude_days: {화,목}, days: {화,목}}

    모순 제약이 걸리면 `_times_violate_constraint`가 모든 분반을 탈락시켜
    **빈 시간표**가 나간다.

    (기존 `test_오전_수업은_빼줘가_정반대로_뒤집히지_않는다`는 메시지에 `만/에만/위주`가
    없어 한정형 분기 자체가 안 돌아서 이 회귀를 못 잡았다.)
    """

    def test_배제와_한정이_동시에_잡히지_않는다(self):
        cases = ("오전만 빼줘", "오후만 빼줘", "화목만 빼고 짜줘", "월수금만 빼줘")
        for message in cases:
            with self.subTest(message=message):
                parsed = timetable_chat_mod._parse_time_constraint(message) or {}
                if "exclude_period" in parsed:
                    self.assertNotIn(
                        "period", parsed,
                        f"{message!r}가 배제와 한정을 동시에 만든다 — 모든 분반이 탈락해 "
                        "빈 시간표가 나간다",
                    )
                if "exclude_days" in parsed:
                    self.assertNotIn("days", parsed, f"{message!r}: 배제·한정 동시 발생")

    def test_배제만_남는다(self):
        self.assertEqual({"exclude_period": "morning"}, timetable_chat_mod._parse_time_constraint("오전만 빼줘"))
        self.assertEqual(
            {"exclude_days": {"화", "목"}}, timetable_chat_mod._parse_time_constraint("화목만 빼고 짜줘")
        )

    def test_순수_한정형은_그대로_동작한다(self):
        """배제 표현이 없으면 한정형이 정상적으로 잡혀야 한다."""
        self.assertEqual({"days": {"월", "수", "금"}}, timetable_chat_mod._parse_time_constraint("월수금만"))
        self.assertEqual({"period": "morning"}, timetable_chat_mod._parse_time_constraint("오전에만"))


class CreditIntentIsLightOnlyTest(unittest.TestCase):
    """`_parse_credit_intent`는 **"가볍게"만** 뽑는다. 숫자는 LLM이 넘긴 값을 쓴다.

    ## 왜 이 테스트가 있는가 — 2026-08-20 설계 검토

    한때 이 파서가 `"18학점으로"` 같은 숫자도 뽑아 **LLM 인자를 덮어썼다.** 네 번의
    리뷰를 거치며 오탐이 계속 나왔고, 마지막에 수렴 불가라는 게 드러났다:

      - 오탐의 원인이 **요청 꼬리 화이트리스트 자체**였다. `만`은 조사(`12학점만`)이자
        `만점`의 첫 글자다. 한국어는 교착어라 접두 검사로 요청과 서술을 가를 수 없다.
        넣으면 오탐, 빼면 미탐 — **배제 목록을 늘려도 안 된다.**
      - `max` 우선 규칙이 그걸 증폭했다. 과거 학점은 대개 큰 값이라
        `"21학점까지 신청 가능하다던데 18학점으로 해줘"` → **21**.
        **이 PR이 없애려던 실패를 파서가 그대로 재생산했다.**

    그리고 원래 동기("LLM이 숫자를 안 넘긴다")는 **관측된 적이 없다.** 2026-08-19의
    "18 요청 → 21" 사고는 LLM이 18을 제대로 넘겼는데 랭킹 키가 버그였던 것이다.

    숫자 파싱을 되살리려면 **먼저 LLM이 실제로 숫자를 빠뜨리는지 측정**해야 한다
    (`credit_intent`가 이미 Langfuse trace로 나간다). 이 테스트는 그 전에 조용히
    되살아나는 것을 막는다.
    """

    def test_숫자만_있는_요청은_파서가_손대지_않는다(self):
        for message in ("18학점으로 짜줘", "12학점만", "딱 15학점", "15학점 이상으로",
                        "총 15학점", "12학점 신청할래", "15학점 채워줘"):
            with self.subTest(message=message):
                self.assertIsNone(
                    timetable_chat_mod._parse_credit_intent(message),
                    "숫자 파싱을 되살리려면 LLM 준수율 측정이 먼저다 — 화이트리스트/"
                    "배제리스트 구조는 오탐과 미탐을 동시에 줄이지 못한다.",
                )

    def test_서술_문장도_당연히_안_잡힌다(self):
        """숫자 경로가 없으니 과거·요건 서술 오탐도 구조적으로 불가능하다."""
        for message in ("작년에 21학점 신청했다가 망했어", "3학점 만점 받았어",
                        "15학점 정도가 평균이래", "21학점까지 신청 가능하다던데",
                        "21학점까지 신청 가능하다던데 18학점으로 해줘"):
            with self.subTest(message=message):
                self.assertIsNone(timetable_chat_mod._parse_credit_intent(message))

    def test_가볍게는_그대로_잡힌다(self):
        """이건 실측 근거가 있다 — mini가 없는 숫자(16)를 지어내 17학점을 내놨다."""
        for message in ("가볍게 듣고 싶어", "이번 학기는 널널하게", "부담없이 듣고 싶어",
                        "쉬엄쉬엄 가고 싶어"):
            with self.subTest(message=message):
                intent = timetable_chat_mod._parse_credit_intent(message)
                self.assertIsNotNone(intent, f"{message!r}를 놓치면 자동 목표(상한 80%)로 돌아간다")
                self.assertEqual("light", intent["style"])
                self.assertIsNone(intent["target_credits"])

    def test_숫자가_가볍게를_가리지_않는다(self):
        """예전엔 숫자 경로가 먼저 return해서 light를 덮었다 —
        `"지난 학기 21학점 신청했는데 이번엔 가볍게 듣고 싶어"` → exact 21."""
        intent = timetable_chat_mod._parse_credit_intent(
            "지난 학기 21학점 신청했는데 이번엔 가볍게 듣고 싶어"
        )
        self.assertIsNotNone(intent)
        self.assertEqual("light", intent["style"])
