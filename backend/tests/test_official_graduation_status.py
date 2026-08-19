"""One-Stop 졸업예정정보의 **학교 공식 판정** 저장 테스트.

이 데이터는 원래 크롤링은 되는데 `portal_sync`가 표 0(학적신청)과 균형교양 세부영역만
쓰고 **나머지를 통째로 버려서**, "졸업요건이랑 토익 등 자격증을 못 가져온다"는 문제로
보였다(2026-08-16 실측으로 확인).

여기서는 정규화 결과 → DB upsert 경로만 본다(네트워크 없음).
"""

import datetime
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.domains.academics.models import (
    StudentGraduationCategory,
    StudentGraduationRequirement,
)
from app.domains.users.models import User
from app.ingestion.normalizers.graduation_status_normalizer import (
    upsert_official_graduation_status,
)


_TABLES = [
    User.__table__,
    StudentGraduationCategory.__table__,
    StudentGraduationRequirement.__table__,
]


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=_TABLES)
    db = sessionmaker(bind=engine)()
    db.add(User(id=1, email="t@e.com", password_hash="x", name="테스트"))
    db.flush()
    return db


def _category(program="주전공", category="전공필수", required=33.0, earned=26.0,
              status="N", reason="전공필수학점미달"):
    return {
        "program_type": program, "category": category,
        "required_credits": required, "earned_credits": earned,
        "registered_credits": 0.0, "expected_credits": 0.0,
        "completed_status": status, "failure_reason": reason,
    }


def _requirement(name="표준외국어능력시험", status="N", program="주전공", detail="",
                 pass_type="", acquired_date=""):
    """실제 크롤 원문과 **같은 키**를 쓴다.

    처음엔 합격구분·취득일자를 `졸업기준_*`로 적었는데 원문엔 그런 키가 없다
    (`학생이수정보_*`가 맞다). 픽스처가 코드와 같은 오타를 쓰고 있어서 **테스트가
    버그를 고정**하고 있었다 — 요건을 통과한 학생의 합격구분·취득일자가 조용히
    버려지는데도 8건이 전부 통과했다.

    실제 키 (표 6 `graduation_requirement_completion`):
        ['No', '졸업기준_상세졸업요건명', '졸업기준_졸업요건명', '졸업기준_학적신청구분',
         '학생이수정보_비고_예외사항_상세내역_점수', '학생이수정보_이수여부',
         '학생이수정보_취득일자', '학생이수정보_합격구분']
    """
    return {
        "requirement_area": "graduation_requirement_completion",
        "source_table_name": "graduation_requirement_completion",
        "required_category": name,
        "required_course_name": detail,
        "completed_status": status,
        "note": "",
        "raw_record": {
            "졸업기준_학적신청구분": program,
            "졸업기준_졸업요건명": name,
            "학생이수정보_합격구분": pass_type,
            "학생이수정보_취득일자": acquired_date,
            "학생이수정보_이수여부": status,
        },
    }


def _no_records_requirement():
    """"조회내역이 없습니다." — 학교가 "요건 없음"이라고 답한 신호."""
    return {
        "requirement_area": "graduation_requirement_completion",
        "source_table_name": "graduation_requirement_completion",
        "completed_status": "no_records",
        "note": "조회내역이 없습니다.",
        "raw_record": {"no_records": "Y", "message": "조회내역이 없습니다."},
    }


class UpsertOfficialStatusTest(unittest.TestCase):
    def test_categories_and_requirements_are_stored(self):
        db = _make_db()
        stats = upsert_official_graduation_status(db, 1, {
            "category_statuses": [_category(), _category(category="교양선택", required=12.0,
                                                         earned=15.0, status="Y", reason="")],
            "requirement_items": [_requirement(), _requirement(name="TOPCIT")],
        })
        self.assertEqual(2, stats["categories_created"])
        self.assertEqual(2, stats["requirements_created"])

        rows = db.query(StudentGraduationCategory).all()
        by_category = {r.category: r for r in rows}
        self.assertFalse(by_category["전공필수"].satisfied)
        self.assertEqual("전공필수학점미달", by_category["전공필수"].failure_reason)
        self.assertTrue(by_category["교양선택"].satisfied)
        # 사유가 빈 문자열이면 None으로 (빈 문자열과 "없음"을 구분할 이유가 없다)
        self.assertIsNone(by_category["교양선택"].failure_reason)

        names = {r.requirement_name for r in db.query(StudentGraduationRequirement).all()}
        self.assertEqual({"표준외국어능력시험", "TOPCIT"}, names)

    def test_upsert_is_idempotent(self):
        db = _make_db()
        payload = {"category_statuses": [_category()], "requirement_items": [_requirement()]}
        upsert_official_graduation_status(db, 1, payload)
        stats = upsert_official_graduation_status(db, 1, payload)

        self.assertEqual(0, stats["categories_created"])
        self.assertEqual(1, stats["categories_updated"])
        self.assertEqual(1, db.query(StudentGraduationCategory).count())
        self.assertEqual(1, db.query(StudentGraduationRequirement).count())

    def test_stale_rows_are_removed(self):
        """스냅샷이므로 이번 크롤에 없는 행은 지운다.

        복수전공을 포기하면 그 프로그램 행이 남아 "충족 못 한 요건"으로 계속 보인다.
        """
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [_category(), _category(program="복수전공")],
            "requirement_items": [_requirement(), _requirement(name="TOPCIT")],
        })
        stats = upsert_official_graduation_status(db, 1, {
            "category_statuses": [_category()],
            "requirement_items": [_requirement()],
        })

        self.assertEqual(1, stats["categories_deleted"])
        self.assertEqual(1, stats["requirements_deleted"])
        self.assertEqual(1, db.query(StudentGraduationCategory).count())
        self.assertEqual(1, db.query(StudentGraduationRequirement).count())

    def test_empty_crawl_does_not_wipe_snapshot(self):
        """페이지 구조 변경이나 일시적 실패로 빈 결과가 왔을 때 멀쩡한 스냅샷을
        통째로 날리는 게 제일 나쁘다."""
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [_category()], "requirement_items": [_requirement()],
        })
        stats = upsert_official_graduation_status(db, 1, {
            "category_statuses": [], "requirement_items": [],
        })

        self.assertEqual(0, stats["categories_deleted"])
        self.assertEqual(1, db.query(StudentGraduationCategory).count())
        self.assertEqual(1, db.query(StudentGraduationRequirement).count())

    def test_unknown_completed_status_is_none_not_false(self):
        """Y/N이 아닌 값을 False로 떨어뜨리면 "학교가 미충족이라 했다"와
        "우리가 못 읽었다"가 구분되지 않는다."""
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [_category(status="")],
            "requirement_items": [_requirement(status="???")],
        })
        self.assertIsNone(db.query(StudentGraduationCategory).one().satisfied)
        self.assertIsNone(db.query(StudentGraduationRequirement).one().satisfied)

    def test_no_records_rows_are_skipped(self):
        """"조회내역이 없습니다." 행은 요건이 아니다."""
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [],
            "requirement_items": [{
                "requirement_area": "graduation_requirement_completion",
                "source_table_name": "graduation_requirement_completion",
                "completed_status": "no_records",
                "raw_record": {"no_records": "Y"},
            }],
        })
        self.assertEqual(0, db.query(StudentGraduationRequirement).count())

    def test_other_tables_rows_are_ignored(self):
        """같은 requirement_items에 다른 표(필수과목·교양영역) 행이 섞여 온다."""
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [],
            "requirement_items": [
                {"source_table_name": "required_course_completion",
                 "required_category": "교양필수", "required_course_name": "고전읽기와토론",
                 "completed_status": "N", "raw_record": {}},
                _requirement(),
            ],
        })
        rows = db.query(StudentGraduationRequirement).all()
        self.assertEqual(["표준외국어능력시험"], [r.requirement_name for r in rows])

    def test_pass_type_and_acquired_date_are_stored(self):
        """요건을 이미 통과한 학생의 합격구분·취득일자가 버려지면 안 된다.

        원문 키는 `학생이수정보_*`인데 `졸업기준_*`으로 읽고 있었다. 이 변경이
        고치겠다던 "가져와놓고 버린다"를 컬럼 2개에서 그대로 반복한 셈이었다.
        """
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [],
            "requirement_items": [_requirement(
                name="TOPCIT", status="Y", pass_type="합격", acquired_date="2026-03-15",
            )],
        })
        row = db.query(StudentGraduationRequirement).one()
        self.assertEqual("합격", row.pass_type)
        self.assertEqual("2026-03-15", row.acquired_date)
        self.assertTrue(row.satisfied)

    def test_school_reporting_no_requirements_clears_stale_rows(self):
        """학교가 "조회내역이 없습니다"라고 답하면 옛 요건을 지워야 한다.

        그 신호를 버리면 "학교가 요건을 지웠다"와 "파싱이 깨졌다"가 구분되지 않아
        옛 행이 영원히 미충족으로 남는다.
        """
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [], "requirement_items": [_requirement()],
        })
        self.assertEqual(1, db.query(StudentGraduationRequirement).count())

        stats = upsert_official_graduation_status(db, 1, {
            "category_statuses": [], "requirement_items": [_no_records_requirement()],
        })
        self.assertEqual(1, stats["requirements_deleted"])
        self.assertEqual(0, db.query(StudentGraduationRequirement).count())

    def test_parse_degradation_does_not_clear_rows(self):
        """표 6은 왔는데 **파싱만 실패**하면 지우면 안 된다.

        "학교가 요건 없음이라 답함"과 "컬럼명이 바뀌어 못 읽음"은 다르다. 플래그를
        `no_records` 분기 밖에 두면 둘이 같아져서, 표가 정상적으로 왔는데 컬럼명만
        바뀐 경우에 **요건 스냅샷을 통째로 날린다** — 원래 가드가 막으려던 그 케이스다.
        (이 변경 자체가 컬럼명 접두어를 틀린 전례가 있어 현실성이 충분하다.)
        """
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [], "requirement_items": [_requirement()],
        })

        # 표 6 행은 3개 왔는데 학적신청구분 키 이름이 바뀌어 전부 파싱 실패
        broken = []
        for name in ("표준외국어능력시험", "TOPCIT", "졸업과제"):
            row = _requirement(name=name)
            row["raw_record"] = {"졸업기준_학적신청구분_변경됨": "주전공"}
            broken.append(row)
        stats = upsert_official_graduation_status(db, 1, {
            "category_statuses": [], "requirement_items": broken,
        })

        self.assertEqual(0, stats["requirements_deleted"])
        self.assertEqual(1, db.query(StudentGraduationRequirement).count())

    def test_rows_from_other_tables_do_not_clear_requirements(self):
        """표 2·3 행만 온 페이로드가 요건을 지우면 안 된다.

        `source_table_name` 검사는 중복 방어가 아니라 **유일한 방어**다.
        """
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [], "requirement_items": [_requirement()],
        })
        stats = upsert_official_graduation_status(db, 1, {
            "category_statuses": [],
            "requirement_items": [{
                "source_table_name": "required_course_completion",
                "required_category": "교양필수", "required_course_name": "고전읽기와토론",
                "completed_status": "N", "raw_record": {},
            }],
        })
        self.assertEqual(0, stats["requirements_deleted"])
        self.assertEqual(1, db.query(StudentGraduationRequirement).count())

    def test_requirement_lookup_is_scoped_to_user(self):
        """요건 쪽 `existing` 조회에도 user_id가 필요하다.

        기존 스코프 테스트는 두 학생에게 **서로 다른 요건명**을 줘서 충돌이 안 났다.
        같은 (program_type, requirement_name, detail_name)을 줘야 실제로 덮어쓰기가 난다.
        """
        db = _make_db()
        db.add(User(id=2, email="other@e.com", password_hash="x", name="남"))
        db.flush()
        upsert_official_graduation_status(db, 2, {
            "category_statuses": [],
            "requirement_items": [_requirement(status="Y", pass_type="합격",
                                               acquired_date="2025-01-01")],
        })
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [],
            "requirement_items": [_requirement(status="N")],
        })

        r2 = db.query(StudentGraduationRequirement).filter_by(user_id=2).one()
        self.assertTrue(r2.satisfied, msg="남의 요건이 덮어써졌다")
        self.assertEqual("합격", r2.pass_type)
        r1 = db.query(StudentGraduationRequirement).filter_by(user_id=1).one()
        self.assertFalse(r1.satisfied)

    def test_duplicate_requirement_rows_keep_the_first(self):
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [],
            "requirement_items": [
                _requirement(status="Y", pass_type="합격"),
                _requirement(status="N", pass_type="불합격"),
            ],
        })
        row = db.query(StudentGraduationRequirement).one()
        self.assertEqual("합격", row.pass_type)

    def test_parse_failure_still_does_not_clear_rows(self):
        """표 자체가 안 온 경우(파싱 실패)는 여전히 지우지 않는다."""
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [], "requirement_items": [_requirement()],
        })
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [], "requirement_items": [],
        })
        self.assertEqual(1, db.query(StudentGraduationRequirement).count())

    def test_other_users_rows_are_untouched(self):
        """**개인 학사정보다.** user_id 스코프가 빠지면 남의 데이터를 덮어쓰거나 지운다.

        이 경로에 테스트가 하나도 없어서, 스코프 필터를 제거하는 뮤테이션이 전부
        살아남았다(독립 리뷰 지적).
        """
        db = _make_db()
        db.add(User(id=2, email="other@e.com", password_hash="x", name="남"))
        db.flush()
        other = {"category_statuses": [_category(category="교양선택")],
                 "requirement_items": [_requirement(name="TOPCIT")]}
        upsert_official_graduation_status(db, 2, other)

        # user 1이 완전히 다른 내용으로 동기화해도 user 2 것은 그대로여야 한다.
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [_category()], "requirement_items": [_requirement()],
        })

        rows2 = db.query(StudentGraduationCategory).filter_by(user_id=2).all()
        self.assertEqual(["교양선택"], [r.category for r in rows2])
        reqs2 = db.query(StudentGraduationRequirement).filter_by(user_id=2).all()
        self.assertEqual(["TOPCIT"], [r.requirement_name for r in reqs2])
        self.assertEqual(1, db.query(StudentGraduationCategory).filter_by(user_id=1).count())

    def test_existing_row_lookup_is_scoped_to_user(self):
        """upsert의 기존 행 조회에 user_id가 빠지면 **남의 행을 덮어쓴다.**

        stale-delete 쪽만 막으면 이 경로가 열려 있다 — 같은 (program_type, category)를
        가진 다른 학생 행을 찾아 그 학점을 내 값으로 갈아끼운다.
        """
        db = _make_db()
        db.add(User(id=2, email="other@e.com", password_hash="x", name="남"))
        db.flush()
        upsert_official_graduation_status(db, 2, {
            "category_statuses": [_category(earned=99.0)], "requirement_items": [],
        })
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [_category(earned=26.0)], "requirement_items": [],
        })

        # 각자 자기 값을 가져야 한다 (스코프가 없으면 user 2 행이 26.0으로 덮인다).
        self.assertEqual(
            99.0, float(db.query(StudentGraduationCategory).filter_by(user_id=2).one().earned_credits))
        self.assertEqual(
            26.0, float(db.query(StudentGraduationCategory).filter_by(user_id=1).one().earned_credits))
        self.assertEqual(2, db.query(StudentGraduationCategory).count())

    def test_no_records_row_is_not_stored_as_a_requirement(self):
        """"조회내역이 없습니다."는 요건이 아니다 — 행으로 저장되면 안 된다.

        (삭제 신호로 쓰는 것과는 별개다. `test_school_reporting_no_requirements_clears_stale_rows`
        는 삭제를, 이건 저장 안 함을 본다.)
        """
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [],
            "requirement_items": [_no_records_requirement(), _requirement()],
        })
        rows = db.query(StudentGraduationRequirement).all()
        self.assertEqual(["표준외국어능력시험"], [r.requirement_name for r in rows])

    def test_duplicate_rows_keep_the_first(self):
        """중복 행이 오면 첫 행만 반영한다(그리고 warning). 뒤 행이 이기면 안 된다."""
        db = _make_db()
        upsert_official_graduation_status(db, 1, {
            "category_statuses": [_category(earned=26.0), _category(earned=99.0)],
            "requirement_items": [],
        })
        self.assertEqual(26.0, float(db.query(StudentGraduationCategory).one().earned_credits))

    def test_synced_at_is_recorded(self):
        db = _make_db()
        stamp = datetime.datetime(2026, 8, 19, 12, 0, tzinfo=datetime.UTC)
        upsert_official_graduation_status(
            db, 1, {"category_statuses": [_category()], "requirement_items": []},
            synced_at=stamp,
        )
        stored = db.query(StudentGraduationCategory).one().synced_at
        # assertIsNotNone만 하면 synced_at 인자를 무시하는 변이가 살아남는다.
        self.assertEqual(stamp.replace(tzinfo=None), stored.replace(tzinfo=None))


if __name__ == "__main__":
    unittest.main()
