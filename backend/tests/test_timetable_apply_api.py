import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.roadmaps import TimetableApplyRequest, apply_timetable_to_roadmap
from app.core.db import Base
from app.domains.academics.models import College, Department, Major, School
from app.domains.courses.models import Course, CourseOffering
from app.domains.planning.models import CourseRoadmap, CourseRoadmapItem
from app.domains.users.models import User


class TimetableApplyApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(cls.engine, tables=[
            School.__table__, College.__table__, Department.__table__, Major.__table__,
            User.__table__, Course.__table__, CourseOffering.__table__,
            CourseRoadmap.__table__, CourseRoadmapItem.__table__,
        ])

    def setUp(self):
        self.db = Session(self.engine)
        self.db.query(CourseRoadmapItem).delete()
        self.db.query(CourseRoadmap).delete()
        self.db.query(CourseOffering).delete()
        self.db.query(Course).delete()
        self.db.query(User).delete()
        self.db.commit()

        self.user = User(id=1, email="t@example.com", password_hash="x", name="테스트")
        self.db.add(self.user)
        self.db.add(CourseRoadmap(id=1, user_id=1))
        # 3개 과목·분반: (자료구조 → 2026 2학기), (알고리즘 → 2026 2학기), (운영체제 → 2026 1학기)
        self.db.add_all([
            Course(id=100, course_name="자료구조", category="전공필수", credits=3),
            Course(id=101, course_name="알고리즘", category="전공필수", credits=3),
            Course(id=102, course_name="운영체제", category="전공선택", credits=3),
        ])
        self.db.add_all([
            CourseOffering(id=200, course_id=100, year="2026", semester="2학기"),
            CourseOffering(id=201, course_id=101, year="2026", semester="2학기"),
            CourseOffering(id=202, course_id=102, year="2026", semester="1학기"),  # 다른 학기
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _call(self, offering_ids: list[int], year="2026", semester="2학기", grade=None):
        payload = TimetableApplyRequest(
            year=year, semester=semester, offering_ids=offering_ids, planned_grade=grade,
        )
        return apply_timetable_to_roadmap(
            roadmap_id=1, payload=payload, current_user=self.user, db=self.db,
        )

    def test_applies_selected_offerings_as_planned_items(self):
        """정상 케이스: 요청 학기와 일치하는 분반들이 로드맵 항목으로 저장된다."""
        result = self._call([200, 201], grade=3)

        self.assertEqual(2, len(result.applied))
        self.assertEqual(0, len(result.skipped))
        names = sorted(i.course_name for i in result.applied)
        self.assertEqual(["알고리즘", "자료구조"], names)
        for item in result.applied:
            self.assertEqual("2026", item.planned_year)
            self.assertEqual("2학기", item.planned_semester)
            self.assertEqual(3, item.planned_grade)
            self.assertEqual("planned", item.status)
            self.assertTrue(item.is_confirmed)  # 사용자 명시적 저장
            self.assertEqual("ai", item.source)

    def test_unknown_offering_id_is_skipped_not_error(self):
        result = self._call([200, 999])  # 999 = 없는 분반
        self.assertEqual(1, len(result.applied))
        self.assertEqual(1, len(result.skipped))
        self.assertEqual(999, result.skipped[0].offering_id)
        self.assertIn("존재하지 않는 분반", result.skipped[0].reason)

    def test_semester_mismatch_is_skipped_with_reason(self):
        """요청 학기(2학기)와 다른 학기(1학기) 개설 분반은 스킵된다."""
        result = self._call([200, 202])
        self.assertEqual(1, len(result.applied))
        self.assertEqual(1, len(result.skipped))
        skipped = result.skipped[0]
        self.assertEqual(202, skipped.offering_id)
        self.assertIn("다릅니다", skipped.reason)
        # DB에는 자료구조만 들어감
        items = self.db.scalars(select(CourseRoadmapItem)).all()
        self.assertEqual(1, len(items))

    def test_duplicate_same_semester_is_silently_skipped(self):
        """이미 로드맵에 같은 학기·같은 과목이 있으면 저장하지 않고 skipped에 표시."""
        self.db.add(CourseRoadmapItem(
            roadmap_id=1, course_id=100, course_name="자료구조", category="전공필수",
            credits=3, planned_year="2026", planned_semester="2학기", status="planned",
        ))
        self.db.commit()

        result = self._call([200, 201])
        self.assertEqual(1, len(result.applied))
        self.assertEqual("알고리즘", result.applied[0].course_name)
        self.assertEqual(1, len(result.skipped))
        self.assertEqual(100, result.skipped[0].course_id)
        self.assertIn("이미", result.skipped[0].reason)

    def test_same_course_in_other_semester_does_not_block(self):
        """같은 과목이 다른 학기에 이미 있어도 이번 학기 저장은 막지 않는다.
        (재수강/재이수 시나리오 대비 — 서버가 아니라 LLM/UI가 판단)"""
        self.db.add(CourseRoadmapItem(
            roadmap_id=1, course_id=100, course_name="자료구조", category="전공필수",
            credits=3, planned_year="2026", planned_semester="1학기", status="planned",
        ))
        self.db.commit()

        result = self._call([200])
        self.assertEqual(1, len(result.applied))
        self.assertEqual(0, len(result.skipped))

    def test_planned_grade_null_when_client_omits(self):
        result = self._call([200])  # grade 안 넘김
        self.assertIsNone(result.applied[0].planned_grade)

    def test_removes_future_semester_duplicate_when_applying(self):
        """이번 학기(2026 2학기)에 자료구조를 저장할 때, 로드맵의 2027 1학기에 같은
        과목이 계획돼 있으면 그 미래 항목을 삭제한다."""
        future_item = CourseRoadmapItem(
            roadmap_id=1, course_id=100, course_name="자료구조", category="전공필수",
            credits=3, planned_year="2027", planned_semester="1학기", status="planned",
        )
        self.db.add(future_item)
        self.db.commit()
        future_id = future_item.id

        result = self._call([200])

        self.assertEqual(1, len(result.applied))
        self.assertEqual(1, len(result.removed_from_future))
        self.assertEqual(future_id, result.removed_from_future[0].item_id)
        self.assertEqual("자료구조", result.removed_from_future[0].course_name)
        # DB에서 정말로 사라졌는지
        remaining = self.db.scalars(
            select(CourseRoadmapItem).where(CourseRoadmapItem.course_id == 100)
        ).all()
        self.assertEqual(1, len(remaining))
        self.assertEqual("2026", remaining[0].planned_year)

    def test_does_not_remove_completed_past_item(self):
        """이미 이수한(completed) 과거 항목은 미래가 아니므로 손대지 않는다.
        정책상 completed는 어떤 경우에도 삭제하지 않는다."""
        self.db.add(CourseRoadmapItem(
            roadmap_id=1, course_id=100, course_name="자료구조", category="전공필수",
            credits=3, planned_year="2024", planned_semester="2학기", status="completed",
        ))
        self.db.commit()

        result = self._call([200])

        self.assertEqual(1, len(result.applied))
        self.assertEqual(0, len(result.removed_from_future))
        remaining = self.db.scalars(
            select(CourseRoadmapItem).where(CourseRoadmapItem.course_id == 100)
        ).all()
        self.assertEqual(2, len(remaining))  # 과거 completed + 이번 학기 planned

    def test_does_not_remove_completed_future_item(self):
        """미래 학기여도 status='completed'면 사실상 이미 이수한 것으로 판정된
        과목이라 삭제 대상에서 제외한다."""
        self.db.add(CourseRoadmapItem(
            roadmap_id=1, course_id=100, course_name="자료구조", category="전공필수",
            credits=3, planned_year="2027", planned_semester="1학기", status="completed",
        ))
        self.db.commit()

        result = self._call([200])

        self.assertEqual(1, len(result.applied))
        self.assertEqual(0, len(result.removed_from_future))

    def test_removes_multiple_future_items_for_same_course(self):
        """같은 과목이 여러 미래 학기에 계획돼 있으면 전부 제거한다 (엣지 케이스)."""
        self.db.add_all([
            CourseRoadmapItem(roadmap_id=1, course_id=100, course_name="자료구조",
                              category="전공필수", credits=3,
                              planned_year="2027", planned_semester="1학기", status="planned"),
            CourseRoadmapItem(roadmap_id=1, course_id=100, course_name="자료구조",
                              category="전공필수", credits=3,
                              planned_year="2027", planned_semester="2학기", status="planned"),
        ])
        self.db.commit()

        result = self._call([200])

        self.assertEqual(1, len(result.applied))
        self.assertEqual(2, len(result.removed_from_future))


if __name__ == "__main__":
    unittest.main()
