"""편입생이 직접 등록한 "전적대 과목 ↔ PNU 과목" 대체 관계.

## 왜 이 테스트가 있는가

편입 학점 인정은 규정 표가 아니라 학과가 학생 개인에게 통보하는 것이라 데이터에
근거가 없다. 그래서 시스템은 이름 유사도로 추측하면 안 되고(`데이터구조`≈`자료구조`가
그럴듯해도 학교가 실제로 인정했는지는 학생만 안다), **학생이 고른 값만** 신뢰해야
한다. 여기서 고정하는 것:

1. 학생이 고르기 전에는 아무 일도 일어나지 않는다 — 자동 매핑이 끼어들면 실패한다.
2. 학생이 고르면 **추천에서만** 효과가 난다: 시간표/로드맵이 그 PNU 과목을 이미
   이수한 것으로 보고 후보에서 뺀다. 이게 이 기능의 실제 가치다.
3. **학점은 변하지 않는다.** 전적대 학점은 이수기록 행에 그대로 있고 졸업요건 엔진은
   category별 합계만 대조한다. 대체 등록으로 판정 숫자가 흔들리면 회귀다.
4. 정규 학기 이수기록에는 대체를 지정할 수 없다 — "입학 전 인정 학점" 행 전용이다.
"""

import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.portal_sync import (
    CourseRecordInput,
    CourseRecordsReplaceRequest,
    CourseSubstitutionRequest,
    list_course_records,
    replace_course_records,
    set_course_substitution,
)
from app.core.db import Base
from app.domains.academics.course_substitution import substituted_course_names
from app.domains.academics.graduation_progress import compute_graduation_progress
from app.domains.academics.models import (
    College,
    Department,
    GraduationRequirement,
    Major,
    School,
    StudentCourseRecord,
    UserAcademicProgram,
)
from app.domains.courses.models import Course
from app.domains.planning.roadmap_chat import _compute_critical_missing_required
from app.domains.planning.timetable import _completed_course_norms
from app.domains.users.models import User


_TABLES = [
    School.__table__, College.__table__, Department.__table__, Major.__table__,
    User.__table__, Course.__table__, StudentCourseRecord.__table__,
    UserAcademicProgram.__table__, GraduationRequirement.__table__,
]


class TransferCourseSubstitutionTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_TABLES)
        self.db = sessionmaker(bind=engine)()

        self.db.add(Department(id=100, college_id=1, name="정보컴퓨터공학부"))
        self.user = User(
            id=1, email="transfer@example.com", password_hash="x", name="편입생",
            department_id=100, admission_type="transfer",
        )
        self.db.add(self.user)
        # 학생이 대체 대상으로 고를 수 있는 PNU 과목.
        self.db.add(Course(
            id=10, course_name="자료구조", category="전공필수", credits=3, department_id=100,
        ))
        # 전적대 이수기록: 성적표에 '데이터구조'로 들어왔고 PNU 교과목번호와 연결이 없다.
        self.transfer_record = StudentCourseRecord(
            id=1, user_id=1, raw_course_name="데이터구조", category="전공필수",
            credits=3, year="2026", semester="입학전성적", source="crawler",
        )
        # 편입 후 PNU에서 정규 학기에 들은 과목.
        self.regular_record = StudentCourseRecord(
            id=2, user_id=1, raw_course_name="운영체제", category="전공필수",
            credits=3, year="2026", semester="1학기", source="crawler",
        )
        self.db.add_all([self.transfer_record, self.regular_record])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_지정하기_전에는_자동으로_매핑되지_않는다(self):
        """이름이 아무리 비슷해도 시스템이 먼저 이어붙이면 안 된다.

        학교가 실제로 무엇을 인정했는지는 데이터에 없기 때문이다. 유사도 추천이
        슬쩍 들어오면 이 테스트가 먼저 깨진다.
        """
        self.assertEqual([], substituted_course_names(self.db, 1))
        self.assertNotIn("자료구조", _completed_course_norms(self.db, 1))

        records = list_course_records(current_user=self.user, db=self.db)
        transfer = next(r for r in records if r.id == 1)
        self.assertTrue(transfer.is_transfer_credit)
        self.assertIsNone(transfer.substitutes_course_id)
        self.assertIsNone(transfer.substitutes_course_name)

    def test_학생이_지정하면_추천에서_그_PNU_과목이_빠진다(self):
        """이 기능의 실제 가치. 이미 인정받은 자료구조를 또 추천하면 안 된다."""
        response = set_course_substitution(
            record_id=1,
            payload=CourseSubstitutionRequest(course_id=10),
            current_user=self.user,
            db=self.db,
        )
        self.assertEqual(10, response.substitutes_course_id)
        self.assertEqual("자료구조", response.substitutes_course_name)

        self.assertEqual(["자료구조"], substituted_course_names(self.db, 1))
        completed = _completed_course_norms(self.db, 1)
        self.assertIn("자료구조", completed)
        # 전적대 과목명 자체도 그대로 남는다 — 대체가 원본을 지우지는 않는다.
        self.assertIn("데이터구조", completed)

    def test_해제하면_다시_추천_후보로_돌아온다(self):
        """학과 통보가 바뀌거나 잘못 골랐을 때 되돌릴 수 있어야 한다."""
        set_course_substitution(
            record_id=1,
            payload=CourseSubstitutionRequest(course_id=10),
            current_user=self.user,
            db=self.db,
        )
        response = set_course_substitution(
            record_id=1,
            payload=CourseSubstitutionRequest(course_id=None),
            current_user=self.user,
            db=self.db,
        )
        self.assertIsNone(response.substitutes_course_id)
        self.assertNotIn("자료구조", _completed_course_norms(self.db, 1))

    def test_학점과_졸업요건_판정_숫자는_그대로다(self):
        """대체를 등록해도 이수학점 합계가 움직이면 회귀다.

        사용자 요구는 "대체해도 학점은 전적대 것으로 계산"인데, 지금 엔진이 이미
        그렇게 동작한다(전적대 학점이 그 행에 있고 엔진은 category 합계만 본다).
        대체 컬럼이 이 계산에 끼어들지 않는지 고정한다.
        """
        self.db.add(UserAcademicProgram(
            id=1, user_id=1, department_id=100, program_type="primary", curriculum_year="2024",
        ))
        self.db.add(GraduationRequirement(
            id=1, department_id=100, program_type="primary", curriculum_year="2024",
            required_total_credits=133, required_major_required=33,
        ))
        self.db.commit()

        before = compute_graduation_progress(self.db, 1, program_types={"primary"})[0]
        before_by_category = {c.category_name: c.earned_credits for c in before.categories}

        set_course_substitution(
            record_id=1,
            payload=CourseSubstitutionRequest(course_id=10),
            current_user=self.user,
            db=self.db,
        )

        after = compute_graduation_progress(self.db, 1, program_types={"primary"})[0]
        after_by_category = {c.category_name: c.earned_credits for c in after.categories}
        self.assertEqual(before_by_category, after_by_category)
        # 전적대 과목 행의 학점도 그대로 (대체가 학점을 옮기거나 지우지 않는다).
        self.assertEqual(3, float(self.db.get(StudentCourseRecord, 1).credits))

    def test_정규_학기_이수기록에는_지정할_수_없다(self):
        """이 기능은 "입학 전 인정 학점" 행 전용이다.

        PNU에서 직접 들은 과목에 대체를 걸 이유가 없고, 허용하면 이수기록이
        실제와 다른 과목을 가리키게 된다.
        """
        with self.assertRaises(HTTPException) as ctx:
            set_course_substitution(
                record_id=2,
                payload=CourseSubstitutionRequest(course_id=10),
                current_user=self.user,
                db=self.db,
            )
        self.assertEqual(422, ctx.exception.status_code)

    def test_남의_이수기록은_건드릴_수_없다(self):
        """record_id만 바꿔 부르면 남의 이수내역을 수정할 수 있으면 안 된다."""
        self.db.add(User(id=2, email="other@example.com", password_hash="x", name="타인"))
        self.db.add(StudentCourseRecord(
            id=3, user_id=2, raw_course_name="데이터구조", category="전공필수",
            credits=3, year="2026", semester="입학전성적", source="crawler",
        ))
        self.db.commit()

        with self.assertRaises(HTTPException) as ctx:
            set_course_substitution(
                record_id=3,
                payload=CourseSubstitutionRequest(course_id=10),
                current_user=self.user,
                db=self.db,
            )
        self.assertEqual(404, ctx.exception.status_code)
        self.assertIsNone(self.db.get(StudentCourseRecord, 3).substitutes_course_id)

    def test_로드맵_추천에서도_대체된_과목이_빠진다(self):
        """시간표뿐 아니라 로드맵 챗의 "놓친 전공필수" 경고에서도 빠져야 한다.

        한쪽만 고치면 시간표는 자료구조를 안 권하는데 로드맵은 "이번에 안 들으면
        위험하다"고 경고하는, 서로 다른 말을 하는 상태가 된다.
        """
        # 1학기 전용 전공필수 → 2학기 기준으로 보면 "이번 학기에 안 열리는 미이수 필수".
        self.db.add(Course(
            id=11, course_name="논리회로및설계", category="전공필수", credits=3,
            department_id=100, semester="1",
        ))
        self.db.add(StudentCourseRecord(
            id=4, user_id=1, raw_course_name="논리설계", category="전공필수",
            credits=3, year="2026", semester="입학전성적", source="crawler",
        ))
        self.db.commit()

        before = _compute_critical_missing_required(self.db, self.user, None, "2학기")
        self.assertIn("논리회로및설계", [c["course_name"] for c in before])

        set_course_substitution(
            record_id=4,
            payload=CourseSubstitutionRequest(course_id=11),
            current_user=self.user,
            db=self.db,
        )

        after = _compute_critical_missing_required(self.db, self.user, None, "2학기")
        self.assertNotIn("논리회로및설계", [c["course_name"] for c in after])

    def test_내_정보_편집_저장을_왕복해도_대체가_남는다(self):
        """성적 편집 저장(PUT /me/course-records)은 전체 교체 방식이다.

        그 경로가 대체 관계를 조용히 날리면, 성적 한 칸 고쳤을 뿐인데 추천이 원래대로
        돌아가고 학생은 이유를 알 수 없다.
        """
        set_course_substitution(
            record_id=1,
            payload=CourseSubstitutionRequest(course_id=10),
            current_user=self.user,
            db=self.db,
        )
        current = list_course_records(current_user=self.user, db=self.db)
        replaced = replace_course_records(
            CourseRecordsReplaceRequest(courses=[
                CourseRecordInput(
                    id=record.id, course_name=record.course_name, category=record.category,
                    credits=record.credits, year=record.year, semester=record.semester,
                    grade=record.grade,
                )
                for record in current
            ]),
            current_user=self.user,
            db=self.db,
        )
        transfer = next(r for r in replaced if r.id == 1)
        self.assertEqual("자료구조", transfer.substitutes_course_name)
        self.assertIn("자료구조", _completed_course_norms(self.db, 1))

    def test_없는_과목으로는_지정할_수_없다(self):
        """프론트가 자동완성 결과에서 고른 course_id만 오는 게 정상이지만,
        직접 호출로 존재하지 않는 id가 들어오면 조용히 저장하면 안 된다."""
        with self.assertRaises(HTTPException) as ctx:
            set_course_substitution(
                record_id=1,
                payload=CourseSubstitutionRequest(course_id=99999),
                current_user=self.user,
                db=self.db,
            )
        self.assertEqual(404, ctx.exception.status_code)


if __name__ == "__main__":
    unittest.main()
