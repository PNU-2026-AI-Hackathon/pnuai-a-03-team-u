import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.domains.academics.models import StudentCourseRecord, StudentCourseSubstitution
from app.domains.courses.models import Course
from app.domains.planning import roadmap_chat as roadmap_chat_mod
from app.domains.planning.history import (
    project_calendar_term,
    project_curriculum_term,
    sync_completed_courses_to_roadmap,
)
from app.domains.planning.models import CourseRoadmap, CourseRoadmapItem
from app.domains.users.models import User


_TABLES = [
    User.__table__,
    Course.__table__,
    StudentCourseRecord.__table__,
    StudentCourseSubstitution.__table__,  # 이수기록을 읽는 경로가 대체 관계를 함께 조회한다
    CourseRoadmap.__table__,
    CourseRoadmapItem.__table__,
]


class SyncCompletedCoursesTest(unittest.TestCase):
    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_TABLES)
        db = sessionmaker(bind=engine)()
        db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트"))
        db.add(CourseRoadmap(id=1, user_id=1))
        db.flush()
        return db

    def test_pre_enrollment_records_keep_their_own_slot(self):
        """입학전성적은 어느 학년에도 속하지 않는 lump-sum이라 학년을 비워 둔다.

        예전에는 3학년 1학기로 못 박았는데, 그러면 편입생이 실제로 이수한 3학년
        1학기와 같은 칸에 합쳐져 버린다. 화면이 "입학 전 인정 학점"을 별도 칸으로
        그리므로 semester 원본을 살려 두는 편이 맞다.
        """
        db = self.make_db()
        db.add_all([
            StudentCourseRecord(user_id=1, raw_course_name="이산수학",
                                 category="전공기초", credits=3, year="2026", semester="입학전성적"),
            StudentCourseRecord(user_id=1, raw_course_name="컴퓨터개론",
                                 category="전공기초", credits=3, year="2026", semester="입학전성적"),
        ])
        db.flush()

        saved = sync_completed_courses_to_roadmap(db, user_id=1, roadmap_id=1)

        self.assertEqual(2, len(saved))
        for item in saved:
            self.assertIsNone(item.planned_grade)
            self.assertEqual("입학전성적", item.planned_semester)
            self.assertEqual("2026", item.planned_year)
            self.assertEqual("completed", item.status)

    def test_regular_semester_records_still_use_relative_rank(self):
        """정규 학기(1학기/2학기) rows는 기존대로 재학 순번 기반 학년 매핑을 유지한다.
        (입학전성적 특수 케이스가 정규 로직을 안 건드리는지 확인)"""
        db = self.make_db()
        db.add_all([
            StudentCourseRecord(user_id=1, raw_course_name="A", category="전공기초",
                                 credits=3, year="2025", semester="1학기"),
            StudentCourseRecord(user_id=1, raw_course_name="B", category="전공기초",
                                 credits=3, year="2025", semester="2학기"),
            StudentCourseRecord(user_id=1, raw_course_name="C", category="전공필수",
                                 credits=3, year="2026", semester="1학기"),
        ])
        db.flush()

        saved = sync_completed_courses_to_roadmap(db, user_id=1, roadmap_id=1)
        by_name = {it.course_name: it for it in saved}

        for name, grade, semester in [("A", 1, "1학기"), ("B", 1, "2학기"), ("C", 2, "1학기")]:
            item = by_name[name]
            self.assertEqual((grade, semester), (item.planned_grade, item.curriculum_semester))
            # 쉬지 않고 다닌 학생은 두 축이 일치한다.
            self.assertEqual(semester, item.planned_semester)

    def test_leave_of_absence_keeps_calendar_and_curriculum_apart(self):
        """휴학한 학기는 재학 순번에서 빠지므로 달력 학기와 커리큘럼 학기가 어긋난다.

        2025-2를 쉰 학생의 2026년 **1학기**는 재학 2번째 학기라 커리큘럼상
        1학년 2학기다. 예전에는 이 커리큘럼 학기를 planned_semester에 그대로
        덮어써서, planned_year와 짝지어 읽으면 다닌 적 없는 "2026년 2학기"가
        됐다 — 성장 로드맵 화면과 DB가 서로 다른 학기를 가리킨 원인.
        """
        db = self.make_db()
        db.add_all([
            StudentCourseRecord(user_id=1, raw_course_name="A", category="전공기초",
                                 credits=3, year="2025", semester="1학기"),
            StudentCourseRecord(user_id=1, raw_course_name="B", category="전공필수",
                                 credits=3, year="2026", semester="1학기"),
        ])
        db.flush()

        by_name = {it.course_name: it
                   for it in sync_completed_courses_to_roadmap(db, user_id=1, roadmap_id=1)}

        self.assertEqual(("2026", "1학기"),
                         (by_name["B"].planned_year, by_name["B"].planned_semester))
        self.assertEqual((1, "2학기"),
                         (by_name["B"].planned_grade, by_name["B"].curriculum_semester))

    def test_seasonal_records_have_no_curriculum_semester(self):
        """계절수업은 학년 슬롯 밖이라 커리큘럼 축이 비고, 달력 축만 남는다."""
        db = self.make_db()
        db.add(StudentCourseRecord(user_id=1, raw_course_name="딥러닝PBL", category="일반선택",
                                    credits=3, year="2026", semester="여름계절수업"))
        db.flush()

        item = sync_completed_courses_to_roadmap(db, user_id=1, roadmap_id=1)[0]

        self.assertEqual(("2026", "여름계절수업"), (item.planned_year, item.planned_semester))
        self.assertIsNone(item.planned_grade)
        self.assertIsNone(item.curriculum_semester)

    def test_transfer_student_first_semester_is_grade_3(self):
        """편입생의 첫 재학 학기는 3학년 1학기다.

        예전에는 재학 순번을 신입생 기준으로만 세서 grade=1로 찍혔고, 입학전성적은
        3학년 1학기로 못 박혀 있어 시간 순서가 뒤집혀 보였다.
        """
        db = self.make_db()
        db.query(User).filter_by(id=1).update({"admission_type": "transfer"})
        db.add_all([
            StudentCourseRecord(user_id=1, raw_course_name="이산수학",
                                 category="전공기초", credits=3, year="2026", semester="입학전성적"),
            StudentCourseRecord(user_id=1, raw_course_name="자료구조",
                                 category="전공필수", credits=3, year="2026", semester="1학기"),
            StudentCourseRecord(user_id=1, raw_course_name="알고리즘",
                                 category="전공필수", credits=3, year="2026", semester="2학기"),
            StudentCourseRecord(user_id=1, raw_course_name="캡스톤",
                                 category="전공필수", credits=3, year="2027", semester="1학기"),
        ])
        db.flush()

        saved = sync_completed_courses_to_roadmap(db, user_id=1, roadmap_id=1)
        by_name = {it.course_name: it for it in saved}

        # 입학 전 인정 학점은 학년 슬롯 밖.
        self.assertIsNone(by_name["이산수학"].planned_grade)
        # 재학 학기는 3학년부터 시작해 두 학기마다 오른다.
        self.assertEqual((3, "1학기"), (by_name["자료구조"].planned_grade, by_name["자료구조"].curriculum_semester))
        self.assertEqual((3, "2학기"), (by_name["알고리즘"].planned_grade, by_name["알고리즘"].curriculum_semester))
        self.assertEqual((4, "1학기"), (by_name["캡스톤"].planned_grade, by_name["캡스톤"].curriculum_semester))

    def test_freshman_with_pre_admission_credits_still_starts_at_grade_1(self):
        """조기이수 인정 학점이 있어도 신입생이면 재학 학기는 1학년부터 센다."""
        db = self.make_db()
        db.add_all([
            StudentCourseRecord(user_id=1, raw_course_name="이산수학",
                                 category="전공기초", credits=3, year="2026", semester="입학전성적"),
            StudentCourseRecord(user_id=1, raw_course_name="자료구조",
                                 category="전공필수", credits=3, year="2026", semester="1학기"),
        ])
        db.flush()

        saved = sync_completed_courses_to_roadmap(db, user_id=1, roadmap_id=1)
        by_name = {it.course_name: it for it in saved}

        self.assertIsNone(by_name["이산수학"].planned_grade)
        self.assertEqual((1, "1학기"), (by_name["자료구조"].planned_grade, by_name["자료구조"].curriculum_semester))


class ProjectCurriculumTermTest(unittest.TestCase):
    """아직 안 다닌 학기의 학년 추정.

    시간표 추천을 로드맵에 반영할 때 planned_grade가 비면, 로드맵 화면이 그
    항목을 학년 슬롯에 못 넣고 "2026년 2학기" 같은 기타 칸으로 떨어뜨린다.
    """

    def make_db(self, admission_type="freshman"):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_TABLES)
        db = sessionmaker(bind=engine)()
        db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트",
                    admission_type=admission_type))
        db.add(CourseRoadmap(id=1, user_id=1))
        db.flush()
        return db

    def _add_terms(self, db, terms):
        for index, (year, semester) in enumerate(terms):
            db.add(StudentCourseRecord(user_id=1, raw_course_name=f"과목{index}",
                                        category="전공필수", credits=3,
                                        year=year, semester=semester))
        db.flush()

    def test_다음_학기는_마지막_등록_학기_뒤로_이어진다(self):
        db = self.make_db()
        self._add_terms(db, [("2025", "1학기"), ("2025", "2학기")])
        # 2학기까지 마쳤으니 다음은 2학년 1학기.
        self.assertEqual((2, "1학기"), project_curriculum_term(db, 1, "2026", "1학기"))

    def test_편입생은_3학년부터_이어진다(self):
        """이 버그를 처음 본 상황. 2025-1학기와 2026-1학기만 다닌 편입생의
        다음 학기(2026-2학기)는 4학년 1학기다."""
        db = self.make_db(admission_type="transfer")
        self._add_terms(db, [("2025", "1학기"), ("2026", "1학기")])
        self.assertEqual((4, "1학기"), project_curriculum_term(db, 1, "2026", "2학기"))

    def test_이미_다닌_학기는_그_순번을_그대로_쓴다(self):
        db = self.make_db()
        self._add_terms(db, [("2025", "1학기"), ("2025", "2학기")])
        self.assertEqual((1, "2학기"), project_curriculum_term(db, 1, "2025", "2학기"))

    def test_이수_기록이_없으면_첫_학기로_본다(self):
        db = self.make_db()
        self.assertEqual((1, "1학기"), project_curriculum_term(db, 1, "2026", "1학기"))
        db_transfer = self.make_db(admission_type="transfer")
        self.assertEqual((3, "1학기"), project_curriculum_term(db_transfer, 1, "2026", "1학기"))

    def test_계절수업은_학년을_매기지_않는다(self):
        """커리큘럼 축으로 환산할 수 없으면 두 값 모두 None이다.

        예전에는 원본 학기를 그대로 돌려줬는데, 호출부가 그걸 커리큘럼 학기로
        믿고 저장하면서 달력 학기가 커리큘럼 컬럼에 섞여 들어갔다.
        """
        db = self.make_db()
        self._add_terms(db, [("2025", "1학기")])
        self.assertEqual((None, None),
                         project_curriculum_term(db, 1, "2025", "여름계절수업"))

    def test_4학년을_넘어가면_비워_둔다(self):
        """졸업 후 학기까지 학년을 붙이면 로드맵에 없는 5학년 슬롯이 생긴다."""
        db = self.make_db()
        self._add_terms(db, [
            ("2022", "1학기"), ("2022", "2학기"), ("2023", "1학기"), ("2023", "2학기"),
            ("2024", "1학기"), ("2024", "2학기"), ("2025", "1학기"), ("2025", "2학기"),
        ])
        self.assertEqual((None, None), project_curriculum_term(db, 1, "2026", "1학기"))

    def test_엇학기_학생은_커리큘럼_학기가_달력과_어긋난다(self):
        """한 학기 휴학한 엇학기 학생의 사례.

        2022-1 신입 → 1-1
        2022-2 → 1-2
        2023-1 → 2-1
        2023-2 → 2-2
        2024-1 → 3-1
        (2024-2 휴학, 기록 없음)
        2025-1 → 3-2 (rank 6)
        2025-2 → 4-1 (rank 7) — 커리큘럼 4-1인데 달력은 2학기!

        다음 달력 학기 2026-1(1학기)의 커리큘럼은 4-2(rank 8)여야 한다.
        엇학기가 정상 반영되면 학생은 여전히 4학년으로 남고 학기만 이동한다.
        """
        db = self.make_db()
        self._add_terms(db, [
            ("2022", "1학기"), ("2022", "2학기"),
            ("2023", "1학기"), ("2023", "2학기"),
            ("2024", "1학기"),
            # 2024-2 휴학 → 기록 없음
            ("2025", "1학기"), ("2025", "2학기"),
        ])
        # 이미 등록한 학기 확인: 2025-2가 커리큘럼 4-1이어야 한다 (달력은 2학기).
        self.assertEqual((4, "1학기"), project_curriculum_term(db, 1, "2025", "2학기"))
        # 다음 달력 학기 2026-1은 커리큘럼 4-2다 (달력은 1학기, 커리큘럼은 2학기).
        self.assertEqual((4, "2학기"), project_curriculum_term(db, 1, "2026", "1학기"))

    def test_커리큘럼_학기를_달력으로_되돌린다(self):
        """로드맵 화면은 커리큘럼 슬롯만 안다 — 달력 학기는 서버가 되돌려야 한다.

        위 엇학기 학생과 같은 이력. 마지막 기록이 2025-2이고 지금이 2026-1이면 공백이
        없으므로(= 지금 재학 중) "4학년 2학기"는 달력상 2026년 1학기다.

        현재 학기를 patch하는 이유: `project_calendar_term`은 휴학 공백 판정에 오늘
        날짜를 쓴다. 고정하지 않으면 9월이 되는 순간 현재 학기가 2026-2로 넘어가면서
        같은 데이터가 "공백 있음"으로 바뀌어 이 테스트가 달력만 보고 깨진다.
        """
        db = self.make_db()
        self._add_terms(db, [
            ("2022", "1학기"), ("2022", "2학기"),
            ("2023", "1학기"), ("2023", "2학기"),
            ("2024", "1학기"),
            ("2025", "1학기"), ("2025", "2학기"),
        ])
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 1)):
            # 이미 등록한 학기는 추정하지 않고 실제 달력값을 돌려준다.
            self.assertEqual(("2025", "2학기"), project_calendar_term(db, 1, 4, "1학기"))
            # 아직 안 다닌 학기는 마지막 등록 학기 뒤로 이어 붙인다.
            self.assertEqual(("2026", "1학기"), project_calendar_term(db, 1, 4, "2학기"))

    def test_계절수업은_달력으로_되돌릴_수_없다(self):
        db = self.make_db()
        self._add_terms(db, [("2025", "1학기")])
        self.assertEqual((None, None), project_calendar_term(db, 1, 1, "여름계절수업"))
        self.assertEqual((None, None), project_calendar_term(db, 1, None, "1학기"))


class ProjectCurriculumTermGapTest(unittest.TestCase):
    """휴학 공백이 있는 학생의 다음 커리큘럼 학기.

    커리큘럼 학년은 달력이 아니라 **재학한 학기 수**로 오른다. 달력 거리로 세면 휴학
    기간만큼 학년이 부풀려지고, 4학년을 넘으면 함수가 None을 돌려줘 **챗이 학년을
    지어낸다** — 골든 케이스 10에서 "다음 학기는 1학년 1학기입니다"로 관측됐다.
    """

    def make_db(self, terms, admission_type="freshman"):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_TABLES)
        db = sessionmaker(bind=engine, autoflush=False)()
        db.add(User(id=1, email="t@x.com", password_hash="x", name="테스트",
                    admission_type=admission_type))
        db.flush()
        for i, (year, sem) in enumerate(terms):
            db.add(StudentCourseRecord(user_id=1, raw_course_name=f"과목{i}",
                                       category="전공선택", credits=3,
                                       year=year, semester=sem))
        db.commit()
        return db

    def project(self, terms, target=("2027", "1학기"), admission_type="freshman"):
        db = self.make_db(terms, admission_type)
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2026, 2)):
            return project_curriculum_term(db, 1, *target)

    def test_gap_does_not_inflate_grade(self):
        """2022 입학, 5학기 이수(→3-1) 후 휴학. 다음 재학 학기는 3-2다."""
        terms = [("2022", "1학기"), ("2022", "2학기"),
                 ("2023", "1학기"), ("2023", "2학기"), ("2024", "1학기")]
        self.assertEqual((3, "2학기"), self.project(terms))

    def test_continuous_student_uses_calendar_distance(self):
        """공백이 없으면 현재 학기도 재학 중이므로 달력 거리가 맞다.

        5학기 이수(마지막 2026-1) + 지금 2026-2 재학 중 → 다음 2027-1은 7번째 = 4-1.
        """
        terms = [("2024", "1학기"), ("2024", "2학기"),
                 ("2025", "1학기"), ("2025", "2학기"), ("2026", "1학기")]
        self.assertEqual((4, "1학기"), self.project(terms))

    def test_no_records_starts_at_first_term(self):
        self.assertEqual((1, "1학기"), self.project([]))

    def test_transfer_student_starts_at_third_grade(self):
        self.assertEqual((3, "1학기"), self.project([], admission_type="transfer"))

    def test_long_gap_still_within_grade_range(self):
        """공백이 아무리 길어도 학년은 재학 학기 수로만 오른다 (None이 되면 안 된다)."""
        terms = [("2018", "1학기"), ("2018", "2학기")]
        grade, semester = self.project(terms)
        self.assertEqual((2, "1학기"), (grade, semester))


class CalendarTermRoundTripTest(unittest.TestCase):
    """`project_curriculum_term`과 `project_calendar_term`은 서로의 역함수여야 한다.

    한쪽만 휴학 공백을 반영하면 역방향이 **학생이 다니지 않은 과거 학기**를 돌려준다.
    실제로 그랬다: 아래 학생에게 정방향은 2027-1학기 → 3학년 2학기를 주는데, 역방향은
    3학년 2학기 → 2024년 2학기(휴학한 학기)를 줬다. 로드맵의 "3학년 2학기" 칸에 과목을
    놓으면 planned_year가 2024로 저장된다는 뜻이다.
    """

    # 2022 입학, 5학기 이수(→ 커리큘럼 3학년 1학기) 후 휴학. 현재는 2026년 2학기.
    TERMS = [("2022", "1학기"), ("2022", "2학기"),
             ("2023", "1학기"), ("2023", "2학기"), ("2024", "1학기")]
    NOW = (2026, 2)

    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_TABLES)
        db = sessionmaker(bind=engine, autoflush=False)()
        db.add(User(id=1, email="t@x.com", password_hash="x", name="테스트",
                    admission_type="freshman"))
        db.flush()
        for index, (year, semester) in enumerate(self.TERMS):
            db.add(StudentCourseRecord(user_id=1, raw_course_name=f"과목{index}",
                                       category="전공선택", credits=3,
                                       year=year, semester=semester))
        db.commit()
        return db

    def test_휴학_학생도_왕복이_성립한다(self):
        db = self.make_db()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=self.NOW):
            forward = project_curriculum_term(db, 1, "2027", "1학기")
            self.assertEqual((3, "2학기"), forward)
            self.assertEqual(("2027", "1학기"), project_calendar_term(db, 1, *forward))

    def test_계획_학기는_현재_학기보다_뒤여야_한다(self):
        """휴학 중인 학생의 어떤 커리큘럼 슬롯도 과거 달력으로 떨어지면 안 된다."""
        db = self.make_db()
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=self.NOW):
            for grade, semester in [(3, "2학기"), (4, "1학기"), (4, "2학기")]:
                with self.subTest(grade=grade, semester=semester):
                    year, sem = project_calendar_term(db, 1, grade, semester)
                    self.assertIsNotNone(year)
                    self.assertGreater(
                        (int(year), 1 if sem == "1학기" else 2), self.NOW,
                        f"{grade}학년 {semester} → {year}년 {sem}는 이미 지난 학기다",
                    )

    def test_공백_없는_학생은_달력_거리를_그대로_쓴다(self):
        """지금도 재학 중이면(마지막 기록 = 직전 학기) 휴학 보정이 끼어들면 안 된다."""
        db = self.make_db()
        # 마지막 기록 2024-1 바로 다음이 현재 학기인 상황.
        with patch.object(roadmap_chat_mod, "_current_academic_term", return_value=(2024, 2)):
            self.assertEqual(("2024", "2학기"), project_calendar_term(db, 1, 3, "2학기"))


if __name__ == "__main__":
    unittest.main()
