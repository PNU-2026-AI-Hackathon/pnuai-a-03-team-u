"""시간표 "과목 추가"의 개설 강좌 검색(GET /courses/offerings).

## 왜 이 테스트가 있는가 — 2026-08-20 사고

시간표 화면에서 갈래를 "전공"으로 고르고 전공기초/전공필수/전공선택 칩을 눌러도
과목이 하나도 안 떴다. 원인은 두 가지였다.

1. 프론트가 "학부만 고르고 전공을 안 골랐다"를 `major_unassigned=true`로 보냈고,
   서버는 `courses.major_id IS NULL`인 과목만 돌려줬다. 그런데 정보컴퓨터공학부
   (department_id=108)는 소속 과목 170건이 전부 세부전공(디자인테크놀로지/인공지능/
   컴퓨터공학)에 배정돼 있어 `major_id IS NULL`이 0건이다 — 학부를 고른 순간
   목록이 통째로 비었다. 2026-2학기 전공 개설이 있는 학부 105곳 중 **4곳이 전멸**했고,
   일부라도 잘린 곳이 13곳, 나머지 92곳(88%)은 영향이 없었다
   (일부 손실 예: 첨단융합학부 108건 중 26건만 남음).
   → `major_unassigned`를 없애고, 전공 미선택이면 그 학부의 모든 전공을 함께 보여준다.

2. 그러면 여러 전공 과목이 한 목록에 섞이므로, 어느 전공 과목인지 줄마다 알려야
   "엉뚱한 게 섞였다"로 보이지 않는다 → 결과에 `major_name`을 실어 보낸다.

`limit` 상한(le=500)도 여기서 지킨다. 프론트가 60으로 자르던 탓에 학부 전체 전공
(음악학과 368건)·효원핵심교양(349건)이 과목명 순으로 조용히 잘려나갔다.
"""

import datetime
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.courses import search_offerings
from app.core.db import Base
from app.domains.academics.models import College, Department, Major, ProgramCourse, School
from app.domains.courses.models import Course, CourseOffering, CourseTime
from app.domains.users.models import User


class OfferingSearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            cls.engine,
            tables=[
                School.__table__,
                College.__table__,
                Department.__table__,
                Major.__table__,
                ProgramCourse.__table__,
                Course.__table__,
                CourseOffering.__table__,
                CourseTime.__table__,
            ],
        )

    def setUp(self):
        self.db = Session(self.engine)
        for model in (CourseTime, CourseOffering, ProgramCourse, Course, Major, Department, College, School):
            self.db.query(model).delete()
        self.db.commit()

        self.db.add(School(id=1, name="부산대학교"))
        self.db.flush()
        self.db.add(College(id=1, school_id=1, name="정보의생명공학대학"))
        self.db.add_all([
            # 실제 108번 학부처럼 모든 과목이 세부전공에 배정된 학부
            Department(id=108, name="정보컴퓨터공학부", college_id=1),
            Department(id=200, name="학부공통있는학부", college_id=1),
            Department(id=300, name="핀테크융합전공", college_id=1),
        ])
        self.db.add_all([
            Major(id=36, name="컴퓨터공학전공", department_id=108),
            Major(id=35, name="인공지능전공", department_id=108),
        ])
        self.db.add_all([
            Course(id=1, course_code="CB1501019", course_name="자료구조",
                   department_id=108, major_id=36, category="전공필수", credits=3),
            Course(id=2, course_code="CB1501022", course_name="컴퓨터구조",
                   department_id=108, major_id=36, category="전공필수", credits=3),
            Course(id=3, course_code="CA2001142", course_name="공학선형대수학",
                   department_id=108, major_id=35, category="전공필수", credits=3),
            Course(id=4, course_code="CB1501005", course_name="일반물리학",
                   department_id=108, major_id=36, category="전공기초", credits=3),
            Course(id=5, course_code="CB2001125", course_name="캡스톤디자인",
                   department_id=108, major_id=36, category="전공선택", credits=3),
            # 전공 미지정(학부 공통) 과목이 있는 학부 — 대조군
            Course(id=6, course_code="ZZ0000001", course_name="학부공통과목",
                   department_id=200, major_id=None, category="전공필수", credits=3),
            # 효원균형·창의교양 세부영역 필터 검증용. 실 서비스에서 "효원균형·창의교양"
            # 갈래 하나가 300건대로 뭉쳐 나와(2026-2학기 357건) 세부영역으로 좁히는
            # 필터를 추가했다 — 사용자 관찰.
            Course(id=8, course_code="ZF0000001", course_name="서양철학사",
                   department_id=None, major_id=None, category="효원균형교양",
                   general_education_area="사상과역사", credits=3),
            Course(id=9, course_code="ZF0000002", course_name="현대사회의이해",
                   department_id=None, major_id=None, category="효원균형교양",
                   general_education_area="사회와문화", credits=3),
            Course(id=10, course_code="ZF0000003", course_name="영역미지정균형교양",
                   department_id=None, major_id=None, category="효원균형교양",
                   general_education_area=None, credits=3),
            # 핀테크 자체 개설 과목은 둘뿐이지만, 컴퓨터공학전공 실제 개설 과목도
            # program_courses로 교차인정한다.
            Course(id=11, course_code="FC0000001", course_name="핀테크세미나",
                   department_id=300, major_id=None, category="전공선택", credits=3),
        ])
        self.db.flush()
        for course_id in (1, 2, 3, 4, 5, 6, 8, 9, 10, 11):
            self.db.add(CourseOffering(id=course_id, course_id=course_id,
                                       year="2026", semester="2학기", section="001",
                                       professor="교수"))
        self.db.flush()
        self.db.add(CourseTime(id=1, offering_id=1, day_of_week="월",
                               start_time=datetime.time(10, 0), end_time=datetime.time(11, 15),
                               classroom="6-201"))
        # 다음 학기 개설은 없어야 한다 — 학기 필터가 실제로 도는지 확인용
        self.db.add(Course(id=7, course_code="CB9999999", course_name="다음학기과목",
                           department_id=108, major_id=36, category="전공필수", credits=3))
        self.db.flush()
        self.db.add(CourseOffering(id=7, course_id=7, year="2026", semester="1학기",
                                   section="001", professor="교수"))
        self.db.add(ProgramCourse(
            department_id=300, major_id=None, course_id=1,
            requirement_group="핀테크융합전공 교차인정과목",
            category="전공필수", curriculum_year="2026",
        ))
        self.db.commit()

        self.user = User(id=1, email="probe@pusan.ac.kr", password_hash="x", name="테스트",
                         student_id="000000000", department_id=108, major_id=36)

    def tearDown(self):
        self.db.close()

    def _search(self, **kwargs):
        # category 기본값은 FastAPI의 Query(None) 객체라, 함수를 직접 부를 때는
        # 명시적으로 None을 넘겨야 한다(conftest 주석의 직접 호출 관행과 같은 사정).
        params = {
            "year": "2026",
            "semester": "2학기",
            "category": None,
            "general_education_area": None,
            "limit": 50,
            "current_user": self.user,
            "db": self.db,
        }
        params.update(kwargs)
        return search_offerings(**params)

    def _names(self, **kwargs):
        return sorted(row.course_name for row in self._search(**kwargs))

    def test_옛_major_unassigned를_보내도_학부_전공이_비지_않는다(self):
        """**이 PR의 헤드라인 회귀.**

        독립 리뷰(2026-08-20)가 잡았다 — `courses.py`를 수정 전으로 통째로 되돌려도
        버그 이름을 딴 테스트들이 그냥 통과했다. 서버 기본값이 `major_unassigned=False`
        였으므로 **그 인자를 안 넘기는 테스트는 수정 전후를 구분하지 못한다.**
        실제 0건 버그는 프론트가 `true`를 보낸 경로였는데 그걸 태우는 테스트가 없었다.

        프론트에는 테스트 러너가 아예 없고(package.json에 test 스크립트 없음), 캐시된
        옛 번들이 계속 이 값을 보낼 수도 있으므로 이 계약은 백엔드에서 지킨다.
        """
        # 파라미터 자체가 사라졌으므로 지금은 시그니처에 없다 — 있으면 회귀다.
        import inspect

        self.assertNotIn(
            "major_unassigned", inspect.signature(search_offerings).parameters,
            "major_unassigned가 되살아나면 학부만 고른 사용자에게 목록이 통째로 빈다 "
            "(정보컴퓨터공학부는 major_id IS NULL이 0건).",
        )
        # 그리고 실제 결과가 학부 전체 전공을 담는지.
        self.assertEqual(
            ["공학선형대수학", "일반물리학", "자료구조", "캡스톤디자인", "컴퓨터구조"],
            self._names(department_id=108),
        )

    def test_limit이_실제로_결과를_자른다(self):
        """상한을 시그니처로만 검사하고 있었다 — `.limit(limit)` 호출을 통째로
        지워도 10건이 전부 통과했다(독립 리뷰 변이 M10). "조용한 절삭 금지"가
        이 PR의 주장인데 절삭 자체는 안 묶여 있었다."""
        self.assertEqual(2, len(self._search(department_id=108, limit=2)))

    def test_학부만_고르면_그_학부의_모든_전공_과목이_나온다(self):
        """예전에는 전공 미지정 과목만 줘서 이 학부는 목록이 통째로 비었다."""
        self.assertEqual(
            ["공학선형대수학", "일반물리학", "자료구조", "캡스톤디자인", "컴퓨터구조"],
            self._names(department_id=108),
        )

    def test_학부_전공필수_칩이_비지_않는다(self):
        """전공필수/전공기초/전공선택 칩을 눌렀을 때가 정확히 안 뜨던 상황이다."""
        self.assertEqual(
            ["공학선형대수학", "자료구조", "컴퓨터구조"],
            self._names(department_id=108, category=["전공필수"]),
        )
        self.assertEqual(["일반물리학"], self._names(department_id=108, category=["전공기초"]))
        self.assertEqual(["캡스톤디자인"], self._names(department_id=108, category=["전공선택"]))

    def test_균형교양_세부영역으로_좁히면_그_영역_과목만_남는다(self):
        self.assertEqual(
            ["서양철학사"],
            self._names(department_id=None, category=["효원균형교양"],
                        general_education_area=["사상과역사"]),
        )
        self.assertEqual(
            ["현대사회의이해"],
            self._names(department_id=None, category=["효원균형교양"],
                        general_education_area=["사회와문화"]),
        )

    def test_균형교양_세부영역_여러_개를_고르면_합집합이_나온다(self):
        """"최소 2개 영역에서 2과목" 같은 요건은 영역을 하나로만 좁히면 후보를
        못 찾는다 — 여러 개를 동시에 골라 OR로 훑을 수 있어야 한다."""
        self.assertEqual(
            ["서양철학사", "현대사회의이해"],
            self._names(department_id=None, category=["효원균형교양"],
                        general_education_area=["사상과역사", "사회와문화"]),
        )

    def test_세부영역_미지정이면_영역_섞인_전체가_그대로_나온다(self):
        """필터를 안 주면(기존 동작 유지) 영역 없는 과목도 함께 나와야 한다 —
        신규 파라미터가 옵트인이어야지, 있는 걸 조용히 걸러내면 안 된다."""
        self.assertEqual(
            ["서양철학사", "영역미지정균형교양", "현대사회의이해"],
            self._names(department_id=None, category=["효원균형교양"]),
        )

    def test_전공을_고르면_그_전공_과목만_남는다(self):
        self.assertEqual(
            ["자료구조", "컴퓨터구조"],
            self._names(department_id=108, major="컴퓨터공학전공", category=["전공필수"]),
        )

    def test_융합전공은_공식_교차인정_타학과_개설도_보인다(self):
        """핀테크 화면이 자체 개설 2건만 보여주지 않아야 한다."""
        self.assertEqual(
            ["자료구조", "핀테크세미나"],
            self._names(department_id=300),
        )

    def test_전공_한_갈래는_기초_필수_선택을_모두_훑는다(self):
        """화면의 '전공 전체'는 category=전공 하나로 부분 일치시켜 보낸다."""
        self.assertEqual(5, len(self._search(department_id=108, category=["전공"])))

    def test_학부_전체_결과에_전공_이름이_실린다(self):
        """여러 전공이 한 목록에 섞이므로 줄마다 소속 전공을 밝혀야 한다."""
        by_name = {row.course_name: row.major_name for row in self._search(department_id=108)}
        self.assertEqual("컴퓨터공학전공", by_name["자료구조"])
        self.assertEqual("인공지능전공", by_name["공학선형대수학"])

    def test_전공_미지정_과목은_major_name이_비어있다(self):
        rows = self._search(department_id=200)
        self.assertEqual(["학부공통과목"], [row.course_name for row in rows])
        self.assertIsNone(rows[0].major_name)

    def test_다른_학기_개설은_섞이지_않는다(self):
        self.assertNotIn("다음학기과목", self._names(department_id=108))

    def test_없는_전공_이름은_빈_결과다(self):
        """조건을 조용히 무시하면 엉뚱한 전공 과목까지 섞여 나온다."""
        self.assertEqual([], self._search(department_id=108, major="없는전공"))

    def test_시간_정보가_함께_실린다(self):
        row = next(r for r in self._search(department_id=108) if r.course_name == "자료구조")
        self.assertEqual(1, len(row.times))
        self.assertEqual(("월", "10:00", "11:15"),
                         (row.times[0].day_of_week, row.times[0].start_time, row.times[0].end_time))


class OfferingSearchLimitTest(unittest.TestCase):
    """limit은 상한이 있어야 한다 — 실수로 큰 값이 오면 전 학기 개설을 통째로 내보낸다."""

    def test_limit_상한이_라우트_시그니처에_박혀있다(self):
        import inspect

        default = inspect.signature(search_offerings).parameters["limit"].default
        bounds = {type(item).__name__: item for item in default.metadata}
        self.assertEqual(500, bounds["Le"].le)
        self.assertEqual(1, bounds["Ge"].ge)


if __name__ == "__main__":
    unittest.main()
