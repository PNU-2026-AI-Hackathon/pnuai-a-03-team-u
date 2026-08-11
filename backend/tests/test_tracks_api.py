"""AI융합트랙(SW융합트랙) API 유닛테스트.

- available: 학생 학과 기준으로 대상 트랙만 노출
- enroll: UserAcademicProgram(interdisciplinary)로 등록
- enrolled: 진도 표시
- cancel: status='cancelled'
- 다른 학과 트랙·SW연계전공(48학점)은 API 대상 아님
"""

import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.tracks import (
    EnrollRequest, cancel_track, enroll_track,
    list_available_tracks, list_enrolled_tracks,
)
from app.core.db import Base
from app.domains.academics.models import (
    College, Department, GraduationRequirement, Major, ProgramCourse, School,
    StudentCourseRecord, UserAcademicProgram,
)
from app.domains.courses.models import Course
from app.domains.users.models import User


_TABLES = [
    School.__table__, College.__table__, Department.__table__, Major.__table__,
    User.__table__, UserAcademicProgram.__table__,
    Course.__table__, StudentCourseRecord.__table__,
    GraduationRequirement.__table__, ProgramCourse.__table__,
]


def _seed(db: Session):
    db.add(School(id=1, name="테스트")); db.flush()
    db.add(College(id=1, school_id=1, name="사회과학대학")); db.flush()
    # 심리학과 (dept 18 - real DB와 정합)
    db.add(Department(id=18, college_id=1, name="심리학과"))
    # 다른 학과 (사회학과)
    db.add(Department(id=17, college_id=1, name="사회학과"))
    db.flush()
    # 심리학과의 트랙 major
    db.add(Major(id=66, department_id=18, name="심리데이터사이언스(SW융합트랙)"))
    # 사회학과의 트랙 major
    db.add(Major(id=65, department_id=17, name="소셜데이터사이언스(SW융합트랙)"))
    # 심리학과의 SW연계전공 (48학점, 트랙 아님)
    db.add(Major(id=99, department_id=18, name="빅데이터(SW연계전공)"))
    db.flush()

    # GR: 심리 트랙
    db.add(GraduationRequirement(
        department_id=18, major_id=66, program_type="interdisciplinary",
        required_total_credits=21,
        special_rules={
            "certification_type": "AI융합트랙",
            "not_graduation_requirement": True,
            "total_credits": 21,
        },
    ))
    # 사회학과 트랙 (다른 학과)
    db.add(GraduationRequirement(
        department_id=17, major_id=65, program_type="interdisciplinary",
        required_total_credits=21,
        special_rules={"certification_type": "AI융합트랙", "not_graduation_requirement": True},
    ))
    # 심리학과 SW연계전공 (48학점) — 트랙 아님
    db.add(GraduationRequirement(
        department_id=18, major_id=99, program_type="interdisciplinary",
        required_total_credits=48,
        special_rules={"total_credits": 48},
    ))
    db.flush()


def _make_user(db: Session, dept_id: int = 18) -> User:
    u = User(id=100, email="t@x.com", password_hash="x", name="테스트", department_id=dept_id)
    db.add(u); db.flush()
    # primary program
    db.add(UserAcademicProgram(user_id=u.id, department_id=dept_id,
                                 program_type="primary", status="active"))
    db.flush()
    return u


def _make_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=_TABLES)
    return Session(engine)


class AvailableTracksTest(unittest.TestCase):
    def test_only_student_dept_tracks_shown(self):
        """심리학과 학생에겐 심리 트랙만 보임. 사회 트랙 X, 48학점 SW연계전공 X."""
        db = _make_db(); _seed(db); user = _make_user(db, dept_id=18); db.commit()
        result = list_available_tracks(current_user=user, db=db)
        self.assertEqual(1, len(result))
        self.assertEqual(66, result[0].major_id)
        self.assertEqual("심리데이터사이언스(SW융합트랙)", result[0].track_name)
        self.assertEqual(21, result[0].total_credits)
        self.assertFalse(result[0].is_enrolled)

    def test_no_dept_returns_empty(self):
        db = _make_db(); _seed(db)
        user = User(id=101, email="x@x.com", password_hash="x", name="?", department_id=None)
        db.add(user); db.commit()
        self.assertEqual([], list_available_tracks(current_user=user, db=db))


class EnrollmentTest(unittest.TestCase):
    def test_enroll_then_appears_as_enrolled(self):
        db = _make_db(); _seed(db); user = _make_user(db, dept_id=18); db.commit()
        # 등록 전
        self.assertEqual(0, len(list_enrolled_tracks(current_user=user, db=db)))
        # 등록
        e = enroll_track(EnrollRequest(major_id=66), current_user=user, db=db)
        self.assertEqual(66, e.major_id)
        self.assertEqual(21, e.total_credits)
        self.assertFalse(e.completed)
        # available에서 is_enrolled=True
        avail = list_available_tracks(current_user=user, db=db)
        self.assertTrue(avail[0].is_enrolled)
        # enrolled 조회
        enrolled = list_enrolled_tracks(current_user=user, db=db)
        self.assertEqual(1, len(enrolled))
        self.assertEqual(66, enrolled[0].major_id)

    def test_enroll_wrong_dept_track_rejected(self):
        """심리학과 학생이 사회학과 트랙 등록 시도 → 404."""
        db = _make_db(); _seed(db); user = _make_user(db, dept_id=18); db.commit()
        with self.assertRaises(HTTPException) as ctx:
            enroll_track(EnrollRequest(major_id=65), current_user=user, db=db)
        self.assertEqual(404, ctx.exception.status_code)

    def test_enroll_sw_convergence_major_rejected(self):
        """SW연계전공(48학점) major_id 넘기면 트랙이 아니라서 404 (certification_type 없음)."""
        db = _make_db(); _seed(db); user = _make_user(db, dept_id=18); db.commit()
        with self.assertRaises(HTTPException) as ctx:
            enroll_track(EnrollRequest(major_id=99), current_user=user, db=db)
        self.assertEqual(404, ctx.exception.status_code)

    def test_cancel_soft_deletes(self):
        db = _make_db(); _seed(db); user = _make_user(db, dept_id=18); db.commit()
        e = enroll_track(EnrollRequest(major_id=66), current_user=user, db=db)
        cancel_track(enrollment_id=e.enrollment_id, current_user=user, db=db)
        # enrolled 조회 시 안 보임
        self.assertEqual(0, len(list_enrolled_tracks(current_user=user, db=db)))
        # UserAcademicProgram row는 남아있음(status=cancelled)
        row = db.get(UserAcademicProgram, e.enrollment_id)
        self.assertIsNotNone(row)
        self.assertEqual("cancelled", row.status)

    def test_reenroll_after_cancel_reactivates(self):
        """취소 후 다시 등록하면 새 row 아니라 status=active로 갱신."""
        db = _make_db(); _seed(db); user = _make_user(db, dept_id=18); db.commit()
        e1 = enroll_track(EnrollRequest(major_id=66), current_user=user, db=db)
        cancel_track(enrollment_id=e1.enrollment_id, current_user=user, db=db)
        e2 = enroll_track(EnrollRequest(major_id=66), current_user=user, db=db)
        self.assertEqual(e1.enrollment_id, e2.enrollment_id)
        self.assertEqual(1, len(list_enrolled_tracks(current_user=user, db=db)))


if __name__ == "__main__":
    unittest.main()
