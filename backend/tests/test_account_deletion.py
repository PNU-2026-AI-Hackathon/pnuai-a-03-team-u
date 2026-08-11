"""회원 탈퇴 API (DELETE /me/account) 유닛테스트.

hard delete가 관련 테이블을 모두 청소하는지, 다른 유저 데이터는 안 건드는지 확인.
"""

import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.api.profile import delete_account
from app.core.db import Base
from app.domains.academics.models import (
    College, Department, Major, School, StudentCourseRecord, UserAcademicProgram,
)
from app.domains.courses.models import Course
from app.domains.planning.models import (
    CourseRoadmap, CourseRoadmapChatMessage, CourseRoadmapChatSession,
    CourseRoadmapItem, PendingRoadmapChange,
)
from app.domains.users.models import (
    PasswordResetToken, PortalCredential, User,
    UserActivity, UserCertification, UserLanguageScore,
)


_TABLES = [
    School.__table__, College.__table__, Department.__table__, Major.__table__,
    User.__table__, UserAcademicProgram.__table__, Course.__table__,
    StudentCourseRecord.__table__,
    CourseRoadmap.__table__, CourseRoadmapItem.__table__,
    CourseRoadmapChatSession.__table__, CourseRoadmapChatMessage.__table__,
    PendingRoadmapChange.__table__,
    PortalCredential.__table__, PasswordResetToken.__table__,
    UserActivity.__table__, UserCertification.__table__, UserLanguageScore.__table__,
]


class DeleteAccountTest(unittest.TestCase):
    def _make_db(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=_TABLES)
        db = Session(engine)
        # SQLite에는 information_schema.tables가 없어서 DELETE /me/account 코드가
        # 그 lookup을 시도하면 실패한다. sqlite_master를 information_schema.tables
        # 형태로 view로 노출해 테스트에서 우회.
        db.execute(text(
            "CREATE TEMP VIEW information_schema_tables AS "
            "SELECT name AS table_name, 'public' AS table_schema FROM sqlite_master WHERE type='table'"
        ))
        # profile.py의 SQL이 "information_schema.tables"를 그대로 쓰므로 tampering이 필요.
        # 대신 monkeypatch로 처리 — 실제 코드는 안 건드리고 테스트에서 쿼리를 갈아치운다.
        return db

    def _seed_two_users_with_data(self, db):
        # 스코프 최소화용 학교 계층
        db.add(School(id=1, name="테스트")); db.add(College(id=1, school_id=1, name="공대")); db.flush()
        db.add(Department(id=100, college_id=1, name="컴퓨터공학과")); db.flush()

        # user_a: 삭제 대상, 다양한 소유 데이터
        ua = User(id=1, email="a@x.com", password_hash="x", name="A", department_id=100)
        # user_b: 남아있어야 함, 유사 데이터
        ub = User(id=2, email="b@x.com", password_hash="x", name="B", department_id=100)
        db.add_all([ua, ub]); db.flush()

        # 각 유저의 데이터
        for uid in (1, 2):
            rm = CourseRoadmap(user_id=uid); db.add(rm); db.flush()
            db.add(CourseRoadmapItem(roadmap_id=rm.id, course_name=f"과목-{uid}"))
            sess = CourseRoadmapChatSession(roadmap_id=rm.id, title=f"세션-{uid}")
            db.add(sess); db.flush()
            db.add(CourseRoadmapChatMessage(roadmap_id=rm.id, session_id=sess.id,
                                             role="user", content=f"메시지-{uid}"))
            db.add(PendingRoadmapChange(roadmap_id=rm.id, action="create"))
            db.add(StudentCourseRecord(user_id=uid, raw_course_name=f"이수-{uid}",
                                        category="전공", credits=3))
            db.add(UserAcademicProgram(user_id=uid, department_id=100, program_type="primary",
                                        status="active"))
            db.add(UserActivity(user_id=uid, title=f"활동-{uid}"))
            db.add(UserCertification(user_id=uid, name=f"자격증-{uid}"))
            db.add(UserLanguageScore(user_id=uid, test_name="토익", score=str(800 + uid)))
            db.add(PortalCredential(user_id=uid, portal="pnu_onestop",
                                     login_id=str(uid), encrypted_password="enc"))
        db.commit()
        return ua, ub

    def _patch_information_schema(self, db):
        """SQLite 테스트에서 information_schema.tables를 흉내낸다.

        profile.py의 코드는 Postgres의 information_schema를 조회하는데, SQLite엔 없다.
        임시로 SessionExecute를 wrapping해서 information_schema 관련 쿼리를 sqlite_master로 리라이트.
        """
        original_execute = db.execute

        def wrapped(stmt, *args, **kwargs):
            text_str = str(stmt) if hasattr(stmt, 'text') else str(stmt)
            if "information_schema" in text_str:
                # sqlite_master로 대체해서 실제 존재 테이블 목록 반환
                return original_execute(text(
                    "SELECT name AS table_name FROM sqlite_master WHERE type='table'"
                ), *args, **kwargs)
            return original_execute(stmt, *args, **kwargs)

        db.execute = wrapped
        return db

    def test_deletes_own_data_and_preserves_other_user(self):
        db = self._make_db()
        ua, ub = self._seed_two_users_with_data(db)
        self._patch_information_schema(db)

        # 삭제 실행
        result = delete_account(current_user=ua, db=db)

        # 응답 확인
        self.assertEqual(1, result.deleted_user_id)
        self.assertGreater(result.deleted_rows["users"], 0)

        # user_a 관련 모든 데이터 사라졌는지
        self.assertIsNone(db.get(User, 1))
        self.assertEqual(0, db.query(CourseRoadmap).filter_by(user_id=1).count())
        self.assertEqual(0, db.query(StudentCourseRecord).filter_by(user_id=1).count())
        self.assertEqual(0, db.query(UserAcademicProgram).filter_by(user_id=1).count())
        self.assertEqual(0, db.query(UserActivity).filter_by(user_id=1).count())
        self.assertEqual(0, db.query(UserCertification).filter_by(user_id=1).count())
        self.assertEqual(0, db.query(UserLanguageScore).filter_by(user_id=1).count())
        self.assertEqual(0, db.query(PortalCredential).filter_by(user_id=1).count())

        # user_b 데이터는 그대로 남아있는지
        self.assertIsNotNone(db.get(User, 2))
        self.assertEqual(1, db.query(CourseRoadmap).filter_by(user_id=2).count())
        self.assertEqual(1, db.query(StudentCourseRecord).filter_by(user_id=2).count())
        self.assertEqual(1, db.query(PortalCredential).filter_by(user_id=2).count())

    def test_deletion_covers_2hop_children(self):
        """course_roadmap_chat_messages 같은 2-hop 자식도 삭제되는지."""
        db = self._make_db()
        ua, _ = self._seed_two_users_with_data(db)
        self._patch_information_schema(db)

        # 삭제 전: 두 유저 각 1건씩 = 2건
        self.assertEqual(2, db.query(CourseRoadmapChatMessage).count())
        self.assertEqual(2, db.query(CourseRoadmapChatSession).count())
        self.assertEqual(2, db.query(CourseRoadmapItem).count())
        self.assertEqual(2, db.query(PendingRoadmapChange).count())

        delete_account(current_user=ua, db=db)

        # user_a 것만 삭제되고 user_b 1건씩 남음
        self.assertEqual(1, db.query(CourseRoadmapChatMessage).count())
        self.assertEqual(1, db.query(CourseRoadmapChatSession).count())
        self.assertEqual(1, db.query(CourseRoadmapItem).count())
        self.assertEqual(1, db.query(PendingRoadmapChange).count())


if __name__ == "__main__":
    unittest.main()
