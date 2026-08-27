"""편입생이 직접 등록한 "전적대 과목 ↔ PNU 과목" 대체 관계.

## 왜 이 테스트가 있는가

편입 학점 인정은 규정 표가 아니라 학과가 학생 개인에게 통보하는 것이라 데이터에
근거가 없다. 그래서 시스템은 이름 유사도로 추측하면 안 되고(`데이터구조`≈`자료구조`가
그럴듯해도 학교가 실제로 인정했는지는 학생만 안다), **학생이 고른 값만** 신뢰해야
한다. 여기서 고정하는 것:

1. 학생이 고르기 전에는 아무 일도 일어나지 않는다 — 자동 매핑이 끼어들면 실패한다.
2. 학생이 고르면 **추천에서만** 효과가 난다: 시간표/로드맵이 그 PNU 과목을 이미
   이수한 것으로 보고 후보에서 뺀다. 이게 이 기능의 실제 가치다.
3. **학점은 변하지 않는다.** 전적대 학점은 이수기록 행에 그대로 있고 졸업요건 엔진은
   category별 합계만 대조한다. 대체 등록으로 판정 숫자가 흔들리면 회귀다.
4. 정규 학기 이수기록에는 대체를 지정할 수 없다 — "입학 전 인정 학점" 행 전용이다.
5. **한 줄이 여러 개를 대체할 수 있다(N:M).** 전적대 `교양선택 15학점` 한 줄은 개별
   과목이 아니라 교양 세부영역 여러 개를 채운 것으로 인정받고, 반대로 전적대 두
   과목이 PNU 한 과목을 대체하기도 한다. 단일 컬럼으로 되돌아가면 여기서 깨진다.
"""

import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.portal_sync import (
    CourseRecordInput,
    CourseRecordsReplaceRequest,
    CourseSubstitutionRequest,
    MAX_SUBSTITUTION_COURSES,
    list_course_records,
    replace_course_records,
    set_course_substitutions,
)
from app.core.db import Base
from app.domains.academics.course_substitution import (
    liberal_area_completions,
    set_substitutions,
    substituted_course_names,
    substituting_record,
)
from app.domains.academics.graduation_progress import compute_graduation_progress
from app.domains.academics.models import (
    College,
    Department,
    GraduationRequirement,
    Major,
    ProgramCourse,
    School,
    StudentCourseRecord,
    StudentCourseSubstitution,
    StudentGraduationCategory,
    UserAcademicProgram,
)
from app.domains.courses.models import Course
from app.domains.planning.roadmap_chat import (
    _ToolContext,
    _compute_critical_missing_required,
    _compute_missing_required_available,
    _compute_prereq_blocked,
)
from app.domains.planning.models import CourseRoadmap, CourseRoadmapItem, PendingRoadmapChange
from app.domains.planning.timetable import _completed_course_norms
from app.domains.users.models import User


_TABLES = [
    School.__table__, College.__table__, Department.__table__, Major.__table__,
    User.__table__, Course.__table__, StudentCourseRecord.__table__,
    UserAcademicProgram.__table__, GraduationRequirement.__table__,
    StudentCourseSubstitution.__table__,
    ProgramCourse.__table__, StudentGraduationCategory.__table__,
    CourseRoadmap.__table__, CourseRoadmapItem.__table__, PendingRoadmapChange.__table__,
]


class TransferCourseSubstitutionTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_TABLES)
        self.db = sessionmaker(bind=engine)()

        self.db.add(Department(id=100, college_id=1, name="정보컴퓨터공학부"))
        self.user = User(
            id=1, email="transfer@example.com", password_hash="x", name="편입생",
            department_id=100, admission_type="transfer",
        )
        self.db.add(self.user)
        # 학생이 대체 대상으로 고를 수 있는 PNU 과목.
        self.db.add(Course(
            id=10, course_name="자료구조", category="전공필수", credits=3, department_id=100,
        ))
        # 전적대 이수기록: 성적표에 '데이터구조'로 들어왔고 PNU 교과목번호와 연결이 없다.
        self.transfer_record = StudentCourseRecord(
            id=1, user_id=1, raw_course_name="데이터구조", category="전공필수",
            credits=3, year="2026", semester="입학전성적", source="crawler",
        )
        # 편입 후 PNU에서 정규 학기에 들은 과목.
        self.regular_record = StudentCourseRecord(
            id=2, user_id=1, raw_course_name="운영체제", category="전공필수",
            credits=3, year="2026", semester="1학기", source="crawler",
        )
        self.db.add_all([self.transfer_record, self.regular_record])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_지정하기_전에는_자동으로_매핑되지_않는다(self):
        """이름이 아무리 비슷해도 시스템이 먼저 이어붙이면 안 된다.

        학교가 실제로 무엇을 인정했는지는 데이터에 없기 때문이다. 유사도 추천이
        슬쩍 들어오면 이 테스트가 먼저 깨진다.
        """
        self.assertEqual([], substituted_course_names(self.db, 1))
        self.assertNotIn("자료구조", _completed_course_norms(self.db, 1))

        records = list_course_records(current_user=self.user, db=self.db)
        transfer = next(r for r in records if r.id == 1)
        self.assertTrue(transfer.is_transfer_credit)
        self.assertEqual([], transfer.substitutes)

    def test_학생이_지정하면_추천에서_그_PNU_과목이_빠진다(self):
        """이 기능의 실제 가치. 이미 인정받은 자료구조를 또 추천하면 안 된다."""
        response = set_course_substitutions(
            record_id=1,
            payload=CourseSubstitutionRequest(course_ids=[10]),
            current_user=self.user,
            db=self.db,
        )
        self.assertEqual([(10, "자료구조")],
                         [(s.course_id, s.course_name) for s in response.substitutes])

        self.assertEqual(["자료구조"], substituted_course_names(self.db, 1))
        completed = _completed_course_norms(self.db, 1)
        self.assertIn("자료구조", completed)
        # 전적대 과목명 자체도 그대로 남는다 — 대체가 원본을 지우지는 않는다.
        self.assertIn("데이터구조", completed)

    def test_해제하면_다시_추천_후보로_돌아온다(self):
        """학과 통보가 바뀌거나 잘못 골랐을 때 되돌릴 수 있어야 한다."""
        set_course_substitutions(
            record_id=1,
            payload=CourseSubstitutionRequest(course_ids=[10]),
            current_user=self.user,
            db=self.db,
        )
        response = set_course_substitutions(
            record_id=1,
            payload=CourseSubstitutionRequest(course_ids=[]),
            current_user=self.user,
            db=self.db,
        )
        self.assertEqual([], response.substitutes)
        self.assertNotIn("자료구조", _completed_course_norms(self.db, 1))

    def test_학점과_졸업요건_판정_숫자는_그대로다(self):
        """대체를 등록해도 이수학점 합계가 움직이면 회귀다.

        사용자 요구는 "대체해도 학점은 전적대 것으로 계산"인데, 지금 엔진이 이미
        그렇게 동작한다(전적대 학점이 그 행에 있고 엔진은 category 합계만 본다).
        대체 컬럼이 이 계산에 끼어들지 않는지 고정한다.
        """
        self.db.add(UserAcademicProgram(
            id=1, user_id=1, department_id=100, program_type="primary", curriculum_year="2024",
        ))
        self.db.add(GraduationRequirement(
            id=1, department_id=100, program_type="primary", curriculum_year="2024",
            required_total_credits=133, required_major_required=33,
        ))
        self.db.commit()

        before = compute_graduation_progress(self.db, 1, program_types={"primary"})[0]
        before_by_category = {c.category_name: c.earned_credits for c in before.categories}

        set_course_substitutions(
            record_id=1,
            payload=CourseSubstitutionRequest(course_ids=[10]),
            current_user=self.user,
            db=self.db,
        )

        after = compute_graduation_progress(self.db, 1, program_types={"primary"})[0]
        after_by_category = {c.category_name: c.earned_credits for c in after.categories}
        self.assertEqual(before_by_category, after_by_category)
        # 전적대 과목 행의 학점도 그대로 (대체가 학점을 옮기거나 지우지 않는다).
        self.assertEqual(3, float(self.db.get(StudentCourseRecord, 1).credits))

    def test_정규_학기_이수기록에는_지정할_수_없다(self):
        """이 기능은 "입학 전 인정 학점" 행 전용이다.

        PNU에서 직접 들은 과목에 대체를 걸 이유가 없고, 허용하면 이수기록이
        실제와 다른 과목을 가리키게 된다.
        """
        with self.assertRaises(HTTPException) as ctx:
            set_course_substitutions(
                record_id=2,
                payload=CourseSubstitutionRequest(course_ids=[10]),
                current_user=self.user,
                db=self.db,
            )
        self.assertEqual(422, ctx.exception.status_code)

    def test_남의_이수기록은_건드릴_수_없다(self):
        """record_id만 바꿔 부르면 남의 이수내역을 수정할 수 있으면 안 된다."""
        self.db.add(User(id=2, email="other@example.com", password_hash="x", name="타인"))
        self.db.add(StudentCourseRecord(
            id=3, user_id=2, raw_course_name="데이터구조", category="전공필수",
            credits=3, year="2026", semester="입학전성적", source="crawler",
        ))
        self.db.commit()

        with self.assertRaises(HTTPException) as ctx:
            set_course_substitutions(
                record_id=3,
                payload=CourseSubstitutionRequest(course_ids=[10]),
                current_user=self.user,
                db=self.db,
            )
        self.assertEqual(404, ctx.exception.status_code)
        self.assertEqual([], self.db.get(StudentCourseRecord, 3).substitutions)

    def test_로드맵_추천에서도_대체된_과목이_빠진다(self):
        """시간표뿐 아니라 로드맵 챗의 "놓친 전공필수" 경고에서도 빠져야 한다.

        한쪽만 고치면 시간표는 자료구조를 안 권하는데 로드맵은 "이번에 안 들으면
        위험하다"고 경고하는, 서로 다른 말을 하는 상태가 된다.
        """
        # 1학기 전용 전공필수 → 2학기 기준으로 보면 "이번 학기에 안 열리는 미이수 필수".
        self.db.add(Course(
            id=11, course_name="논리회로및설계", category="전공필수", credits=3,
            department_id=100, semester="1",
        ))
        self.db.add(StudentCourseRecord(
            id=4, user_id=1, raw_course_name="논리설계", category="전공필수",
            credits=3, year="2026", semester="입학전성적", source="crawler",
        ))
        self.db.commit()

        before = _compute_critical_missing_required(self.db, self.user, None, "2학기")
        self.assertIn("논리회로및설계", [c["course_name"] for c in before])

        set_course_substitutions(
            record_id=4,
            payload=CourseSubstitutionRequest(course_ids=[11]),
            current_user=self.user,
            db=self.db,
        )

        after = _compute_critical_missing_required(self.db, self.user, None, "2학기")
        self.assertNotIn("논리회로및설계", [c["course_name"] for c in after])

    def test_내_정보_편집_저장을_왕복해도_대체가_남는다(self):
        """성적 편집 저장(PUT /me/course-records)은 전체 교체 방식이다.

        그 경로가 대체 관계를 조용히 날리면, 성적 한 칸 고쳤을 뿐인데 추천이 원래대로
        돌아가고 학생은 이유를 알 수 없다.
        """
        set_course_substitutions(
            record_id=1,
            payload=CourseSubstitutionRequest(course_ids=[10]),
            current_user=self.user,
            db=self.db,
        )
        current = list_course_records(current_user=self.user, db=self.db)
        replaced = replace_course_records(
            CourseRecordsReplaceRequest(courses=[
                CourseRecordInput(
                    id=record.id, course_name=record.course_name, category=record.category,
                    credits=record.credits, year=record.year, semester=record.semester,
                    grade=record.grade,
                )
                for record in current
            ]),
            current_user=self.user,
            db=self.db,
        )
        transfer = next(r for r in replaced if r.id == 1)
        self.assertEqual(["자료구조"], [s.course_name for s in transfer.substitutes])
        self.assertIn("자료구조", _completed_course_norms(self.db, 1))

    def test_한_줄이_여러_과목을_대체할_수_있다(self):
        """전적대 `교양선택 15학점` 한 줄은 교양 세부영역 여러 개를 채운 것으로 인정된다.

        부산대는 균형·창의교양의 **영역 자체**를 `courses`에 placeholder 행으로 넣어둔다
        (`ZFz000091 사상과역사` …). 학생이 그중 여러 개를 체크할 수 있어야 하는데,
        단일 컬럼이면 마지막 하나만 남고 앞의 선택이 조용히 지워진다.
        """
        self.db.add_all([
            Course(id=20, course_code="ZFz000091", course_name="사상과역사",
                   category="효원균형교양", credits=3, department_id=100),
            Course(id=21, course_code="ZFz000093", course_name="문학과예술",
                   category="효원균형교양", credits=3, department_id=100),
            Course(id=22, course_code="ZFz000096", course_name="융합과 창의",
                   category="효원창의교양", credits=3, department_id=100),
        ])
        self.db.add(StudentCourseRecord(
            id=5, user_id=1, raw_course_name="교양선택", category="교양선택",
            credits=15, year="2026", semester="입학전성적", source="crawler",
        ))
        self.db.commit()

        response = set_course_substitutions(
            record_id=5,
            payload=CourseSubstitutionRequest(course_ids=[20, 21, 22]),
            current_user=self.user,
            db=self.db,
        )
        self.assertEqual(
            {"사상과역사", "문학과예술", "융합과 창의"},
            {s.course_name for s in response.substitutes},
        )
        self.assertEqual(
            {"사상과역사", "문학과예술", "융합과 창의"},
            set(substituted_course_names(self.db, 1)),
        )

        completions = liberal_area_completions(
            self.db,
            self.user.id,
            ("사상과역사", "문학과예술", "융복합"),
        )
        self.assertTrue(completions["사상과역사"].completed)
        self.assertTrue(completions["문학과예술"].completed)
        self.assertEqual(["교양선택 (대체 인정)"], completions["사상과역사"].course_names)
        # 15학점 묶음을 선택한 영역마다 15학점씩 중복 배분하지 않는다.
        self.assertEqual(0, completions["사상과역사"].direct_credits)
        # 현재 균형교양 목록과 이름이 다른 옛 창의영역은 임의로 융복합 처리하지 않는다.
        self.assertFalse(completions["융복합"].completed)

    def test_다시_저장하면_고른_집합으로_치환된다(self):
        """부분 추가가 아니라 치환이다 — 화면이 체크박스 전체 상태를 보낸다.

        추가만 되고 해제가 반영되지 않으면, 잘못 체크한 영역을 학생이 영영 못 뺀다.
        """
        self.db.add_all([
            Course(id=20, course_code="ZFz000091", course_name="사상과역사",
                   category="효원균형교양", credits=3, department_id=100),
            Course(id=21, course_code="ZFz000093", course_name="문학과예술",
                   category="효원균형교양", credits=3, department_id=100),
        ])
        self.db.add(StudentCourseRecord(
            id=5, user_id=1, raw_course_name="교양선택", category="교양선택",
            credits=15, year="2026", semester="입학전성적", source="crawler",
        ))
        self.db.commit()

        for course_ids, expected in [([20, 21], {20, 21}), ([21], {21}), ([], set())]:
            response = set_course_substitutions(
                record_id=5,
                payload=CourseSubstitutionRequest(course_ids=course_ids),
                current_user=self.user,
                db=self.db,
            )
            self.assertEqual(expected, {s.course_id for s in response.substitutes})

    def test_같은_집합을_두_번_보내도_행이_늘지_않는다(self):
        """멱등. 재시도나 더블클릭으로 중복 행이 쌓이면 배지가 같은 이름을 두 번 띄운다."""
        for _ in range(2):
            set_course_substitutions(
                record_id=1,
                payload=CourseSubstitutionRequest(course_ids=[10]),
                current_user=self.user,
                db=self.db,
            )
        rows = self.db.query(StudentCourseSubstitution).filter_by(record_id=1).all()
        self.assertEqual(1, len(rows))

    def test_전적대_두_과목이_PNU_한_과목을_대체할_수_있다(self):
        """1·2학기로 쪼개져 들어온 전적대 과목 둘이 PNU 한 과목으로 인정되는 경우."""
        self.db.add(StudentCourseRecord(
            id=6, user_id=1, raw_course_name="데이터구조II", category="전공필수",
            credits=3, year="2026", semester="입학전성적", source="crawler",
        ))
        self.db.commit()

        for record_id in (1, 6):
            set_course_substitutions(
                record_id=record_id,
                payload=CourseSubstitutionRequest(course_ids=[10]),
                current_user=self.user,
                db=self.db,
            )
        # 과목명 목록은 중복 없이 하나. 두 이수기록 각각의 학점은 그대로 남는다.
        self.assertEqual(["자료구조"], substituted_course_names(self.db, 1))
        self.assertEqual(3, float(self.db.get(StudentCourseRecord, 1).credits))
        self.assertEqual(3, float(self.db.get(StudentCourseRecord, 6).credits))

    def test_로드맵_재추가를_막을_때_인용하는_근거가_실제_대체_행이다(self):
        """차단만 맞으면 되는 게 아니라 **왜 막혔는지**도 맞아야 한다.

        이 에러 문자열은 LLM 도구 결과로 들어가 학생에게 그대로 전달된다. `자료구조`를
        대체한 건 `데이터구조` 행인데 엉뚱한 `교양선택` 행을 인용하면, 학생은 자기
        성적표를 의심하게 된다 — 졸업요건에 관해 틀린 말을 하지 않는 게 이 제품의 전제다.

        "대체된 과목이 있나?"만 보고 아무 전적대 행이나 근거로 집으면 여기서 깨진다.
        """
        # 실제로 대체를 등록하는 행은 **뒤쪽**에 둔다. 앞에 있는 전적대 행(record 1,
        # '데이터구조')이 미끼다 — "아무 전적대 행이나 집는" 구현은 이걸 집는다.
        self.db.add(StudentCourseRecord(
            id=7, user_id=1, raw_course_name="자료구조기초", category="전공필수",
            credits=3, year="2025", semester="입학전성적", source="crawler",
        ))
        self.db.add(CourseRoadmap(id=1, user_id=1, title="테스트", status="draft"))
        self.db.commit()
        set_course_substitutions(
            record_id=7,
            payload=CourseSubstitutionRequest(course_ids=[10]),
            current_user=self.user,
            db=self.db,
        )

        ctx = _ToolContext(self.db, self.user, self.db.get(CourseRoadmap, 1))
        result = ctx.propose_change(
            action="create", reason="테스트", course_id=10,
            planned_year="2026", planned_semester="2학기",
        )

        self.assertIn("error", result, "대체 등록된 과목은 재추가가 막혀야 한다")
        self.assertIn("자료구조기초", result["error"])
        self.assertNotIn("데이터구조", result["error"])

    def test_로드맵_경고_세_경로_모두에서_대체된_과목이_빠진다(self):
        """시간표뿐 아니라 로드맵의 **세 계산 경로 전부**에서 빠져야 한다.

        한 곳만 배선하면 "이번 학기 놓치면 위험"에서는 사라졌는데 "이번 학기 들을 수
        있는 미이수 필수"에는 그대로 남는, 서로 다른 말을 하는 상태가 된다.
        """
        # description에 선수과목 라벨을 둔다 — 그래야 prereq_blocked 경로에도 뜬다.
        # (선수과목 `대학수학`은 미이수라 대체 등록 전에는 blocked에 잡힌다.)
        self.db.add(Course(
            id=12, course_name="이산수학", category="전공필수", credits=3,
            department_id=100, semester="2", year="1",
            description="선수과목: 대학수학",
        ))
        self.db.add(StudentCourseRecord(
            id=8, user_id=1, raw_course_name="이산수학개론", category="전공필수",
            credits=3, year="2026", semester="입학전성적", source="crawler",
        ))
        self.db.commit()

        paths = {
            "critical_missing": lambda: _compute_critical_missing_required(
                self.db, self.user, None, "1학기"),
            "missing_available": lambda: _compute_missing_required_available(
                self.db, self.user, None, "2학기"),
            "prereq_blocked": lambda: _compute_prereq_blocked(self.db, self.user, None),
        }
        # 대체 등록 전에는 **세 경로 모두** 떠 있어야 한다. 한 경로라도 원래 안 뜨면
        # 그 경로의 배선을 지워도 이 테스트가 안 깨진다(= 검증하는 척만 한다).
        for name, fn in paths.items():
            with self.subTest(path=name, phase="before"):
                self.assertIn("이산수학", [c["course_name"] for c in fn()])

        set_course_substitutions(
            record_id=8,
            payload=CourseSubstitutionRequest(course_ids=[12]),
            current_user=self.user,
            db=self.db,
        )

        for name, fn in paths.items():
            with self.subTest(path=name):
                self.assertNotIn("이산수학", [c["course_name"] for c in fn()])

    def test_course_ids를_빼먹은_요청은_거절된다(self):
        """필드 누락이 조용히 "전체 해제"가 되면 프론트 버그 하나로 등록이 다 날아간다."""
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            CourseSubstitutionRequest()
        # 해제는 빈 배열을 **명시**해야 한다.
        self.assertEqual([], CourseSubstitutionRequest(course_ids=[]).course_ids)

    def test_한_요청에_담을_수_있는_과목_수에_상한이_있다(self):
        """상한이 없으면 한 요청으로 courses 전량을 밀어 넣을 수 있다."""
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            CourseSubstitutionRequest(course_ids=list(range(MAX_SUBSTITUTION_COURSES + 1)))

    def test_남의_대체_등록이_내_이수_완료에_섞이지_않는다(self):
        """조회 경로의 `user_id` 필터. 개인정보 경계이자 판정 정확성 문제다.

        남이 등록한 대체가 내 "이미 이수" 집합에 섞이면, 아직 안 들은 과목이 추천에서
        빠져 학생이 졸업요건을 잘못 믿는다. 필터를 지워도 안 깨지던 자리다.
        """
        self.db.add(User(id=3, email="other2@example.com", password_hash="x", name="타인2",
                         department_id=100, admission_type="transfer"))
        self.db.add(StudentCourseRecord(
            id=9, user_id=3, raw_course_name="남의전적대과목", category="전공필수",
            credits=3, year="2026", semester="입학전성적", source="crawler",
        ))
        self.db.commit()
        # 남(user 3)이 자기 기록에 '자료구조' 대체를 등록한다.
        set_substitutions(self.db, 9, [10])
        self.db.commit()

        # 내(user 1) 쪽에는 아무것도 없어야 한다.
        self.assertEqual([], substituted_course_names(self.db, 1))
        self.assertNotIn("자료구조", _completed_course_norms(self.db, 1))
        self.assertIsNone(substituting_record(self.db, 1, 10))
        # 남 쪽에는 그대로 있다(필터가 과하게 걸린 게 아니다).
        self.assertEqual(["자료구조"], substituted_course_names(self.db, 3))
        self.assertEqual(9, substituting_record(self.db, 3, 10).id)

    def test_없는_과목으로는_지정할_수_없다(self):
        """프론트가 자동완성 결과에서 고른 course_id만 오는 게 정상이지만,
        직접 호출로 존재하지 않는 id가 들어오면 조용히 저장하면 안 된다."""
        with self.assertRaises(HTTPException) as ctx:
            set_course_substitutions(
                record_id=1,
                payload=CourseSubstitutionRequest(course_ids=[99999]),
                current_user=self.user,
                db=self.db,
            )
        self.assertEqual(404, ctx.exception.status_code)


if __name__ == "__main__":
    unittest.main()
