import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.domains.academics.models import StudentCourseRecord
from app.domains.courses.models import Course
from app.domains.planning.history import (
    project_curriculum_term,
    sync_completed_courses_to_roadmap,
)
from app.domains.planning.models import CourseRoadmap, CourseRoadmapItem
from app.domains.users.models import User


_TABLES = [
    User.__table__,
    Course.__table__,
    StudentCourseRecord.__table__,
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

        self.assertEqual((1, "1학기"), (by_name["A"].planned_grade, by_name["A"].planned_semester))
        self.assertEqual((1, "2학기"), (by_name["B"].planned_grade, by_name["B"].planned_semester))
        self.assertEqual((2, "1학기"), (by_name["C"].planned_grade, by_name["C"].planned_semester))

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
        self.assertEqual((3, "1학기"), (by_name["자료구조"].planned_grade, by_name["자료구조"].planned_semester))
        self.assertEqual((3, "2학기"), (by_name["알고리즘"].planned_grade, by_name["알고리즘"].planned_semester))
        self.assertEqual((4, "1학기"), (by_name["캡스톤"].planned_grade, by_name["캡스톤"].planned_semester))

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
        self.assertEqual((1, "1학기"), (by_name["자료구조"].planned_grade, by_name["자료구조"].planned_semester))


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
        db = self.make_db()
        self._add_terms(db, [("2025", "1학기")])
        self.assertEqual((None, "여름계절수업"),
                         project_curriculum_term(db, 1, "2025", "여름계절수업"))

    def test_4학년을_넘어가면_비워_둔다(self):
        """졸업 후 학기까지 학년을 붙이면 로드맵에 없는 5학년 슬롯이 생긴다."""
        db = self.make_db()
        self._add_terms(db, [
            ("2022", "1학기"), ("2022", "2학기"), ("2023", "1학기"), ("2023", "2학기"),
            ("2024", "1학기"), ("2024", "2학기"), ("2025", "1학기"), ("2025", "2학기"),
        ])
        self.assertEqual((None, "1학기"), project_curriculum_term(db, 1, "2026", "1학기"))


if __name__ == "__main__":
    unittest.main()
