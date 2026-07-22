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

    def test_semester_filter_includes_agnostic_courses(self):
        """semester='2학기' 필터는 courses.semester='2' + 학기 무관('1,2'/'전학기')도
        같이 반환해야 한다. 언제나 이수 가능한 과목이 통째로 빠지면 검색이 필요
        이상으로 좁아진다."""
        db = self.make_db()
        db.add_all(
            [
                Course(id=1, course_name="정규2학기", department_id=10, category="전공선택",
                       credits=3.0, year="3", semester="2"),
                Course(id=2, course_name="정규1학기", department_id=10, category="전공선택",
                       credits=3.0, year="3", semester="1"),
                Course(id=3, course_name="학기무관", department_id=10, category="전공선택",
                       credits=3.0, year="3", semester="전학기"),
                Course(id=4, course_name="쉼표12", department_id=10, category="전공선택",
                       credits=3.0, year="3", semester="1,2"),
                Course(id=5, course_name="여름계절", department_id=10, category="전공선택",
                       credits=3.0, year="3", semester="여름계절수업"),
            ]
        )
        db.commit()

        results = CurriculumRetriever(db).search(
            query="", department_id=10, major_id=None, curriculum_year=2026,
            filters={"semester": "2학기"},
        )
        ids = {r["course_id"] for r in results}
        self.assertEqual({1, 3, 4}, ids)  # 2 (다른 학기) / 5 (계절수업)는 제외

    def test_grade_filter_includes_전학년_courses(self):
        db = self.make_db()
        db.add_all(
            [
                Course(id=1, course_name="3학년", department_id=10, category="전공선택",
                       credits=3.0, year="3", semester="1"),
                Course(id=2, course_name="2학년", department_id=10, category="전공선택",
                       credits=3.0, year="2", semester="1"),
                Course(id=3, course_name="전학년", department_id=10, category="전공선택",
                       credits=3.0, year="전학년", semester="1"),
            ]
        )
        db.commit()

        results = CurriculumRetriever(db).search(
            query="", department_id=10, major_id=None, curriculum_year=2026,
            filters={"grade": "3"},
        )
        ids = {r["course_id"] for r in results}
        self.assertEqual({1, 3}, ids)

    def test_curriculum_retriever_normalizes_semester_for_agent_consumption(self):
        """courses.semester는 DB에 `"1"`/`"2"`/`"1,2"`/`"전학기"` 등 원시값으로 들어있는데,
        로드맵 항목(planned_semester)이 `"1학기"`/`"2학기"`로 저장되는 것과 어긋나면
        에이전트가 search_courses 결과를 그대로 propose_change로 흘렸을 때 매칭이
        깨진다. 검색 결과에서는 이걸 정규화된 표시 형식으로 돌려줘야 한다."""
        db = self.make_db()
        db.add_all(
            [
                Course(id=1, course_name="A", department_id=10, category="전공선택",
                       credits=3.0, year="3", semester="1"),
                Course(id=2, course_name="B", department_id=10, category="전공선택",
                       credits=3.0, year="3", semester="2"),
                Course(id=3, course_name="C", department_id=10, category="전공선택",
                       credits=3.0, year="3", semester="1,2"),
                Course(id=4, course_name="D", department_id=10, category="전공선택",
                       credits=3.0, year="전학년", semester="전학기"),
            ]
        )
        db.commit()

        results = CurriculumRetriever(db).search(
            query="", department_id=10, major_id=None, curriculum_year=2026
        )
        by_id = {r["course_id"]: r for r in results}
        self.assertEqual(by_id[1]["semester"], "1학기")
        self.assertEqual(by_id[2]["semester"], "2학기")
        self.assertEqual(by_id[3]["semester"], "1학기 또는 2학기")
        self.assertEqual(by_id[4]["semester"], "전학기")

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


    def test_same_named_courses_dedup_in_results(self):
        """학과별 서로 다른 course_code로 시딩된 동일 개념 교양(예: 공학작문및발표 4개
        code)이 결과에 한 번만 나와야 한다 — LLM이 같은 과목을 여러 번 추천하는 것을
        방지."""
        db = self.make_db()
        db.add_all([
            Course(id=1, course_name="공학작문및발표", course_code="ZE1000119",
                   department_id=None, category="효원핵심교양", credits=3.0, year="3", semester="2"),
            Course(id=2, course_name="공학작문및발표", course_code="DM1100179",
                   department_id=None, category="효원핵심교양", credits=3.0, year="3", semester="2"),
            Course(id=3, course_name="공학작문및발표", course_code="CB1000119",
                   department_id=None, category="효원핵심교양", credits=3.0, year="3", semester="2"),
        ])
        db.commit()

        results = CurriculumRetriever(db).search(
            query="", department_id=10, major_id=None, curriculum_year=2026,
            filters={"category": "교양필수"},
        )
        names = [r["course_name"] for r in results]
        self.assertEqual(names.count("공학작문및발표"), 1)

    def test_category_alias_교양필수_matches_효원핵심교양_and_기초교양(self):
        """졸업요건 표기(교양필수)로 필터해도 DB 원시 카테고리(효원핵심교양·기초교양)에 매칭돼야 한다.
        실제 사고: CB1000119 공학작문및발표를 category='교양필수'로 검색하면 0건이 나와
        LLM이 교양필수 추천을 못했다."""
        db = self.make_db()
        db.add_all([
            Course(id=1, course_name="공학작문및발표", department_id=None, category="효원핵심교양",
                   credits=3.0, year="3", semester="2"),
            Course(id=2, course_name="공학미적분학", department_id=None, category="기초교양",
                   credits=3.0, year="1", semester="1"),
            Course(id=3, course_name="사상과역사", department_id=None, category="효원균형교양",
                   credits=3.0, year="전학년", semester="전학기"),
            Course(id=4, course_name="딴카테고리", department_id=10, category="전공필수",
                   credits=3.0, year="3", semester="2"),
        ])
        db.commit()

        results = CurriculumRetriever(db).search(
            query="", department_id=10, major_id=None, curriculum_year=2026,
            filters={"category": "교양필수"},
        )
        ids = {r["course_id"] for r in results}
        self.assertEqual({1, 2}, ids)  # 효원핵심교양 + 기초교양만

        results2 = CurriculumRetriever(db).search(
            query="", department_id=10, major_id=None, curriculum_year=2026,
            filters={"category": "교양선택"},
        )
        ids2 = {r["course_id"] for r in results2}
        self.assertEqual({3}, ids2)  # 효원균형교양 (창의교양은 이 테스트에 없음)

        # 전공 카테고리는 exact match 유지
        results3 = CurriculumRetriever(db).search(
            query="", department_id=10, major_id=None, curriculum_year=2026,
            filters={"category": "전공필수"},
        )
        self.assertEqual({4}, {r["course_id"] for r in results3})


if __name__ == "__main__":
    unittest.main()
