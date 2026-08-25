"""`CurriculumRetriever`의 키워드 매칭 경로(`use_vector=False`, 실제 서비스가 쓰는 기본
경로) 테스트. `app/ai/rag/career_keywords.expand_career_query`와 `_course_evidence`의
description 처리가 실제 사고(2026-08-25)에서 문제였던 지점이다:

- `expand_career_query`가 예전엔 CAREER_ALIASES에 걸린 진로 문구만 CAREER_KEYWORDS로
  확장했는데, "시스템 프로그래머"처럼 5개 진로군(ai/data/backend/security/bio) 밖의
  문구는 원문 토큰 2개로만 폴백해서 사실상 신호가 거의 없었다(실측: 후보 15개 중 13개가
  키워드 점수 0). 지금은 항상 원문 토큰만 쓴다.
- `_course_evidence`가 description을 150자로 잘라서, 강의계획서 크롤링 이후 수백 자짜리
  실제 교수목표/강의개요 대부분이 매칭에 안 쓰였다. 지금은 자르지 않는다.
"""

import unittest

from app.ai.rag.career_keywords import expand_career_query
from app.ai.rag.curriculum_retriever import CurriculumRetriever, _keyword_score
from app.domains.courses.models import Course


class ExpandCareerQueryTest(unittest.TestCase):
    def test_tokenizes_raw_query_without_needing_a_known_career_group(self):
        """"시스템 프로그래머"는 CAREER_ALIASES의 ai/data/backend/security/bio
        어디에도 안 걸린다(2026-08-25 실측) — 그래도 원문 토큰은 그대로 나와야 한다."""
        self.assertEqual(("시스템", "프로그래머"), expand_career_query("시스템 프로그래머"))

    def test_no_longer_expands_matched_career_group_into_fixed_keywords(self):
        """예전엔 "AI 엔지니어" 같은 문구가 ai 진로군에 걸려서 CAREER_KEYWORDS['ai']
        전체(인공지능/머신러닝/딥러닝/데이터/알고리즘/확률/통계)가 덧붙었다 — 이제는
        원문 토큰만 나온다."""
        terms = expand_career_query("AI 엔지니어")
        self.assertEqual(("AI", "엔지니어"), terms)
        self.assertNotIn("확률", terms)
        self.assertNotIn("통계", terms)

    def test_splits_on_slash(self):
        self.assertEqual(("백엔드", "프론트엔드"), expand_career_query("백엔드/프론트엔드"))


class CourseEvidenceTest(unittest.TestCase):
    """`_course_evidence`는 staticmethod라 DB 세션 없이 Course 객체만으로 테스트한다."""

    def test_full_description_kept_without_150_char_truncation(self):
        long_overview = "본 강좌는 " + "실제 강의계획서 원문 " * 30  # 150자보다 훨씬 길다
        self.assertGreater(len(long_overview), 150)
        course = Course(
            id=1, course_name="자료구조", department_id=10, category="전공필수",
            credits=3.0, year="2", semester="2", description=long_overview,
        )
        evidence = CurriculumRetriever._course_evidence(course)
        self.assertIn(long_overview, evidence)

    def test_syllabus_sourced_description_gets_accurate_disclaimer(self):
        course = Course(
            id=2, course_name="AI프로그래밍", department_id=108, category="전공선택",
            credits=3.0, year="2", semester="2", description="AI/ML 알고리즘을 다룬다.",
            source_document="One-Stop 수강편람 교수계획표(강의계획서) — 홍길동 교수, X/001분반, 2026년 2학기",
        )
        evidence = CurriculumRetriever._course_evidence(course)
        self.assertIn("실제 설명", evidence)
        self.assertNotIn("개편 이전 자료", evidence)

    def test_catalog_import_description_keeps_stale_data_disclaimer(self):
        course = Course(
            id=3, course_name="옛날과목", department_id=10, category="전공선택",
            credits=3.0, year="3", semester="1", description="학과 교육과정표에서 가져온 설명.",
            source_document=None,
        )
        evidence = CurriculumRetriever._course_evidence(course)
        self.assertIn("개편 이전 자료", evidence)


class KeywordScoreTest(unittest.TestCase):
    def test_matches_directly_against_raw_query_terms_in_evidence(self):
        evidence = "3학년 2학기 전공선택 운영체제(3.0학점) — 프로세스와 스레드, 메모리 관리 등 시스템 프로그래밍의 핵심 개념을 다룬다."
        score = _keyword_score("시스템 프로그래머", evidence)
        self.assertGreater(score, 0)

    def test_unrelated_course_scores_zero(self):
        evidence = "3학년 2학기 전공선택 사회심리학(3.0학점) — 사회적 상황에서 개인의 사고와 행동을 탐구한다."
        score = _keyword_score("시스템 프로그래머", evidence)
        self.assertEqual(0, score)


if __name__ == "__main__":
    unittest.main()
