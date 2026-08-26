from types import SimpleNamespace
import unittest

from app.ai.rag.curriculum_ingestion import CurriculumRagIngestionService


class _RowsSession:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _statement):
        return SimpleNamespace(all=lambda: self.rows)


class SyllabusRagDraftTest(unittest.TestCase):
    def test_uses_only_verified_structured_fields_not_pdf_raw_text(self):
        course = SimpleNamespace(
            id=31,
            course_name="C++프로그래밍",
            course_code="CB1501014",
            department_id=4,
            major_id=7,
            category="전공선택",
            year="2",
            credits=3.0,
        )
        offering = SimpleNamespace(id=52, year="2026", semester="1학기", section="001", professor="홍길동")
        syllabus = SimpleNamespace(
            id=71,
            course_overview="C 언어를 확장해 객체지향 프로그래밍을 다룬다.",
            course_objectives="C++ 프로그램의 설계 및 구현 능력을 기른다.",
            prerequisites_text="C 언어 기초",
            teaching_mode="강의 및 실습",
            evaluation_method="중간 30%, 기말 30%, 과제 40%",
            textbooks="C++ Primer",
            core_competencies=["창의융합"],
            weekly_plan=[{"week": "제1주", "content": "C++ 개요"}],
            raw_text="강의 및 실험 실기 내용 장애학생 지원 안내 연락처 표 머리말",
        )

        draft = CurriculumRagIngestionService(_RowsSession([(syllabus, offering, course)]))._syllabus_drafts(
            curriculum_year="2026"
        )[0]

        self.assertEqual(draft.document_type, "syllabus")
        self.assertEqual(draft.semester, "1")
        self.assertIn("강의개요: C 언어를 확장", draft.content)
        self.assertIn("교수목표: C++ 프로그램의 설계", draft.content)
        self.assertIn("주차계획: 제1주: C++ 개요", draft.content)
        self.assertNotIn("장애학생", draft.content)
        self.assertNotIn("표 머리말", draft.content)
