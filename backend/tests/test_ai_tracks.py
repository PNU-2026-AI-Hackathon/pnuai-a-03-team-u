"""AI융합트랙 판별 + 로드맵 챗 조회 도구.

트랙은 `graduation_requirements`에 program_type='interdisciplinary'로 들어가는데,
그 유형에는 정식 연계전공(42·48학점)과 복수전공(36학점)도 섞인다. 총학점 21과
special_rules.certification_type을 **함께** 봐야 트랙만 골라진다.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domains.academics.models import (
    College, Department, GraduationRequirement, Major, ProgramCourse, School,
    UserAcademicProgram,
)
from app.domains.academics.tracks import (
    find_ai_tracks_for_department, is_ai_track, track_scope_major_ids,
)
from app.domains.courses.models import Course, CourseOffering
from app.domains.planning.models import CourseRoadmap
from app.domains.planning.roadmap_chat import _ToolContext
from app.domains.users.models import User

_TRACK_RULES = {
    "certification_type": "AI융합트랙",
    "not_graduation_requirement": True,
    "dept_credits": {"min": 15, "max": 15},
    "ai_common_credits": {"min": 6, "max": 6},
}

_TABLES = [
    School.__table__, College.__table__, Department.__table__, Major.__table__,
    User.__table__, UserAcademicProgram.__table__, GraduationRequirement.__table__,
    CourseRoadmap.__table__, Course.__table__, CourseOffering.__table__,
    ProgramCourse.__table__,
]


class AiTrackDetectionTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        for t in _TABLES:
            t.create(engine)
        self.db = sessionmaker(bind=engine, autoflush=False)()
        self.db.add(School(id=1, name="부산대학교")); self.db.flush()
        self.db.add(College(id=1, school_id=1, name="사회과학대학")); self.db.flush()
        self.db.add_all([
            Department(id=18, college_id=1, name="심리학과"),
            Department(id=108, college_id=1, name="정보컴퓨터공학부"),
        ])
        self.db.flush()
        self.db.add_all([
            Major(id=66, department_id=18, name="심리데이터사이언스(SW융합트랙)"),
            Major(id=76, department_id=18, name="산업수학SW(SW연계전공)"),
            User(id=1, email="t@example.com", password_hash="x", name="학생", department_id=18),
        ])
        self.db.add_all([
            # 진짜 트랙
            GraduationRequirement(
                id=271, department_id=18, major_id=66, program_type="interdisciplinary",
                required_total_credits=21, special_rules=_TRACK_RULES,
            ),
            # 연계전공 — 21학점이 아니라 걸러진다
            GraduationRequirement(
                id=281, department_id=18, major_id=76, program_type="interdisciplinary",
                required_total_credits=48, special_rules={"notes": "SW융합 라벨 자동 파싱"},
            ),
            # 21학점이지만 certification_type이 없다 — 걸러진다
            GraduationRequirement(
                id=999, department_id=18, major_id=None, program_type="interdisciplinary",
                required_total_credits=21, special_rules={"notes": "부전공류"},
            ),
        ])
        self.db.flush()

    def tearDown(self):
        self.db.close()

    def test_총학점과_인증유형을_함께_봐야_트랙만_남는다(self):
        found = find_ai_tracks_for_department(self.db, 18)
        self.assertEqual([271], [gr.id for gr in found])

    def test_대상_학과가_아니면_빈_목록(self):
        """정보컴퓨터공학부처럼 SW 학과는 트랙 대상이 아니다."""
        self.assertEqual([], find_ai_tracks_for_department(self.db, 108))

    def test_학과가_없으면_빈_목록(self):
        self.assertEqual([], find_ai_tracks_for_department(self.db, None))

    def test_is_ai_track는_인증유형만_본다(self):
        self.assertTrue(is_ai_track(self.db.get(GraduationRequirement, 271)))
        self.assertFalse(is_ai_track(self.db.get(GraduationRequirement, 281)))


class TrackMajorScopeTest(unittest.TestCase):
    """한 학부 아래 여러 전공이 있고 트랙이 그중 한 전공 대상일 때
    (바이오메디컬디바이스&데이터 트랙 = 의생명융합공학부지만 의생명공학전공 대상),
    형제 전공 학생에게는 안 뜬다."""

    def setUp(self):
        engine = create_engine("sqlite://")
        for t in _TABLES:
            t.create(engine)
        self.db = sessionmaker(bind=engine, autoflush=False)()
        self.db.add(School(id=1, name="부산대학교")); self.db.flush()
        self.db.add(College(id=1, school_id=1, name="공과대학")); self.db.flush()
        self.db.add(Department(id=1, college_id=1, name="의생명융합공학부"))
        self.db.add(Department(id=118, college_id=1, name="소프트웨어융합교육원"))
        self.db.flush()
        self.db.add_all([
            Major(id=1, department_id=1, name="데이터사이언스전공"),
            Major(id=33, department_id=1, name="의생명공학전공"),
            Major(id=73, department_id=1, name="바이오메디컬디바이스&데이터(SW융합트랙)"),
        ])
        self.db.flush()
        self.db.add(GraduationRequirement(
            id=278, department_id=1, major_id=73, program_type="interdisciplinary",
            required_total_credits=21, special_rules=_TRACK_RULES,
        ))
        # 학과전공과목 = 의생명공학전공(33) 과목 / SW공통 = 소프트웨어융합교육원 개설
        self.db.add_all([
            Course(id=6069, course_name="바이오센서공학", department_id=1, major_id=33, credits=3),
            Course(id=6051, course_name="회로이론", department_id=1, major_id=33, credits=3),
            Course(id=6605, course_name="생체고체역학", department_id=1, major_id=None, credits=3),
            Course(id=6512, course_name="데이터분석입문", department_id=118, major_id=None, credits=3),
        ])
        self.db.flush()
        for cid in (6069, 6051, 6605, 6512):
            self.db.add(ProgramCourse(department_id=1, major_id=73, course_id=cid))
        self.db.flush()

    def tearDown(self):
        self.db.close()

    def test_scope는_학부개설_전공지정_과목의_전공id만(self):
        # 6069·6051 → {33}. 6605(전공 미지정)·6512(타 학과 개설)는 제외.
        self.assertEqual(
            {33}, track_scope_major_ids(self.db, self.db.get(GraduationRequirement, 278))
        )

    def test_대상_전공_학생에게는_뜬다(self):
        self.assertEqual([278], [gr.id for gr in find_ai_tracks_for_department(self.db, 1, 33)])

    def test_형제_전공_학생에게는_안_뜬다(self):
        self.assertEqual([], find_ai_tracks_for_department(self.db, 1, 1))

    def test_전공_미지정이면_학과_단위로_판단(self):
        # 회원가입 홍보 카드 등 — major_id 없이 호출하면 종전대로 학과 단위.
        self.assertEqual([278], [gr.id for gr in find_ai_tracks_for_department(self.db, 1)])

    def test_전공지정_과목이_없는_트랙은_전공제한_없음(self):
        # 학과전공과목이 전부 전공 미지정이면 scope 비어 형제 전공에도 뜬다(종전 동작).
        self.db.query(ProgramCourse).filter_by(course_id=6069).delete()
        self.db.query(ProgramCourse).filter_by(course_id=6051).delete()
        self.db.flush()
        self.assertEqual(set(), track_scope_major_ids(self.db, self.db.get(GraduationRequirement, 278)))
        self.assertEqual([278], [gr.id for gr in find_ai_tracks_for_department(self.db, 1, 1)])


class GetAvailableTracksToolTest(unittest.TestCase):
    """로드맵 챗의 조회 도구.

    프로필 블록(텍스트)에 트랙이 적혀 있는데도 LLM이 "확인된 항목이 없습니다"라고
    답한 사고가 있었다(2026-08-19 실측, 심리학과). 도구로 사실을 확인하는 구조라
    조회 수단이 없는 정보는 "없는 것"으로 기운다.
    """

    def setUp(self):
        engine = create_engine("sqlite://")
        for t in _TABLES:
            t.create(engine)
        self.db = sessionmaker(bind=engine, autoflush=False)()
        self.db.add(School(id=1, name="부산대학교")); self.db.flush()
        self.db.add(College(id=1, school_id=1, name="사회과학대학")); self.db.flush()
        self.db.add_all([
            Department(id=18, college_id=1, name="심리학과"),
            Department(id=108, college_id=1, name="정보컴퓨터공학부"),
        ])
        self.db.flush()
        self.db.add_all([
            Major(id=66, department_id=18, name="심리데이터사이언스(SW융합트랙)"),
            GraduationRequirement(
                id=271, department_id=18, major_id=66, program_type="interdisciplinary",
                required_total_credits=21, special_rules=_TRACK_RULES,
            ),
        ])
        self.db.flush()

    def tearDown(self):
        self.db.close()

    def _ctx(self, department_id):
        user = User(id=1, email="t@example.com", password_hash="x", name="학생",
                    department_id=department_id)
        self.db.add(user)
        self.db.flush()
        roadmap = CourseRoadmap(id=1, user_id=1)
        return _ToolContext(self.db, user, roadmap)

    def test_대상_학과면_트랙과_학점구성을_돌려준다(self):
        result = self._ctx(18).get_available_tracks()
        self.assertEqual(1, len(result["tracks"]))
        track = result["tracks"][0]
        self.assertEqual("심리데이터사이언스(SW융합트랙)", track["track_name"])
        self.assertEqual(21, track["total_credits"])
        self.assertFalse(track["is_enrolled"])
        self.assertIn("졸업요건이 아니라", result["note"])

    def test_대상_학과가_아니면_언급하지_말라고_알려준다(self):
        result = self._ctx(108).get_available_tracks()
        self.assertEqual([], result["tracks"])
        self.assertIn("언급하지 마라", result["note"])

    def test_공통교과목_목록을_함께_돌려준다(self):
        """트랙 학점의 절반 가까이가 공통교과목이라, 목록 없이는 무엇을 담을지 모른다."""
        result = self._ctx(18).get_available_tracks()
        names = [c["course_name"] for group in
                 ("ai_common_can_take_now", "ai_common_not_offered_this_term", "ai_common_not_in_catalog")
                 for c in result[group]]
        self.assertIn("AI리터러시의이해", names)
        self.assertEqual(10, len(names), "10개가 어느 배열에도 빠지지 않고 들어가야 한다")
        self.assertIn("금요일", result["ai_common_scheduling"])

    def test_공통교과목은_일반선택만_매칭한다(self):
        """이름만 맞추면 학과 개설 동명 과목을 집는다(전공선택 '데이터마이닝' 오탐)."""
        self.db.add_all([
            Course(id=900, course_name="데이터 마이닝", category="전공선택", credits=3),
            Course(id=901, course_name="AI리터러시의이해", category="일반선택", credits=3),
        ])
        self.db.flush()
        result = self._ctx(18).get_available_tracks()
        not_in_catalog = [c["course_name"] for c in result["ai_common_not_in_catalog"]]
        self.assertIn("데이터 마이닝", not_in_catalog, "전공선택 동명 과목을 집으면 안 된다")
        self.assertNotIn("AI리터러시의이해", not_in_catalog)

    def test_구명칭으로_적재된_과목도_찾는다(self):
        """수강편람에 'AI활용디지털전환'이 아직 '창의적 프로그래밍'으로 있다."""
        self.db.add(Course(id=902, course_name="창의적프로그래밍", category="일반선택", credits=3))
        self.db.flush()
        result = self._ctx(18).get_available_tracks()
        by_name = {c["course_name"]: c for group in
                   ("ai_common_can_take_now", "ai_common_not_offered_this_term", "ai_common_not_in_catalog")
                   for c in result[group]}
        entry = by_name["AI활용디지털전환"]
        self.assertTrue(entry["in_catalog"])
        self.assertEqual("창의적 프로그래밍", entry["listed_as"])

    def test_카탈로그에_있어도_그_학기에_개설_안됐으면_구분한다(self):
        """카탈로그 존재와 이번 학기 수강 가능은 다르다.

        2026-2학기 실측에서 카탈로그에는 8/10이 있는데 실제 개설은 3개뿐이었다.
        구분하지 않으면 담을 수 없는 과목을 담으라고 안내하게 된다.
        """
        self.db.add_all([
            Course(id=910, course_name="AI리터러시의이해", category="일반선택", credits=3),
            Course(id=911, course_name="데이터리터러시의이해", category="일반선택", credits=3),
        ])
        self.db.flush()
        # 둘 중 하나만 이번 학기에 분반이 열린다.
        self.db.add(CourseOffering(id=1, course_id=911, school="부산대학교",
                                   year="2026", semester="2학기", section="001"))
        self.db.flush()

        from app.domains.academics.tracks import list_ai_common_courses
        by_name = {c["course_name"]: c
                   for c in list_ai_common_courses(self.db, year="2026", semester="2학기")}
        self.assertTrue(by_name["AI리터러시의이해"]["in_catalog"])
        self.assertFalse(by_name["AI리터러시의이해"]["offered_this_term"])
        self.assertTrue(by_name["데이터리터러시의이해"]["offered_this_term"])

    def test_학기를_안주면_개설여부_키가_없다(self):
        """"모르는 것"과 "안 열렸다"를 섞지 않는다."""
        from app.domains.academics.tracks import list_ai_common_courses
        entry = list_ai_common_courses(self.db)[0]
        self.assertNotIn("offered_this_term", entry)

    def test_개설상태별로_배열이_나뉜다(self):
        """한 배열에 플래그로 담아 주면 LLM이 섞는다.

        실측(2026-08-19)에서 "이번 학기 담을 수 있는 과목" 목록에 미개설 과목을 넣고,
        정작 개설된 과목은 "학기마다 다르다"로 분류했다.
        """
        self.db.add_all([
            Course(id=920, course_name="AI리터러시의이해", category="일반선택", credits=3),
            Course(id=921, course_name="데이터리터러시의이해", category="일반선택", credits=3),
        ])
        self.db.flush()
        self.db.add(CourseOffering(id=2, course_id=921, school="부산대학교",
                                   year="2026", semester="2학기", section="001"))
        self.db.flush()

        result = self._ctx(18).get_available_tracks()
        can_now = [c["course_name"] for c in result["ai_common_can_take_now"]]
        not_now = [c["course_name"] for c in result["ai_common_not_offered_this_term"]]
        self.assertIn("데이터리터러시의이해", can_now)
        self.assertNotIn("데이터리터러시의이해", not_now)
        self.assertIn("AI리터러시의이해", not_now)
        self.assertNotIn("AI리터러시의이해", can_now)

    def test_이미_등록했으면_is_enrolled(self):
        ctx = self._ctx(18)
        self.db.add(UserAcademicProgram(
            user_id=1, department_id=18, major_id=66,
            program_type="interdisciplinary", status="active",
        ))
        self.db.flush()
        self.assertTrue(ctx.get_available_tracks()["tracks"][0]["is_enrolled"])


if __name__ == "__main__":
    unittest.main()
