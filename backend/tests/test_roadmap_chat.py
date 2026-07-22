import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.domains.academics.models import (
    College, Department, GraduationRequirement, Major, School, StudentCourseRecord,
    UserAcademicProgram,
)
from app.domains.courses.models import Course
from app.domains.planning.models import CourseRoadmap, CourseRoadmapItem, PendingRoadmapChange
from app.domains.planning import roadmap_chat as roadmap_chat_mod
from app.domains.planning.roadmap_chat import _ToolContext
from app.domains.users.models import User


# 학점 상한 조회가 UserAcademicProgram/GraduationRequirement/hierarchy 테이블을 참조하므로
# in-memory sqlite에서도 이 스키마들을 함께 만들어놔야 한다. get_roadmap_items 호출이 있는
# 테스트가 여러 클래스에 걸쳐 있어 공통 상수로 뽑아둔다.
_ROADMAP_TEST_TABLES = [
    School.__table__, College.__table__, Department.__table__, Major.__table__,
    User.__table__, Course.__table__,
    CourseRoadmap.__table__, CourseRoadmapItem.__table__, PendingRoadmapChange.__table__,
    UserAcademicProgram.__table__, GraduationRequirement.__table__,
    StudentCourseRecord.__table__,
]


class ProposeChangeGradeGuardTest(unittest.TestCase):
    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        session_factory = sessionmaker(bind=engine)
        return session_factory()

    def make_roadmap(self, db, completed_grades):
        user = User(id=1, email="t@example.com", password_hash="x", name="테스트")
        db.add(user)
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(roadmap)
        db.flush()
        for i, grade in enumerate(completed_grades):
            db.add(
                CourseRoadmapItem(
                    roadmap_id=roadmap.id,
                    course_name=f"이수과목{i}",
                    planned_grade=grade,
                    status="completed",
                )
            )
        db.flush()
        return user, roadmap

    def test_transfer_student_rejects_lower_grade_than_earliest_completed(self):
        db = self.make_db()
        user, roadmap = self.make_roadmap(db, completed_grades=[3, 3, 4])
        ctx = _ToolContext(db, user, roadmap)

        result = ctx.propose_change(action="create", reason="test", planned_grade=1)

        self.assertIn("error", result)
        self.assertEqual(0, len(ctx.pending_changes))

    def test_allows_grade_at_or_above_earliest_completed(self):
        db = self.make_db()
        user, roadmap = self.make_roadmap(db, completed_grades=[3, 4])
        ctx = _ToolContext(db, user, roadmap)

        result = ctx.propose_change(action="create", reason="test", planned_grade=3)

        self.assertNotIn("error", result)
        self.assertEqual(1, len(ctx.pending_changes))

    def test_no_completed_items_means_no_restriction(self):
        db = self.make_db()
        user, roadmap = self.make_roadmap(db, completed_grades=[])
        ctx = _ToolContext(db, user, roadmap)

        result = ctx.propose_change(action="create", reason="test", planned_grade=1)

        self.assertNotIn("error", result)
        self.assertEqual(1, len(ctx.pending_changes))

    def test_get_roadmap_items_exposes_earliest_recorded_grade(self):
        db = self.make_db()
        user, roadmap = self.make_roadmap(db, completed_grades=[3, 4])
        ctx = _ToolContext(db, user, roadmap)

        result = ctx.get_roadmap_items()

        self.assertEqual(3, result["earliest_recorded_grade"])

    def test_get_roadmap_items_exposes_current_and_next_term(self):
        """LLM이 '지금 몇 학기인지'를 알아야 과거 학기로 새 항목을 만들지 않는다."""
        db = self.make_db()
        user, roadmap = self.make_roadmap(db, completed_grades=[])
        ctx = _ToolContext(db, user, roadmap)

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.get_roadmap_items()

        self.assertEqual(result["current_academic_term"], {"year": "2026", "semester": "1학기"})
        self.assertEqual(result["next_plannable_term"], {"year": "2026", "semester": "2학기"})

    def test_get_roadmap_items_wraps_year_when_current_is_second_semester(self):
        db = self.make_db()
        user, roadmap = self.make_roadmap(db, completed_grades=[])
        ctx = _ToolContext(db, user, roadmap)

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 2)):
            result = ctx.get_roadmap_items()

        self.assertEqual(result["next_plannable_term"], {"year": "2027", "semester": "1학기"})


class SearchCoursesBrowsingTest(unittest.TestCase):
    """search_courses가 빈 query + semester/category 필터만으로도 학기별 후보를
    돌려줘야 한다. 예전엔 빈 query면 무조건 빈 결과였고 필터도 노출 안 됐다 —
    그래서 계절수업 후보를 걸러낸 뒤 다른 정규 학기 대안을 찾지 못하고 "추천할 게
    없다"고 답하고 끝나던 사례가 발생했다.
    """

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def make_ctx(self, db, department_id=10, major_id=None):
        user = User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=department_id, major_id=major_id)
        db.add(user)
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(roadmap)
        db.flush()
        return _ToolContext(db, user, roadmap)

    def test_empty_query_with_semester_filter_returns_regular_and_agnostic_courses(self):
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add_all(
            [
                Course(id=1, course_name="정규2학기전공선택", department_id=10,
                       category="전공선택", credits=3.0, year="3", semester="2"),
                Course(id=2, course_name="정규1학기전공선택", department_id=10,
                       category="전공선택", credits=3.0, year="3", semester="1"),
                Course(id=3, course_name="여름계절PBL", department_id=10,
                       category="전공선택", credits=3.0, year="3", semester="여름계절수업"),
                Course(id=4, course_name="학기무관과목", department_id=10,
                       category="전공선택", credits=3.0, year="3", semester="전학기"),
            ]
        )
        db.commit()

        result = ctx.search_courses(query="", semester="2학기", category="전공선택")
        ids = {r["course_id"] for r in result["results"]}
        self.assertEqual({1, 4}, ids)  # 2 (다른 학기), 3 (계절수업) 제외

    def test_empty_query_without_department_returns_nothing(self):
        db = self.make_db()
        ctx = self.make_ctx(db, department_id=None)
        result = ctx.search_courses(query="", semester="2학기")
        self.assertEqual([], result["results"])


class ProposeChangePastTermGuardTest(unittest.TestCase):
    """이미 지난 학기로 새 항목을 만들려는 시도는 create에서 거부돼야 한다.

    실제 pending_roadmap_changes에 `(planned_year='2023', '2학기')` 같은 과거 학기
    제안이 쌓여 있어 발견된 버그. LLM이 학기 정보를 참조하지 않고 임의 학기를
    지정하는 걸 도구 계층에서 막는다.
    """

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def make_ctx(self, db):
        user = User(id=1, email="t@example.com", password_hash="x", name="테스트")
        db.add(user)
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(roadmap)
        db.flush()
        return _ToolContext(db, user, roadmap)

    def test_create_in_past_term_is_rejected(self):
        db = self.make_db()
        ctx = self.make_ctx(db)
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test",
                planned_year="2024", planned_semester="2학기", planned_grade=2,
            )
        self.assertIn("error", result)
        self.assertIn("과거", result["error"])
        self.assertEqual(0, len(ctx.pending_changes))

    def test_create_in_current_term_is_allowed(self):
        db = self.make_db()
        ctx = self.make_ctx(db)
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test",
                planned_year="2026", planned_semester="1학기", planned_grade=2,
            )
        self.assertNotIn("error", result)
        self.assertEqual(1, len(ctx.pending_changes))

    def test_create_in_future_term_is_allowed(self):
        db = self.make_db()
        ctx = self.make_ctx(db)
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test",
                planned_year="2027", planned_semester="1학기", planned_grade=3,
            )
        self.assertNotIn("error", result)

    def test_create_with_ambiguous_semester_string_does_not_get_blocked(self):
        """`"1학기 또는 2학기"`(전학기 개설)처럼 파싱 불가한 학기 문자열이 오면
        가드는 통과시켜야 한다 — 오탐으로 정상 제안을 막지 않는다."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test",
                planned_year="2024", planned_semester="1학기 또는 2학기", planned_grade=2,
            )
        self.assertNotIn("error", result)

    def test_summer_session_course_cannot_be_placed_into_regular_semester(self):
        """실제 사고 재현: '로보틱스 AI PBL'(courses.semester='여름계절수업')을
        '3학년 2학기(=다음 학기)' 슬롯에 create로 제안하는 시도는 거부돼야 한다."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=42, course_name="로보틱스 AI PBL", department_id=108,
                      major_id=35, category="전공선택", credits=3.0,
                      year="3", semester="여름계절수업"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="다음 학기 추천",
                course_id=42, planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertIn("error", result)
        self.assertIn("여름계절수업", result["error"])
        self.assertEqual(0, len(ctx.pending_changes))

    def test_summer_session_course_can_be_placed_into_summer_session_slot(self):
        """계절수업 과목을 계절수업 슬롯으로 제안하는 정당한 경우는 통과해야 한다."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=42, course_name="로보틱스 AI PBL", department_id=108,
                      major_id=35, category="전공선택", credits=3.0,
                      year="3", semester="여름계절수업"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="여름계절수업 추천",
                course_id=42, planned_year="2026", planned_semester="여름계절수업",
                planned_grade=3,
            )
        self.assertNotIn("error", result)
        self.assertEqual(1, len(ctx.pending_changes))

    def test_regular_semester_course_still_allowed_in_regular_semester(self):
        """정규 1/2학기 개설 과목은 정규 학기 슬롯으로 자유롭게 제안 가능해야 한다."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=100, course_name="일반 전공선택", department_id=10,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test",
                course_id=100, planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertNotIn("error", result)

    def test_semester_agnostic_course_is_allowed_in_regular_semester(self):
        """'전학기'/'1,2' 처럼 학기 무관 개설 과목은 정규 학기 슬롯 배치 정상."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=101, course_name="학기무관 과목", department_id=10,
                      category="전공선택", credits=3.0, year="전학년", semester="전학기"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test",
                course_id=101, planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertNotIn("error", result)

    def test_update_in_past_term_is_not_blocked_by_this_guard(self):
        """update는 이미 있는 항목의 이동/정정이라 과거로 되돌리는 요청도 정당한 경우가
        있다(계절수업으로 옮기기 등). 이 가드는 create만 대상으로 한다."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        # 우선 update 대상이 될 기존 item을 만든다.
        item = CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="X", planned_grade=2)
        db.add(item)
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="update", reason="test", item_id=item.id,
                planned_year="2024", planned_semester="2학기",
            )
        self.assertNotIn("error", result)


class TermCreditCapGuardTest(unittest.TestCase):
    """PNU 학사 규정: 정규 학기당 수강신청 학점 상한(졸업기준학점 133 이상=21학점,
    이하=19학점). 로드맵에 이 상한을 넘겨 create/update되는 걸 도구 단에서 막는다.
    """

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def make_ctx(self, db, total_req=133):
        user = User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=10, major_id=20)
        db.add(user)
        db.add(UserAcademicProgram(user_id=1, program_type="primary",
                                    department_id=10, major_id=20, curriculum_year=2026))
        db.add(GraduationRequirement(department_id=10, major_id=20, program_type="primary",
                                      curriculum_year="2026", required_total_credits=total_req))
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(roadmap)
        db.flush()
        return _ToolContext(db, user, roadmap)

    def test_get_roadmap_items_exposes_credit_cap_and_planned_by_term(self):
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)
        db.add_all([
            CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="A", credits=3,
                               planned_year="2026", planned_semester="2학기"),
            CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="B", credits=4,
                               planned_year="2026", planned_semester="2학기"),
        ])
        db.flush()
        result = ctx.get_roadmap_items()
        self.assertEqual(21, result["term_credit_cap"])
        by_term = {(t["planned_year"], t["planned_semester"]): t["credits"]
                   for t in result["planned_credits_by_term"]}
        self.assertEqual(7.0, by_term[("2026", "2학기")])

    def test_credit_cap_19_when_total_required_is_132_or_less(self):
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=130)
        self.assertEqual(19, ctx._term_credit_cap())

    def test_create_rejects_when_new_credit_exceeds_cap(self):
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)  # cap=21
        # 이미 19학점 잡혀 있음
        db.add_all([
            CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="A", credits=6,
                               planned_year="2026", planned_semester="2학기"),
            CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="B", credits=7,
                               planned_year="2026", planned_semester="2학기"),
            CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="C", credits=6,
                               planned_year="2026", planned_semester="2학기"),
        ])
        # 새 3학점 과목 추가 시도 → 19 + 3 = 22 > 21
        db.add(Course(id=200, course_name="새전공", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test", course_id=200,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertIn("error", result)
        self.assertIn("학기당 상한", result["error"])
        self.assertEqual(0, len(ctx.pending_changes))

    def test_cap_exceeded_error_carries_swap_candidates(self):
        """상한 초과 시 그 학기에 이미 있는 항목 목록을 함께 돌려줘야 한다 — LLM이 대체
        가능한 항목을 골라 swap 제안을 만들 수 있도록."""
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)  # cap=21
        db.add_all([
            CourseRoadmapItem(id=101, roadmap_id=ctx.roadmap.id, course_id=1001,
                               course_name="이미A", category="전공선택", credits=6,
                               planned_year="2026", planned_semester="2학기"),
            CourseRoadmapItem(id=102, roadmap_id=ctx.roadmap.id, course_id=1002,
                               course_name="이미B", category="전공선택", credits=7,
                               planned_year="2026", planned_semester="2학기"),
            CourseRoadmapItem(id=103, roadmap_id=ctx.roadmap.id, course_id=1003,
                               course_name="이미C", category="전공선택", credits=6,
                               planned_year="2026", planned_semester="2학기"),
            # 다른 학기 항목은 결과에 나오면 안 됨
            CourseRoadmapItem(id=104, roadmap_id=ctx.roadmap.id, course_id=1004,
                               course_name="딴학기", category="전공선택", credits=3,
                               planned_year="2026", planned_semester="1학기"),
        ])
        db.add(Course(id=300, course_name="새전공", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test", course_id=300,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertIn("error", result)
        self.assertIn("current_items_in_term", result)
        item_ids = {it["item_id"] for it in result["current_items_in_term"]}
        self.assertEqual({101, 102, 103}, item_ids)  # 그 학기 것만
        self.assertEqual(result["term_credit_cap"], 21)
        self.assertEqual(result["term_existing_credits"], 19.0)
        self.assertIn("hint", result)

    def _fill_term_to_19(self, db, ctx):
        db.add_all([
            CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="X1", credits=6,
                               planned_year="2026", planned_semester="2학기"),
            CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="X2", credits=7,
                               planned_year="2026", planned_semester="2학기"),
            CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="X3", credits=6,
                               planned_year="2026", planned_semester="2학기"),
        ])

    def test_cap_hint_semester_locked_course_not_deferable_across_terms(self):
        """2학기 전용 개설 과목이 상한에 걸리면 '다음 학기(1학기)로'가 아니라 '같은 학기의
        다음 연도(4-2)로' 미루라고 안내돼야 한다."""
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)  # cap=21
        self._fill_term_to_19(db, ctx)
        # 2학기 전용
        db.add(Course(id=500, course_name="2학기전용", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test", course_id=500,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertIn("hint", result)
        self.assertEqual(result["course_semester"], "2")
        self.assertIn("2학기 전용", result["hint"])
        self.assertIn("다음 연도", result["hint"])

    def test_cap_hint_semester_agnostic_course_is_deferable(self):
        """1,2/전학기 개설 과목이 상한에 걸리면 다음 정규 학기로 옮길 수 있다고 안내돼야 한다."""
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)
        self._fill_term_to_19(db, ctx)
        db.add(Course(id=501, course_name="학기무관", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="전학년", semester="1,2"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test", course_id=501,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertEqual(result["course_semester"], "1,2")
        self.assertIn("1학기·2학기 모두 개설", result["hint"])

    def test_create_allowed_at_boundary(self):
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)  # cap=21
        db.add(CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="A", credits=18,
                                  planned_year="2026", planned_semester="2학기"))
        db.add(Course(id=201, course_name="새3학점", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test", course_id=201,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertNotIn("error", result)  # 18+3=21, 상한과 같아 통과

    def test_summer_session_not_capped_by_regular_limit(self):
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)
        # 여름계절수업에는 이미 계획된 학점이 상한 넘어도 정규 상한 가드는 걸리지 않아야 함
        db.add(CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="A", credits=21,
                                  planned_year="2026", planned_semester="여름계절수업"))
        db.add(Course(id=202, course_name="계절3학점", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="여름계절수업"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test", course_id=202,
                planned_year="2026", planned_semester="여름계절수업", planned_grade=3,
            )
        self.assertNotIn("error", result)

    def test_update_moves_credit_between_terms_without_self_counting(self):
        """같은 학기 안에서 자신을 옮기는 update가 자기 학점을 이중 계산하지 않아야 한다."""
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)  # cap=21
        db.add(Course(id=203, course_name="X", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        item = CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_id=203, course_name="X",
                                  credits=3, planned_year="2026", planned_semester="2학기")
        db.add(item)
        # 다른 항목들이 그 학기에 18학점 더 있음. 자기 자신 3 포함해서 21학점.
        db.add(CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="Y", credits=18,
                                  planned_year="2026", planned_semester="2학기"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            # 같은 학기(=2026-2학기)로 재배치 update: exclude_item_id로 자신 학점 빠지면
            # 다른 항목 18 + 자기 3 = 21 (상한 이내). 통과해야 함.
            result = ctx.propose_change(
                action="update", reason="test", item_id=item.id, course_id=203,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertNotIn("error", result)


class TransferStudentFallbackGuardTest(unittest.TestCase):
    """편입생이 로드맵에 아직 completed 항목이 하나도 없어도(편입 인정만 있는 상태),
    StudentCourseRecord.semester='입학전성적' 존재로 편입생임을 감지해 1·2학년
    create를 도구 단에서 차단해야 한다."""

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def make_ctx(self, db):
        user = User(id=1, email="t@example.com", password_hash="x", name="편입생",
                    department_id=10, major_id=20)
        db.add(user)
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(roadmap)
        db.flush()
        return _ToolContext(db, user, roadmap)

    def test_transfer_student_with_only_pre_enrollment_records_defaults_to_grade3(self):
        db = self.make_db()
        ctx = self.make_ctx(db)
        # 편입 인정만 있고 아직 부산대 학기 시작 전
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이산수학",
                                     category="전공기초", credits=3,
                                     year="2026", semester="입학전성적"))
        db.flush()
        self.assertEqual(3, ctx._min_completed_grade())

    def test_transfer_student_create_at_grade_2_is_rejected(self):
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이산수학",
                                     category="전공기초", credits=3,
                                     year="2026", semester="입학전성적"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test",
                planned_year="2026", planned_semester="1학기", planned_grade=2,
            )
        self.assertIn("error", result)
        self.assertIn("최저 학년은 3학년", result["error"])

    def test_freshman_without_records_is_not_blocked(self):
        """일반 신입생(이수기록 없음)은 1학년으로 자유롭게 create 가능해야 한다."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test",
                planned_year="2026", planned_semester="1학기", planned_grade=1,
            )
        self.assertNotIn("error", result)

    def test_actual_completed_takes_precedence_over_fallback(self):
        """이미 학기 밟아 completed items 있으면 그 min을 쓴다(폴백 안 발동)."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        # 편입 인정 + 이미 3-1 학기 completed
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이산수학",
                                     category="전공기초", credits=3,
                                     year="2026", semester="입학전성적"))
        db.add(CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="X",
                                  planned_grade=4, status="completed"))
        db.flush()
        # min=4가 되어야 함 (편입 폴백 3이 아니라)
        self.assertEqual(4, ctx._min_completed_grade())


class StudentContextBlockTest(unittest.TestCase):
    """시스템 프롬프트에 학생 진로/전공/이수기록이 실제로 붙는지 확인."""

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def test_context_block_includes_career_and_program_and_completed(self):
        from app.domains.planning.roadmap_chat import _build_student_context_block
        db = self.make_db()
        # 학과 계층 시드
        db.add_all([
            School(id=1, name="부산대학교"),
            College(id=1, school_id=1, name="정보의생명공학대학"),
            Department(id=10, college_id=1, name="정보컴퓨터공학부"),
            Major(id=20, department_id=10, name="컴퓨터공학전공"),
        ])
        db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=10, major_id=20, career_goal="시스템 프로그래밍"))
        db.add(UserAcademicProgram(user_id=1, program_type="primary",
                                    department_id=10, major_id=20, curriculum_year=2024))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이산수학",
                                     category="전공기초", credits=3, year="2026", semester="입학전성적"))
        db.commit()

        u = db.get(User, 1)
        block = _build_student_context_block(db, u)
        self.assertIn("시스템 프로그래밍", block)
        self.assertIn("컴퓨터공학전공", block)
        self.assertIn("주전공", block)
        self.assertIn("2024 교육과정", block)
        self.assertIn("이산수학", block)

    def test_context_block_handles_missing_career_gracefully(self):
        from app.domains.planning.roadmap_chat import _build_student_context_block
        db = self.make_db()
        db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=None, major_id=None, career_goal=None))
        db.commit()
        block = _build_student_context_block(db, db.get(User, 1))
        self.assertIn("등록된 진로 목표 없음", block)
        self.assertIn("등록된 학적 프로그램 없음", block)
        self.assertIn("성적표 이수기록 없음", block)

    def test_context_block_reflects_secondary_program(self):
        from app.domains.planning.roadmap_chat import _build_student_context_block
        db = self.make_db()
        db.add_all([
            School(id=1, name="부산대학교"),
            College(id=1, school_id=1, name="정보의생명공학대학"),
            Department(id=10, college_id=1, name="정보컴퓨터공학부"),
            Major(id=20, department_id=10, name="컴퓨터공학전공"),
            Department(id=11, college_id=1, name="통계학과"),
        ])
        db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=10, major_id=20, career_goal=None))
        db.add(UserAcademicProgram(user_id=1, program_type="primary",
                                    department_id=10, major_id=20, curriculum_year=2024))
        db.add(UserAcademicProgram(user_id=1, program_type="minor",
                                    department_id=11, major_id=None, curriculum_year=2024))
        db.commit()
        block = _build_student_context_block(db, db.get(User, 1))
        self.assertIn("주전공", block)
        self.assertIn("부전공", block)
        self.assertIn("통계학과", block)


class CompletedCoursesGuardTest(unittest.TestCase):
    """이미 이수한 과목(student_course_records) 재추천 방지. 성적표 파싱 이수기록은
    course_id가 대부분 None이라 이름 기준으로 매칭한다."""

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def make_ctx(self, db):
        user = User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=10, major_id=20)
        db.add(user)
        db.add(CourseRoadmap(id=1, user_id=1))
        db.flush()
        return _ToolContext(db, user, db.get(CourseRoadmap, 1))

    def test_get_roadmap_items_exposes_completed_courses(self):
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(StudentCourseRecord(user_id=1, raw_course_name="자료구조",
                                     category="전공필수", credits=3, year="2026", semester="1학기"))
        db.flush()
        result = ctx.get_roadmap_items()
        self.assertEqual(1, len(result["completed_courses"]))
        self.assertEqual("자료구조", result["completed_courses"][0]["course_name"])

    def test_create_rejects_course_already_completed_by_name(self):
        """성적표에 '데이터구조'로, 교육과정에 '자료구조'로 들어와도 정규화 매칭이 되면 거절."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(StudentCourseRecord(user_id=1, raw_course_name="자료구조",
                                     category="전공필수", credits=3, year="2026", semester="1학기"))
        db.add(Course(id=200, course_name="자료구조", department_id=10, major_id=20,
                      category="전공필수", credits=3.0, year="2", semester="2"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test", course_id=200,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertIn("error", result)
        self.assertIn("이미 이수한 과목", result["error"])
        self.assertEqual(0, len(ctx.pending_changes))

    def test_create_rejects_course_with_roman_numeral_variants(self):
        """이수기록: '컴퓨터프로그래밍 Ⅰ' vs 교육과정: '컴퓨터프로그래밍(I)' 정규화 매칭."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(StudentCourseRecord(user_id=1, raw_course_name="컴퓨터프로그래밍 Ⅰ",
                                     category="전공기초", credits=3, year="2026", semester="입학전성적"))
        db.add(Course(id=201, course_name="컴퓨터프로그래밍(I)", department_id=10, major_id=20,
                      category="전공기초", credits=3.0, year="1", semester="1"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test", course_id=201,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertIn("error", result)
        self.assertIn("이미 이수한 과목", result["error"])

    def test_create_allowed_when_not_in_completed(self):
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이산수학",
                                     category="전공기초", credits=3, year="2026", semester="입학전성적"))
        db.add(Course(id=202, course_name="네트워크보안", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test", course_id=202,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertNotIn("error", result)


class ProposeChangeDuplicateGuardTest(unittest.TestCase):
    """이미 로드맵에 있는 course_id를 create로 또 넣으려는 시도를 도구 단에서 거절.

    실제 관측 사고: 에이전트가 get_roadmap_items를 확인하지 않고, 이미 계획학기에
    같은 과목이 있는데도 propose_change(action="create", course_id=...)로 다시
    제안해서 같은 과목이 로드맵에 두 번 들어가던 사례. update로만 학기 이동 가능하고
    create는 새 과목에만 쓰라는 룰을 도구가 강제하도록 한다.
    """

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def make_ctx(self, db):
        user = User(id=1, email="t@example.com", password_hash="x", name="테스트")
        db.add(user)
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(roadmap)
        db.flush()
        return _ToolContext(db, user, roadmap)

    def test_create_rejects_course_already_on_roadmap(self):
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=100, course_name="자료구조", department_id=10,
                      category="전공필수", credits=3.0, year="2", semester="2"))
        db.add(CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_id=100,
                                 course_name="자료구조", planned_grade=2,
                                 planned_year="2025", planned_semester="2학기"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="다시 추천", course_id=100,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertIn("error", result)
        self.assertIn("이미 로드맵에", result["error"])
        self.assertEqual(0, len(ctx.pending_changes))

    def test_create_rejects_course_already_pending_in_same_run(self):
        """한 대화 안에서 같은 course_id로 create를 두 번 부르면 두 번째는 거절."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=101, course_name="네트워크보안", department_id=10,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            first = ctx.propose_change(
                action="create", reason="추천1", course_id=101,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
            second = ctx.propose_change(
                action="create", reason="추천2", course_id=101,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertNotIn("error", first)
        self.assertIn("error", second)
        self.assertIn("방금 이 대화에서 이미", second["error"])
        self.assertEqual(1, len(ctx.pending_changes))

    def test_update_of_existing_item_still_allowed(self):
        """중복 가드는 create만 대상. 같은 과목을 다른 학기로 옮기는 update는 계속 허용."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=102, course_name="데이터베이스", department_id=10,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        item = CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_id=102,
                                 course_name="데이터베이스", planned_grade=3,
                                 planned_year="2026", planned_semester="1학기")
        db.add(item)
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="update", reason="학기 이동", item_id=item.id,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertNotIn("error", result)

    def test_create_without_course_id_is_not_blocked_by_duplicate_guard(self):
        """course_id 없이 course_name만으로 create하는 경우(자유입력)는 이 가드를 피한다."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test",
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertNotIn("error", result)

    def test_get_roadmap_items_exposes_course_id_for_dedup(self):
        """LLM이 중복을 스스로 피하려면 items의 course_id도 봐야 한다."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=200, course_name="X", department_id=10, category="전공선택",
                      credits=3.0, year="3", semester="1"))
        db.add(CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_id=200,
                                 course_name="X", planned_grade=3))
        db.flush()
        result = ctx.get_roadmap_items()
        self.assertEqual(1, len(result["items"]))
        self.assertEqual(200, result["items"][0]["course_id"])


if __name__ == "__main__":
    unittest.main()
