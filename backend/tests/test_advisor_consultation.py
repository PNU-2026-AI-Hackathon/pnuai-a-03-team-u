"""지도교수 상담내역 조회 테스트.

2026-08-19 관측: 이 조회가 `None`을 돌려줘서 상담을 완료한 학생의 `advisor_consulted`가
갱신되지 않았다. 곧바로 다시 돌리니 정상이었고(단독 5회 + 동일 메뉴 순서 1회 전부 재현
실패) 원인은 특정하지 못했다. 문제는 실패가 **정상적인 "신청 내역 없음"과 똑같이
`None`** 이라 아무도 모른다는 것이었다.

여기서는 네트워크 없이 판정 로직만 본다 — 표 추출 결과를 시나리오로 주입한다.
"""

import unittest
from unittest.mock import patch

from app.ingestion.crawlers import advisor_consultation as mod


_HEADER = ["상담구분", "상담형태", "교수", "상담내용", "학생신청일자", "상담희망일시", "상태"]
_ROW = ["진로 및 취업", "대면상담", "김태운", "문의", "2026-05-15", "2026-05-18 18:00:00", "완료"]


class _FakePage:
    """extract_tables가 돌려줄 값을 시도 횟수별로 주입한다."""

    def __init__(self, per_attempt, raise_on_attempts=()):
        self._per_attempt = per_attempt
        # 이 시도 번호(1-indexed)에서 goto_menu가 터진다. 재시도는 정의상 "페이지가
        # 이상한 상태"에서만 도는데, goto_menu는 그 상태에서 selectMenu 미정의로
        # ReferenceError를 낸다 — 그게 portal-sync 전체를 502로 만들면 안 된다.
        self._raise_on_attempts = set(raise_on_attempts)
        self.navigations = 0
        self.waits = 0

    def wait_for_timeout(self, ms):
        self.waits += 1

    def tables_for_current_attempt(self):
        i = min(self.navigations - 1, len(self._per_attempt) - 1)
        return self._per_attempt[i]


class _Harness(unittest.TestCase):
    def run_fetch(self, per_attempt, year=2026, semester=1, raise_on_attempts=()):
        page = _FakePage(per_attempt, raise_on_attempts=raise_on_attempts)

        def _goto(p, menu_cd):
            p.navigations += 1
            if p.navigations in p._raise_on_attempts:
                raise RuntimeError("selectMenu is not defined")

        with patch.object(mod, "goto_menu", _goto), \
             patch.object(mod, "extract_tables", lambda p: p.tables_for_current_attempt()):
            return mod.fetch_current_term_consultation_status(page, year, semester), page


class ConsultationFetchTest(_Harness):
    def test_normal_row_is_read(self):
        status, page = self.run_fetch([[[_HEADER, _ROW]]])
        self.assertEqual("완료", status)
        self.assertEqual(1, page.navigations)  # 정상이면 재시도 없음

    def test_missing_table_is_retried(self):
        """표 자체가 없으면 크롤 실패로 보고 한 번 더 시도한다."""
        status, page = self.run_fetch([[], [[_HEADER, _ROW]]])
        self.assertEqual("완료", status)
        self.assertEqual(2, page.navigations)
        self.assertEqual(1, page.waits)

    def test_unexpected_header_is_retried(self):
        status, page = self.run_fetch([[[["엉뚱", "헤더"]]], [[_HEADER, _ROW]]])
        self.assertEqual("완료", status)
        self.assertEqual(2, page.navigations)

    def test_gives_up_after_attempts_and_returns_none(self):
        status, page = self.run_fetch([[], []])
        self.assertIsNone(status)
        self.assertEqual(mod._FETCH_ATTEMPTS, page.navigations)

    def test_header_only_is_not_retried(self):
        """신청 내역이 없는 학생이 흔하다 — 그 경우 재시도는 순수 낭비다."""
        status, page = self.run_fetch([[[_HEADER]]])
        self.assertIsNone(status)
        self.assertEqual(1, page.navigations)
        self.assertEqual(0, page.waits)

    def test_other_term_rows_do_not_match(self):
        """행은 있지만 대상 학기가 아니면 None (재시도 대상 아님)."""
        status, page = self.run_fetch([[[_HEADER, _ROW]]], year=2026, semester=2)
        self.assertIsNone(status)
        self.assertEqual(1, page.navigations)

    def test_navigation_exception_does_not_escape(self):
        """재시도 중 예외가 portal-sync 전체를 502로 만들면 안 된다.

        예전엔 크롤이 실패해도 상담 여부만 갱신이 안 되고 학적부·성적·졸업요건은 정상
        저장됐다. 재시도를 넣으면서 예외를 안 감싸면, 문제를 보이게 만들려다
        **아무것도 저장 안 되는** 상태로 악화시킨다(독립 리뷰 지적).
        """
        status, page = self.run_fetch([[], [[_HEADER, _ROW]]], raise_on_attempts=(1,))
        self.assertEqual("완료", status)   # 1회차 예외 → 2회차 성공
        self.assertEqual(2, page.navigations)

    def test_all_attempts_raising_returns_none(self):
        status, page = self.run_fetch([[], []], raise_on_attempts=(1, 2))
        self.assertIsNone(status)          # 예외가 밖으로 새지 않는다
        self.assertEqual(mod._FETCH_ATTEMPTS, page.navigations)

    def test_table_is_found_even_if_not_first(self):
        """상담내역 표가 첫 번째가 아니어도 찾아야 한다.

        `extract_tables`는 페이지의 **모든 표**를 문서 순서로 돌려준다. 검색 필터나
        레이아웃용 표가 앞에 하나 끼면 예전 코드(`tables[0]`)는 못 찾았고, 재시도로도
        절대 안 고쳐졌다 — 원인 미상 간헐 실패의 유력 가설 중 하나다.
        """
        filler = [["검색조건"], ["2026학년도"]]
        status, page = self.run_fetch([[filler, [_HEADER, _ROW]]])
        self.assertEqual("완료", status)
        self.assertEqual(1, page.navigations)   # 재시도 없이 첫 시도에 찾는다

    def test_latest_row_wins_within_same_term(self):
        older = list(_ROW); older[5], older[6] = "2026-03-02 10:00:00", "신청"
        status, _ = self.run_fetch([[[_HEADER, older, _ROW]]])
        self.assertEqual("완료", status)


if __name__ == "__main__":
    unittest.main()
