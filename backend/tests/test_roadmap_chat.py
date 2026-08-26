import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.domains.academics.models import (
    College, Department, GraduationRequirement, Major, ProgramCourse, School, StudentCourseRecord, StudentCourseSubstitution,
    UserAcademicProgram,
)
from app.domains.courses.models import Course
from app.domains.planning.models import (
    CourseRoadmap,
    CourseRoadmapChatMessage,
    CourseRoadmapChatSession,
    CourseRoadmapItem,
    PendingRoadmapChange,
)
from app.domains.planning import roadmap_chat as roadmap_chat_mod
from app.domains.planning.roadmap_chat import _ToolContext, run_roadmap_chat
from app.domains.users.models import User


# 학점 상한 조회가 UserAcademicProgram/GraduationRequirement/hierarchy 테이블을 참조하므로
# in-memory sqlite에서도 이 스키마들을 함께 만들어놔야 한다. get_roadmap_items 호출이 있는
# 테스트가 여러 클래스에 걸쳐 있어 공통 상수로 뽑아둔다.
_ROADMAP_TEST_TABLES = [
    School.__table__, College.__table__, Department.__table__, Major.__table__,
    User.__table__, Course.__table__,
    CourseRoadmap.__table__, CourseRoadmapItem.__table__, PendingRoadmapChange.__table__,
    CourseRoadmapChatSession.__table__, CourseRoadmapChatMessage.__table__,
    UserAcademicProgram.__table__, GraduationRequirement.__table__,
    StudentCourseRecord.__table__, ProgramCourse.__table__,
    StudentCourseSubstitution.__table__,  # 추천 경로가 substituted_course_names를 조회한다
]


# create는 course_id를 요구하므로(빈 로드맵 항목 방지), 다른 가드를 검증하는 테스트도
# 통과시킬 실제 과목이 하나 필요하다. 학기 무관('1,2') 개설이라 계절수업·학기 전용 가드에
# 걸리지 않고, 이름도 다른 시드와 겹치지 않아 이수/중복 가드를 건드리지 않는다.
_GENERIC_COURSE_ID = 7777


def _seed_generic_course(db):
    db.add(Course(id=_GENERIC_COURSE_ID, course_name="일반선택과목", department_id=10,
                  category="전공선택", credits=3, year="1", semester="1,2"))
    db.flush()
    return _GENERIC_COURSE_ID


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
        course_id = _seed_generic_course(db)
        ctx = _ToolContext(db, user, roadmap)

        result = ctx.propose_change(action="create", reason="test", planned_grade=3,
                                    course_id=course_id)

        self.assertNotIn("error", result)
        self.assertEqual(1, len(ctx.pending_changes))

    def test_no_completed_items_means_no_restriction(self):
        db = self.make_db()
        user, roadmap = self.make_roadmap(db, completed_grades=[])
        course_id = _seed_generic_course(db)
        ctx = _ToolContext(db, user, roadmap)

        result = ctx.propose_change(action="create", reason="test", planned_grade=1,
                                    course_id=course_id)

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

    def test_liberal_area_filters_by_general_education_area_not_category(self):
        """liberal_area는 courses.general_education_area 컬럼을 걸러야 한다 — category나
        과목명이 아니라. 같은 교양선택 카테고리 안에서도 영역이 다르면 빠져야 하고,
        결과에 general_education_area가 그대로 노출돼야 LLM이 과목명으로 영역을
        추측하지 않아도 된다."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add_all(
            [
                Course(id=1, course_name="철학의이해", department_id=10,
                       category="효원균형교양", general_education_area="사상과역사",
                       credits=3.0, year="전학년", semester="전학기"),
                Course(id=2, course_name="사회문제탐구", department_id=10,
                       category="효원균형교양", general_education_area="사회와문화",
                       credits=3.0, year="전학년", semester="전학기"),
            ]
        )
        db.commit()

        result = ctx.search_courses(query="", liberal_area="사상과역사")
        self.assertEqual([1], [r["course_id"] for r in result["results"]])
        self.assertEqual("사상과역사", result["results"][0]["general_education_area"])

    def test_liberal_area_no_match_hints_note(self):
        """'외국어'/'융복합'처럼 general_education_area가 아예 없는 영역을 필터하면
        빈 결과에 liberal_area 관련 안내가 붙어야 한다 — LLM이 같은 인수로 반복
        호출하지 않도록."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(
            Course(id=1, course_name="영어회화", department_id=10,
                   category="효원균형교양", general_education_area=None,
                   credits=3.0, year="전학년", semester="전학기"),
        )
        db.commit()

        result = ctx.search_courses(query="", liberal_area="외국어")
        self.assertEqual([], result["results"])
        self.assertIn("liberal_area", result["note"])


class ProposeChangeDepartmentScopeGuardTest(unittest.TestCase):
    """실제 사고(2026-08-25) 재현: gpt-5.4-nano가 컴퓨터공학전공 학생에게 심리학과
    전공선택 과목 3개를 course_id로 직접 지어내 propose_change(action="create")했다.
    search_courses는 department 스코프를 SQL WHERE로 강제해서 그 3과목을 절대
    반환할 수 없었으니, LLM이 search_courses 결과를 실제로 안 보고 course_id를
    지어낸 것 — propose_change가 course_id를 db.get()으로 그냥 신뢰해서 걸러내지
    못했다. 이 가드가 그 자리에서 막아야 한다."""

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def test_rejects_course_outside_student_department(self):
        db = self.make_db()
        user = User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=108)
        db.add(user)
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(roadmap)
        db.add(Course(id=691, course_name="사회심리학", department_id=18,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        db.flush()
        ctx = _ToolContext(db, user, roadmap)

        result = ctx.propose_change(
            action="create", reason="AI/웹응용 계열로 선택", course_id=691,
            planned_year="2026", planned_semester="2학기", planned_grade=3,
        )

        self.assertIn("error", result)
        self.assertIn("소속 범위 밖", result["error"])
        self.assertEqual(0, len(ctx.pending_changes))

    def test_allows_course_in_own_department(self):
        db = self.make_db()
        user = User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=108)
        db.add(user)
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(roadmap)
        db.add(Course(id=6468, course_name="AI프로그래밍", department_id=108,
                      category="전공선택", credits=3.0, year="2", semester="2"))
        db.flush()
        ctx = _ToolContext(db, user, roadmap)

        result = ctx.propose_change(
            action="create", reason="전공선택 추가", course_id=6468,
            planned_year="2026", planned_semester="2학기", planned_grade=3,
        )

        self.assertNotIn("error", result)
        self.assertEqual(1, len(ctx.pending_changes))

    def test_allows_course_in_active_secondary_program_department(self):
        """활성 상태인 부전공/복수전공/연계전공의 department도 허용 범위다."""
        db = self.make_db()
        user = User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=108)
        db.add(user)
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(UserAcademicProgram(user_id=1, program_type="minor",
                                    department_id=18, status="active", curriculum_year=2024))
        db.add(roadmap)
        db.add(Course(id=691, course_name="사회심리학", department_id=18,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        db.flush()
        ctx = _ToolContext(db, user, roadmap)

        result = ctx.propose_change(
            action="create", reason="부전공(심리학과) 이수", course_id=691,
            planned_year="2026", planned_semester="2학기", planned_grade=3,
        )

        self.assertNotIn("error", result)
        self.assertEqual(1, len(ctx.pending_changes))

    def test_unknown_student_scope_does_not_block(self):
        """department_id도 없고 활성 프로그램도 없는(정보 자체가 없는) 학생은
        모르는 걸 위반으로 단정하지 않는다 — _career_looks_mismatched와 같은 원칙."""
        db = self.make_db()
        user = User(id=1, email="t@example.com", password_hash="x", name="테스트")
        db.add(user)
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(roadmap)
        db.add(Course(id=100, course_name="아무과목", department_id=99,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        db.flush()
        ctx = _ToolContext(db, user, roadmap)

        result = ctx.propose_change(
            action="create", reason="추천", course_id=100,
            planned_year="2026", planned_semester="2학기", planned_grade=3,
        )

        self.assertNotIn("error", result)


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
        course_id = _seed_generic_course(db)
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test", course_id=course_id,
                planned_year="2026", planned_semester="1학기", planned_grade=2,
            )
        self.assertNotIn("error", result)
        self.assertEqual(1, len(ctx.pending_changes))

    def test_create_in_future_term_is_allowed(self):
        db = self.make_db()
        ctx = self.make_ctx(db)
        course_id = _seed_generic_course(db)
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test", course_id=course_id,
                planned_year="2027", planned_semester="1학기", planned_grade=3,
            )
        self.assertNotIn("error", result)

    def test_create_with_ambiguous_semester_string_does_not_get_blocked(self):
        """`"1학기 또는 2학기"`(전학기 개설)처럼 파싱 불가한 학기 문자열이 오면
        가드는 통과시켜야 한다 — 오탐으로 정상 제안을 막지 않는다."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        course_id = _seed_generic_course(db)
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test", course_id=course_id,
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


class ProposeChangeUpdateSemesterGuardTest(unittest.TestCase):
    """실제 사고(2026-08-26) 재현: 캡스톤디자인을 4학년 1학기로 옮기는 update 요청을
    처리하며, 2학기 전용 개설인 '딥러닝프로그래밍'이 같이 딸려가 1학기 슬롯에
    꽂혔는데 아무 가드도 안 걸렸다. update는 course_id를 안 넘기는 게 보통이라
    (이미 있는 항목의 학기만 옮기므로) course_obj가 항상 None이었고, 그래서
    create만 쓰던 계절수업/단일학기 가드가 update에서는 통째로 죽어 있었다."""

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

    def test_update_into_wrong_semester_for_single_semester_course_is_rejected(self):
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=708, course_name="딥러닝프로그래밍", department_id=10,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        item = CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_id=708,
                                 course_name="딥러닝프로그래밍", planned_grade=3,
                                 planned_year="2026", planned_semester="2학기",
                                 status="planned")
        db.add(item)
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="update", reason="캡스톤디자인 이동에 딸려간 실수",
                item_id=item.id, planned_grade=4,
                planned_year="2027", planned_semester="1학기",
            )
        self.assertIn("error", result)
        self.assertIn("정규 2학기 전용", result["error"])

    def test_update_into_matching_semester_for_single_semester_course_is_allowed(self):
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=708, course_name="딥러닝프로그래밍", department_id=10,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        item = CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_id=708,
                                 course_name="딥러닝프로그래밍", planned_grade=3,
                                 planned_year="2026", planned_semester="2학기",
                                 status="planned")
        db.add(item)
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="update", reason="4학년 2학기로 정확히 이동",
                item_id=item.id, planned_grade=4,
                planned_year="2027", planned_semester="2학기",
            )
        self.assertNotIn("error", result)

    def test_update_without_semester_change_falls_back_to_existing_placement(self):
        """학년 표기만 고치는 update(planned_semester 없음)는 기존 배치 기준으로
        검사한다 — 이미 맞는 학기에 있으면 통과해야 한다."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=709, course_name="데이터과학입문", department_id=10,
                      category="전공필수", credits=3.0, year="2", semester="1"))
        item = CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_id=709,
                                 course_name="데이터과학입문", planned_grade=2,
                                 planned_year="2027", planned_semester="1학기",
                                 status="planned")
        db.add(item)
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="update", reason="학년 표기 교정", item_id=item.id, planned_grade=4,
            )
        self.assertNotIn("error", result)


class ProposeChangeGradeYearConsistencyGuardTest(unittest.TestCase):
    """실제 사고(2026-08-26) 재현: "캡스톤디자인을 4학년 1학기로 옮겨줘" 처리 중
    LLM이 같은 턴에서 3학년 항목 하나에 4학년 연도(2027)를 잘못 붙인 update를
    하나 더 만들어 승인까지 됐다(pending_roadmap_changes id=498). planned_grade와
    planned_year는 매 호출마다 LLM이 따로 계산해서 넘기는 값이라 서로 어긋나도
    아무도 걸러내지 않았다."""

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

    def test_update_year_conflicting_with_sibling_same_grade_is_rejected(self):
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="캡스톤디자인",
                                  planned_grade=4, planned_year="2027",
                                  planned_semester="1학기", status="planned"))
        # 3학년 2학기 배치의 다른 항목 — 이 학생의 "3학년=2026년" 매핑을 이미 확정해둔
        # 시빌. 이게 없으면 딥러닝프로그래밍 하나만 있어서 그 항목 자신 말고는 비교
        # 대상이 없다(실제 사고에서는 같은 2026-2학기 묶음 항목 여럿이 이 역할이었다).
        db.add(CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="논리회로설계및실험",
                                  planned_grade=3, planned_year="2026",
                                  planned_semester="2학기", status="planned"))
        item = CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="딥러닝프로그래밍",
                                 planned_grade=3, planned_year="2026",
                                 planned_semester="2학기", status="planned")
        db.add(item)
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="update", reason="사용자 요청에 따라 캡스톤디자인을 4학년 1학기로 이동",
                item_id=item.id, planned_grade=3,
                planned_year="2027", planned_semester="2학기",
            )
        self.assertIn("error", result)
        self.assertIn("이미", result["error"])

    def test_update_year_matching_sibling_same_grade_is_allowed(self):
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="캡스톤디자인",
                                  planned_grade=4, planned_year="2027",
                                  planned_semester="1학기", status="planned"))
        item = CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="딥러닝프로그래밍",
                                 planned_grade=3, planned_year="2026",
                                 planned_semester="2학기", status="planned")
        db.add(item)
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="update", reason="4학년 1학기로 정확히 이동",
                item_id=item.id, planned_grade=4,
                planned_year="2027", planned_semester="2학기",
            )
        self.assertNotIn("error", result)

    def test_no_sibling_with_same_grade_means_no_conflict(self):
        db = self.make_db()
        ctx = self.make_ctx(db)
        course_id = _seed_generic_course(db)
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="첫 항목", course_id=course_id, planned_grade=3,
                planned_year="2026", planned_semester="1학기",
            )
        self.assertNotIn("error", result)

    def test_completed_sibling_with_different_year_is_ignored(self):
        """완료된(status='completed') 항목은 실제 이수 기록이라 학년↔연도가 어긋나
        보여도(예: 재수강/편입 이력) 이 가드의 비교 대상에서 뺀다."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_name="이수한과목",
                                  planned_grade=3, planned_year="2025",
                                  planned_semester="1학기", status="completed"))
        course_id = _seed_generic_course(db)
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test", course_id=course_id, planned_grade=3,
                planned_year="2026", planned_semester="1학기",
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

    def test_credit_cap_23_for_pharmacy_college_regardless_of_total_required(self):
        """약학대학은 졸업기준학점이 133 이상이라도(=일반 로직이면 21) 규정상 23학점
        상한이다 — college 오버라이드가 132/133 이분법보다 먼저 적용돼야 한다."""
        db = self.make_db()
        db.add_all([
            School(id=1, name="부산대학교"),
            College(id=100, school_id=1, name="약학대학"),
        ])
        user = User(id=2, email="pharm@example.com", password_hash="x", name="약대생",
                    department_id=200, major_id=None)
        db.add(user)
        db.add(Department(id=200, college_id=100, name="약학과"))
        db.add(UserAcademicProgram(user_id=2, program_type="primary",
                                    department_id=200, major_id=None, curriculum_year=2026))
        db.add(GraduationRequirement(department_id=200, major_id=None, program_type="primary",
                                      curriculum_year="2026", required_total_credits=160))
        roadmap = CourseRoadmap(id=2, user_id=2)
        db.add(roadmap)
        db.flush()
        ctx = _ToolContext(db, user, roadmap)
        self.assertEqual(23, ctx._term_credit_cap())

    def test_credit_cap_19_for_architecture_department_even_in_engineering_college(self):
        """건축학과는 공과대학 소속이라 college만 보면(졸업기준학점도 133 이상이라)
        21학점이 될 대상이지만, 규정이 학과 단위로 19학점을 못박아 둔다 — department
        오버라이드가 college 오버라이드보다 먼저 확인돼야 한다."""
        db = self.make_db()
        db.add_all([
            School(id=1, name="부산대학교"),
            College(id=100, school_id=1, name="공과대학"),
        ])
        user = User(id=3, email="arch@example.com", password_hash="x", name="건축학생",
                    department_id=201, major_id=None)
        db.add(user)
        db.add(Department(id=201, college_id=100, name="건축학과"))
        db.add(UserAcademicProgram(user_id=3, program_type="primary",
                                    department_id=201, major_id=None, curriculum_year=2026))
        db.add(GraduationRequirement(department_id=201, major_id=None, program_type="primary",
                                      curriculum_year="2026", required_total_credits=140))
        roadmap = CourseRoadmap(id=3, user_id=3)
        db.add(roadmap)
        db.flush()
        ctx = _ToolContext(db, user, roadmap)
        self.assertEqual(19, ctx._term_credit_cap())

    def test_credit_cap_24_for_medicine_department(self):
        db = self.make_db()
        db.add_all([
            School(id=1, name="부산대학교"),
            College(id=100, school_id=1, name="의과대학"),
        ])
        user = User(id=4, email="med@example.com", password_hash="x", name="의대생",
                    department_id=202, major_id=None)
        db.add(user)
        db.add(Department(id=202, college_id=100, name="의학과"))
        db.add(UserAcademicProgram(user_id=4, program_type="primary",
                                    department_id=202, major_id=None, curriculum_year=2026))
        db.add(GraduationRequirement(department_id=202, major_id=None, program_type="primary",
                                      curriculum_year="2026", required_total_credits=200))
        roadmap = CourseRoadmap(id=4, user_id=4)
        db.add(roadmap)
        db.flush()
        ctx = _ToolContext(db, user, roadmap)
        self.assertEqual(24, ctx._term_credit_cap())

    def test_credit_cap_unaffected_department_falls_back_to_threshold(self):
        """오버라이드 표에 없는 일반 학과는 여전히 132/133 이분법을 그대로 쓴다."""
        db = self.make_db()
        db.add_all([
            School(id=1, name="부산대학교"),
            College(id=100, school_id=1, name="정보의생명공학대학"),
        ])
        user = User(id=5, email="cs@example.com", password_hash="x", name="컴공생",
                    department_id=203, major_id=None)
        db.add(user)
        db.add(Department(id=203, college_id=100, name="정보컴퓨터공학부"))
        db.add(UserAcademicProgram(user_id=5, program_type="primary",
                                    department_id=203, major_id=None, curriculum_year=2026))
        db.add(GraduationRequirement(department_id=203, major_id=None, program_type="primary",
                                      curriculum_year="2026", required_total_credits=130))
        roadmap = CourseRoadmap(id=5, user_id=5)
        db.add(roadmap)
        db.flush()
        ctx = _ToolContext(db, user, roadmap)
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


class TermCreditCapBonusTest(unittest.TestCase):
    """PNU 학사 규정: 성적우수자(+3)/학점이월제(+2) 보너스는 "바로 다음 학기"에만
    붙는다. 이월제의 "직전 학기 수강취소 없어야 함" 조건은 이 시스템이 수강취소
    이력을 안 쌓아서 검증 불가 — 사용자 확정대로 생략하고 계산한다."""

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

    def test_academic_excellence_bonus_applies_when_previous_term_qualifies(self):
        """직전 학기 18학점 이상 + 평점평균 3.80 이상 → 다음 학기 +3학점."""
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)  # base cap=21
        db.add_all([
            StudentCourseRecord(user_id=1, raw_course_name="A", credits=9,
                                 grade_point=4.5, year="2026", semester="1학기"),
            StudentCourseRecord(user_id=1, raw_course_name="B", credits=9,
                                 grade_point=3.5, year="2026", semester="1학기"),
        ])
        db.flush()
        # 평균 = (9*4.5 + 9*3.5)/18 = 4.0 ≥ 3.80, 취득학점 18 ≥ 18 → 성적우수자 +3.
        # 이월도 min(2, 21-18)=2 붙어서 21+3+2=26이지만 24로 clamp된다.
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            cap = ctx._credit_cap_for_term("2026", "2학기")
        self.assertEqual(24, cap)

    def test_no_bonus_when_gpa_below_threshold(self):
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)  # base cap=21
        db.add_all([
            StudentCourseRecord(user_id=1, raw_course_name="A", credits=10.5,
                                 grade_point=3.0, year="2026", semester="1학기"),
            StudentCourseRecord(user_id=1, raw_course_name="B", credits=10.5,
                                 grade_point=3.0, year="2026", semester="1학기"),
        ])
        db.flush()
        # 취득학점 21(≥18)이지만 평균 3.0 < 3.80 → 성적우수자 미달. 상한(21)을 이미
        # 꽉 채워 들었으니 이월도 0 → 보너스 전혀 없음.
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            cap = ctx._credit_cap_for_term("2026", "2학기")
        self.assertEqual(21, cap)

    def test_carryover_bonus_from_unused_previous_term_credits(self):
        """직전 학기에 상한만큼 못 채웠으면 미사용분을 최대 2학점까지 이월."""
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)  # base cap=21
        db.add(StudentCourseRecord(user_id=1, raw_course_name="A", credits=15,
                                    grade_point=4.0, year="2026", semester="1학기"))
        db.flush()
        # 직전 학기 15학점만 사용 → 21-15=6, 이월 상한 2로 clamp → +2.
        # 취득학점 15 < 18이라 성적우수자는 미달.
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            cap = ctx._credit_cap_for_term("2026", "2학기")
        self.assertEqual(23, cap)

    def test_bonus_capped_at_absolute_24_for_high_base_cap(self):
        """base cap이 이미 23(약학대학 등)이면 보너스를 더해도 24를 넘지 않는다
        ("이월 학점을 포함하여 24학점을 초과할 수 없다")."""
        db = self.make_db()
        db.add_all([
            School(id=1, name="부산대학교"),
            College(id=100, school_id=1, name="약학대학"),
        ])
        user = User(id=9, email="pharm2@example.com", password_hash="x", name="약대생2",
                    department_id=209, major_id=None)
        db.add(user)
        db.add(Department(id=209, college_id=100, name="약학과"))
        db.add(UserAcademicProgram(user_id=9, program_type="primary",
                                    department_id=209, major_id=None, curriculum_year=2026))
        db.add(GraduationRequirement(department_id=209, major_id=None, program_type="primary",
                                      curriculum_year="2026", required_total_credits=160))
        roadmap = CourseRoadmap(id=9, user_id=9)
        db.add(roadmap)
        db.add_all([
            StudentCourseRecord(user_id=9, raw_course_name="A", credits=9,
                                 grade_point=4.5, year="2026", semester="1학기"),
            StudentCourseRecord(user_id=9, raw_course_name="B", credits=9,
                                 grade_point=4.5, year="2026", semester="1학기"),
        ])
        db.flush()
        ctx = _ToolContext(db, user, roadmap)
        # base cap 23 + 성적우수자 3 + 이월 min(2, 23-18)=2 = 28 → 24로 clamp.
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            cap = ctx._credit_cap_for_term("2026", "2학기")
        self.assertEqual(24, cap)

    def test_bonus_only_applies_to_immediate_next_term_not_later_ones(self):
        """"바로 다음 학기"만 보너스 대상이다 — 그 이후 학기는 base cap 그대로
        (사용자 확정 스코프, 2026-08-25)."""
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)  # base cap=21
        # 직전 학기 20학점, 평균 4.5 → 성적우수자 +3, 이월 min(2, 21-20)=1 → 총 +4,
        # 21+4=25는 24로 clamp된다.
        db.add(StudentCourseRecord(user_id=1, raw_course_name="A", credits=20,
                                    grade_point=4.5, year="2026", semester="1학기"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            next_term_cap = ctx._credit_cap_for_term("2026", "2학기")  # 바로 다음 학기
            later_term_cap = ctx._credit_cap_for_term("2027", "1학기")  # 그 다음다음 학기
        self.assertEqual(24, next_term_cap)
        self.assertEqual(21, later_term_cap)

    def test_no_bonus_without_any_previous_term_records(self):
        """직전 학기 이수기록이 아예 없으면(편입 직후 등) 보너스 없이 base cap 그대로 —
        없는 이수내역으로 자격을 지어내지 않는다."""
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)  # base cap=21
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            cap = ctx._credit_cap_for_term("2026", "2학기")
        self.assertEqual(21, cap)

    def test_remaining_terms_and_get_roadmap_items_surface_the_bonus_cap(self):
        """remaining_terms[0]와 get_roadmap_items의 term_credit_cap이 실제로
        보너스 적용된 값을 노출해야 LLM이 그 근거로 더 많은 학점을 제안할 수 있다."""
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)  # base cap=21
        db.add(StudentCourseRecord(user_id=1, raw_course_name="A", credits=15,
                                    grade_point=4.0, year="2026", semester="1학기"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.get_roadmap_items()
        self.assertEqual(23, result["term_credit_cap"])
        self.assertEqual(23, result["remaining_terms"][0]["term_credit_cap"])
        # 그 다음 학기부터는 base cap.
        self.assertEqual(21, result["remaining_terms"][1]["term_credit_cap"])


class TransferStudentFallbackGuardTest(unittest.TestCase):
    """편입생에게 1·2학년 과목을 새로 추천하지 못하게 막는다.

    판정 근거는 users.admission_type='transfer'다. 예전에는 이수 기록에
    semester='입학전성적' 행이 있는지로 추론했는데, 포털 동기화 전인 편입생은
    판정할 수 없었고 조기이수 인정 학점이 있는 신입생은 잘못 걸렸다.
    """

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def make_ctx(self, db, admission_type="freshman"):
        user = User(id=1, email="t@example.com", password_hash="x", name="편입생",
                    department_id=10, major_id=20, admission_type=admission_type)
        db.add(user)
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(roadmap)
        db.flush()
        return _ToolContext(db, user, roadmap)

    def test_transfer_student_without_any_records_still_starts_at_grade3(self):
        """포털 동기화 전이라 이수 기록이 하나도 없어도 편입생으로 판정된다.

        추론 방식으로는 불가능했던 케이스다.
        """
        db = self.make_db()
        ctx = self.make_ctx(db, admission_type="transfer")
        self.assertEqual(3, ctx._min_completed_grade())

    def test_transfer_student_create_at_grade_2_is_rejected(self):
        db = self.make_db()
        ctx = self.make_ctx(db, admission_type="transfer")
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test",
                planned_year="2026", planned_semester="1학기", planned_grade=2,
            )
        self.assertIn("error", result)
        self.assertIn("최저 학년은 3학년", result["error"])

    def test_freshman_with_pre_admission_credits_is_not_treated_as_transfer(self):
        """조기이수 인정 학점이 있는 신입생. 옛 추론 방식은 이걸 편입생으로 잘못 봤다."""
        db = self.make_db()
        ctx = self.make_ctx(db, admission_type="freshman")
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이산수학",
                                     category="전공기초", credits=3,
                                     year="2026", semester="입학전성적"))
        course_id = _seed_generic_course(db)
        db.flush()
        self.assertIsNone(ctx._min_completed_grade())
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test", course_id=course_id,
                planned_year="2026", planned_semester="1학기", planned_grade=1,
            )
        self.assertNotIn("error", result)

    def test_freshman_without_records_is_not_blocked(self):
        """일반 신입생(이수기록 없음)은 1학년으로 자유롭게 create 가능해야 한다."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        course_id = _seed_generic_course(db)
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test", course_id=course_id,
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

    def test_context_block_summarizes_balanced_liberal_area_completion(self):
        """portal_sync가 override 한 세부영역 카테고리를 프롬프트 블록이 이수/미이수로 요약한다."""
        from app.domains.planning.roadmap_chat import _build_student_context_block
        db = self.make_db()
        db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=None, major_id=None, career_goal=None))
        # 세부영역 이수 rows (portal_sync가 전용 컬럼에 저장한 상태).
        db.add(StudentCourseRecord(user_id=1, raw_course_name="서양철학사",
                                     category="교양선택", liberal_area="사상과역사",
                                     credits=3, year="2025", semester="1"))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="현대사회의이해",
                                     category="교양선택", liberal_area="사회와문화",
                                     credits=3, year="2025", semester="2"))
        # override 안 된 교양선택 (미이수 세부영역 판정 대상)
        db.add(StudentCourseRecord(user_id=1, raw_course_name="영화의이해",
                                     category="교양선택", credits=2, year="2025", semester="1"))
        db.commit()
        block = _build_student_context_block(db, db.get(User, 1))
        # 이수 영역이 학점과 함께 나온다
        self.assertIn("사상과역사: 3학점 이수", block)
        self.assertIn("사회와문화: 3학점 이수", block)
        # 미이수 영역 목록에 나머지 6개가 다 잡힌다
        for area in ["문학과예술", "과학과기술", "건강과레포츠", "외국어", "융복합", "효원브릿지"]:
            self.assertIn(area, block)
        # 이미 이수한 영역은 "미이수" 라벨 뒤에 딸린 목록에는 나오지 않는다
        # (전체 블록에는 "이수" 섹션에서 등장하므로, 문자열 위치로 확인)
        missing_idx = block.index("미이수 세부영역")
        self.assertNotIn("사상과역사", block[missing_idx : missing_idx + 200])

    def test_context_block_warns_llm_not_to_auto_match_similar_names(self):
        """이수 완료 과목 안내에 유사명(예: 데이터구조↔자료구조)을 자동 매칭하지 말고
        사용자에게 되묻도록 안내하는 문구가 포함된다."""
        from app.domains.planning.roadmap_chat import _build_student_context_block
        db = self.make_db()
        db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=None, major_id=None, career_goal=None))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="데이터구조",
                                     category="전공기초", credits=3, year="2025", semester="1"))
        db.commit()
        block = _build_student_context_block(db, db.get(User, 1))
        self.assertIn("자료구조", block)  # 예시로 등장
        self.assertIn("되물어", block)  # 되묻기 지침 문구

    def test_context_block_marks_no_liberal_area_data_when_not_synced(self):
        """포털 동기화 전이라 세부영역 override가 없을 때는 그 사실을 명시한다."""
        from app.domains.planning.roadmap_chat import _build_student_context_block
        db = self.make_db()
        db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=None, major_id=None, career_goal=None))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="영화의이해",
                                     category="교양선택", credits=2, year="2025", semester="1"))
        db.commit()
        block = _build_student_context_block(db, db.get(User, 1))
        self.assertIn("이수한 균형교양 세부영역 없음", block)

    def test_context_block_uses_2026_curriculum_areas_for_2026_student(self):
        """주전공 curriculum_year=2026이면 신체계 세부영역(효원균형·창의교양)으로 자문해야
        한다 — 2021체계 이름('외국어'/'융복합')을 미이수라고 잘못 짚으면 안 된다."""
        from app.domains.planning.roadmap_chat import _build_student_context_block
        db = self.make_db()
        db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=None, major_id=None, career_goal=None))
        db.add(UserAcademicProgram(user_id=1, program_type="primary",
                                    department_id=None, major_id=None, curriculum_year="2026"))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="글로벌커뮤니케이션",
                                     category="교양선택", liberal_area="세계와 소통",
                                     credits=3, year="2026", semester="1"))
        db.commit()
        block = _build_student_context_block(db, db.get(User, 1))
        self.assertIn("세계와 소통: 3학점 이수", block)
        missing_idx = block.index("미이수 세부영역")
        missing_section = block[missing_idx : missing_idx + 300]
        # 신체계 나머지 미이수 영역은 나와야 하고
        self.assertIn("인성과 사회봉사", missing_section)
        # 구체계 전용 이름은 이 학생 자문에 아예 등장하면 안 된다
        self.assertNotIn("외국어", block)
        self.assertNotIn("융복합", block)

    def test_context_block_includes_transfer_liberal_area_substitution(self):
        """학생이 직접 지정한 입학 전 인정 영역도 미이수가 아니라 대체 인정이다."""
        from app.domains.planning.roadmap_chat import _build_student_context_block
        db = self.make_db()
        db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트"))
        db.add(Course(
            id=91,
            course_code="ZFz000091",
            course_name="사상과역사",
            category="효원균형교양",
            credits=3,
        ))
        db.add(StudentCourseRecord(
            id=10,
            user_id=1,
            raw_course_name="교양선택",
            category="교양선택",
            credits=10,
            semester="입학전성적",
        ))
        db.add(StudentCourseSubstitution(record_id=10, course_id=91))
        db.commit()

        block = _build_student_context_block(db, db.get(User, 1))

        self.assertIn("사상과역사: 대체 인정", block)
        missing_idx = block.index("미이수 세부영역")
        self.assertNotIn("사상과역사", block[missing_idx : missing_idx + 200])

    def test_context_block_does_not_mislabel_zero_credit_direct_record_as_substitution(self):
        """직접 이수 레코드(liberal_area 판정)가 있는데 credits가 None/0이면 학점 합계가
        falsy가 돼도, 대체 인정 근거(StudentCourseSubstitution)가 전혀 없는데 "대체 인정"
        으로 잘못 표시되면 안 된다."""
        from app.domains.planning.roadmap_chat import _build_student_context_block
        db = self.make_db()
        db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=None, major_id=None, career_goal=None))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="서양철학사",
                                     category="교양선택", liberal_area="사상과역사",
                                     credits=None, year="2025", semester="1"))
        db.commit()
        block = _build_student_context_block(db, db.get(User, 1))
        self.assertIn("사상과역사: 이수 (학점 정보 없음)", block)
        self.assertNotIn("사상과역사: 대체 인정", block)


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

    def test_create_without_course_id_is_rejected(self):
        """course_id 없는 create는 거절한다.

        예전에는 "자유입력 항목"으로 보고 통과시켰지만, 이 도구는 course_name을 받지 않고
        apply_pending_changes가 이름·학점·이수구분을 Course에서만 가져온다 — 그래서 승인하면
        전부 NULL인 빈 로드맵 행이 생겼다. 게다가 이수·중복·재수강·계절수업 가드가 모두
        course_obj가 있을 때만 도는 분기라 통째로 우회됐다 (골든 케이스 22에서 실제 관측:
        is_retake=True + course_id=None이 모든 검증을 지나감).
        """
        db = self.make_db()
        ctx = self.make_ctx(db)
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test",
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertIn("error", result)
        self.assertIn("course_id", result["error"])

    def test_create_without_course_id_is_rejected_even_with_retake_flag(self):
        """재수강 우회 플래그가 course_id 누락을 덮지 못한다."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="사용자 재수강 요청", is_retake=True,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertIn("error", result)

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


class CriticalMissingRequiredTest(unittest.TestCase):
    """졸업 위험 감지: 학과 필수인데 미이수 + 개설 학기 어긋남을 도구가 계산해서
    LLM에게 노출한다. LLM 혼자 courses.semester를 크로스체크 못 하는 걸 보완."""

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def make_ctx(self, db):
        user = User(id=1, email="t@x.com", password_hash="x", name="테스트",
                    department_id=10, major_id=20)
        db.add(user)
        db.add(UserAcademicProgram(user_id=1, program_type="primary",
                                    department_id=10, major_id=20, curriculum_year=2024))
        db.add(GraduationRequirement(department_id=10, major_id=20, program_type="primary",
                                      curriculum_year="2024", required_total_credits=133))
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(roadmap)
        db.flush()
        return _ToolContext(db, user, roadmap)

    def test_flags_1st_only_required_when_next_is_2nd(self):
        """자료구조(1학기 전용, 전공필수) 미이수인 학생이 다음 학기가 2학기면 critical."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=100, course_name="자료구조", department_id=10, major_id=20,
                      category="전공필수", credits=3.0, year="2", semester="1"))
        db.flush()
        result = ctx._critical_missing_required(next_planned_semester="2학기")
        self.assertEqual(1, len(result))
        self.assertEqual("자료구조", result[0]["course_name"])
        self.assertEqual("1", result[0]["offered_semester"])

    def test_skips_course_offered_this_semester(self):
        """개설 학기가 next와 같으면 이번에 들 수 있으니 critical 아님."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        # 2학기 전용 필수 → next도 2학기면 이번 학기에 들 수 있음
        db.add(Course(id=101, course_name="컴퓨터구조", department_id=10, major_id=20,
                      category="전공필수", credits=3.0, year="2", semester="2"))
        db.flush()
        result = ctx._critical_missing_required(next_planned_semester="2학기")
        self.assertEqual(0, len(result))

    def test_skips_completed_from_records(self):
        """이수 완료 과목(성적표)은 위험 아님."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=102, course_name="자료구조", department_id=10, major_id=20,
                      category="전공필수", credits=3.0, year="2", semester="1"))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="자료구조",
                                     category="전공필수", credits=3, year="2024"))
        db.flush()
        result = ctx._critical_missing_required(next_planned_semester="2학기")
        self.assertEqual(0, len(result))

    def test_skips_completed_from_roadmap_items(self):
        """로드맵 status='completed' 항목도 이수로 취급."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=103, course_name="자료구조", department_id=10, major_id=20,
                      category="전공필수", credits=3.0, year="2", semester="1"))
        db.add(CourseRoadmapItem(roadmap_id=ctx.roadmap.id, course_id=103,
                                  course_name="자료구조", planned_grade=2,
                                  status="completed"))
        db.flush()
        result = ctx._critical_missing_required(next_planned_semester="2학기")
        self.assertEqual(0, len(result))

    def test_skips_all_semester_courses(self):
        """전학기·1,2 개설(계절수업 등)은 다음 학기든 언제든 미룰 수 있어 위험 아님."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=104, course_name="여름캡스톤", department_id=10, major_id=20,
                      category="전공필수", credits=3.0, year="3", semester="1,2"))
        db.flush()
        result = ctx._critical_missing_required(next_planned_semester="2학기")
        self.assertEqual(0, len(result))

    def test_matches_norm_across_roman_variants(self):
        """이수기록 '컴퓨터프로그래밍 Ⅰ' vs 카탈로그 '컴퓨터프로그래밍(I)' 정규화 매칭."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=105, course_name="컴퓨터프로그래밍(I)", department_id=10, major_id=20,
                      category="전공기초", credits=3.0, year="1", semester="1"))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="컴퓨터프로그래밍 Ⅰ",
                                     category="전공기초", credits=3, year="2024"))
        db.flush()
        result = ctx._critical_missing_required(next_planned_semester="2학기")
        self.assertEqual(0, len(result))

    def test_exposed_in_get_roadmap_items(self):
        """get_roadmap_items 응답에 critical_missing_required 키가 포함된다."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=106, course_name="자료구조", department_id=10, major_id=20,
                      category="전공필수", credits=3.0, year="2", semester="1"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            # next = 2026-2학기 → 자료구조(1학기 전용)은 critical
            result = ctx.get_roadmap_items()
        self.assertIn("critical_missing_required", result)
        names = [c["course_name"] for c in result["critical_missing_required"]]
        self.assertIn("자료구조", names)


class RetakeCandidatesTest(unittest.TestCase):
    """재수강 권유 후보 감지: SCR grade_point가 C+(2.5) 이하인 과목만 flag.
    이름 정규화 후 최고 grade_point 기준(재수강 후 개선된 성적 반영)."""

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def make_user(self, db):
        user = User(id=1, email="t@x.com", password_hash="x", name="테스트",
                    department_id=10, major_id=20)
        db.add(user)
        db.flush()
        return user

    def test_flags_low_gpa_course(self):
        from app.domains.planning.roadmap_chat import _compute_retake_candidates
        db = self.make_db()
        user = self.make_user(db)
        # D+ (1.5) — 재수강 대상
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이산수학",
                                     category="전공기초", credits=3,
                                     grade="D+", grade_point=1.5, year="2024"))
        db.flush()
        result = _compute_retake_candidates(db, user)
        self.assertEqual(1, len(result))
        self.assertEqual("이산수학", result[0]["course_name"])
        self.assertEqual(1.5, result[0]["current_grade_point"])

    def test_skips_high_gpa_course(self):
        from app.domains.planning.roadmap_chat import _compute_retake_candidates
        db = self.make_db()
        user = self.make_user(db)
        # A0 (4.0) — 재수강 불필요
        db.add(StudentCourseRecord(user_id=1, raw_course_name="자료구조",
                                     category="전공필수", credits=3,
                                     grade="A0", grade_point=4.0, year="2024"))
        db.flush()
        self.assertEqual([], _compute_retake_candidates(db, user))

    def test_boundary_at_c_plus(self):
        """C+ (2.5) 정확히 경계 — 규정상 재수강 가능이라 pass (<=)."""
        from app.domains.planning.roadmap_chat import _compute_retake_candidates
        db = self.make_db()
        user = self.make_user(db)
        db.add(StudentCourseRecord(user_id=1, raw_course_name="알고리즘",
                                     category="전공필수", credits=3,
                                     grade="C+", grade_point=2.5, year="2024"))
        db.flush()
        result = _compute_retake_candidates(db, user)
        self.assertEqual(1, len(result))

    def test_uses_best_grade_across_retakes(self):
        """같은 과목의 두 기록(원 성적 D0, 재수강 B0)이면 최고 B0(3.0) 기준 → 재수강 불필요."""
        from app.domains.planning.roadmap_chat import _compute_retake_candidates
        db = self.make_db()
        user = self.make_user(db)
        db.add(StudentCourseRecord(user_id=1, raw_course_name="컴퓨터구조",
                                     category="전공필수", credits=3,
                                     grade="D0", grade_point=1.0, year="2024", is_retake=False))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="컴퓨터구조",
                                     category="전공필수", credits=3,
                                     grade="B0", grade_point=3.0, year="2025", is_retake=True))
        db.flush()
        self.assertEqual([], _compute_retake_candidates(db, user))

    def test_skips_records_without_grade_point(self):
        """grade_point가 None(포털 미동기화 등)이면 판단 불가로 제외."""
        from app.domains.planning.roadmap_chat import _compute_retake_candidates
        db = self.make_db()
        user = self.make_user(db)
        db.add(StudentCourseRecord(user_id=1, raw_course_name="교양A",
                                     category="교양선택", credits=2,
                                     grade=None, grade_point=None, year="2024"))
        db.flush()
        self.assertEqual([], _compute_retake_candidates(db, user))

    def test_normalizes_roman_variants(self):
        """'컴퓨터프로그래밍 Ⅰ' 원 성적 F + '컴퓨터프로그래밍(I)' 재수강 A0 → 정규화 후 A0."""
        from app.domains.planning.roadmap_chat import _compute_retake_candidates
        db = self.make_db()
        user = self.make_user(db)
        db.add(StudentCourseRecord(user_id=1, raw_course_name="컴퓨터프로그래밍 Ⅰ",
                                     category="전공기초", credits=3,
                                     grade="F", grade_point=0.0, year="2024"))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="컴퓨터프로그래밍(I)",
                                     category="전공기초", credits=3,
                                     grade="A0", grade_point=4.0, year="2025", is_retake=True))
        db.flush()
        self.assertEqual([], _compute_retake_candidates(db, user))

    def test_sort_by_grade_ascending(self):
        """성적 낮은 순 정렬 — LLM이 우선순위 짐작에 도움."""
        from app.domains.planning.roadmap_chat import _compute_retake_candidates
        db = self.make_db()
        user = self.make_user(db)
        db.add(StudentCourseRecord(user_id=1, raw_course_name="A",
                                     grade="C0", grade_point=2.0, year="2024"))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="B",
                                     grade="F", grade_point=0.0, year="2024"))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="C",
                                     grade="C+", grade_point=2.5, year="2024"))
        db.flush()
        result = _compute_retake_candidates(db, user)
        self.assertEqual(["B", "A", "C"], [c["course_name"] for c in result])


class ConditionalPromptAssemblyTest(unittest.TestCase):
    """프롬프트 fatigue 대응 — 학생 상태에 맞는 조건부 규칙만 시스템 프롬프트에 포함.
    무관한 규칙이 매 대화턴 노출돼 LLM 규칙 준수도가 떨어지는 걸 완화 (case 08 관측)."""

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def make_baseline_user(self, db, career_goal=None, admission_type="freshman"):
        user = User(id=1, email="t@x.com", password_hash="x", name="테스트",
                    department_id=10, major_id=20, career_goal=career_goal,
                    admission_type=admission_type)
        db.add(user)
        db.add(UserAcademicProgram(user_id=1, program_type="primary",
                                    department_id=10, major_id=20, curriculum_year=2024))
        db.add(CourseRoadmap(id=1, user_id=1))
        db.flush()
        return user

    def test_baseline_freshman_gets_minimal_rules(self):
        """부·복수전공 없고 진로 없는 신입은 조건부 규칙 거의 없음."""
        from app.domains.planning.roadmap_chat import _select_applicable_rules
        db = self.make_db()
        user = self.make_baseline_user(db)
        db.commit()
        rules = _select_applicable_rules(db, user)
        self.assertNotIn("non_primary_programs", rules)
        self.assertNotIn("career_dept_mismatch", rules)
        self.assertNotIn("transfer_student", rules)
        self.assertNotIn("retake_candidates", rules)

    def test_non_primary_activates_rule(self):
        from app.domains.planning.roadmap_chat import _select_applicable_rules
        db = self.make_db()
        user = self.make_baseline_user(db)
        db.add(UserAcademicProgram(user_id=1, program_type="minor",
                                    department_id=40, curriculum_year=2024))
        db.commit()
        rules = _select_applicable_rules(db, user)
        self.assertIn("non_primary_programs", rules)
        # non-primary가 있으면 mismatch 규칙은 배제 (이미 부·복수로 대응)
        self.assertNotIn("career_dept_mismatch", rules)

    def _seed_dept_courses(self, db, names):
        for i, name in enumerate(names):
            db.add(Course(id=950 + i, course_name=name, department_id=10,
                          category="전공선택", credits=3, year="2", semester="1"))
        db.flush()

    def test_career_unrelated_to_department_curriculum_triggers_mismatch(self):
        """진로군 키워드가 학과 커리큘럼에 전혀 없으면 부·복수전공 안내 규칙을 붙인다."""
        from app.domains.planning.roadmap_chat import _select_applicable_rules
        db = self.make_db()
        user = self.make_baseline_user(db, career_goal="백엔드 개발자")
        self._seed_dept_courses(db, ["현대문학의이해", "국어학개론"])
        db.commit()
        rules = _select_applicable_rules(db, user)
        self.assertIn("career_dept_mismatch", rules)

    def test_career_matching_department_curriculum_does_not_trigger_mismatch(self):
        """진로와 전공이 잘 맞으면 규칙을 붙이지 않는다.

        옛 구현은 "진로 목표가 있고 부·복수전공이 없으면" 무조건 붙여서, 정컴 학생 +
        백엔드 진로처럼 완벽히 맞는 경우에도 "부전공을 제안해라"는 강한 지시가 매 대화에
        실렸다 (골든 케이스 16개 중 10개에서 발동, 2026-08 관측).
        """
        from app.domains.planning.roadmap_chat import _select_applicable_rules
        db = self.make_db()
        user = self.make_baseline_user(db, career_goal="백엔드 개발자")
        self._seed_dept_courses(db, ["데이터베이스", "운영체제", "컴퓨터네트워크"])
        db.commit()
        rules = _select_applicable_rules(db, user)
        self.assertNotIn("career_dept_mismatch", rules)

    def test_transfer_admission_triggers_rule(self):
        from app.domains.planning.roadmap_chat import _select_applicable_rules
        db = self.make_db()
        user = self.make_baseline_user(db, admission_type="transfer")
        db.commit()
        rules = _select_applicable_rules(db, user)
        self.assertIn("transfer_student", rules)

    def test_low_gpa_triggers_retake_rule(self):
        from app.domains.planning.roadmap_chat import _select_applicable_rules
        db = self.make_db()
        user = self.make_baseline_user(db)
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이산수학",
                                     category="전공기초", credits=3,
                                     grade="D+", grade_point=1.5, year="2024"))
        db.commit()
        rules = _select_applicable_rules(db, user)
        self.assertIn("retake_candidates", rules)

    def test_build_system_prompt_shorter_for_baseline(self):
        """baseline 학생의 프롬프트가 non-primary+mismatch+... 학생보다 짧다."""
        from app.domains.planning.roadmap_chat import _build_system_prompt
        db = self.make_db()
        user = self.make_baseline_user(db)
        db.commit()
        baseline_prompt, _ = _build_system_prompt(db, user)

        # 복잡한 학생: 진로 + non-primary + 편입 + 저성적
        db2 = self.make_db()
        user2 = self.make_baseline_user(db2, career_goal="AI",
                                        admission_type="transfer")
        db2.add(UserAcademicProgram(user_id=1, program_type="minor",
                                     department_id=40, curriculum_year=2024))
        db2.add(StudentCourseRecord(user_id=1, raw_course_name="X",
                                      grade="D+", grade_point=1.5, year="2024"))
        db2.commit()
        complex_prompt, _ = _build_system_prompt(db2, user2)

        self.assertLess(len(baseline_prompt), len(complex_prompt))


class RetakePropseBypassTest(unittest.TestCase):
    """propose_change의 is_retake 플래그로 이수 완료 재추천 가드를 우회. 단 실제
    재수강 자격(grade_point <= 2.5)이 있는 과목만 통과."""

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def make_ctx(self, db):
        user = User(id=1, email="t@x.com", password_hash="x", name="테스트",
                    department_id=10, major_id=20)
        db.add(user)
        db.add(UserAcademicProgram(user_id=1, program_type="primary",
                                    department_id=10, major_id=20, curriculum_year=2024))
        db.add(GraduationRequirement(department_id=10, major_id=20, program_type="primary",
                                      curriculum_year="2024", required_total_credits=133))
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(roadmap)
        db.flush()
        return _ToolContext(db, user, roadmap)

    def test_default_blocks_completed_course_recreate(self):
        """is_retake 기본 False — 이수 완료 과목 create 시도는 여전히 거절."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=200, course_name="이산수학", department_id=10, major_id=20,
                      category="전공기초", credits=3.0, year="1", semester="2"))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이산수학",
                                     category="전공기초", credits=3,
                                     grade="D+", grade_point=1.5, year="2024"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="test", course_id=200,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
            )
        self.assertIn("error", result)
        self.assertIn("이미 이수한 과목", result["error"])

    def test_retake_flag_bypasses_when_grade_below_threshold(self):
        """is_retake=True + grade_point <= 2.5 → 정상 통과."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=201, course_name="이산수학", department_id=10, major_id=20,
                      category="전공기초", credits=3.0, year="1", semester="2"))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이산수학",
                                     category="전공기초", credits=3,
                                     grade="D+", grade_point=1.5, year="2024"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="사용자 재수강 요청", course_id=201,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
                is_retake=True,
            )
        self.assertNotIn("error", result)
        # reason에 [재수강] 태그 자동 부착
        self.assertEqual(1, len(ctx.pending_changes))
        self.assertIn("[재수강]", ctx.pending_changes[0].reason)

    def test_retake_flag_rejects_when_grade_above_threshold(self):
        """is_retake=True 넘겨도 grade_point > 2.5 (B- 이상)면 거절."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=202, course_name="자료구조", department_id=10, major_id=20,
                      category="전공필수", credits=3.0, year="2", semester="1"))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="자료구조",
                                     category="전공필수", credits=3,
                                     grade="B0", grade_point=3.0, year="2024"))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="재수강 요청", course_id=202,
                planned_year="2026", planned_semester="1학기", planned_grade=3,
                is_retake=True,
            )
        self.assertIn("error", result)
        self.assertIn("재수강 대상이 아닙니다", result["error"])

    def test_retake_uses_best_grade_across_multiple_records(self):
        """같은 과목 두 record: 원 성적 F(0.0) + 재수강 B0(3.0). 최고치=3.0이라 재수강 불가."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=203, course_name="컴퓨터구조", department_id=10, major_id=20,
                      category="전공필수", credits=3.0, year="2", semester="2"))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="컴퓨터구조",
                                     grade="F", grade_point=0.0, year="2024"))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="컴퓨터구조",
                                     grade="B0", grade_point=3.0, year="2025",
                                     is_retake=True))
        db.flush()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_change(
                action="create", reason="다시 재수강", course_id=203,
                planned_year="2026", planned_semester="2학기", planned_grade=3,
                is_retake=True,
            )
        self.assertIn("error", result)
        self.assertIn("재수강 대상이 아닙니다", result["error"])


class StripMarkdownFenceTest(unittest.TestCase):
    """`_llm_judge`가 gpt-4o-mini의 ```json ... ``` 감싼 응답에서 fence만 제거하고
    본문을 온전히 반환하는지. 이전 문자셋 기반(lstrip("json\\n"))의 왜곡 가능성 회피."""

    def test_plain_json_passthrough(self):
        from tests.eval.run_eval import _strip_markdown_fence
        s = '{"pass": true}'
        self.assertEqual(s, _strip_markdown_fence(s))

    def test_strips_json_fence(self):
        from tests.eval.run_eval import _strip_markdown_fence
        s = '```json\n{"pass": true, "reason": "OK"}\n```'
        self.assertEqual('{"pass": true, "reason": "OK"}', _strip_markdown_fence(s))

    def test_strips_bare_fence(self):
        from tests.eval.run_eval import _strip_markdown_fence
        s = '```\n{"pass": false}\n```'
        self.assertEqual('{"pass": false}', _strip_markdown_fence(s))

    def test_does_not_mangle_content_starting_with_j_or_s(self):
        """이전 lstrip("json\\n")은 첫 글자가 j/s/o/n이면 왜곡. 지금은 line 단위라 안전."""
        from tests.eval.run_eval import _strip_markdown_fence
        s = '{"json_key": "sample string with json in it"}'
        self.assertEqual(s, _strip_markdown_fence(s))


class PrereqExtractTest(unittest.TestCase):
    """description 텍스트에서 선수과목명 추출 — 라벨 있는 경우만 잡고 자유서술은 무시."""

    def test_extracts_after_label_with_comma(self):
        from app.domains.planning.roadmap_chat import _extract_prereqs_from_description
        result = _extract_prereqs_from_description("선수과목: 자료구조, 알고리즘")
        self.assertEqual(["자료구조", "알고리즘"], result)

    def test_extracts_with_fullwidth_colon(self):
        from app.domains.planning.roadmap_chat import _extract_prereqs_from_description
        result = _extract_prereqs_from_description("선이수 과목: 컴퓨터프로그래밍(I)")
        self.assertEqual(["컴퓨터프로그래밍(I)"], result)

    def test_splits_on_conjunctions(self):
        from app.domains.planning.roadmap_chat import _extract_prereqs_from_description
        result = _extract_prereqs_from_description("선수과목: A 및 B 또는 C")
        self.assertEqual(["A", "B", "C"], result)

    def test_ignores_free_prose_without_label(self):
        """'X를 미리 이수한 학생 대상' 같은 서술문은 잡지 않는다 (false positive 방지)."""
        from app.domains.planning.roadmap_chat import _extract_prereqs_from_description
        result = _extract_prereqs_from_description("자료구조를 미리 이수한 학생 대상")
        self.assertEqual([], result)

    def test_returns_empty_on_none_and_empty(self):
        from app.domains.planning.roadmap_chat import _extract_prereqs_from_description
        self.assertEqual([], _extract_prereqs_from_description(None))
        self.assertEqual([], _extract_prereqs_from_description(""))

    def test_stops_at_descriptive_verb(self):
        """라벨이 문장 중간에 있고 뒤에 서술어가 이어져도 과목명만 추출."""
        from app.domains.planning.roadmap_chat import _extract_prereqs_from_description
        # "선수과목: 자료구조 를 요구한다" → 개선 전엔 "자료구조 를 요구한다" 로 실패
        result = _extract_prereqs_from_description("본 과목은 선수과목: 자료구조 를 요구한다.")
        self.assertEqual(["자료구조"], result)

    def test_stops_at_period_before_next_sentence(self):
        """마침표 뒤에 다른 서술이 이어져도 앞 절만."""
        from app.domains.planning.roadmap_chat import _extract_prereqs_from_description
        result = _extract_prereqs_from_description(
            "선수과목: 자료구조. 이 과목은 심화 내용을 다룬다."
        )
        self.assertEqual(["자료구조"], result)


class PrereqBlockedTest(unittest.TestCase):
    """선수과목 미이수 감지: 학과 개설 과목 중 description에서 뽑은 선수가 이수 세트에
    없으면 blocked. 로드맵/시간표 챗 자매 노출은 각 챗 유닛에서 커버."""

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def make_setup(self, db):
        user = User(id=1, email="t@x.com", password_hash="x", name="테스트",
                    department_id=10, major_id=20)
        db.add(user)
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(roadmap)
        db.flush()
        return user, roadmap

    def test_flags_course_with_missing_prereq(self):
        from app.domains.planning.roadmap_chat import _compute_prereq_blocked
        db = self.make_db()
        user, rm = self.make_setup(db)
        db.add(Course(id=100, course_name="운영체제", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="1",
                      description="선수과목: 자료구조"))
        db.flush()
        result = _compute_prereq_blocked(db, user, roadmap_id=rm.id)
        self.assertEqual(1, len(result))
        self.assertEqual("운영체제", result[0]["course_name"])
        self.assertEqual(["자료구조"], result[0]["missing_prerequisites"])

    def test_skips_when_prereq_completed(self):
        from app.domains.planning.roadmap_chat import _compute_prereq_blocked
        db = self.make_db()
        user, rm = self.make_setup(db)
        db.add(Course(id=101, course_name="운영체제", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="1",
                      description="선수과목: 자료구조"))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="자료구조",
                                     category="전공필수", credits=3, year="2024"))
        db.flush()
        result = _compute_prereq_blocked(db, user, roadmap_id=rm.id)
        self.assertEqual([], result)

    def test_skips_course_without_description(self):
        from app.domains.planning.roadmap_chat import _compute_prereq_blocked
        db = self.make_db()
        user, rm = self.make_setup(db)
        db.add(Course(id=102, course_name="X", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="1",
                      description=None))
        db.flush()
        self.assertEqual([], _compute_prereq_blocked(db, user, roadmap_id=rm.id))

    def test_skips_course_already_completed(self):
        """이미 이수한 과목은 판단 대상 아님 (다른 가드가 재추천 막음)."""
        from app.domains.planning.roadmap_chat import _compute_prereq_blocked
        db = self.make_db()
        user, rm = self.make_setup(db)
        db.add(Course(id=103, course_name="컴파일러", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="4", semester="1",
                      description="선수과목: 자료구조"))
        # 컴파일러는 이수, 자료구조는 미이수
        db.add(StudentCourseRecord(user_id=1, raw_course_name="컴파일러",
                                     category="전공선택", credits=3, year="2024"))
        db.flush()
        self.assertEqual([], _compute_prereq_blocked(db, user, roadmap_id=rm.id))

    def test_partial_prereq_completion_still_blocks(self):
        """선수 여러 개 중 하나라도 미이수면 blocked."""
        from app.domains.planning.roadmap_chat import _compute_prereq_blocked
        db = self.make_db()
        user, rm = self.make_setup(db)
        db.add(Course(id=104, course_name="네트워크보안", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="4", semester="2",
                      description="선수과목: 컴퓨터네트워크, 시스템프로그래밍"))
        # 컴퓨터네트워크만 이수
        db.add(StudentCourseRecord(user_id=1, raw_course_name="컴퓨터네트워크",
                                     category="전공선택", credits=3, year="2024"))
        db.flush()
        result = _compute_prereq_blocked(db, user, roadmap_id=rm.id)
        self.assertEqual(1, len(result))
        self.assertEqual(["시스템프로그래밍"], result[0]["missing_prerequisites"])

    def test_uses_roadmap_completed_when_roadmap_id_given(self):
        """로드맵 status='completed' 항목도 이수 세트에 포함."""
        from app.domains.planning.roadmap_chat import _compute_prereq_blocked
        db = self.make_db()
        user, rm = self.make_setup(db)
        db.add(Course(id=105, course_name="운영체제", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="1",
                      description="선수과목: 자료구조"))
        db.add(CourseRoadmapItem(roadmap_id=rm.id, course_name="자료구조",
                                  planned_grade=2, status="completed"))
        db.flush()
        self.assertEqual([], _compute_prereq_blocked(db, user, roadmap_id=rm.id))

    def test_normalizes_roman_variants_in_matching(self):
        """이수기록 '컴퓨터프로그래밍 Ⅰ' vs 선수 라벨 '컴퓨터프로그래밍(I)' 매칭."""
        from app.domains.planning.roadmap_chat import _compute_prereq_blocked
        db = self.make_db()
        user, rm = self.make_setup(db)
        db.add(Course(id=106, course_name="자료구조", department_id=10, major_id=20,
                      category="전공필수", credits=3.0, year="2", semester="1",
                      description="선수과목: 컴퓨터프로그래밍(I)"))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="컴퓨터프로그래밍 Ⅰ",
                                     category="전공기초", credits=3, year="2024"))
        db.flush()
        self.assertEqual([], _compute_prereq_blocked(db, user, roadmap_id=rm.id))

    def test_uses_roadmap_planned_not_just_completed(self):
        """'졸업까지 로드맵 짜줘'로 3-2에 자료구조를 이미 계획해 뒀으면(아직 status=
        'planned', 실제로 듣지는 않음) 4-1의 후속 과목을 선수과목 미이수로 막으면
        안 된다 — 로드맵은 시간순으로 짜인다고 가정한다."""
        from app.domains.planning.roadmap_chat import _compute_prereq_blocked
        db = self.make_db()
        user, rm = self.make_setup(db)
        db.add(Course(id=107, course_name="운영체제", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="1",
                      description="선수과목: 자료구조"))
        db.add(CourseRoadmapItem(roadmap_id=rm.id, course_name="자료구조",
                                  planned_grade=3, planned_year="2026",
                                  planned_semester="2학기", status="planned"))
        db.flush()
        self.assertEqual([], _compute_prereq_blocked(db, user, roadmap_id=rm.id))

    def test_dropped_roadmap_item_does_not_satisfy_prereq(self):
        """계획에서 뺀(dropped) 과목은 이수 예정이 아니다.

        `CourseRoadmapItem.status`는 `planned`/`completed`/`dropped` 셋뿐이다
        (`rejected`는 `PendingRoadmapChange.status`의 값이지 이 모델과 무관 —
        독립 리뷰가 `!= "rejected"` 필터가 실제로는 절대 안 걸리는 죽은 조건이었다는
        걸 잡아냈다. 이 테스트도 원래 "rejected"로 잘못 써서 신·구 코드 양쪽에서
        전부 통과하는 가짜 안전망이었다 — 이제 실제로 존재하는 값으로 고쳤다)."""
        from app.domains.planning.roadmap_chat import _compute_prereq_blocked
        db = self.make_db()
        user, rm = self.make_setup(db)
        db.add(Course(id=108, course_name="운영체제", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="1",
                      description="선수과목: 자료구조"))
        db.add(CourseRoadmapItem(roadmap_id=rm.id, course_name="자료구조",
                                  planned_grade=3, status="dropped"))
        db.flush()
        result = _compute_prereq_blocked(db, user, roadmap_id=rm.id)
        self.assertEqual(1, len(result))

    def test_pending_create_this_turn_satisfies_prereq(self):
        """propose_term_plan이 같은 턴 안에서 앞 학기(3-2)에 자료구조를 방금
        pending_changes로 쌓아둔 상태 — 아직 DB에 저장 전이라도 뒤 학기(4-1)의
        후속 과목을 선수과목 미이수로 막으면 안 된다."""
        from app.domains.planning.roadmap_chat import _compute_prereq_blocked
        db = self.make_db()
        user, rm = self.make_setup(db)
        db.add(Course(id=109, course_name="운영체제", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="1",
                      description="선수과목: 자료구조"))
        db.flush()
        result = _compute_prereq_blocked(
            db, user, roadmap_id=rm.id, pending_course_names=["자료구조"],
        )
        self.assertEqual([], result)


class SafeCallDispatchGuardTest(unittest.TestCase):
    """LLM(gpt-4o-mini)이 종종 잘못된 kwarg를 낸다 — 예: `{"query=": "..."}` (등호 붙음),
    스키마에 없는 필드 추가. 예전엔 handler(**tool_input)가 TypeError로 죽고, langfuse
    span context가 그 위에서 `generator didn't stop after throw()`로 재폭발해 세션
    전체가 크래시됐다. _safe_call은 알 수 없는 키를 드롭하고 error dict으로 돌린다.
    """

    def test_unknown_kwarg_is_dropped_and_reported(self):
        from app.domains.planning.roadmap_chat import _safe_call

        def handler(query: str = ""):
            return {"ok": True, "got": query}

        result = _safe_call(handler, {"query": "abc", "query=": "junk", "extra": 1})
        self.assertTrue(result["ok"])
        self.assertEqual("abc", result["got"])
        self.assertEqual(sorted(["query=", "extra"]), sorted(result["_dropped_args"]))

    def test_type_error_inside_handler_returns_error_not_raises(self):
        from app.domains.planning.roadmap_chat import _safe_call

        def handler(x: int):
            raise TypeError("boom")

        result = _safe_call(handler, {"x": 1})
        self.assertIn("error", result)
        # 세션 크래시 대신 dict으로 돌려주기만 하면 목표 달성

    def test_var_keyword_handler_receives_extras(self):
        from app.domains.planning.roadmap_chat import _safe_call

        def handler(**kwargs):
            return {"echo": kwargs}

        result = _safe_call(handler, {"a": 1, "weird=key": 2})
        self.assertEqual({"a": 1, "weird=key": 2}, result["echo"])
        self.assertNotIn("_dropped_args", result)

    def test_clean_call_passes_through_unchanged(self):
        from app.domains.planning.roadmap_chat import _safe_call

        def handler(query: str = "", limit: int = 10):
            return {"q": query, "n": limit}

        result = _safe_call(handler, {"query": "x", "limit": 5})
        self.assertEqual({"q": "x", "n": 5}, result)


class NarrowScopeRequestProbeTest(unittest.TestCase):
    """"이것만 해줘"류 요청에만 붙는 범위 준수 규칙.

    CORE에도 같은 취지의 규칙이 있지만 프롬프트 뒤쪽에 묻혀 준수도가 낮았다 —
    골든 케이스 26(N=3 중 2회 위반: "데이터베이스만 옮겨줘"에 컴퓨터네트워크까지 이동).
    """

    def test_narrow_markers_detected(self):
        from app.domains.planning.roadmap_chat import _looks_like_narrow_scope_request
        for msg in [
            "데이터베이스를 4학년 2학기로 옮겨주세요. 그것만요.",
            "이것만 바꿔주세요",
            "하나만 옮겨줘",
            "다른 건 건드리지 말고 이 과목만 미뤄줘",
        ]:
            self.assertTrue(_looks_like_narrow_scope_request(msg), msg)

    def test_broad_requests_not_flagged(self):
        from app.domains.planning.roadmap_chat import _looks_like_narrow_scope_request
        for msg in [
            "다음 학기 수강계획 추천해주세요",
            "졸업까지 뭐가 남았는지 정리해줘",
            "AI 진로에 도움되는 과목 알려줘",
            None,
            "",
        ]:
            self.assertFalse(_looks_like_narrow_scope_request(msg), msg)

    def test_rule_is_appended_last_for_recency(self):
        """규칙은 프롬프트 맨 끝에 와야 한다 (recency로 준수도 확보)."""
        from app.domains.planning.roadmap_chat import _CONDITIONAL_RULES, _build_system_prompt
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        db = sessionmaker(bind=engine)()
        user = User(id=1, email="t@x.com", password_hash="x", name="테스트",
                    department_id=10, major_id=20)
        db.add(user)
        db.add(CourseRoadmap(id=1, user_id=1))
        db.commit()

        prompt, rules = _build_system_prompt(db, user, "이거만 옮겨주세요")
        self.assertIn("narrow_scope_request", rules)
        self.assertEqual("narrow_scope_request", rules[-1])
        self.assertTrue(prompt.rstrip().endswith(
            _CONDITIONAL_RULES["narrow_scope_request"].rstrip()
        ))

        _, rules_broad = _build_system_prompt(db, user, "수강계획 추천해줘")
        self.assertNotIn("narrow_scope_request", rules_broad)


class PromptHasNoCopyableCourseNamesTest(unittest.TestCase):
    """프롬프트의 "모델이 말할 문장" 예시에 실제 과목명이 박혀 있으면 안 된다.

    LLM은 예시 문장을 그대로 옮겨 적는다. `_CORE_PROMPT`에 "예: 3학년인데 이산수학(전공기초)
    미이수면 ... '전공기초 이산수학이 미이수라 이번 학기 최우선 추천'이라고 명시하고"가
    있었는데, **이산수학을 이미 이수한 학생에게도 그 문장을 그대로 말하는** 사례가
    관측됐다(골든 케이스 24, 2026-08-13). 자리표시자 `〈과목명〉`으로 바꿔야 한다.

    시간표 챗의 `critical_missing` 규칙도 같은 형태였다.
    """

    # 부산대 교육과정에 실재하는 이름들. 예시로 쓰면 LLM이 사실처럼 복사한다.
    REAL_COURSE_NAMES = (
        "이산수학", "자료구조", "알고리즘", "컴퓨터구조", "운영체제",
        "컴퓨터네트워크", "데이터베이스", "시스템프로그래밍", "머신러닝",
    )

    def assert_no_real_names(self, text, where):
        found = [n for n in self.REAL_COURSE_NAMES if n in text]
        self.assertEqual(
            [], found,
            f"{where}에 실제 과목명 {found}이 있다. LLM이 그대로 복사해 없는 사실을 말한다 — "
            "〈과목명〉 같은 자리표시자를 쓰고 '실제 값으로 바꿔라'를 명시할 것.",
        )

    def test_roadmap_core_prompt(self):
        from app.domains.planning.roadmap_chat import _CORE_PROMPT
        self.assert_no_real_names(_CORE_PROMPT, "로드맵 CORE 프롬프트")

    def test_roadmap_conditional_rules(self):
        from app.domains.planning.roadmap_chat import _CONDITIONAL_RULES
        for key, text in _CONDITIONAL_RULES.items():
            self.assert_no_real_names(text, f"로드맵 조건부 규칙 '{key}'")

    def test_timetable_conditional_rules(self):
        from app.domains.planning.timetable_chat import _TIMETABLE_CONDITIONAL_RULES
        for key, text in _TIMETABLE_CONDITIONAL_RULES.items():
            self.assert_no_real_names(text, f"시간표 조건부 규칙 '{key}'")

    def test_no_quotable_placeholder_syntax(self):
        """자리표시자 문법도 쓰면 안 된다 — LLM이 꺾쇠째 복사한다.

        `"전공기초 〈과목명〉이 미이수라..."`로 바꿨더니 LLM이 과목명은 치환하면서
        **꺾쇠는 그대로 둬서** `〈컴퓨터프로그래밍(I)〉`이 사용자 응답에 나왔다
        (2026-08-14 관측). 인용 가능한 템플릿 문장 자체를 두지 않는 게 맞다.
        """
        from app.domains.planning.roadmap_chat import _CONDITIONAL_RULES, _CORE_PROMPT
        from app.domains.planning.timetable_chat import _TIMETABLE_CONDITIONAL_RULES

        texts = [("로드맵 CORE", _CORE_PROMPT)]
        texts += [(f"로드맵 규칙 {k}", v) for k, v in _CONDITIONAL_RULES.items()]
        texts += [(f"시간표 규칙 {k}", v) for k, v in _TIMETABLE_CONDITIONAL_RULES.items()]
        for where, text in texts:
            for token in ("〈", "〉"):
                self.assertNotIn(
                    token, text,
                    f"{where}에 자리표시자 문법 {token}가 있다 — LLM이 꺾쇠째 복사한다.",
                )

    def test_rule_points_at_tool_list_not_an_example(self):
        """미이수 필수 규칙은 예시 문장이 아니라 **도구가 준 목록**을 가리켜야 한다.

        구체적 예시("이산수학 미이수면...")는 이미 이수한 학생에게도 복사됐고, 예시를 빼자
        이번엔 규칙 준수가 무너졌다(케이스 12가 0/3). 크로스체크를 도구로 내리고
        프롬프트는 목록만 가리키게 한 뒤 3/3으로 회복했다.

        문구 자체는 스윕 결과에 따라 계속 다듬으므로 정확한 문장을 박아두지 않는다 —
        규칙이 갖춰야 할 **세 가지 성질**만 검사한다.
        """
        from app.domains.planning.roadmap_chat import _CORE_PROMPT

        # (1) 도구가 준 목록을 가리킨다.
        self.assertIn("missing_required_available", _CORE_PROMPT)

        # (2) 목록이 비었을 때의 가드가 있다 — 이산수학 환각의 직접 원인이었다.
        self.assertRegex(
            _CORE_PROMPT, r"비어 ?있으면",
            "빈 목록일 때 '미이수 없음'으로 처리하라는 가드가 없다 — 이미 이수한 과목을 "
            "미이수라고 말하는 환각이 되살아난다.",
        )

        # (3) 실제 과목명을 예시로 박아두지 않는다. LLM이 그대로 복사한다.
        for name in ("이산수학", "자료구조", "컴퓨터프로그래밍"):
            self.assertNotIn(
                name, _CORE_PROMPT,
                f"CORE 프롬프트에 실제 과목명 '{name}'이 있다 — 해당 과목을 이미 이수한 "
                f"학생에게도 그대로 복사된다.",
            )


class TermGapProbeTest(unittest.TestCase):
    """엇학기 판정 — 마지막 이수 학기와 현재 학기 사이 공백.

    옛 판정은 "최신 SCR 연도 - curriculum_year >= 4"라 **정작 대상인 한 학기 휴학생이
    안 걸렸다** (골든 케이스 10이 규칙을 한 번도 못 받고 3/3 실패).
    "이수 학기 수 < 경과 학기 수"도 부적절하다 — 포털 미동기화/부분 동기화 학생이 전부
    걸린다. 마지막 이수 학기만 보는 게 맞다.
    """

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        db = sessionmaker(bind=engine, autoflush=False)()
        db.add(User(id=1, email="t@x.com", password_hash="x", name="테스트", department_id=10))
        db.flush()
        return db

    def probe_with(self, terms):
        """terms: [(year, semester), ...] 이수 기록을 깔고 판정 (현재 학기 2026-2 고정)."""
        db = self.make_db()
        for i, (year, sem) in enumerate(terms):
            db.add(StudentCourseRecord(user_id=1, raw_course_name=f"과목{i}",
                                       category="전공선택", credits=3,
                                       year=year, semester=sem))
        db.commit()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 2)):
            return roadmap_chat_mod._has_term_gap(db, db.get(User, 1))

    def test_previous_semester_is_normal(self):
        """직전 학기까지 이수 = 정상 재학생."""
        self.assertFalse(self.probe_with([("2025", "2학기"), ("2026", "1학기")]))

    def test_current_semester_record_is_normal(self):
        """이번 학기 기록이 벌써 들어온 경우도 정상."""
        self.assertFalse(self.probe_with([("2026", "2학기")]))

    def test_one_semester_gap_is_staggered(self):
        """한 학기 휴학 — 옛 판정이 못 잡던 바로 그 케이스."""
        self.assertTrue(self.probe_with([("2025", "1학기"), ("2025", "2학기")]))

    def test_long_gap_is_staggered(self):
        self.assertTrue(self.probe_with([("2022", "1학기"), ("2024", "1학기")]))

    def test_no_records_is_not_judged(self):
        """신입·편입·포털 미동기화는 근거가 없어 판정하지 않는다."""
        self.assertFalse(self.probe_with([]))

    def test_pre_admission_credits_are_ignored(self):
        """'입학전성적'은 학기를 특정할 수 없는 lump-sum이라 제외한다."""
        self.assertFalse(self.probe_with([("2026", "1학기"), ("2026", "입학전성적")]))

    def test_seasonal_terms_are_ignored_for_gap(self):
        """계절수업은 정규 학기 순번을 매길 수 없다."""
        self.assertFalse(self.probe_with([("2026", "1학기"), ("2026", "여름계절수업")]))


class CareerMismatchProbeTest(unittest.TestCase):
    """`_career_looks_mismatched` — 진로-전공 mismatch 규칙을 붙일지 판정하는 probe.

    이 규칙은 "부전공/복수전공을 능동적으로 제안해라"는 강한 지시라, 진로와 전공이 잘 맞는
    학생에게까지 붙으면 불필요한 권유를 유발하고 프롬프트 fatigue로 다른 규칙의 준수도를
    떨어뜨린다. 옛 구현은 "진로 목표가 있고 부·복수전공이 없으면" 전부 붙였다.
    """

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def make_user(self, db, career_goal, dept_id=10, course_names=()):
        db.add(School(id=1, name="부산대학교"))
        db.add(College(id=1, school_id=1, name="테스트대학"))
        db.add(Department(id=dept_id, college_id=1, name="테스트학과"))
        db.flush()
        for i, name in enumerate(course_names):
            db.add(Course(id=900 + i, course_name=name, department_id=dept_id,
                          category="전공선택", credits=3, year="2", semester="1"))
        user = User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=dept_id, career_goal=career_goal)
        db.add(user)
        db.flush()
        return user

    def probe(self, career_goal, course_names):
        db = self.make_db()
        user = self.make_user(db, career_goal, course_names=course_names)
        return roadmap_chat_mod._career_looks_mismatched(db, user)

    def test_career_keywords_absent_from_department_is_mismatch(self):
        # 국문학과 커리큘럼 + 백엔드 진로 → 규칙이 붙어야 한다 (골든 케이스 14)
        self.assertTrue(self.probe("백엔드 개발자", ["현대문학의이해", "국어학개론"]))

    def test_career_keywords_present_in_department_is_not_mismatch(self):
        # 정컴 커리큘럼 + 백엔드 진로 → 잘 맞으므로 규칙을 붙이지 않는다
        self.assertFalse(self.probe("백엔드 개발자", ["데이터베이스", "운영체제", "컴퓨터네트워크"]))

    def test_unknown_career_group_never_fires(self):
        # 알려진 진로군에 안 걸리면 판단 근거가 없다 → mismatch로 단정하지 않는다
        self.assertFalse(self.probe("자동차 엔지니어", ["현대문학의이해", "국어학개론"]))

    def test_loose_alias_is_rescued_by_course_name_overlap(self):
        # "재무분석가"는 '분석' 때문에 data 진로군에 걸리지만, 경영학과에 '재무관리'가
        # 있으므로 mismatch가 아니다 — 진로 문구와 과목명의 2글자 겹침으로 구제한다
        self.assertFalse(self.probe("재무분석가", ["재무관리", "회계원리", "투자론"]))

    def test_empty_catalog_is_not_treated_as_mismatch(self):
        # 학과 개설과목 데이터가 아직 없는 상태를 mismatch로 오인하면 안 된다
        self.assertFalse(self.probe("백엔드 개발자", []))

    def test_description_also_counts_as_alignment_evidence(self):
        # 과목명에 키워드가 없어도 교과목개요에 있으면 정합으로 본다
        db = self.make_db()
        db.add(School(id=1, name="부산대학교"))
        db.add(College(id=1, school_id=1, name="테스트대학"))
        db.add(Department(id=10, college_id=1, name="테스트학과"))
        db.flush()
        db.add(Course(id=901, course_name="정보처리특론", department_id=10,
                      category="전공선택", credits=3, year="3", semester="1",
                      description="서버 구축과 데이터베이스 설계를 다룬다."))
        user = User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=10, career_goal="백엔드 개발자")
        db.add(user)
        db.flush()
        self.assertFalse(roadmap_chat_mod._career_looks_mismatched(db, user))


if __name__ == "__main__":
    unittest.main()


class ApplyPendingChangeItemOwnershipTest(unittest.TestCase):
    """승인 반영 시 `change.item_id`가 **이 로드맵의 항목인지** 다시 확인한다.

    `apply_pending_changes`는 change 자체는 `change.roadmap_id != roadmap.id`로 거르지만,
    예전에는 `change.item_id`를 그대로 믿고 `db.get(CourseRoadmapItem, change.item_id)`로
    가져와 수정/삭제했다. 지금은 propose_change가 제안을 만들 때 항목 소유권을 확인하므로
    남의 item_id가 담긴 행이 생기지 않지만, **승인은 항목을 수정·삭제하는 경로**라 한 겹
    위에서만 지키면 그 위쪽이 바뀌는 순간 남의 로드맵이 조용히 훼손된다.

    학사 계획은 개인정보이자 사용자가 직접 쌓은 데이터라 조용한 손상이 특히 나쁘다.
    """

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def _two_roadmaps(self, db):
        """공격자(user 1, roadmap 1)와 피해자(user 2, roadmap 2)."""
        db.add_all([
            User(id=1, email="a@example.com", password_hash="x", name="공격자"),
            User(id=2, email="v@example.com", password_hash="x", name="피해자"),
            CourseRoadmap(id=1, user_id=1),
            CourseRoadmap(id=2, user_id=2),
        ])
        db.flush()
        victim_item = CourseRoadmapItem(
            roadmap_id=2, course_id=None, course_name="피해자과목",
            planned_grade=3, planned_year="2026", planned_semester="1학기",
        )
        db.add(victim_item)
        db.flush()
        return db.get(CourseRoadmap, 1), victim_item

    def test_update_does_not_touch_other_roadmaps_item(self):
        db = self.make_db()
        attacker_roadmap, victim_item = self._two_roadmaps(db)
        change = PendingRoadmapChange(
            roadmap_id=attacker_roadmap.id,   # 내 로드맵의 제안이지만
            item_id=victim_item.id,           # 남의 항목을 겨냥한다
            action="update", planned_semester="2학기", status="pending",
        )
        db.add(change)
        db.flush()

        roadmap_chat_mod.apply_pending_changes(db, attacker_roadmap, [change.id], [])

        db.refresh(victim_item)
        self.assertEqual("1학기", victim_item.planned_semester,
                         "남의 로드맵 항목이 수정됐다")

    def test_delete_does_not_remove_other_roadmaps_item(self):
        db = self.make_db()
        attacker_roadmap, victim_item = self._two_roadmaps(db)
        victim_item_id = victim_item.id
        change = PendingRoadmapChange(
            roadmap_id=attacker_roadmap.id,
            item_id=victim_item_id,
            action="delete", status="pending",
        )
        db.add(change)
        db.flush()

        roadmap_chat_mod.apply_pending_changes(db, attacker_roadmap, [change.id], [])

        self.assertIsNotNone(db.get(CourseRoadmapItem, victim_item_id),
                             "남의 로드맵 항목이 삭제됐다")


class FullHorizonPlanningTest(unittest.TestCase):
    """"졸업까지 로드맵 짜줘"에 미래 학기가 하나도 안 만들어지던 문제.

    2026-08-20 실계정(편입 3학년, 남은 학기 3개 = 3-2/4-1/4-2) 실측: "졸업까지 로드맵
    짜줘" / "남은 학기 전부 계획해줘" / "4학년 2학기까지 어떻게 들어야 해?" 세 요청 모두
    **다음 한 학기(3-2)에만** 0~2건을 제안하고 "승인해주시면 4-1, 4-2도 이어서
    해드릴게요"로 끝냈다 — 4-1·4-2 항목은 0건. 도구 반복 상한(당시 8)에 걸린 게 아니라
    3/5/4회만 쓰고 스스로 종료했다.

    원인 세 가지를 각각 막는다:
      1. 남은 학기가 몇 개인지 알려주는 값이 어디에도 없었다 → `remaining_terms`
      2. 학기당 과목마다 propose_change를 부르면 왕복이 모자란다 → `propose_term_plan`
      3. 학기 여유를 남긴 채 끝내도 아무도 안 막았다 → run 루프의 finish 게이트
    """

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def make_ctx(self, db, total_req=133, admission_type=None, major_elective=None):
        user = User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=10, major_id=20, admission_type=admission_type)
        db.add(user)
        db.add(UserAcademicProgram(user_id=1, program_type="primary",
                                   department_id=10, major_id=20, curriculum_year=2026))
        db.add(GraduationRequirement(department_id=10, major_id=20, program_type="primary",
                                     curriculum_year="2026", required_total_credits=total_req,
                                     required_major_elective=major_elective))
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(roadmap)
        db.flush()
        return _ToolContext(db, user, roadmap)

    # ---- 1) 남은 학기 노출 ----

    def test_remaining_terms_covers_every_term_until_graduation(self):
        """편입 3학년(2026-1 재학)이면 남은 학기는 3-2, 4-1, 4-2 세 개다."""
        db = self.make_db()
        ctx = self.make_ctx(db, admission_type="transfer")
        # 편입 첫 학기(3-1) 이수기록 — 커리큘럼 학년 환산의 기준점. 21학점 꽉 채워서
        # 학점이월제 보너스(상한 대비 미사용분)가 안 붙게 한다 — 이 테스트는 학기
        # 범위(horizon) 커버리지가 목적이지 신청학점 보너스 계산이 목적이 아니다.
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이수A", credits=21,
                                   year="2026", semester="1학기", category="전공선택"))
        db.flush()

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            terms = ctx.get_roadmap_items()["remaining_terms"]

        self.assertEqual(
            [("2026", "2학기", 3), ("2027", "1학기", 4), ("2027", "2학기", 4)],
            [(t["planned_year"], t["planned_semester"], t["planned_grade"]) for t in terms],
        )
        # 빈 학기라면 상한만큼 여유가 있다고 알려줘야 한다
        self.assertEqual(21.0, terms[0]["credits_left_in_term"])

    # ---- 2) 벌크 제안 ----

    def test_propose_term_plan_creates_items_across_multiple_terms(self):
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add_all([
            Course(id=301, course_name="가", department_id=10, major_id=20,
                   category="전공선택", credits=3.0, year="3", semester="2"),
            Course(id=302, course_name="나", department_id=10, major_id=20,
                   category="전공선택", credits=3.0, year="4", semester="1"),
            Course(id=303, course_name="다", department_id=10, major_id=20,
                   category="전공선택", credits=3.0, year="4", semester="2"),
        ])
        db.flush()

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_term_plan(terms=[
                {"planned_year": "2026", "planned_semester": "2학기",
                 "planned_grade": 3, "course_ids": [301]},
                {"planned_year": "2027", "planned_semester": "1학기",
                 "planned_grade": 4, "course_ids": [302]},
                {"planned_year": "2027", "planned_semester": "2학기",
                 "planned_grade": 4, "course_ids": [303]},
            ], reason="졸업까지 계획")

        self.assertEqual(3, result["accepted_count"])
        self.assertEqual(0, result["rejected_count"])
        self.assertEqual(3, len(ctx.pending_changes))
        self.assertEqual(
            {("2026", "2학기"), ("2027", "1학기"), ("2027", "2학기")},
            {(c.planned_year, c.planned_semester) for c in ctx.pending_changes},
        )

    def test_propose_term_plan_reuses_propose_change_guards(self):
        """가드를 복제하지 않는다 — 계절수업 전용 과목은 벌크 경로에서도 거절돼야 한다.

        한 과목이 거절돼도 나머지는 그대로 제안되고, 사유가 rejected에 담긴다.
        """
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add_all([
            Course(id=310, course_name="정상", department_id=10, major_id=20,
                   category="전공선택", credits=3.0, year="3", semester="2"),
            Course(id=311, course_name="계절전용", department_id=10, major_id=20,
                   category="전공선택", credits=3.0, year="3", semester="여름계절수업"),
        ])
        db.flush()

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_term_plan(terms=[{
                "planned_year": "2026", "planned_semester": "2학기",
                "planned_grade": 3, "course_ids": [310, 311],
            }], reason="test")

        self.assertEqual(1, result["accepted_count"])
        self.assertEqual(1, result["rejected_count"])
        rejected = result["terms"][0]["rejected"][0]
        self.assertEqual(311, rejected["course_id"])
        self.assertIn("여름계절수업", rejected["error"])

    def test_pending_creates_count_toward_term_credit_cap(self):
        """아직 승인 전인 이번 턴 제안도 학기 학점 합계에 세야 한다.

        예전에는 DB의 CourseRoadmapItem만 셌다. 그래서 아직 비어 있는 미래 학기
        (4학년 1학기 등)에는 과목을 몇 개를 밀어넣든 합계가 계속 0이라 상한 가드가
        한 번도 걸리지 않았다 — 승인하면 그대로 저장되는데도.
        """
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)  # cap=21
        for i in range(8):
            db.add(Course(id=400 + i, course_name=f"과목{i}", department_id=10, major_id=20,
                          category="전공선택", credits=3.0, year="4", semester="1"))
        db.flush()

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_term_plan(terms=[{
                "planned_year": "2027", "planned_semester": "1학기",
                "planned_grade": 4, "course_ids": [400 + i for i in range(8)],
            }], reason="test")

        # 3학점 × 7 = 21까지만 통과, 8번째는 상한 초과로 거절
        self.assertEqual(7, result["accepted_count"])
        self.assertEqual(1, result["rejected_count"])
        self.assertIn("학기당 상한", result["terms"][0]["rejected"][0]["error"])
        self.assertEqual(21.0, result["terms"][0]["term_credits_after"])

    def test_학기를_안_옮기는_update는_그_학기_학점을_증발시키지_않는다(self):
        """학점 상한 가드가 **느슨해지는** 방향의 회귀를 막는다.

        `_planned_credits_by_term`은 옛 학기에서 학점을 빼고 새 학기에 더하는 식으로
        update를 반영하는데, 예전엔 `planned_year`가 없는 update(예: planned_grade만
        교정)에도 빼기만 하고 다시 더하지 않았다. 그런 제안 하나가 그 학기 학점을 통째로
        증발시켜서, 이미 21학점이 찬 학기에 과목을 더 밀어넣을 수 있었다.
        """
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)  # cap=21
        # 이미 21학점이 찬 학기를 만든다.
        for i in range(7):
            db.add(CourseRoadmapItem(
                id=700 + i, roadmap_id=1, course_name=f"기존{i}", credits=3.0,
                planned_year="2027", planned_semester="1학기", planned_grade=3,
                status="planned",
            ))
        db.add(Course(id=600, course_name="추가과목", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="4", semester="1"))
        db.flush()

        counted = ctx._planned_credits_by_term()[("2027", "1학기")]
        self.assertEqual(21.0, counted)

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            # 학기는 그대로 두고 학년 표기만 고치는 update.
            moved = ctx.propose_change(
                action="update", reason="학년 표기 교정", item_id=700, planned_grade=4,
            )
            self.assertNotIn("error", moved, moved)

            # 그 학기 학점은 여전히 21이어야 한다.
            self.assertEqual(21.0, ctx._planned_credits_by_term()[("2027", "1학기")])

            # 그러므로 3학점을 더 넣으려는 create는 상한으로 막혀야 한다.
            blocked = ctx.propose_change(
                action="create", reason="추가", course_id=600,
                planned_year="2027", planned_semester="1학기", planned_grade=4,
            )
        self.assertIn("error", blocked)
        self.assertIn("학기당 상한", blocked["error"])

    def test_같은_항목에_변경이_두_번_쌓여도_학점이_이중으로_빠지지_않는다(self):
        """델타 누적 방식이라 같은 item을 두 번 delete하면 학점이 두 번 빠진다.

        중복 가드는 `action=="create"`에만 있어서 delete/update는 그대로 쌓인다.
        실측으로 21학점이 찬 학기에 6학점이 더 들어갔다 — base(pending을 아예 안 세던
        시절)에서는 막히던 경로라, 이 브랜치가 새로 연 구멍이다.
        """
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)  # cap=21
        for i in range(7):
            db.add(CourseRoadmapItem(
                id=750 + i, roadmap_id=1, course_name=f"기존{i}", credits=3.0,
                planned_year="2027", planned_semester="1학기", planned_grade=4,
                status="planned",
            ))
        db.add(Course(id=650, course_name="추가과목", department_id=10, major_id=20,
                      category="전공선택", credits=6.0, year="4", semester="1,2"))
        db.flush()
        key = ("2027", "1학기")

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            for n in range(2):
                ctx.propose_change(action="delete", reason=f"삭제{n}", item_id=750)
            # 한 항목(3학점)만 빠져야 한다.
            self.assertEqual(18.0, ctx._planned_credits_by_term()[key])
            blocked = ctx.propose_change(
                action="create", reason="추가", course_id=650,
                planned_year="2027", planned_semester="1학기", planned_grade=4,
            )
        self.assertIn("error", blocked)
        self.assertIn("학기당 상한", blocked["error"])

    def test_학기를_옮기는_update는_학점도_따라_옮긴다(self):
        """위 수정이 반대로 "update는 아무것도 안 한다"가 되면 안 된다."""
        db = self.make_db()
        ctx = self.make_ctx(db, total_req=133)
        db.add(CourseRoadmapItem(
            id=800, roadmap_id=1, course_name="옮길과목", credits=3.0,
            planned_year="2027", planned_semester="1학기", planned_grade=4,
            status="planned",
        ))
        db.flush()

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            moved = ctx.propose_change(
                action="update", reason="학기 이동", item_id=800,
                planned_year="2027", planned_semester="2학기", planned_grade=4,
            )
            self.assertNotIn("error", moved, moved)

        planned = ctx._planned_credits_by_term()
        self.assertEqual(0.0, planned.get(("2027", "1학기"), 0.0))
        self.assertEqual(3.0, planned.get(("2027", "2학기"), 0.0))

    def test_requirement_coverage_reports_what_is_still_missing(self):
        """제안을 다 이수해도 남는 이수구분을 도구가 계산해 준다 (판정은 규칙 기반)."""
        db = self.make_db()
        ctx = self.make_ctx(db, major_elective=9)
        db.add(Course(id=500, course_name="전선", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="4", semester="1"))
        db.flush()

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_term_plan(terms=[{
                "planned_year": "2027", "planned_semester": "1학기",
                "planned_grade": 4, "course_ids": [500],
            }], reason="test")

        coverage = {c["category_name"]: c for c in result["requirement_coverage"]}
        self.assertEqual(3.0, coverage["전공선택"]["planned_in_this_turn"])
        self.assertEqual(6.0, coverage["전공선택"]["remaining_after_plan"])
        self.assertIn("전공선택", [u["category_name"]
                                for u in result["unmet_categories_after_plan"]])
        # 아직 채울 여지가 있으면 finish 게이트가 볼 상태가 남는다
        self.assertIsNotNone(ctx.plan_gap)

    def test_plan_gap_flags_terms_left_completely_empty(self):
        """`course_ids: []`인 빈 학기를 넣고 넘어가는 걸 잡아낸다.

        원래 보고된 증상이 정확히 "미래 학기 항목 0건"이었고, 고친 뒤 실측에서도
        LLM이 2027-1/2027-2를 `course_ids: []`로 넣고 2026-2만 채운 채 끝내려 한
        적이 있다. "N학점 미배정"보다 "2027년 1학기가 비어 있다"가 구체적이라
        게이트 메시지가 그 학기를 이름으로 지목하게 한다.

        **단 졸업요건이 남아 있을 때만이다** — 요건을 다 채웠으면 빈 학기가 있어도
        되돌리지 않는다(아래 `test_요건이_충족되면…` 참고).
        """
        db = self.make_db()
        ctx = self.make_ctx(db, admission_type="transfer", major_elective=30)
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이수A", credits=3,
                                   year="2026", semester="1학기", category="전공선택"))
        db.add(Course(id=550, course_name="가", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        db.flush()

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            ctx.propose_term_plan(terms=[
                {"planned_year": "2026", "planned_semester": "2학기",
                 "planned_grade": 3, "course_ids": [550]},
                {"planned_year": "2027", "planned_semester": "1학기",
                 "planned_grade": 4, "course_ids": []},
                {"planned_year": "2027", "planned_semester": "2학기",
                 "planned_grade": 4, "course_ids": []},
            ], reason="test")

        self.assertIsNotNone(ctx.plan_gap)
        self.assertEqual(
            ["2027년 1학기(4학년)", "2027년 2학기(4학년)"],
            ctx.plan_gap["empty_terms"],
        )

    def test_요건이_충족되면_빈_학기가_있어도_더_채우라고_하지_않는다(self):
        """목표는 "학기를 꽉 채우기"가 아니라 "졸업요건 충족"이다.

        예전엔 빈 학기가 하나라도 있으면 게이트가 발동해서, 요건을 다 채운 학생에게도
        "2027년 2학기가 비어 있으니 채워라"라고 밀어붙였다 — 졸업에 필요 없는 과목을
        억지로 넣게 만든다.
        """
        db = self.make_db()
        # 총 6학점짜리 요건 + 전공선택 3학점 잔여 → 한 과목이면 **총학점까지** 다 찬다.
        # 총요구학점을 낮추지 않으면 이수구분 잔여가 0이어도 총학점이 남아 미충족이다
        # (사범대처럼 이수구분 합 < 총요구학점인 요건 행이 운영 DB에 17개 있다).
        ctx = self.make_ctx(db, admission_type="transfer", total_req=6, major_elective=3)
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이수A", credits=3,
                                   year="2026", semester="1학기", category="전공선택"))
        db.add(Course(id=560, course_name="마지막전선", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        db.flush()

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_term_plan(terms=[{
                "planned_year": "2026", "planned_semester": "2학기",
                "planned_grade": 3, "course_ids": [560],
            }], reason="test")

        # 2027-1, 2027-2가 통째로 비어 있지만 요건이 다 찼으므로 되돌리지 않는다.
        self.assertEqual([], result["unmet_categories_after_plan"])
        self.assertEqual(0.0, result["remaining_total_credits_after_plan"])
        self.assertIsNone(ctx.plan_gap)
        self.assertIn("더 채우지 마라", result["next_action"])

    def test_이수구분을_다_채워도_총_이수학점이_남으면_충족이_아니다(self):
        """운영 DB의 primary 요건 126행 중 17행(사범대 전체)이 **이수구분 합 <
        총요구학점**이다(차이 22학점 = 교직). 이수구분 잔여만 보면 다 채웠는데
        졸업요건 엔진은 같은 호출에서 `satisfied=False`라고 판정한다.

        그 상태에서 "졸업요건이 모두 충족됐다. 더 채우지 마라"라고 지시하면 학생이
        22학점을 덜 들은 채 졸업할 수 있다고 믿게 된다.
        """
        db = self.make_db()
        # 사범대형: 총 30학점 요건인데 이수구분 합은 6학점뿐.
        ctx = self.make_ctx(db, admission_type="transfer", total_req=30, major_elective=3)
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이수A", credits=3,
                                   year="2026", semester="1학기", category="전공선택"))
        db.add(Course(id=580, course_name="마지막전선", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        db.flush()

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_term_plan(terms=[{
                "planned_year": "2026", "planned_semester": "2학기",
                "planned_grade": 3, "course_ids": [580],
            }], reason="test")

        self.assertEqual([], result["unmet_categories_after_plan"])
        self.assertEqual(24.0, result["remaining_total_credits_after_plan"])
        self.assertIsNotNone(ctx.plan_gap, "총학점이 남았는데 되돌리지 않았다")
        self.assertNotIn("더 채우지 마라", result["next_action"])
        self.assertIn("총 이수학점", result["next_action"])

    def test_교양_과목을_제안하면_교양_요건_잔여가_줄어든다(self):
        """요건 라벨(`교양필수`/`교양선택`)과 `courses.category`(`효원핵심교양` 등)의
        어휘가 다르다 — 운영 DB에 `교양필수`/`교양선택` category 과목은 **0건**이다.

        정규화 없이 이름으로 맞추면 교양 과목을 아무리 계획해도 교양 잔여가 1학점도
        안 줄어들어, "요건 충족" 상태에 영영 도달하지 못하고 게이트가 계속 되돌린다.
        """
        db = self.make_db()
        ctx = self.make_ctx(db, admission_type="transfer", total_req=133)
        db.add(GraduationRequirement(
            department_id=10, major_id=20, program_type="primary",
            curriculum_year="2026", required_total_credits=133,
            required_general_required=3, required_general_elective=6,
        ))
        db.query(GraduationRequirement).filter(
            GraduationRequirement.required_general_required.is_(None)).delete()
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이수A", credits=3,
                                   year="2026", semester="1학기", category="전공선택"))
        db.add_all([
            Course(id=590, course_name="핵심교양과목", department_id=10, major_id=20,
                   category="효원핵심교양", credits=3.0, year="3", semester="2"),
            Course(id=591, course_name="균형교양과목", department_id=10, major_id=20,
                   category="효원균형교양", credits=3.0, year="3", semester="2"),
        ])
        db.flush()

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_term_plan(terms=[{
                "planned_year": "2026", "planned_semester": "2학기",
                "planned_grade": 3, "course_ids": [590, 591],
            }], reason="test")

        cov = {c["category_name"]: c for c in result["requirement_coverage"]}
        # 효원핵심교양 → 교양필수, 효원균형교양 → 교양선택 (2026 개편 대응)
        self.assertEqual(3.0, cov["교양필수"]["planned_in_this_turn"])
        self.assertEqual(0.0, cov["교양필수"]["remaining_after_plan"])
        self.assertEqual(3.0, cov["교양선택"]["planned_in_this_turn"])
        self.assertEqual(3.0, cov["교양선택"]["remaining_after_plan"])

    def test_총요구학점을_모르면_충족됐다고_말하지_않는다(self):
        """이수구분 잔여가 0이어도 총요구학점을 모르면 "모두 충족"을 주장할 수 없다.

        사범대처럼 총학점 축에만 남는 학점이 있는 학과가 실재하므로, 그 축을 모르는
        채로 "다 채웠다"고 말하면 학생이 덜 들은 채 졸업할 수 있다고 믿는다.
        """
        db = self.make_db()
        ctx = self.make_ctx(db, admission_type="transfer")
        db.query(GraduationRequirement).delete()
        # 총요구학점 없이 이수구분만 있는 요건 행.
        db.add(GraduationRequirement(
            department_id=10, major_id=20, program_type="primary",
            curriculum_year="2026", required_total_credits=None,
            required_major_elective=3))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이수A", credits=3,
                                   year="2026", semester="1학기", category="전공선택"))
        db.add(Course(id=920, course_name="마지막전선", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        db.flush()

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_term_plan(terms=[{
                "planned_year": "2026", "planned_semester": "2학기",
                "planned_grade": 3, "course_ids": [920],
            }], reason="test")

        self.assertEqual([], result["unmet_categories_after_plan"])
        self.assertFalse(ctx.requirements_known, "총요구학점을 모르는데 안다고 판단했다")
        self.assertNotIn("모두 충족", result["next_action"])
        self.assertIn("확인할 수 없다", result["next_action"])

    def test_요건_기준이_없으면_충족됐다고_말하지_않는다(self):
        """학과 요건 행이 없으면 잔여 학점이 전부 None이라 "미충족 0"과 "판단 불가"가
        구분되지 않는다. 그 둘을 섞으면 요건을 모르는 학생에게 "다 채웠다"고 말한다.
        """
        db = self.make_db()
        ctx = self.make_ctx(db, admission_type="transfer")
        # 요건 행 제거 — 기준을 모르는 상태를 만든다.
        db.query(GraduationRequirement).delete()
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이수A", credits=3,
                                   year="2026", semester="1학기", category="전공선택"))
        db.add(Course(id=570, course_name="아무전선", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        db.flush()

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_term_plan(terms=[{
                "planned_year": "2026", "planned_semester": "2학기",
                "planned_grade": 3, "course_ids": [570],
            }], reason="test")

        self.assertFalse(ctx.requirements_known)
        self.assertIn("확인할 수 없다", result["next_action"])
        # 요건을 **모른다**는 건 "채울 필요 없다"의 근거가 못 된다. 빈 학기가 남아
        # 있으면 계속 채우게 둔다 — 아니면 원래 증상("한 학기만 제안")으로 돌아간다.
        self.assertIsNotNone(ctx.plan_gap, "요건 미상인데 게이트가 통째로 사라졌다")
        # "다 채워졌다"고 단정하는 문구는 없어야 한다("충족 여부를 확인할 수 없다"는 정상).
        self.assertNotIn("모두 충족", result["next_action"])
        self.assertNotIn("더 채우지 마라", result["next_action"])

    def test_reproposing_same_course_is_not_a_rejection(self):
        """이미 제안한 과목을 다시 넘기면 실패가 아니라 already_in_plan이다.

        LLM이 보강 라운드에서 같은 계획을 통째로 다시 넘기는 일이 잦은데, 중복 create가
        rejected에 섞이면 "다 반려됐다"고 읽고 앞서 성공한 제안까지 없던 일처럼 답한다
        (2026-08-20 실측: 실제로 accepted된 4학년 1학기 3과목을 "확정 없음"이라고 적었다).
        """
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=520, course_name="가", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="4", semester="1"))
        db.flush()
        term = {"planned_year": "2027", "planned_semester": "1학기",
                "planned_grade": 4, "course_ids": [520]}

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            first = ctx.propose_term_plan(terms=[dict(term)], reason="test")
            second = ctx.propose_term_plan(terms=[dict(term)], reason="test")

        self.assertEqual(1, first["accepted_count"])
        self.assertEqual(0, second["accepted_count"])
        self.assertEqual(0, second["rejected_count"], "중복 재제출이 반려로 잡혔다")
        self.assertEqual([520], [c["course_id"]
                                 for c in second["terms"][0]["already_in_plan"]])
        # 제안이 두 배로 쌓이지도 않는다
        self.assertEqual(1, len(ctx.pending_changes))

    def test_plan_so_far_carries_every_term_proposed_this_turn(self):
        """여러 번 호출해도 답변에 옮겨 적을 단일 출처가 있어야 한다."""
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add_all([
            Course(id=530, course_name="가", department_id=10, major_id=20,
                   category="전공선택", credits=3.0, year="3", semester="2"),
            Course(id=531, course_name="나", department_id=10, major_id=20,
                   category="전공선택", credits=3.0, year="4", semester="1"),
        ])
        db.flush()

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            ctx.propose_term_plan(terms=[{
                "planned_year": "2026", "planned_semester": "2학기",
                "planned_grade": 3, "course_ids": [530]}], reason="1차")
            result = ctx.propose_term_plan(terms=[{
                "planned_year": "2027", "planned_semester": "1학기",
                "planned_grade": 4, "course_ids": [531]}], reason="2차")

        plan = {(t["planned_year"], t["planned_semester"]): t for t in result["plan_so_far"]}
        self.assertEqual(
            ["가"], [c["course_name"] for c in plan[("2026", "2학기")]["courses"]],
            "2차 호출 결과만 보면 1차에서 성공한 학기가 사라진다",
        )
        self.assertEqual(["나"], [c["course_name"] for c in plan[("2027", "1학기")]["courses"]])
        self.assertEqual(3.0, plan[("2026", "2학기")]["total_credits"])

    # ---- 3) 요청 판정 ----

    def test_full_horizon_markers_need_both_scope_and_planning_intent(self):
        from app.domains.planning.roadmap_chat import _looks_like_full_horizon_request
        for msg in [
            "졸업까지 로드맵 짜줘",
            "남은 학기 전부 계획해줘",
            "4학년 2학기까지 어떻게 들어야 해?",
            "졸업할 때까지 수강계획 짜줘",
        ]:
            self.assertTrue(_looks_like_full_horizon_request(msg), msg)

        # 범위 표현만 있고 계획 의도가 없으면 걸리면 안 된다 — 단순 조회 요청에
        # 묻지도 않은 3개 학기 제안이 승인 대기에 쌓인다.
        for msg in [
            "졸업까지 뭐가 남았는지 정리해줘",
            "졸업요건 얼마나 남았어?",
            "다음 학기 뭐 들을까",
            "데이터베이스만 옮겨줘",
            None,
            "",
        ]:
            self.assertFalse(_looks_like_full_horizon_request(msg), msg)

    def test_narrow_scope_beats_full_horizon(self):
        """"졸업까지 계획 중인데 이 과목만 옮겨줘"는 좁은 쪽이 이겨야 한다."""
        from app.domains.planning.roadmap_chat import _build_system_prompt
        db = self.make_db()
        ctx = self.make_ctx(db)
        _, rules = _build_system_prompt(
            db, ctx.user, "졸업까지 로드맵 짜는 건 나중에 하고, 데이터베이스 그것만 옮겨줘"
        )
        self.assertIn("narrow_scope_request", rules)
        self.assertNotIn("full_horizon_request", rules)

    def test_unscoped_build_request_detects_missing_scope(self):
        """"로드맵 짜줘"처럼 계획 의도는 있는데 다음 학기 하나인지 졸업까지인지
        범위를 안 밝힌 요청만 걸려야 한다."""
        from app.domains.planning.roadmap_chat import _looks_like_unscoped_build_request

        for msg in [
            "로드맵 짜줘",
            "성장 로드맵 만들어줘",
            "수강 계획 세워줘",
            "커리큘럼 짜줘",
        ]:
            self.assertTrue(_looks_like_unscoped_build_request(msg), msg)

        for msg in [
            "졸업까지 로드맵 짜줘",  # full_horizon이 이겨야 함
            "다음 학기 뭐 들을까",  # 이미 특정 학기를 짚음
            "3학년 2학기 계획해줘",  # 이미 특정 학년/학기를 짚음
            "데이터베이스만 옮겨줘",  # narrow_scope, 애초에 계획 의도가 없음
            "로드맵 어떻게 돼 있어?",  # 조회일 뿐, build verb 없음
            None,
            "",
        ]:
            self.assertFalse(_looks_like_unscoped_build_request(msg), msg)

    def test_unscoped_build_request_wired_into_system_prompt(self):
        from app.domains.planning.roadmap_chat import _build_system_prompt
        db = self.make_db()
        ctx = self.make_ctx(db)

        _, rules = _build_system_prompt(db, ctx.user, "성장 로드맵 만들어줘")
        self.assertIn("unscoped_build_request", rules)
        self.assertNotIn("full_horizon_request", rules)

        # 이미 범위를 짚은 요청엔 안 걸려야 한다.
        _, rules2 = _build_system_prompt(db, ctx.user, "다음 학기 로드맵 짜줘")
        self.assertNotIn("unscoped_build_request", rules2)


class FullHorizonFinishGateTest(unittest.TestCase):
    """미배정 학점을 남긴 채 끝내려는 finish_response를 루프가 한 번 되돌린다.

    프롬프트로도, 도구 응답의 `next_action`으로도 "한 번 더 채워라"라고 지시했는데
    LLM은 그 지시를 **사용자에게 설명만 하고** 끝냈다 (2026-08-20 실측: 전공선택
    23학점을 남긴 채 "다음 단계로 더 채우는 플랜을 만들게요"로 종료). 그래서 프롬프트가
    아니라 실행 루프에서 막는다.

    되돌림은 턴당 한 번뿐이다 — 후보가 정말 없을 때 무한 루프가 되면 안 되고,
    남은 왕복이 모자랄 때 되돌리면 finish_response를 아예 못 받는다.
    """

    def test_gate_reserve_leaves_room_for_another_round(self):
        """게이트는 보충 검색 + 2차 제안 + finish를 할 왕복이 남았을 때만 발동한다."""
        self.assertGreaterEqual(
            roadmap_chat_mod.MAX_TOOL_ITERATIONS - roadmap_chat_mod._FINISH_GATE_RESERVE,
            1,
            "게이트가 첫 왕복부터 아예 못 걸리면 의미가 없다",
        )
        self.assertGreaterEqual(
            roadmap_chat_mod._FINISH_GATE_RESERVE, 3,
            "되돌린 뒤 search_courses + propose_term_plan + finish_response 3왕복은 남겨야 한다",
        )

    def test_fallback_summary_shows_proposals_instead_of_apology(self):
        """LLM 마무리 요약까지 실패해도, 쌓인 제안은 사실 그대로 보여준다.

        게이트를 넣은 직후 실측에서 제안 19건을 만들어놓고 "죄송해요, 답변을 정리하지
        못했어요"만 나간 적이 있다 — 사용자는 승인 대기에 뭐가 올라왔는지 알 수 없다.
        """
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        db = sessionmaker(bind=engine)()
        db.add(Course(id=600, course_name="자료구조", department_id=10,
                      category="전공필수", credits=3.0, year="2", semester="2"))
        db.flush()
        pending = [PendingRoadmapChange(
            roadmap_id=1, action="create", course_id=600,
            planned_year="2027", planned_semester="1학기", status="pending",
        )]

        text = roadmap_chat_mod._fallback_summary(db, pending)

        self.assertIn("자료구조", text)
        self.assertIn("2027년 1학기", text)
        self.assertNotIn("죄송해요", text)

    def test_fallback_summary_apologizes_when_nothing_was_proposed(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        db = sessionmaker(bind=engine)()
        self.assertIn("죄송", roadmap_chat_mod._fallback_summary(db, []))


class _ScriptedLLM:
    """스크립트된 tool_calls를 순서대로 돌려주는 가짜 LLM.

    `run_roadmap_chat`의 루프를 실제로 태우기 위한 것이다. finish 게이트는 그 루프
    안에만 있어서, `_ToolContext`만 직접 부르는 테스트로는 **한 줄도 실행되지 않는다** —
    독립 리뷰가 게이트를 `if False and (...)`로 무력화하고도 전체 스위트를 통과시켰다.
    """

    def __init__(self, script):
        self._script = list(script)
        self.calls_made = 0
        # 게이트 되돌림 문구는 ToolMessage로 다음 호출에 실려 온다. 발동 여부만 세면
        # 문구가 자가당착이어도 테스트가 통과한다.
        self.tool_messages: list[str] = []

    def bind_tools(self, tools, tool_choice=None):
        return self

    def invoke(self, messages, config=None):
        self.calls_made += 1
        if not self._script:
            raise AssertionError(
                f"스크립트가 {self.calls_made - 1}번 만에 소진됐다 — 루프가 예상보다 더 돌았다"
            )
        for m in messages:
            content = getattr(m, "content", None)
            if isinstance(content, str) and content:
                self.tool_messages.append(content)
        calls = self._script.pop(0)
        msg = MagicMock()
        msg.content = ""
        msg.tool_calls = calls
        return msg


class FinishGateBehaviourTest(unittest.TestCase):
    """finish 게이트가 실제 루프에서 어떻게 동작하는가.

    이 PR에서 가장 위험한 부분이다 — LLM의 종료를 서버가 되돌리므로, 되돌림이 안 걸리면
    기능이 없는 것이고 계속 걸리면 무한루프다.
    """

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def make_student(self, db):
        # `_build_student_context_block`이 학과·전공 이름을 조회하므로 실제 행이 필요하다.
        db.add_all([
            School(id=1, name="부산대학교"),
            College(id=1, school_id=1, name="정보의생명공학대학"),
            Department(id=10, college_id=1, name="정보컴퓨터공학부"),
            Major(id=20, department_id=10, name="컴퓨터공학전공"),
        ])
        user = User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=10, major_id=20, admission_type="transfer")
        db.add(user)
        db.add(UserAcademicProgram(user_id=1, program_type="primary",
                                   department_id=10, major_id=20, curriculum_year=2026))
        db.add(GraduationRequirement(department_id=10, major_id=20, program_type="primary",
                                     curriculum_year="2026", required_total_credits=133))
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(roadmap)
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이수A", credits=3,
                                   year="2026", semester="1학기", category="전공선택"))
        db.flush()
        return user, roadmap

    def run_chat(self, db, user, roadmap, script, message):
        llm = _ScriptedLLM(script)
        with patch.object(roadmap_chat_mod, "_build_llm", return_value=llm), \
                patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = run_roadmap_chat(db=db, user=user, roadmap=roadmap, message=message)
        return result, llm

    def test_전체_학기_요청인데_제안을_안_하고_끝내면_되돌린다(self):
        db = self.make_db()
        user, roadmap = self.make_student(db)
        script = [
            [{"name": "finish_response", "args": {"message": "편성 들어갈까요?"}, "id": "c1"}],
            [{"name": "finish_response", "args": {"message": "알겠습니다."}, "id": "c2"}],
        ]
        result, llm = self.run_chat(
            db, user, roadmap, script, "졸업까지 로드맵 짜줘")

        # 첫 finish가 되돌려져서 LLM이 한 번 더 불렸다.
        self.assertEqual(2, llm.calls_made)
        self.assertEqual("알겠습니다.", result["reply"])

    def test_되돌림은_턴당_한_번뿐이다(self):
        """무한루프 방지. 후보가 정말 없으면 두 번째 finish는 그대로 통과해야 한다."""
        db = self.make_db()
        user, roadmap = self.make_student(db)
        script = [
            [{"name": "finish_response", "args": {"message": "첫 시도"}, "id": "c1"}],
            [{"name": "finish_response", "args": {"message": "두 번째 시도"}, "id": "c2"}],
        ]
        result, llm = self.run_chat(
            db, user, roadmap, script, "졸업까지 로드맵 짜줘")

        self.assertEqual(2, llm.calls_made, "세 번 불렸다면 되돌림이 두 번 걸린 것이다")
        self.assertEqual("두 번째 시도", result["reply"])

    def test_예산이_얼마_안_남았으면_되돌리지_않는다(self):
        """`_FINISH_GATE_RESERVE`의 존재 이유. 되돌려도 채울 여유가 없으면 답을 내보낸다."""
        db = self.make_db()
        user, roadmap = self.make_student(db)
        reserve = roadmap_chat_mod._FINISH_GATE_RESERVE
        budget = roadmap_chat_mod.MAX_TOOL_ITERATIONS - reserve
        # 게이트가 안 걸릴 때까지 get_roadmap_items로 예산을 태운다.
        script = [
            [{"name": "get_roadmap_items", "args": {}, "id": f"w{i}"}]
            for i in range(budget)
        ]
        script.append(
            [{"name": "finish_response", "args": {"message": "예산 소진"}, "id": "fin"}])
        result, llm = self.run_chat(
            db, user, roadmap, script, "졸업까지 로드맵 짜줘")

        self.assertEqual(budget + 1, llm.calls_made, "되돌림이 걸렸다면 한 번 더 불렸을 것")
        self.assertEqual("예산 소진", result["reply"])

    def test_남은_학기가_없으면_게이트가_걸리지_않는다(self):
        """"remaining_terms에 있는 학기별로 채워라"가 실행 불가능한 지시가 된다.

        이수기록이 없으면 남은 학기 목록이 빈다(근거 없이 지어내지 않는다). 그 상태로
        되돌리면 LLM은 채울 학기를 모르는 채 한 왕복을 버린다.
        """
        db = self.make_db()
        # 이수기록 없는 학생 — make_student가 넣는 기록을 지운다.
        user, roadmap = self.make_student(db)
        db.query(StudentCourseRecord).delete()
        db.flush()

        script = [
            [{"name": "finish_response", "args": {"message": "성적표를 먼저 올려주세요."}, "id": "c1"}],
        ]
        result, llm = self.run_chat(db, user, roadmap, script, "졸업까지 로드맵 짜줘")

        self.assertEqual(1, llm.calls_made, "되돌림이 걸렸다면 두 번 불렸을 것")
        self.assertEqual("성적표를 먼저 올려주세요.", result["reply"])

    def test_이수구분_잔여가_0인데_되돌릴_때_0학점_미배정이라고_하지_않는다(self):
        """총학점만 남았거나 요건을 모를 때도 게이트가 걸린다. 그때 이수구분 문구를
        그대로 쓰면 "아직 0학점이 미배정이다()"라는 자가당착 지시가 나간다 — 되돌림은
        finish를 막는 가장 강한 신호인데 도구 자신의 next_action과 반대말을 하게 된다.
        """
        db = self.make_db()
        user, roadmap = self.make_student(db)
        # 이수구분 잔여는 0이고 총학점만 남은 사범대형 + 빈 학기 없음(else 분기로 간다)
        db.query(GraduationRequirement).delete()
        db.add(GraduationRequirement(
            department_id=10, major_id=20, program_type="primary",
            curriculum_year="2026", required_total_credits=60, required_major_elective=3))
        for i, (y, sem, g) in enumerate(
                [("2026", "2학기", 3), ("2027", "1학기", 4), ("2027", "2학기", 4)]):
            db.add(CourseRoadmapItem(
                id=900 + i, roadmap_id=1, course_name=f"기존{i}", credits=3.0,
                planned_year=y, planned_semester=sem, planned_grade=g, status="planned"))
        db.add(Course(id=910, course_name="마지막전선", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="1,2"))
        db.flush()

        script = [
            [{"name": "propose_term_plan", "args": {
                "reason": "계획", "terms": [{
                    "planned_year": "2026", "planned_semester": "2학기",
                    "planned_grade": 3, "course_ids": [910]}]}, "id": "c1"}],
            [{"name": "finish_response", "args": {"message": "1차"}, "id": "c2"}],
            [{"name": "finish_response", "args": {"message": "2차"}, "id": "c3"}],
        ]
        result, llm = self.run_chat(db, user, roadmap, script, "졸업까지 로드맵 짜줘")

        self.assertEqual(3, llm.calls_made, "총학점이 남았는데 되돌리지 않았다")
        self.assertEqual("2차", result["reply"])

        gate = [m for m in llm.tool_messages if "delivered" in m and "false" in m.lower()]
        self.assertTrue(gate, "되돌림 메시지를 못 찾았다")
        text = " ".join(gate)
        self.assertIn("총 이수학점", text)
        self.assertNotIn("0학점이 미배정", text)

    def test_요건을_모를_때_되돌리는_문구도_0학점_미배정이_아니다(self):
        """요건미상 경로도 `unmet_categories=[]`라 같은 자가당착에 걸린다.

        "총학점만 남음" 경로만 고정하면 이쪽은 열려 있다.
        """
        db = self.make_db()
        user, roadmap = self.make_student(db)
        db.query(GraduationRequirement).delete()  # 요건 기준을 모르는 상태
        for i, (y, sem, g) in enumerate(
                [("2026", "2학기", 3), ("2027", "1학기", 4), ("2027", "2학기", 4)]):
            db.add(CourseRoadmapItem(
                id=930 + i, roadmap_id=1, course_name=f"기존{i}", credits=3.0,
                planned_year=y, planned_semester=sem, planned_grade=g, status="planned"))
        db.add(Course(id=940, course_name="아무전선", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="1,2"))
        db.flush()

        script = [
            [{"name": "propose_term_plan", "args": {
                "reason": "계획", "terms": [{
                    "planned_year": "2026", "planned_semester": "2학기",
                    "planned_grade": 3, "course_ids": [940]}]}, "id": "c1"}],
            [{"name": "finish_response", "args": {"message": "1차"}, "id": "c2"}],
            [{"name": "finish_response", "args": {"message": "2차"}, "id": "c3"}],
        ]
        result, llm = self.run_chat(db, user, roadmap, script, "졸업까지 로드맵 짜줘")

        self.assertEqual(3, llm.calls_made)
        gate = [m for m in llm.tool_messages if "delivered" in m and "false" in m.lower()]
        text = " ".join(gate)
        self.assertIn("확인할 수 없", text)
        self.assertNotIn("0학점이 미배정", text)

    def test_좁은_요청에는_게이트가_걸리지_않는다(self):
        """"다음 학기만" 요청에 "나머지 학기도 채워라"라고 되돌리면 안 된다.

        plan_gap의 empty_terms는 사용자가 요청한 학기가 아니라 남은 학기 **전부**를
        보므로, expects_term_plan 가드가 없으면 여기서 걸린다.
        """
        db = self.make_db()
        user, roadmap = self.make_student(db)
        db.add(Course(id=900, course_name="다음학기과목", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="3", semester="2"))
        db.flush()
        script = [
            [{"name": "propose_term_plan", "args": {
                "reason": "다음 학기",
                "terms": [{"planned_year": "2026", "planned_semester": "2학기",
                           "planned_grade": 3, "course_ids": [900]}],
            }, "id": "c1"}],
            [{"name": "finish_response", "args": {"message": "다음 학기만 짰어요."}, "id": "c2"}],
        ]
        result, llm = self.run_chat(
            db, user, roadmap, script, "다음 학기만 짜줘")

        self.assertEqual(2, llm.calls_made, "좁은 요청인데 되돌림이 걸렸다")
        self.assertEqual("다음 학기만 짰어요.", result["reply"])


class RemainingTermsEdgeCaseTest(unittest.TestCase):
    """이수기록이 없는 학생에게 남은 학기를 지어내면 안 된다."""

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def test_이수기록이_없으면_남은_학기를_지어내지_않는다(self):
        """`project_curriculum_term`은 기록이 없으면 매번 "이번이 첫 학기"라고 답한다.

        학년이 전진하지 않으므로 그대로 두면 상한(8)이 잘라줄 때까지 **같은 학기가
        8개** 쌓이고, LLM은 "2030년 1학기(1학년)"를 계획하라는 지시를 받는다.
        """
        db = self.make_db()
        db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=10, major_id=20))
        db.flush()

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            terms = roadmap_chat_mod._remaining_terms_until_graduation(db, 1)

        self.assertEqual([], terms)

    def test_이수기록이_있으면_학기가_전진한다(self):
        """위 수정이 "항상 빈 목록"이 되면 안 된다."""
        db = self.make_db()
        db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=10, major_id=20, admission_type="transfer"))
        db.add(StudentCourseRecord(user_id=1, raw_course_name="이수A", credits=3,
                                   year="2026", semester="1학기", category="전공선택"))
        db.flush()

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            terms = roadmap_chat_mod._remaining_terms_until_graduation(db, 1)

        self.assertEqual(
            [("2026", "2학기", 3), ("2027", "1학기", 4), ("2027", "2학기", 4)],
            [(t["planned_year"], t["planned_semester"], t["planned_grade"]) for t in terms],
        )


class AlreadyInPlanTest(unittest.TestCase):
    """중복 재제출이 `rejected`로 새면 LLM이 "다 반려됐다"고 읽는다."""

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_ROADMAP_TEST_TABLES)
        return sessionmaker(bind=engine)()

    def make_ctx(self, db):
        user = User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    department_id=10, major_id=20)
        db.add(user)
        db.add(UserAcademicProgram(user_id=1, program_type="primary",
                                   department_id=10, major_id=20, curriculum_year=2026))
        db.add(GraduationRequirement(department_id=10, major_id=20, program_type="primary",
                                     curriculum_year="2026", required_total_credits=133))
        roadmap = CourseRoadmap(id=1, user_id=1)
        db.add(roadmap)
        db.flush()
        return _ToolContext(db, user, roadmap)

    def test_이미_승인돼_저장된_로드맵_과목도_already_in_plan이다(self):
        """"1턴에 승인 → 2턴에 '졸업까지 마저 짜줘'"가 이 기능의 주 시나리오다.

        그때 DB 항목과의 중복이 rejected로 떨어지면, 고치려던 오독이 그대로 재현된다.
        """
        db = self.make_db()
        ctx = self.make_ctx(db)
        db.add(Course(id=950, course_name="이미담긴과목", department_id=10, major_id=20,
                      category="전공선택", credits=3.0, year="4", semester="1"))
        db.add(CourseRoadmapItem(id=950, roadmap_id=1, course_id=950,
                                 course_name="이미담긴과목", credits=3.0,
                                 planned_year="2027", planned_semester="1학기",
                                 planned_grade=4, status="planned"))
        db.flush()

        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            result = ctx.propose_term_plan(terms=[{
                "planned_year": "2027", "planned_semester": "1학기",
                "planned_grade": 4, "course_ids": [950],
            }], reason="test")

        self.assertEqual(0, result["rejected_count"])
        self.assertEqual(0, result["accepted_count"])
        entry = result["terms"][0]["already_in_plan"][0]
        self.assertEqual(950, entry["course_id"])
        # 안내가 없으면 "다른 학기로 옮겨달라"가 조용한 no-op이 된다.
        self.assertIn("propose_change", entry["note"])


class FullHorizonDetectionBoundaryTest(unittest.TestCase):
    """`_looks_like_full_horizon_request`의 오탐/미탐 경계.

    오탐은 프롬프트 오염에서 끝나지 않는다 — `expects_term_plan=True`가 되어 finish
    게이트가 첫 종료를 되돌리고 "propose_term_plan을 부른 뒤 끝내라"고 강제한다.
    즉 **조회 요청에 묻지도 않은 학기 제안이 승인 대기에 쌓인다.**
    """

    QUERY_ONLY = [
        # 계획 동사의 **수동·서술형**. veto 예외 마커를 어간으로 두면 여기 다 걸린다
        # ("채워"가 "채워져 있는지"에 걸리는 식) — 3차 리뷰가 뚫은 축이다.
        "졸업 로드맵 어떻게 채워져 있는지 보여줘",
        "전체 학기가 어떻게 채워져 있는지 확인해줘",
        "남은 학기 전부 편성이 끝났는지 확인해줘",
        "졸업 로드맵이 어떻게 설계돼 있는지 보여줘",
        "전체 로드맵에 뭐가 채워져 있는지만 정리해줘",
        "4학년까지 계획해둔 과목 알려줘",
        "졸업까지 계획 세워져 있는지 확인해줘",
        "졸업 로드맵 지금 어떻게 돼 있어?",
        "졸업까지 계획 잘 세워져 있는지 확인만 해줘",
        "이전 학기 계획 어떻게 됐지?",
        "직전 학기 수강계획 보여줘",
        "4학년까지 내가 뭘 들었는지 알려줘",
        "졸업 전에 인턴 계획 있는데 조언해줘",
        "졸업까지 몇 학점 남았는지 계획 대비 알려줘",
        "졸업까지 뭐가 남았는지 정리해줘",
        "졸업 요건 알려줘",
    ]
    PLANNING = [
        "졸업까지 로드맵 짜줘",
        "남은 학기 전부 계획해줘",
        "4학년 2학기까지 어떻게 들어야 해?",
        "졸업 로드맵 짜줘",
        "전체 로드맵 편성해줘",
        "남은 학기 다 채워줘",
        "졸업할 때까지 수강 순서 설계해줘",
    ]

    def test_조회성_요청은_전체계획으로_보지_않는다(self):
        for message in self.QUERY_ONLY:
            with self.subTest(message=message):
                self.assertFalse(
                    roadmap_chat_mod._looks_like_full_horizon_request(message))

    def test_계획_요청은_전체계획으로_본다(self):
        for message in self.PLANNING:
            with self.subTest(message=message):
                self.assertTrue(
                    roadmap_chat_mod._looks_like_full_horizon_request(message))

    def test_범위표현이_의도단어를_품고_있어도_AND가_유지된다(self):
        """`졸업 로드맵`/`전체 로드맵`/`남은 학기 계획`은 그 자체가 의도 단어를 품는다.

        문장 전체에서 의도를 찾으면 이 마커들에 대해 "둘 다 있어야 한다"가 무의미해진다.
        """
        for scope in ("졸업 로드맵", "전체 로드맵", "남은 학기 계획"):
            with self.subTest(scope=scope):
                self.assertFalse(
                    roadmap_chat_mod._looks_like_full_horizon_request(f"{scope} 어떻게 되어 있어?"))
                self.assertTrue(
                    roadmap_chat_mod._looks_like_full_horizon_request(f"{scope} 짜줘"))

    def test_계획_동사가_있으면_조회_표현이_섞여도_계획_요청이다(self):
        """`짜서 알려줘`처럼 "만들어서 보여줘"가 자연스러운 한국어다.

        조회 표현만 보고 무조건 veto하면 이 기능이 고치려던 증상(다음 한 학기만 제안하고
        끝냄)으로 그대로 돌아간다.
        """
        for message in (
            "졸업까지 어떻게 들어야 할지 짜서 알려줘",
            "졸업까지 로드맵 짜서 보여줘",
            "남은 학기 전부 계획 세워서 알려줘",
            "전체 로드맵 짜서 정리해줘",
        ):
            with self.subTest(message=message):
                self.assertTrue(
                    roadmap_chat_mod._looks_like_full_horizon_request(message))

    def test_범위표현만_있고_의도가_없으면_계획_요청이_아니다(self):
        """veto가 아니라 **범위 밖에서 의도 찾기** 로직이 판정하는 자리다.

        조회 표현이 하나도 없어서 veto가 안 걸리므로, 이 문장들은 그 로직만으로 갈린다.
        """
        for message in ("졸업 로드맵", "전체 로드맵", "남은 학기 계획"):
            with self.subTest(message=message):
                self.assertFalse(
                    roadmap_chat_mod._looks_like_full_horizon_request(message))

    def test_겹치는_범위표현에서도_의도를_찾는다(self):
        """`남은 학기 계획` ⊗ `앞으로 남은 학기`가 겹친다. 한꺼번에 지우면 그 사이의
        의도 단어까지 사라져서 결과가 마커 선언 순서에 좌우된다."""
        self.assertTrue(
            roadmap_chat_mod._looks_like_full_horizon_request("앞으로 남은 학기 계획 좀"))

    def test_이전_직전_학기는_전체_학기가_아니다(self):
        """`전 학기`가 `이전학기`/`직전학기`의 부분문자열이라 걸리던 것."""
        for message in ("이전 학기 계획 짜줘", "직전 학기 수강계획 편성해줘"):
            with self.subTest(message=message):
                self.assertFalse(
                    roadmap_chat_mod._looks_like_full_horizon_request(message))
