"""신입학/편입학 값 해석.

컬럼이 nullable이라 이 값이 생기기 전에 가입한 사용자는 NULL이고, 손으로 넣은
오타가 들어올 수도 있다. 편입 처리는 화면에서 1·2학년을 감추는 파괴적인 동작이라
확신이 없으면 하지 않는 쪽이 안전하다.
"""

import unittest

from app.domains.users.admission import entry_grade, is_transfer, normalize_admission_type


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


if __name__ == "__main__":
    unittest.main()
