import unittest

from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.auth import SignupRequest, _load_user_response, signup
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
    StudentCourseRecord, StudentCourseSubstitution,
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
            StudentCourseSubstitution.__table__,  # 추천 경로가 substituted_course_names를 조회한다
            CourseRoadmap.__table__,
            CourseRoadmapItem.__table__,
            CourseRoadmapChatSession.__table__,
            CourseRoadmapChatMessage.__table__,
            PendingRoadmapChange.__table__,
        ]
        Base.metadata.create_all(cls.engine, tables=tables)

    def setUp(self):
        self.db = Session(self.engine)
        self.db.query(PendingRoadmapChange).delete()
        self.db.query(CourseRoadmapChatMessage).delete()
        self.db.query(CourseRoadmapChatSession).delete()
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
            email="student@pusan.ac.kr",
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
            request=None,
            payload=SignupRequest(
                email="new-student@pusan.ac.kr",
                password="password123",
                name="신규 학생",
                student_id="202699999",
                academic_year=4,
                school="부산대학교",
                college="정보의생명공학대학",
                department="의생명융합공학부",
                privacy_consent=True,
            ),
            db=self.db,
        )

        saved_user = self.db.scalar(select(User).where(User.student_id == "202699999"))
        self.assertEqual(response.academic_year, 4)
        self.assertIsNotNone(saved_user)
        self.assertEqual(saved_user.academic_year, 4)
        self.assertTrue(saved_user.privacy_consent)
        self.assertIsNotNone(saved_user.privacy_consent_at)
        self.assertTrue(response.privacy_consent)

    def test_signup_rejects_missing_privacy_consent(self):
        """체크박스 검증은 프론트뿐 아니라 서버 스키마 레벨에서도 강제해야 한다 —
        안 그러면 API를 직접 호출해 동의 없이 가입할 수 있다."""
        with self.assertRaises(ValidationError):
            SignupRequest(
                email="no-consent@pusan.ac.kr",
                password="password123",
                name="미동의 학생",
                student_id="202699998",
                privacy_consent=False,
            )

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
        # 응답 모델은 raw_course_name을 course_name으로 내보낸다
        # (대체 과목 필드가 붙으면서 ORM 행이 아니라 CourseRecordResponse를 돌려주게 됐다).
        self.assertEqual(created[0].course_name, "데이터베이스")

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

    def test_liberal_area_cleared_when_category_moves_off_general_elective(self):
        """category가 교양선택에서 다른 값으로 바뀌면, payload가 이전 liberal_area를
        그대로 들고 와도 서버가 강제로 지워야 한다. 안 그러면 liberal_area_completions()가
        이미 다른 이수구분으로 옮겨간 과목을 계속 그 세부영역 이수로 잘못 집계한다."""
        created = replace_course_records(
            CourseRecordsReplaceRequest(
                courses=[
                    CourseRecordInput(
                        course_name="철학의이해",
                        category="교양선택",
                        liberal_area="사상과역사",
                        credits=3,
                        year="2026",
                        semester="1",
                    )
                ]
            ),
            current_user=self.user,
            db=self.db,
        )
        saved_id = created[0].id
        record = self.db.get(StudentCourseRecord, saved_id)
        self.assertEqual("사상과역사", record.liberal_area)

        # 프론트가 category만 바꿔 재제출하면서 liberal_area를 여전히 실어 보내는 상황을
        # 재현한다 (기존 레코드를 불러와 category 필드만 고친 뒤 그대로 재전송하는 경우).
        replace_course_records(
            CourseRecordsReplaceRequest(
                courses=[
                    CourseRecordInput(
                        id=saved_id,
                        course_name="철학의이해",
                        category="교양필수",
                        liberal_area="사상과역사",
                        credits=3,
                        year="2026",
                        semester="1",
                    )
                ]
            ),
            current_user=self.user,
            db=self.db,
        )
        self.db.refresh(record)
        self.assertEqual("교양필수", record.category)
        self.assertIsNone(record.liberal_area)

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

    def test_academic_programs_response_includes_active_hides_cancelled(self):
        # AI융합 패널에서 담은 융합전공(fusion_plan)은 active면 노출,
        # 취소하면 status='cancelled'로만 남는데 "내 전공" 목록에서 빠져야 한다.
        self.db.add_all([
            UserAcademicProgram(
                user_id=self.user.id,
                department_id=self.department.id,
                major_id=None,
                program_type="dual",
                curriculum_year="2026",
                status="active",
                source="fusion_plan",
            ),
            UserAcademicProgram(
                user_id=self.user.id,
                department_id=self.department.id,
                major_id=self.major.id,
                program_type="minor",
                curriculum_year="2026",
                status="cancelled",
                source="fusion_plan",
            ),
        ])
        self.db.commit()

        response = _load_user_response(self.db, self.user)
        types = sorted(p.program_type for p in response.academic_programs)
        self.assertEqual(types, ["dual", "primary"])

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
        # 메시지는 반드시 세션에 속한다(session_id NOT NULL).
        session = CourseRoadmapChatSession(roadmap_id=roadmap.id, title="기본 대화")
        self.db.add(session)
        self.db.flush()
        self.db.add_all(
            [
                CourseRoadmapChatMessage(
                    roadmap_id=roadmap.id,
                    session_id=session.id,
                    role="user",
                    content="전공 필수 과목을 먼저 보고 싶어",
                ),
                CourseRoadmapChatMessage(
                    roadmap_id=roadmap.id,
                    session_id=session.id,
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
