import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.domains.courses.models import Course
from app.domains.planning.models import CourseRoadmap, CourseRoadmapItem, PendingRoadmapChange
from app.domains.planning.roadmap_chat import _ToolContext
from app.domains.users.models import User


class ProposeChangeGradeGuardTest(unittest.TestCase):
    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                Course.__table__,
                CourseRoadmap.__table__,
                CourseRoadmapItem.__table__,
                PendingRoadmapChange.__table__,
            ],
        )
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


if __name__ == "__main__":
    unittest.main()
