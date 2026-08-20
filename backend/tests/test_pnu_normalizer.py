"""One-Stop 크롤 결과 → 도메인 모델 매핑(pnu_normalizer) 테스트.

이 경로에는 테스트가 없었는데 졸업요건 판정의 입력을 만드는 곳이다 —
성적표 행이 `student_course_records`가 되고, 그 `category` 합계가 곧 졸업 판정이다.
여기서 잘못 매핑되면 아래 모든 판정이 조용히 틀린다.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.domains.academics.models import (
    College,
    Department,
    GraduationRequirement,
    Major,
    School,
    StudentCourseRecord,
    UserAcademicProgram,
)
from app.domains.courses.models import Course  # noqa: F401 — SCR.course_id FK 해석용
from app.domains.users.models import User
from app.domains.academics.program_status import is_active_program_status
from app.ingestion.normalizers.pnu_normalizer import (
    _grade_to_point,
    _normalize_category,
    _split_college_department_major,
    map_academic_program_registrations,
    map_grades,
    map_student_record,
)

_TABLES = [
    School.__table__, College.__table__, Department.__table__, Major.__table__,
    User.__table__, Course.__table__, UserAcademicProgram.__table__,
    GraduationRequirement.__table__, StudentCourseRecord.__table__,
]

# 성적표 한 학기 표의 실제 구조: 헤더(8열) + 과목 행(8열) + 학기 요약(2열).
_HEADER = ["학년도", "학기", "성적분류", "교과구분", "교과목명", "학점", "성적등급", "비고"]


def _grade_row(year, semester, category, name, credits, grade):
    return [year, semester, "정규", category, name, credits, grade, ""]


class SplitCollegeDepartmentMajorTest(unittest.TestCase):
    """학적부 '소속학과' 원문 분해. 여기서 틀리면 학과·전공이 통째로 어긋난다."""

    def test_college_department_major(self):
        self.assertEqual(
            ("정보의생명공학대학", "의생명융합공학부", "데이터사이언스전공"),
            _split_college_department_major("정보의생명공학대학 의생명융합공학부 데이터사이언스전공"),
        )

    def test_department_without_major(self):
        """'OO과'처럼 세부 전공이 없으면 major는 None이어야 한다."""
        self.assertEqual(
            ("사회과학대학", "심리학과", None),
            _split_college_department_major("사회과학대학 심리학과"),
        )

    def test_department_only(self):
        self.assertEqual((None, "심리학과", None), _split_college_department_major("심리학과"))

    def test_empty_input(self):
        self.assertEqual((None, None, None), _split_college_department_major(""))
        self.assertEqual((None, None, None), _split_college_department_major(None))


class NormalizeCategoryTest(unittest.TestCase):
    def test_strips_parenthetical(self):
        self.assertEqual("전공기초", _normalize_category("전공기초(학부)"))

    def test_alias_is_mapped(self):
        self.assertEqual("교양선택", _normalize_category("기초교양"))

    def test_passthrough_and_empty(self):
        self.assertEqual("전공필수", _normalize_category("전공필수"))
        self.assertIsNone(_normalize_category(""))


class GradeToPointTest(unittest.TestCase):
    """성적등급 → 평점.

    이 값이 없으면 재수강 기능이 통째로 죽는다 — `_compute_retake_candidates`가
    `grade_point is None`인 행을 판단 불가로 전부 제외하기 때문이다.
    2026-08-14 실측: 운영 DB 87개 기록 전부 grade는 있는데 grade_point가 NULL이었다.
    """

    def test_standard_scale(self):
        for grade, point in [("A+", 4.5), ("A0", 4.0), ("B+", 3.5), ("B0", 3.0),
                              ("C+", 2.5), ("C0", 2.0), ("D0", 1.0), ("F", 0.0)]:
            self.assertEqual(point, _grade_to_point(grade), grade)

    def test_pass_fail_grades_have_no_point(self):
        """'S'(Pass)는 평점이 없다. 0.0으로 두면 재수강 후보로 잘못 잡힌다."""
        for grade in ("S", "P", "NP", "U", "", None):
            self.assertIsNone(_grade_to_point(grade), grade)

    def test_case_and_whitespace_tolerant(self):
        self.assertEqual(4.5, _grade_to_point(" a+ "))


class MapGradesTest(unittest.TestCase):
    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_TABLES)
        # 운영 SessionLocal과 같은 autoflush=False — 이 설정에서만 나는 버그가 있다
        # (my_pusan normalizer 중복 저장 건, 2026-08-14).
        db = sessionmaker(bind=engine, autoflush=False)()
        db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트"))
        db.flush()
        return db

    def test_maps_rows_with_grade_point(self):
        db = self.make_db()
        saved = map_grades(db, 1, [[
            _HEADER,
            _grade_row("2025", "1학기", "전공필수", "자료구조", "3", "C0"),
            ["신청학점", "18"],   # 학기 요약 행 — 건너뛰어야 한다
        ]])
        self.assertEqual(1, len(saved))
        rec = saved[0]
        self.assertEqual("자료구조", rec.raw_course_name)
        self.assertEqual("전공필수", rec.category)
        self.assertEqual(3.0, rec.credits)
        self.assertEqual("C0", rec.grade)
        self.assertEqual(2.0, rec.grade_point)   # 재수강 판정의 유일한 근거
        self.assertTrue(rec.is_retake)

    def test_pass_grade_gets_no_point_and_is_not_retake(self):
        db = self.make_db()
        saved = map_grades(db, 1, [[
            _HEADER, _grade_row("2025", "1학기", "교양선택", "봉사활동", "1", "S"),
        ]])
        self.assertIsNone(saved[0].grade_point)
        self.assertFalse(saved[0].is_retake)

    def test_summary_and_header_rows_are_skipped(self):
        db = self.make_db()
        saved = map_grades(db, 1, [[
            _HEADER,
            ["평점평균", "3.85"],
            _grade_row("2025", "1학기", "전공선택", "운영체제", "3", "A0"),
        ]])
        self.assertEqual(["운영체제"], [r.raw_course_name for r in saved])

    def test_unknown_category_row_is_skipped(self):
        """이수구분이 인정 목록에 없으면 실제 과목 행이 아니다 (소계·구분 헤더)."""
        db = self.make_db()
        saved = map_grades(db, 1, [[
            _HEADER, _grade_row("2025", "1학기", "합계", "교양선택", "18", ""),
        ]])
        self.assertEqual([], saved)

    def test_category_alias_is_normalized(self):
        db = self.make_db()
        saved = map_grades(db, 1, [[
            _HEADER, _grade_row("2025", "1학기", "기초교양", "글쓰기", "3", "B+"),
        ]])
        self.assertEqual("교양선택", saved[0].category)

    def test_rerun_updates_instead_of_duplicating(self):
        """포털 동기화는 여러 번 돌린다 — 같은 (과목, 연도, 학기)는 갱신돼야 한다."""
        db = self.make_db()
        table = [[_HEADER, _grade_row("2025", "1학기", "전공필수", "자료구조", "3", "C0")]]
        map_grades(db, 1, table)
        db.commit()
        # 재수강해서 성적이 올랐다고 가정
        map_grades(db, 1, [[_HEADER, _grade_row("2025", "1학기", "전공필수", "자료구조", "3", "B+")]])
        db.commit()

        rows = db.query(StudentCourseRecord).all()
        self.assertEqual(1, len(rows), "같은 학기 같은 과목이 두 행이 되면 학점이 이중 집계된다")
        self.assertEqual(3.5, rows[0].grade_point)
        self.assertFalse(rows[0].is_retake)

    def test_invalid_credits_becomes_none(self):
        db = self.make_db()
        saved = map_grades(db, 1, [[
            _HEADER, _grade_row("2025", "1학기", "전공선택", "이상한과목", "-", "A0"),
        ]])
        self.assertIsNone(saved[0].credits)


class MapStudentRecordTest(unittest.TestCase):
    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_TABLES)
        # 운영 SessionLocal과 같은 autoflush=False — 이 설정에서만 나는 버그가 있다
        # (my_pusan normalizer 중복 저장 건, 2026-08-14).
        db = sessionmaker(bind=engine, autoflush=False)()
        db.add(User(id=1, email="t@example.com", password_hash="x", name="이전이름"))
        db.flush()
        return db

    def test_updates_user_and_creates_primary_program(self):
        db = self.make_db()
        program = map_student_record(db, 1, {
            "성명": "홍길동",
            "학번": "202412345",
            "소속학과": "정보의생명공학대학 정보컴퓨터공학부 컴퓨터공학전공",
            "학년/학기": "3",
            "교육과정적용년도": "2024",
            "학적상태": "재학",
        })
        user = db.get(User, 1)
        self.assertEqual("홍길동", user.name)
        self.assertEqual("202412345", user.student_id)
        self.assertEqual(3, user.academic_year)
        self.assertEqual("primary", program.program_type)
        self.assertEqual("2024", program.curriculum_year)
        self.assertEqual("active", program.status)
        self.assertIsNotNone(program.major_id)

    def test_학년_라벨은_학년슬래시학기다(self):
        """실제 학적부 라벨은 "학년"이 아니라 "학년/학기"다(값 예: "3").

        예전 코드는 `record["학년"]`을 찾아 **항상 빈 문자열**을 읽었고, 그 결과
        academic_year가 영영 None으로 남아 로드맵이 학년을 1로 잡았다. 이 테스트의
        픽스처도 같이 틀린 라벨을 쓰고 있어서 버그를 못 잡았다(2026-08-19).
        """
        db = self.make_db()
        map_student_record(db, 1, {
            "성명": "홍길동", "학번": "202412345",
            "소속학과": "정보의생명공학대학 정보컴퓨터공학부 컴퓨터공학전공",
            "학년/학기": "3", "교육과정적용년도": "2024", "학적상태": "재학",
        })
        self.assertEqual(3, db.get(User, 1).academic_year)

    def test_학년에_학기가_붙어와도_학년만_읽는다(self):
        """"3/1"처럼 학기까지 붙어 나와도 31이 되면 안 된다."""
        db = self.make_db()
        map_student_record(db, 1, {
            "성명": "홍길동", "학번": "202412345",
            "소속학과": "정보의생명공학대학 정보컴퓨터공학부 컴퓨터공학전공",
            "학년/학기": "3/1", "교육과정적용년도": "2024", "학적상태": "재학",
        })
        self.assertEqual(3, db.get(User, 1).academic_year)

    def test_학적변동에_편입학이_있으면_transfer로_잡는다(self):
        db = self.make_db()
        map_student_record(db, 1, {
            "성명": "홍길동", "학번": "202455494",
            "소속학과": "정보의생명공학대학 정보컴퓨터공학부 컴퓨터공학전공",
            "학년/학기": "3", "교육과정적용년도": "2024", "학적상태": "재학",
        }, [{"학년도": "2026", "학기": "1학기", "변동일자": "2026-03-01",
             "변동구분": "편입학", "취소여부": "N"}])
        self.assertEqual("transfer", db.get(User, 1).admission_type)

    def test_학적변동을_못읽으면_기존_admission_type을_유지한다(self):
        """빈 목록은 "신입학"이 아니라 "판정 불가"다.

        표 구조가 바뀌어 못 읽은 경우와 진짜 신입학을 구분할 수 없으므로,
        기존에 transfer로 잡혀 있던 사용자를 freshman으로 덮어쓰면 안 된다.
        """
        db = self.make_db()
        db.get(User, 1).admission_type = "transfer"
        db.flush()
        map_student_record(db, 1, {
            "성명": "홍길동", "학번": "202455494",
            "소속학과": "정보의생명공학대학 정보컴퓨터공학부 컴퓨터공학전공",
            "학년/학기": "3", "교육과정적용년도": "2024", "학적상태": "재학",
        }, [])
        self.assertEqual("transfer", db.get(User, 1).admission_type)

    def test_rerun_updates_the_same_primary_program(self):
        db = self.make_db()
        base = {"성명": "홍길동", "학번": "202412345", "학년/학기": "3",
                "소속학과": "정보의생명공학대학 정보컴퓨터공학부 컴퓨터공학전공",
                "교육과정적용년도": "2024", "학적상태": "재학"}
        map_student_record(db, 1, base)
        db.commit()
        map_student_record(db, 1, {**base, "학년/학기": "4"})
        db.commit()

        programs = db.query(UserAcademicProgram).filter_by(program_type="primary").all()
        self.assertEqual(1, len(programs), "주전공 프로그램이 두 개가 되면 판정이 중복된다")
        self.assertEqual(4, db.get(User, 1).academic_year)

    def test_leave_of_absence_status_is_kept_verbatim(self):
        """휴학이면 status에 원문이 그대로 들어간다.

        이 값 자체는 보존한다 — 판정 대상 여부는 `program_status.ACTIVE_PROGRAM_STATUSES`가
        정하고, 휴학은 거기 포함된다(복학 예정이라 남은 요건을 알아야 한다).
        """
        db = self.make_db()
        program = map_student_record(db, 1, {
            "성명": "홍길동", "학번": "202412345",
            "소속학과": "정보의생명공학대학 정보컴퓨터공학부",
            "교육과정적용년도": "2024", "학적상태": "휴학",
        })
        self.assertEqual("휴학", program.status)
        self.assertTrue(is_active_program_status(program.status))

    def test_withdrawn_status_is_not_active(self):
        """자퇴·제적은 학적이 없어진 것이라 판정 대상이 아니다."""
        db = self.make_db()
        program = map_student_record(db, 1, {
            "소속학과": "정보의생명공학대학 정보컴퓨터공학부",
            "교육과정적용년도": "2024", "학적상태": "자퇴",
        })
        self.assertEqual("자퇴", program.status)
        self.assertFalse(is_active_program_status(program.status))


class MapAcademicProgramRegistrationsTest(unittest.TestCase):
    def make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_TABLES)
        # 운영 SessionLocal과 같은 autoflush=False — 이 설정에서만 나는 버그가 있다
        # (my_pusan normalizer 중복 저장 건, 2026-08-14).
        db = sessionmaker(bind=engine, autoflush=False)()
        db.add(User(id=1, email="t@example.com", password_hash="x", name="테스트"))
        db.flush()
        return db

    def test_maps_labels_to_program_types(self):
        db = self.make_db()
        saved = map_academic_program_registrations(db, 1, [
            ["1", "주전공", "정보컴퓨터공학부 컴퓨터공학전공", "N", "선택"],
            ["2", "복수전공", "수학과", "N", "선택"],
            ["3", "부전공", "경영학과", "N", "선택"],
        ])
        self.assertEqual(["primary", "dual", "minor"], [p.program_type for p in saved])

    def test_unknown_label_and_short_rows_are_skipped(self):
        db = self.make_db()
        saved = map_academic_program_registrations(db, 1, [
            ["순번", "학적신청구분", "학과"],      # 헤더
            ["1", "알수없는구분", "수학과", "N"],
            ["2"],                                  # 열 부족
        ])
        self.assertEqual([], saved)

    def test_rerun_does_not_duplicate(self):
        db = self.make_db()
        rows = [["1", "복수전공", "수학과", "N", "선택"]]
        map_academic_program_registrations(db, 1, rows)
        db.commit()
        map_academic_program_registrations(db, 1, rows)
        db.commit()
        self.assertEqual(1, len(db.query(UserAcademicProgram).filter_by(program_type="dual").all()))

    def test_reuses_existing_department_when_college_missing(self):
        """학적신청 행에는 단과대 표기가 없다. 학적부가 만든 학과를 재사용해야
        '미지정' 단과대 밑에 같은 이름의 학과가 또 생기지 않는다."""
        db = self.make_db()
        map_student_record(db, 1, {
            "소속학과": "자연과학대학 수학과", "교육과정적용년도": "2024", "학적상태": "재학",
        })
        db.commit()
        existing_dept_id = db.get(User, 1).department_id

        saved = map_academic_program_registrations(db, 1, [["1", "복수전공", "수학과", "N", "선택"]])
        self.assertEqual(existing_dept_id, saved[0].department_id)
        self.assertEqual(1, len(db.query(Department).filter_by(name="수학과").all()))


if __name__ == "__main__":
    unittest.main()
