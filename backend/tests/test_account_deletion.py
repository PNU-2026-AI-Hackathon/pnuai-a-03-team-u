"""회원 탈퇴 API (DELETE /me/account) 유닛테스트.

hard delete가 관련 테이블을 모두 청소하는지, 다른 유저 데이터는 안 건드는지 확인.
그리고 `_ACCOUNT_DELETE_STEPS`(하드코딩 리스트)가 실제 스키마를 따라가고 있는지를
SQLAlchemy 메타데이터에서 유도해서 검증한다 (security-privacy-plan.md P1-1).
"""

import importlib
import pathlib
import unittest

import app
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, configure_mappers

from app.api.profile import _ACCOUNT_DELETE_STEPS, delete_account
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


# --- P1-1: 삭제 목록 커버리지를 메타데이터에서 유도해 검증 --------------------
#
# `_ACCOUNT_DELETE_STEPS`는 손으로 관리하는 리스트라, 새 개인정보 테이블이
# 생겨도 아무도 안 알려준다 → 탈퇴 후에도 그 데이터가 조용히 남는다.
# 아래 테스트는 SQLAlchemy 메타데이터에서 "유저에게 귀속된 테이블" 집합을
# 직접 계산해서 삭제 목록과 대조한다. 누락되면 CI가 깨진다.

# migrations/env.py와 같은 모델 모듈 목록. 하나라도 빠지면 Base.metadata가
# 불완전해진다 — FK 해석이 NoReferencedTableError로 터지거나, 더 나쁘게는
# 테이블이 통째로 안 보인 채 커버리지 검사가 조용히 통과해버린다.
_MODEL_MODULES = (
    "app.ai.rag.models",
    "app.domains.academics.models",
    "app.domains.content.models",
    "app.domains.courses.models",
    "app.domains.planning.models",
    "app.domains.users.models",
)

# user_id/users FK를 가졌지만 계정 삭제에서 의도적으로 빼는 테이블.
# {테이블명: 면제 사유}. 새로 추가할 때는 "왜 개인정보가 아닌가"를 반드시 적는다.
# 현재는 비어 있다 — 유저에 귀속된 테이블은 전부 실제로 지운다.
_DELETE_EXEMPT_TABLES: dict[str, str] = {}

# ORM 모델 없이 raw SQL로만 지우는 테이블. profile.py가 information_schema로
# 존재 여부를 확인하고 없으면 스킵하기 때문에, 다른 브랜치에만 있는 테이블도
# 삭제 목록에 미리 넣어둘 수 있다. 다만 오타를 조용히 삼키는 경로이기도 해서
# 여기에 명시적으로 적은 이름만 허용한다. {테이블명: 사유}.
_STEPS_WITHOUT_ORM_MODEL: dict[str, str] = {}


def _load_full_metadata():
    """모든 모델 모듈을 import한 뒤 Base.metadata를 돌려준다."""
    for module in _MODEL_MODULES:
        importlib.import_module(module)
    configure_mappers()
    return Base.metadata


def _parent_tables(table) -> set[str]:
    return {fk.column.table.name for col in table.columns for fk in col.foreign_keys}


def _user_scoped_tables(metadata) -> set[str]:
    """유저에게 귀속된 테이블 = 직접 소유 + FK로 이어지는 자손 전부.

    직접 소유: `user_id` 컬럼이 있거나 users 테이블로 가는 FK가 있는 테이블.
    자손: 직접 소유 테이블(또는 그 자손)을 부모로 참조하는 테이블 —
    그런 행은 부모 행이 사라지면 같이 사라져야 하는 유저 데이터다.
    """
    owned = {
        name
        for name, table in metadata.tables.items()
        if "user_id" in table.columns or "users" in _parent_tables(table)
    }
    closure = set(owned)
    changed = True
    while changed:
        changed = False
        for name, table in metadata.tables.items():
            if name in closure or name == "users":
                continue
            if _parent_tables(table) & closure:
                closure.add(name)
                changed = True
    return closure


class AccountDeleteCoverageTest(unittest.TestCase):
    """P1-1 — 삭제 목록이 스키마를 따라가는지 회귀 감시."""

    def test_all_model_modules_are_imported(self):
        """app/ 아래 models.py가 새로 생겼는데 _MODEL_MODULES에 안 넣은 경우 잡는다."""
        app_dir = pathlib.Path(app.__file__).resolve().parent
        on_disk = {
            "app." + ".".join(path.relative_to(app_dir).with_suffix("").parts)
            for path in app_dir.rglob("models.py")
        }
        self.assertEqual(
            on_disk,
            set(_MODEL_MODULES),
            "모델 모듈 목록이 실제 파일과 다르다. _MODEL_MODULES와 migrations/env.py를 "
            "같이 갱신할 것 — 빠지면 메타데이터가 불완전해져 커버리지 검사가 무의미해진다.",
        )

    def test_metadata_is_complete(self):
        """모든 FK가 실제 테이블로 해석되는지 (= 메타데이터가 온전한지) 확인."""
        metadata = _load_full_metadata()
        self.assertGreater(len(metadata.tables), 0)
        self.assertIn("users", metadata.tables)
        for table in metadata.tables.values():
            for col in table.columns:
                for fk in col.foreign_keys:
                    # 참조 대상 모듈이 import 안 됐으면 여기서 NoReferencedTableError.
                    self.assertIsNotNone(fk.column)

    def test_every_user_scoped_table_is_covered(self):
        """user_id/users FK를 가진 테이블과 그 자손이 전부 삭제 목록에 있는지."""
        metadata = _load_full_metadata()
        expected = _user_scoped_tables(metadata) - set(_DELETE_EXEMPT_TABLES)
        covered = {table for table, _ in _ACCOUNT_DELETE_STEPS}
        missing = sorted(expected - covered)
        self.assertEqual(
            [],
            missing,
            "탈퇴 시 삭제되지 않는 개인 데이터 테이블이 있다: "
            f"{missing}. app/api/profile.py의 _ACCOUNT_DELETE_STEPS에 추가하거나, "
            "개인정보가 아니라면 _DELETE_EXEMPT_TABLES에 사유와 함께 등록할 것.",
        )

    def test_delete_steps_reference_real_tables(self):
        """삭제 목록의 테이블명 오타 방지.

        profile.py는 없는 테이블을 조용히 스킵하므로 오타가 나도 API는 200을 준다.
        ORM에 없는 이름은 _STEPS_WITHOUT_ORM_MODEL에 명시한 것만 허용한다.
        """
        metadata = _load_full_metadata()
        known = set(metadata.tables) | set(_STEPS_WITHOUT_ORM_MODEL)
        unknown = sorted({table for table, _ in _ACCOUNT_DELETE_STEPS} - known)
        self.assertEqual(
            [],
            unknown,
            f"_ACCOUNT_DELETE_STEPS에 ORM에 없는 테이블이 있다: {unknown}. "
            "오타이거나, 의도된 것이면 _STEPS_WITHOUT_ORM_MODEL에 사유와 함께 등록할 것.",
        )

    def test_delete_steps_have_no_duplicates(self):
        tables = [table for table, _ in _ACCOUNT_DELETE_STEPS]
        self.assertEqual(len(tables), len(set(tables)), f"중복 스텝: {tables}")


if __name__ == "__main__":
    unittest.main()
