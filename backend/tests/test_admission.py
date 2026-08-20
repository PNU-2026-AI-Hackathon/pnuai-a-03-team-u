"""신입학/편입학 값 해석.

컬럼이 nullable이라 이 값이 생기기 전에 가입한 사용자는 NULL이고, 손으로 넣은
오타가 들어올 수도 있다. 편입 처리는 화면에서 1·2학년을 감추는 파괴적인 동작이라
확신이 없으면 하지 않는 쪽이 안전하다.
"""

import unittest

from app.domains.users.admission import (
    entry_grade,
    infer_admission_type_from_status_changes,
    is_transfer,
    normalize_admission_type,
)


class NormalizeAdmissionTypeTest(unittest.TestCase):
    def test_transfer만_편입으로_본다(self):
        self.assertEqual("transfer", normalize_admission_type("transfer"))
        self.assertTrue(is_transfer("transfer"))

    def test_null과_모르는_값은_신입학으로_떨어진다(self):
        for value in (None, "", "freshman", "TRANSFER", "편입", "unknown"):
            with self.subTest(value=value):
                self.assertEqual("freshman", normalize_admission_type(value))
                self.assertFalse(is_transfer(value))

    def test_편입생은_3학년부터_신입생은_1학년부터(self):
        self.assertEqual(3, entry_grade("transfer"))
        self.assertEqual(1, entry_grade("freshman"))
        self.assertEqual(1, entry_grade(None))


class InferAdmissionTypeFromStatusChangesTest(unittest.TestCase):
    """학적부 학적변동 내역 → admission_type 자동 판정.

    회원가입 때 사용자가 고르는 값에만 의존하면, 잘못 고른 순간 로드맵 학년이
    통째로 어긋난다(편입생이 1학년으로 잡혀 1·2학년 과목을 추천받음).
    """

    def test_편입학_행이_있으면_transfer(self):
        rows = [{"학년도": "2026", "학기": "1학기", "변동일자": "2026-03-01",
                 "변동구분": "편입학", "취소여부": "N"}]
        self.assertEqual("transfer", infer_admission_type_from_status_changes(rows))

    def test_취소된_편입은_무시한다(self):
        rows = [{"변동구분": "편입학", "취소여부": "Y"}]
        self.assertIsNone(infer_admission_type_from_status_changes(rows))

    def test_편입이_아닌_변동은_판정하지_않는다(self):
        rows = [{"변동구분": "휴학", "취소여부": "N"},
                {"변동구분": "복학", "취소여부": "N"}]
        self.assertIsNone(infer_admission_type_from_status_changes(rows))

    def test_빈_입력은_판정불가로_None(self):
        """None을 돌려줘야 호출부가 기존 값을 유지한다 — freshman으로 덮어쓰면 안 된다."""
        for rows in (None, []):
            with self.subTest(rows=rows):
                self.assertIsNone(infer_admission_type_from_status_changes(rows))

    def test_편입_표기가_바뀌어도_부분일치로_잡는다(self):
        rows = [{"변동구분": "일반편입학", "취소여부": "N"}]
        self.assertEqual("transfer", infer_admission_type_from_status_changes(rows))


if __name__ == "__main__":
    unittest.main()
