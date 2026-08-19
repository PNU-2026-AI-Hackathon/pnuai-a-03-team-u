"""별표2 "영역별 졸업기준 학점" 파서 테스트.

이 파서가 왜 생겼는지는 파서 모듈 docstring 참고 — `graduation_requirements`의
전공 학점이 원문과 어긋나 있었고(전공필수 36/전공선택 41 vs 원문 37/40), **합계가
같아서 조용히 지나갔다**.

표 모양은 실제 HWP(2024·2026 컴퓨터공학전공)를 hwp5html로 변환한 결과 그대로다.
"""

import unittest

from app.ingestion.parsers.annex2_curriculum import (
    Annex2Credits,
    parse_annex2,
    _split_deep_major,
)


def _xhtml(rows: list[list[str]]) -> str:
    body = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
    )
    return f"<html><body><table>{body}</table></body></html>"


# 2024학년도: 교양이 교양필수 | 교양선택 두 칸
_ROWS_2024 = [
    ["학과 명", "교 양", "전 공", "일반선택", "졸업기준 학 점"],
    ["교양필수", "교양선택", "최소전공", "심화전공"],
    ["전공기초", "전공일반 (필수/선택)"],
    ["정보컴퓨터 공학부 컴퓨터공학 전공", "10", "15", "25",
     "33 (전공필수)", "44 (전공필수 4 전공선택 40)", "6", "133"],
]

# 2026학년도: 교양이 효원핵심 | 효원균형(기초) | 효원창의 세 칸
_ROWS_2026 = [
    ["학과 명", "교 양", "전 공", "일반선택", "졸업기준 학 점"],
    ["효원핵심교양", "효원균형 교양 (기초교양)", "효원창의교양", "최소전공", "심화전공"],
    ["전공기초", "전공일반 (필수/선택)"],
    ["정보컴퓨터 공학부 컴퓨터공학 전공", "10", "9 (3)", "6", "25",
     "33 (전공필수)", "44 (전공필수 4 전공선택 40)", "6", "133"],
]


class ParseAnnex2Test(unittest.TestCase):
    def test_2024_layout(self):
        c = parse_annex2(_xhtml(_ROWS_2024))
        self.assertEqual(
            {
                "required_total_credits": 133,
                "required_major_foundation": 25,
                "required_major_required": 33,
                "required_major_elective": 44,
                "required_general_required": 10,
                "required_general_elective": 15,
                "required_free_elective": 6,
            },
            c.as_columns(),
        )
        self.assertTrue(c.sums_to_total())

    def test_2026_layout_merges_two_general_elective_columns(self):
        """2026은 효원균형 + 효원창의를 합쳐 교양선택으로 본다(기존 시드와 같은 규칙)."""
        c = parse_annex2(_xhtml(_ROWS_2026))
        self.assertEqual(15, c.required_general_elective)   # 9 + 6
        self.assertEqual(10, c.required_general_required)
        self.assertTrue(c.sums_to_total())

    def test_minimum_and_deep_major_are_not_merged(self):
        """**핵심**: 최소전공과 심화전공은 서로 다른 축이라 합치지 않는다.

        전공기초 25 + 전공필수(최소전공) 33 = 최소전공인정학점 58이고,
        심화전공 44(전공필수 4 + 전공선택 40)는 심화로 졸업할 때 더 듣는 몫이다.
        심화전공의 "전공필수 4"를 최소전공에 더해 37로 만들면 학교 졸업요건 화면이
        쓰는 값(전공필수 33)과 4학점 어긋난다 — 2026-08-19 실계정 대조로 확인.
        """
        c = parse_annex2(_xhtml(_ROWS_2024))
        self.assertEqual(33, c.required_major_required)
        self.assertEqual(44, c.required_major_elective)
        # 학교가 쓰는 "최소전공인정학점" 단위와 맞는지도 같이 고정한다.
        self.assertEqual(58, c.required_major_foundation + c.required_major_required)

    def test_deep_major_without_detail_goes_to_elective(self):
        """괄호 세부가 없으면 전부 전공선택. 추측으로 필수에 배분하지 않는다."""
        self.assertEqual((0.0, 44.0), _split_deep_major("44"))

    def test_deep_major_detail_mismatch_raises(self):
        """세부 합이 대표값과 다르면 조용히 넘어가면 안 된다."""
        with self.assertRaises(ValueError):
            _split_deep_major("44 (전공필수 4 전공선택 30)")

    def test_unexpected_column_count_raises(self):
        rows = [r[:] for r in _ROWS_2024]
        rows[-1] = rows[-1][:-1]
        with self.assertRaises(ValueError):
            parse_annex2(_xhtml(rows))

    def test_missing_credit_table_raises(self):
        with self.assertRaises(ValueError):
            parse_annex2(_xhtml([["엉뚱한", "표"], ["1", "2"]]))

    def test_sums_to_total_detects_bad_split(self):
        bad = Annex2Credits("x", 133, 25, 36, 41, 10, 15, 6)
        self.assertTrue(bad.sums_to_total())   # 합계만으로는 못 잡는다 — 그래서 이 사고가 났다
        worse = Annex2Credits("x", 133, 25, 36, 40, 10, 15, 6)
        self.assertFalse(worse.sums_to_total())


if __name__ == "__main__":
    unittest.main()
