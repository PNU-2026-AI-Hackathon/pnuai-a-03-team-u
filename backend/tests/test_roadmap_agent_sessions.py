"""로드맵 대화 조회/삭제의 세션 범위.

세션 도입 전에는 GET/DELETE /agent/messages가 로드맵 전체를 대상으로 동작해서,
스레드를 나눠 놓아도 화면에서는 다시 하나로 섞여 보였다. 여기서 검증하는 것은
session_id를 준 요청이 그 스레드만 건드린다는 것 — 그리고 session_id를 주지 않은
옛 호출부는 예전처럼 전체를 보는 호환 동작이 남아 있다는 것이다.
"""

import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.roadmap_agent import delete_roadmap_messages, get_roadmap_messages
from app.core.db import Base
from app.domains.planning.models import (
    CourseRoadmap,
    CourseRoadmapChatMessage,
    CourseRoadmapChatSession,
    CourseRoadmapItem,
    PendingRoadmapChange,
)
from app.domains.users.models import User


class RoadmapAgentSessionScopeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            cls.engine,
            tables=[
                User.__table__,
                CourseRoadmap.__table__,
                CourseRoadmapItem.__table__,
                CourseRoadmapChatSession.__table__,
                CourseRoadmapChatMessage.__table__,
                PendingRoadmapChange.__table__,
            ],
        )

    def setUp(self):
        self.db = Session(self.engine)
        for model in (
            PendingRoadmapChange,
            CourseRoadmapChatMessage,
            CourseRoadmapChatSession,
            CourseRoadmap,
            User,
        ):
            self.db.query(model).delete()
        self.db.commit()

        self.user = User(
            email="dowon@pusan.ac.kr", password_hash="x", name="이도원", student_id="202355699"
        )
        self.db.add(self.user)
        self.db.commit()

        self.roadmap = CourseRoadmap(user_id=self.user.id, title="내 로드맵")
        self.db.add(self.roadmap)
        self.db.commit()

        # 스레드 A는 로드맵 상담, 스레드 B는 별도 대화라고 치자.
        self.session_a = CourseRoadmapChatSession(roadmap_id=self.roadmap.id, title="A")
        self.session_b = CourseRoadmapChatSession(roadmap_id=self.roadmap.id, title="B")
        self.db.add_all([self.session_a, self.session_b])
        self.db.commit()

        self.db.add_all(
            [
                CourseRoadmapChatMessage(
                    roadmap_id=self.roadmap.id,
                    session_id=self.session_a.id,
                    role="user",
                    content="A에서 물어본 말",
                ),
                CourseRoadmapChatMessage(
                    roadmap_id=self.roadmap.id,
                    session_id=self.session_a.id,
                    role="assistant",
                    content="A의 답변",
                ),
                CourseRoadmapChatMessage(
                    roadmap_id=self.roadmap.id,
                    session_id=self.session_b.id,
                    role="user",
                    content="B에서 물어본 말",
                ),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _get(self, session_id=None):
        return get_roadmap_messages(
            roadmap_id=self.roadmap.id,
            session_id=session_id,
            current_user=self.user,
            db=self.db,
        )

    def test_session_id를_주면_그_스레드만_읽는다(self):
        result = self._get(self.session_a.id)
        self.assertEqual(
            ["A에서 물어본 말", "A의 답변"], [m.content for m in result.messages]
        )

        result_b = self._get(self.session_b.id)
        self.assertEqual(["B에서 물어본 말"], [m.content for m in result_b.messages])

    def test_session_id를_생략하면_로드맵_전체를_읽는다(self):
        """세션 개념 이전 호출부와의 호환 동작. 새 화면은 쓰면 안 된다."""
        result = self._get()
        self.assertEqual(3, len(result.messages))

    def test_남의_세션_id로는_읽을_수_없다(self):
        other_roadmap = CourseRoadmap(user_id=self.user.id, title="다른 로드맵")
        self.db.add(other_roadmap)
        self.db.commit()
        foreign = CourseRoadmapChatSession(roadmap_id=other_roadmap.id, title="남의 것")
        self.db.add(foreign)
        self.db.commit()

        with self.assertRaises(HTTPException) as caught:
            self._get(foreign.id)
        self.assertEqual(404, caught.exception.status_code)

    def test_세션을_지정해_지우면_다른_스레드는_남는다(self):
        delete_roadmap_messages(
            roadmap_id=self.roadmap.id,
            session_id=self.session_a.id,
            current_user=self.user,
            db=self.db,
        )
        self.assertEqual([], list(self._get(self.session_a.id).messages))
        self.assertEqual(1, len(self._get(self.session_b.id).messages))
        # 스레드를 비운 것이지 세션을 없앤 게 아니다.
        self.assertIsNotNone(
            self.db.get(CourseRoadmapChatSession, self.session_a.id)
        )

    def test_세션_삭제는_pending_change를_건드리지_않는다(self):
        """pending change는 로드맵 전역이라, 한 스레드를 비웠다고 날아가면 안 된다."""
        self.db.add(
            PendingRoadmapChange(roadmap_id=self.roadmap.id, action="create", status="pending")
        )
        self.db.commit()

        delete_roadmap_messages(
            roadmap_id=self.roadmap.id,
            session_id=self.session_a.id,
            current_user=self.user,
            db=self.db,
        )
        self.assertEqual(1, self.db.query(PendingRoadmapChange).count())

    def test_세션_없이_지우면_전체가_비워진다(self):
        self.db.add(
            PendingRoadmapChange(roadmap_id=self.roadmap.id, action="create", status="pending")
        )
        self.db.commit()

        delete_roadmap_messages(
            roadmap_id=self.roadmap.id,
            session_id=None,
            current_user=self.user,
            db=self.db,
        )
        self.assertEqual(0, self.db.query(CourseRoadmapChatMessage).count())
        self.assertEqual(0, self.db.query(PendingRoadmapChange).count())


if __name__ == "__main__":
    unittest.main()
