import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.rag.curriculum_retriever import CurriculumRetriever, GraduationRequirementRetriever
from app.core.db import Base
from app.domains.academics.models import College, Department, GraduationRequirement, Major, School
from app.domains.courses.models import Course


class RagRetrieverTest(unittest.TestCase):
    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=[
                School.__table__,
                College.__table__,
                Department.__table__,
                Major.__table__,
                Course.__table__,
                GraduationRequirement.__table__,
            ],
        )
        session_factory = sessionmaker(bind=engine)
        return session_factory()

    def test_curriculum_retriever_filters_department_major_and_normalizes_filters(self):
        db = self.make_db()
        db.add_all(
            [
                Course(
                    id=1,
                    course_name="머신러닝",
                    department_id=10,
                    major_id=20,
                    category="전공선택",
                    credits=3.0,
                    year="3",
                    semester="1",
                ),
                Course(
                    id=2,
                    course_name="타학과 머신러닝",
                    department_id=99,
                    major_id=88,
                    category="전공선택",
                    credits=3.0,
                    year="3",
                    semester="1",
                ),
            ]
        )
        db.commit()

        results = CurriculumRetriever(db).search(
            query="AI 머신러닝",
            department_id=10,
            major_id=20,
            curriculum_year=2026,
            filters={"grade": "3학년", "semester": "1학기", "category": "전공선택"},
        )

        self.assertEqual([result["course_id"] for result in results], [1])
        self.assertEqual(results[0]["course_name"], "머신러닝")
        self.assertEqual(results[0]["document_type"], "curriculum")

    def test_curriculum_retriever_without_major_id_still_returns_major_specific_courses(self):
        """학부제 학과에서 전공을 아직 정하지 않은 학생(major_id=None)도 그 학과의
        전공별 과목을 볼 수 있어야 한다 — major_id IS NULL인 행만 보이면 안 된다."""
        db = self.make_db()
        db.add_all(
            [
                Course(
                    id=1,
                    course_name="자료구조",
                    department_id=10,
                    major_id=20,
                    category="전공필수",
                    credits=3.0,
                    year="2",
                    semester="1",
                ),
                Course(
                    id=2,
                    course_name="공학수학",
                    department_id=10,
                    major_id=None,
                    category="전공기초",
                    credits=3.0,
                    year="1",
                    semester="1",
                ),
                Course(
                    id=3,
                    course_name="타학과 과목",
                    department_id=99,
                    major_id=None,
                    category="전공기초",
                    credits=3.0,
                    year="1",
                    semester="1",
                ),
            ]
        )
        db.commit()

        results = CurriculumRetriever(db).search(
            query="",
            department_id=10,
            major_id=None,
            curriculum_year=2026,
        )

        course_ids = {result["course_id"] for result in results}
        self.assertIn(1, course_ids)  # 전공별 과목도 포함돼야 함
        self.assertIn(2, course_ids)  # 학과 공통 과목도 포함
        self.assertNotIn(3, course_ids)  # 타학과는 여전히 제외

    def test_graduation_requirement_retriever_returns_rag_shaped_requirements(self):
        db = self.make_db()
        db.add(
            GraduationRequirement(
                id=1,
                department_id=10,
                major_id=20,
                program_type="primary",
                curriculum_year="2026",
                required_total_credits=130,
                required_major_required=18,
                required_major_elective=42,
            )
        )
        db.commit()

        results = GraduationRequirementRetriever(db).search(
            query="전공필수",
            department_id=10,
            major_id=20,
            curriculum_year=2026,
            filters={"category": "전공필수"},
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["category"], "전공필수")
        self.assertEqual(results[0]["credits"], 18.0)
        self.assertEqual(results[0]["source"], "graduation_requirements")
        self.assertEqual(results[0]["document_type"], "graduation_requirement")

    def test_curriculum_retriever_expands_career_query_for_db_first_ranking(self):
        db = self.make_db()
        db.add_all(
            [
                Course(
                    id=1,
                    course_name="서버프로그래밍",
                    department_id=10,
                    major_id=20,
                    category="전공선택",
                    credits=3.0,
                    year="3",
                    semester="1",
                ),
                Course(
                    id=2,
                    course_name="머신러닝",
                    department_id=10,
                    major_id=20,
                    category="전공선택",
                    credits=3.0,
                    year="3",
                    semester="1",
                ),
            ]
        )
        db.commit()

        results = CurriculumRetriever(db).search(
            query="AI 개발자",
            department_id=10,
            major_id=20,
            curriculum_year=2026,
            filters={"category": "전공선택"},
        )

        self.assertEqual(results[0]["course_name"], "머신러닝")

    def test_curriculum_retriever_enriches_evidence_with_course_description_column(self):
        """courses.description이 채워진 과목만 evidence에 내용이 붙는다. description이
        없는 과목(id=2)은 평소처럼 정상 동작해야 한다."""
        db = self.make_db()
        db.add_all(
            [
                Course(
                    id=1,
                    course_name="자료구조",
                    department_id=10,
                    major_id=None,
                    category="전공필수",
                    credits=3.0,
                    year="2",
                    semester="1",
                    description="적절한 자료구조를 선정하고 구현하는 능력을 배양한다.",
                ),
                Course(
                    id=2,
                    course_name="이름이바뀐과목",
                    department_id=10,
                    major_id=None,
                    category="전공필수",
                    credits=3.0,
                    year="2",
                    semester="1",
                ),
            ]
        )
        db.commit()

        results = CurriculumRetriever(db).search(
            query="", department_id=10, major_id=None, curriculum_year=2026
        )
        by_id = {result["course_id"]: result for result in results}

        self.assertIn("적절한 자료구조를", by_id[1]["evidence"])
        self.assertEqual(by_id[1]["description"], "적절한 자료구조를 선정하고 구현하는 능력을 배양한다.")
        self.assertIsNone(by_id[2]["description"])


if __name__ == "__main__":
    unittest.main()
