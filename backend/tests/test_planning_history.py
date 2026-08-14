import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.domains.academics.models import StudentCourseRecord
from app.domains.courses.models import Course
from app.domains.planning import roadmap_chat as roadmap_chat_mod
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


if __name__ == "__main__":
    unittest.main()


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
