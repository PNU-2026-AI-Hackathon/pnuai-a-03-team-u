import unittest

from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.auth import SignupRequest, signup
from app.api.curriculum import get_my_curriculum
from app.api.graduation import CategoryProgressResponse, GraduationOverrideInput
from app.api.portal_sync import (
    AdvisorConsultedRequest,
    CourseRecordInput,
    CourseRecordsReplaceRequest,
    list_course_records,
    replace_course_records,
    set_advisor_consulted,
)
from app.api.profile import ProfileUpdateRequest, update_profile
from app.api.roadmap_agent import delete_roadmap_messages, get_roadmap_messages
from app.core.db import Base
from app.domains.academics.models import (
    College,
    Department,
    Major,
    School,
    StudentCourseRecord,
    UserAcademicProgram,
)
from app.domains.courses.models import Course
from app.domains.planning.models import (
    CourseRoadmap,
    CourseRoadmapChatMessage,
    CourseRoadmapItem,
    PendingRoadmapChange,
)
from app.domains.users.models import User


class ConnectedProfileRoadmapApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        tables = [
            School.__table__,
            College.__table__,
            Department.__table__,
            Major.__table__,
            User.__table__,
            UserAcademicProgram.__table__,
            Course.__table__,
            StudentCourseRecord.__table__,
            CourseRoadmap.__table__,
            CourseRoadmapItem.__table__,
            CourseRoadmapChatMessage.__table__,
            PendingRoadmapChange.__table__,
        ]
        Base.metadata.create_all(cls.engine, tables=tables)

    def setUp(self):
        self.db = Session(self.engine)
        self.db.query(PendingRoadmapChange).delete()
        self.db.query(CourseRoadmapChatMessage).delete()
        self.db.query(CourseRoadmapItem).delete()
        self.db.query(CourseRoadmap).delete()
        self.db.query(StudentCourseRecord).delete()
        self.db.query(Course).delete()
        self.db.query(UserAcademicProgram).delete()
        self.db.query(User).delete()
        self.db.query(Major).delete()
        self.db.query(Department).delete()
        self.db.query(College).delete()
        self.db.query(School).delete()
        self.db.commit()

        school = School(name="부산대학교")
        self.db.add(school)
        self.db.flush()
        college = College(school_id=school.id, name="정보의생명공학대학")
        self.db.add(college)
        self.db.flush()
        self.department = Department(college_id=college.id, name="의생명융합공학부")
        self.db.add(self.department)
        self.db.flush()
        self.major = Major(department_id=self.department.id, name="데이터사이언스전공")
        self.db.add(self.major)
        self.db.flush()
        self.user = User(
            email="student@example.com",
            password_hash="not-used",
            name="테스트 학생",
            student_id="202312345",
            department_id=self.department.id,
            major_id=self.major.id,
            academic_year=3,
        )
        self.db.add(self.user)
        self.db.flush()
        self.db.add(
            UserAcademicProgram(
                user_id=self.user.id,
                department_id=self.department.id,
                major_id=self.major.id,
                program_type="primary",
                curriculum_year="2026",
            )
        )
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self):
        self.db.close()

    def test_signup_saves_academic_year(self):
        response = signup(
            SignupRequest(
                email="new-student@example.com",
                password="password123",
                name="신규 학생",
                student_id="202699999",
                academic_year=4,
                school="부산대학교",
                college="정보의생명공학대학",
                department="의생명융합공학부",
            ),
            self.db,
        )

        saved_user = self.db.scalar(select(User).where(User.student_id == "202699999"))
        self.assertEqual(response.academic_year, 4)
        self.assertIsNotNone(saved_user)
        self.assertEqual(saved_user.academic_year, 4)

    def test_course_records_are_replaced_and_reloaded(self):
        created = replace_course_records(
            CourseRecordsReplaceRequest(
                courses=[
                    CourseRecordInput(
                        course_name="데이터베이스",
                        category="전공필수",
                        credits=3,
                        year="2026",
                        semester="1",
                        grade="A+",
                    )
                ]
            ),
            current_user=self.user,
            db=self.db,
        )
        self.assertEqual(created[0].raw_course_name, "데이터베이스")

        saved_id = created[0].id
        replace_course_records(
            CourseRecordsReplaceRequest(
                courses=[
                    CourseRecordInput(
                        id=saved_id,
                        course_name="데이터베이스",
                        category="전공필수",
                        credits=3,
                        year="2026",
                        semester="1",
                        grade="A0",
                    ),
                    CourseRecordInput(
                        course_name="자료구조",
                        category="전공필수",
                        credits=3,
                        year="2026",
                        semester="1",
                        grade="B+",
                    ),
                ]
            ),
            current_user=self.user,
            db=self.db,
        )
        reloaded = list_course_records(current_user=self.user, db=self.db)
        self.assertEqual(len(reloaded), 2)
        self.assertEqual(next(record for record in reloaded if record.id == saved_id).grade, "A0")

    def test_profile_and_advisor_status_are_persisted(self):
        response = update_profile(
            ProfileUpdateRequest(
                name="수정 학생",
                department="의생명융합공학부",
                major="데이터사이언스전공",
                academic_year=4,
            ),
            current_user=self.user,
            db=self.db,
        )
        self.assertEqual(response.name, "수정 학생")
        self.assertEqual(response.academic_year, 4)

        result = set_advisor_consulted(
            AdvisorConsultedRequest(advisor_consulted=True),
            current_user=self.user,
            db=self.db,
        )
        self.assertTrue(result["advisor_consulted"])

    def test_curriculum_uses_course_and_user_status(self):
        completed = Course(
            course_code="DS101",
            course_name="데이터베이스",
            department_id=self.department.id,
            major_id=self.major.id,
            category="전공필수",
            credits=3,
            year="2",
            semester="1",
        )
        planned = Course(
            course_code="DS201",
            course_name="머신러닝",
            department_id=self.department.id,
            major_id=self.major.id,
            category="전공선택",
            credits=3,
            year="3",
            semester="2",
        )
        self.db.add_all([completed, planned])
        self.db.flush()
        self.db.add(
            StudentCourseRecord(
                user_id=self.user.id,
                raw_course_name=completed.course_name,
                credits=3,
                source="crawler",
            )
        )
        roadmap = CourseRoadmap(user_id=self.user.id, title="내 로드맵")
        self.db.add(roadmap)
        self.db.flush()
        self.db.add(
            CourseRoadmapItem(
                roadmap_id=roadmap.id,
                course_id=planned.id,
                course_name=planned.course_name,
                status="planned",
            )
        )
        self.db.commit()

        response = get_my_curriculum(current_user=self.user, db=self.db)
        statuses = {
            course.course_name: course.status
            for group in response.groups
            for course in group.courses
        }
        self.assertEqual(statuses["데이터베이스"], "done")
        self.assertEqual(statuses["머신러닝"], "planned")

    def test_conversation_can_be_loaded_and_deleted(self):
        roadmap = CourseRoadmap(user_id=self.user.id, title="내 로드맵")
        self.db.add(roadmap)
        self.db.flush()
        self.db.add_all(
            [
                CourseRoadmapChatMessage(
                    roadmap_id=roadmap.id,
                    role="user",
                    content="전공 필수 과목을 먼저 보고 싶어",
                ),
                CourseRoadmapChatMessage(
                    roadmap_id=roadmap.id,
                    role="assistant",
                    content="필수 과목부터 확인할게요.",
                ),
            ]
        )
        self.db.commit()

        response = get_roadmap_messages(
            roadmap.id, current_user=self.user, db=self.db
        )
        self.assertEqual(len(response.messages), 2)
        self.assertEqual(response.suggested_actions[0].label, "필수 과목 학기 배치")

        delete_roadmap_messages(roadmap.id, current_user=self.user, db=self.db)
        remaining = self.db.scalars(
            select(CourseRoadmapChatMessage).where(
                CourseRoadmapChatMessage.roadmap_id == roadmap.id
            )
        ).all()
        self.assertEqual(remaining, [])

    def test_graduation_override_rejects_inconsistent_totals(self):
        category = CategoryProgressResponse(
            category_code="required_major_required",
            category_name="전공필수",
            required_credits=18,
            earned_credits=12,
            remaining_credits=6,
            satisfied=False,
        )
        with self.assertRaises(ValidationError):
            GraduationOverrideInput(
                required_total_credits=130,
                earned_total_credits=12,
                categories=[category],
            )


if __name__ == "__main__":
    unittest.main()
