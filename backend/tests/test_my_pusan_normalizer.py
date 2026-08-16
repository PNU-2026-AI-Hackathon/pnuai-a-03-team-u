"""my.pusan.ac.kr 크롤 결과 → 비교과/자격증/어학성적 매핑 테스트.

## 세션 설정을 운영과 맞춘다 (중요)

이 테스트들은 `autoflush=False`로 세션을 만든다. 운영의 `SessionLocal`이 그렇기 때문이다
(`app/core/db.py`). 기본값(`autoflush=True`)으로 테스트하면 **운영에서만 나는 버그를
못 잡는다** — 실제로 2026-08-14에 그 차이로 중복 저장 버그가 숨어 있었다:

    autoflush=True  (테스트 기본값)  → 같은 자격증 2번 입력 시 1행  ✅ 통과해버림
    autoflush=False (운영 SessionLocal) → 2행  ❌ 중복

`db.add()` 후 flush하지 않으면 같은 루프의 다음 조회에 그 행이 안 보이기 때문이다.
"""

import datetime
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.domains.academics.models import College, Department, Major, School
from app.domains.users.models import User, UserActivity, UserCertification, UserLanguageScore
from app.ingestion.normalizers.my_pusan_normalizer import (
    _parse_date,
    _parse_date_range,
    upsert_certifications,
    upsert_extracurricular_activities,
    upsert_language_scores,
)

_TABLES = [
    School.__table__, College.__table__, Department.__table__, Major.__table__,
    User.__table__, UserActivity.__table__, UserCertification.__table__,
    UserLanguageScore.__table__,
]


def _make_db():
    """운영과 동일하게 autoflush=False. 이 설정이 이 파일 테스트의 핵심이다."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=_TABLES)
    db = sessionmaker(bind=engine, autoflush=False)()
    db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트"))
    db.flush()
    return db


class ParseDateTest(unittest.TestCase):
    def test_common_formats(self):
        for text in ("2024-05-01", "2024.05.01", "2024/05/01"):
            self.assertEqual(datetime.date(2024, 5, 1), _parse_date(text))

    def test_year_month_becomes_first_day(self):
        self.assertEqual(datetime.date(2024, 3, 1), _parse_date("2024-03"))

    def test_weekday_suffix_is_absorbed(self):
        self.assertEqual(datetime.date(2024, 5, 1), _parse_date("2024-05-01(수)"))

    def test_invalid_and_empty(self):
        self.assertIsNone(_parse_date("날짜없음"))
        self.assertIsNone(_parse_date(""))
        self.assertIsNone(_parse_date(None))
        self.assertIsNone(_parse_date("2024-13-45"))   # 존재하지 않는 날짜

    def test_range(self):
        self.assertEqual(
            (datetime.date(2024, 3, 1), datetime.date(2025, 2, 1)),
            _parse_date_range("2024-03 ~ 2025-02"),
        )

    def test_range_with_single_date(self):
        self.assertEqual((datetime.date(2024, 3, 1), None), _parse_date_range("2024-03"))

    def test_range_empty(self):
        self.assertEqual((None, None), _parse_date_range(""))


class CertificationUpsertTest(unittest.TestCase):
    ROW = {"name": "정보처리기사", "issuer": "한국산업인력공단",
           "certificate_no": "24201234", "issued_at": "2024-05-01"}

    def test_details_are_kept_in_display_name(self):
        """스키마에 발급기관/번호/취득일 컬럼이 없어 name에 병기한다 — 정보 손실 방지."""
        db = _make_db()
        upsert_certifications(db, 1, [self.ROW])
        name = db.query(UserCertification).one().name
        self.assertIn("정보처리기사", name)
        self.assertIn("한국산업인력공단", name)
        self.assertIn("24201234", name)
        self.assertIn("2024-05-01", name)

    def test_duplicate_within_one_call_is_not_stored_twice(self):
        """크롤 결과에 같은 자격증이 두 번 올 수 있다. autoflush=False에서 재현되던 버그."""
        db = _make_db()
        created, _ = upsert_certifications(db, 1, [self.ROW, self.ROW])
        self.assertEqual(1, created)
        self.assertEqual(1, db.query(UserCertification).count())

    def test_rerun_is_idempotent(self):
        db = _make_db()
        upsert_certifications(db, 1, [self.ROW])
        created, _ = upsert_certifications(db, 1, [self.ROW])
        self.assertEqual(0, created)
        self.assertEqual(1, db.query(UserCertification).count())

    def test_nameless_row_is_skipped(self):
        db = _make_db()
        created, _ = upsert_certifications(db, 1, [{"issuer": "어딘가"}])
        self.assertEqual(0, created)
        self.assertEqual(0, db.query(UserCertification).count())


class LanguageScoreUpsertTest(unittest.TestCase):
    ROW = {"test_name": "TOEIC", "score": "900"}

    def test_duplicate_within_one_call_is_not_stored_twice(self):
        db = _make_db()
        created, _ = upsert_language_scores(db, 1, [self.ROW, self.ROW])
        self.assertEqual(1, created)
        self.assertEqual(1, db.query(UserLanguageScore).count())

    def test_different_score_is_a_new_row(self):
        """같은 시험을 다시 봐서 점수가 오르면 별개 기록으로 남는다 (키가 test_name+score)."""
        db = _make_db()
        upsert_language_scores(db, 1, [self.ROW])
        upsert_language_scores(db, 1, [{"test_name": "TOEIC", "score": "950"}])
        self.assertEqual(2, db.query(UserLanguageScore).count())

    def test_incomplete_row_is_skipped(self):
        db = _make_db()
        created, _ = upsert_language_scores(db, 1, [{"test_name": "TOEIC"}, {"score": "900"}])
        self.assertEqual(0, created)


class ExtracurricularActivityUpsertTest(unittest.TestCase):
    # 필드명은 크롤러 출력 기준이다 — raw_date(활동기간), institution(주관기관).
    ROW = {"title": "교내 봉사활동", "raw_date": "2024-03 ~ 2024-06",
           "category": "봉사", "institution": "학생처"}

    def test_period_is_split_into_start_and_end(self):
        db = _make_db()
        upsert_extracurricular_activities(db, 1, [self.ROW])
        act = db.query(UserActivity).one()
        self.assertEqual(datetime.date(2024, 3, 1), act.start_date)
        self.assertEqual(datetime.date(2024, 6, 1), act.end_date)

    def test_duplicate_within_one_call_is_not_stored_twice(self):
        db = _make_db()
        created, _ = upsert_extracurricular_activities(db, 1, [self.ROW, self.ROW])
        self.assertEqual(1, created)
        self.assertEqual(1, db.query(UserActivity).count())

    def test_rerun_updates_end_date_without_duplicating(self):
        """진행 중이던 활동이 끝나면 종료일만 갱신돼야 한다."""
        db = _make_db()
        upsert_extracurricular_activities(db, 1, [{**self.ROW, "raw_date": "2024-03"}])
        created, updated = upsert_extracurricular_activities(db, 1, [self.ROW])
        self.assertEqual(0, created)
        self.assertEqual(1, updated)
        act = db.query(UserActivity).one()
        self.assertEqual(datetime.date(2024, 6, 1), act.end_date)

    def test_titleless_row_is_skipped(self):
        db = _make_db()
        created, _ = upsert_extracurricular_activities(db, 1, [{"raw_date": "2024-03"}])
        self.assertEqual(0, created)


if __name__ == "__main__":
    unittest.main()
