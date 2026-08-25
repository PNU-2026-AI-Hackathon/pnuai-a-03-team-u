"""`scripts/eval_syllabus_rag`의 결정론적 부분(nDCG 계산, LLM 판정 응답 파싱)만
단위 테스트한다. 실제 검색/LLM 호출은 API 키·비용이 드는 오프라인 평가라 여기서
재현하지 않는다 — `evaluate_persona`/`run_eval`은 `python -m scripts.eval_syllabus_rag`
로 수동 실행해서 검증한다(스크립트 자체 docstring 참고)."""

import unittest
from unittest.mock import MagicMock, patch

from scripts.eval_syllabus_rag import _judge_relevance, _ndcg_at_k


class NdcgAtKTest(unittest.TestCase):
    def test_all_relevant_gives_perfect_score(self):
        self.assertAlmostEqual(1.0, _ndcg_at_k([True] * 10, 10))

    def test_all_irrelevant_gives_zero(self):
        self.assertEqual(0.0, _ndcg_at_k([False] * 10, 10))

    def test_relevant_items_ranked_lower_score_less_than_ranked_higher(self):
        """관련 있는 결과가 뒤로 밀릴수록 점수가 낮아져야 한다(순위에 민감해야 정상)."""
        top_heavy = _ndcg_at_k([True, True, False, False, False], 5)
        bottom_heavy = _ndcg_at_k([False, False, False, True, True], 5)
        self.assertGreater(top_heavy, bottom_heavy)

    def test_empty_relevance_list_does_not_divide_by_zero(self):
        self.assertEqual(0.0, _ndcg_at_k([], 10))


class JudgeRelevanceParsingTest(unittest.TestCase):
    def _client_returning(self, content: str) -> MagicMock:
        client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content=content))]
        client.chat.completions.create.return_value = response
        return client

    def test_no_candidates_skips_the_api_call(self):
        client = self._client_returning("{}")
        result = _judge_relevance(client, "AI 엔지니어", [])
        self.assertEqual([], result)
        client.chat.completions.create.assert_not_called()

    def test_parses_judgments_key(self):
        """response_format=json_object는 최상위가 object여야 해서, 배열을 바로 못
        돌려주고 "judgments" 키에 담아달라고 프롬프트로 요청한다 — 실측으로 걸렸던
        회귀(2026-08-25): 모델이 배열을 직접 요청받자 json_object 제약 때문에 항목
        하나만 담긴 object로 응답해서, 후보 10개 중 인덱스 1만 판정되고 나머지가
        전부 관련없음으로 잘못 집계됐다."""
        client = self._client_returning(
            '{"judgments": ['
            '{"index": 1, "relevant": true}, '
            '{"index": 2, "relevant": false}, '
            '{"index": 3, "relevant": true}'
            "]}"
        )
        candidates = [{"course_name": f"과목{i}", "evidence": ""} for i in range(3)]
        result = _judge_relevance(client, "AI 엔지니어", candidates)
        self.assertEqual([True, False, True], result)

    def test_missing_index_defaults_to_not_relevant(self):
        """모델이 일부 인덱스를 빠뜨려도(예: 10개 중 8개만 응답) 크래시 대신 나머지는
        관련없음으로 보수적으로 처리한다."""
        client = self._client_returning('{"judgments": [{"index": 2, "relevant": true}]}')
        candidates = [{"course_name": f"과목{i}", "evidence": ""} for i in range(3)]
        result = _judge_relevance(client, "AI 엔지니어", candidates)
        self.assertEqual([False, True, False], result)

    def test_malformed_json_falls_back_to_all_not_relevant(self):
        client = self._client_returning("이건 JSON이 아님")
        candidates = [{"course_name": "과목1", "evidence": ""}]
        result = _judge_relevance(client, "AI 엔지니어", candidates)
        self.assertEqual([False], result)


if __name__ == "__main__":
    unittest.main()
