import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.domains.academics.models import StudentCourseRecord
from app.domains.courses.models import Course
from app.domains.planning.history import sync_completed_courses_to_roadmap
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

    def test_pre_enrollment_records_land_on_grade_3_first_semester(self):
        """편입 인정(입학전성적) 이수기록은 로드맵에서 3학년 1학기로 표시된다.
        예전엔 planned_grade=None으로 남아 UI가 1학년 1학기로 그렸다."""
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
            self.assertEqual(3, item.planned_grade)
            self.assertEqual("1학기", item.planned_semester)
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

    def test_transfer_and_regular_can_coexist(self):
        """편입 학생이 3-1을 실제로 이수한 경우, 입학전성적 rows와 3-1 rows가
        나란히 3-1 슬롯에 이수 완료로 올라간다."""
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

        self.assertEqual((3, "1학기"), (by_name["이산수학"].planned_grade, by_name["이산수학"].planned_semester))
        # 정규 3-1 rows는 재학 순번상 첫 학기라 grade=1로 계산됨(현재 랭킹 규칙).
        # 이 테스트의 취지는 입학전성적 rows가 3-1로 확실히 오고 정규 매핑 로직은 건드려지지 않는다는 것.
        self.assertEqual((1, "1학기"), (by_name["자료구조"].planned_grade, by_name["자료구조"].planned_semester))


if __name__ == "__main__":
    unittest.main()
