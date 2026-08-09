"""시간표(수강계획) CRUD.

시간표는 로드맵과 독립된 문서다 — 여기서 지키려는 선은 두 가지다.
소유자가 아니면 어떤 동작도 404이고, 시간표를 지워도 로드맵은 안 변한다.
"""

import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.timetables import (
    AddItemsRequest,
    CreateTimetableRequest,
    RenameTimetableRequest,
    add_timetable_items,
    create_timetable,
    delete_timetable,
    get_timetable,
    list_timetables,
    remove_timetable_item,
    rename_timetable,
)
from app.core.db import Base
from app.domains.courses.models import Course, CourseOffering, CourseTime
from app.domains.planning.models import CoursePlan, CoursePlanItem
from app.domains.users.models import User


class TimetablesApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(cls.engine, tables=[
            User.__table__, Course.__table__, CourseOffering.__table__,
            CourseTime.__table__, CoursePlan.__table__, CoursePlanItem.__table__,
        ])

    def setUp(self):
        self.db = Session(self.engine)
        for model in (CoursePlanItem, CoursePlan, CourseTime, CourseOffering, Course, User):
            self.db.query(model).delete()
        self.db.commit()

        self.user = User(id=1, email="t@example.com", password_hash="x", name="테스트")
        self.other = User(id=2, email="o@example.com", password_hash="x", name="남")
        self.db.add_all([self.user, self.other])
        self.db.add_all([
            Course(id=100, course_name="자료구조", category="전공필수", credits=3),
            Course(id=101, course_name="알고리즘", category="전공필수", credits=3),
        ])
        self.db.add_all([
            CourseOffering(id=200, course_id=100, year="2026", semester="2학기"),
            CourseOffering(id=201, course_id=101, year="2026", semester="2학기"),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _create(self, title=None, user=None):
        return create_timetable(
            CreateTimetableRequest(year="2026", semester="2학기", title=title),
            current_user=user or self.user,
            db=self.db,
        )

    def test_생성_시_이름을_안_주면_학기_안_순번으로_짓는다(self):
        first = self._create()
        second = self._create()
        self.assertEqual("시간표 1", first.title)
        self.assertEqual("시간표 2", second.title)

    def test_담기는_멱등이고_학점이_집계된다(self):
        plan = self._create()
        detail = add_timetable_items(
            plan.id, AddItemsRequest(offering_ids=[200, 201, 200]),
            current_user=self.user, db=self.db,
        )
        self.assertEqual(2, detail.item_count)
        self.assertEqual(6.0, detail.total_credits)
        # 한 번 더 담아도 늘지 않는다
        detail = add_timetable_items(
            plan.id, AddItemsRequest(offering_ids=[200]),
            current_user=self.user, db=self.db,
        )
        self.assertEqual(2, detail.item_count)

    def test_빼기(self):
        plan = self._create()
        add_timetable_items(plan.id, AddItemsRequest(offering_ids=[200, 201]),
                            current_user=self.user, db=self.db)
        detail = remove_timetable_item(plan.id, 200, current_user=self.user, db=self.db)
        self.assertEqual(["알고리즘"], [o.course_name for o in detail.offerings])

    def test_이름_변경(self):
        plan = self._create()
        detail = rename_timetable(
            plan.id, RenameTimetableRequest(title="공강 몰빵안"),
            current_user=self.user, db=self.db,
        )
        self.assertEqual("공강 몰빵안", detail.title)

    def test_삭제하면_항목도_같이_지워진다(self):
        plan = self._create()
        add_timetable_items(plan.id, AddItemsRequest(offering_ids=[200]),
                            current_user=self.user, db=self.db)
        delete_timetable(plan.id, current_user=self.user, db=self.db)
        self.assertEqual(0, self.db.query(CoursePlan).count())
        self.assertEqual(0, self.db.query(CoursePlanItem).count())

    def test_남의_시간표는_모든_동작이_404(self):
        plan = self._create()
        for call in (
            lambda: get_timetable(plan.id, current_user=self.other, db=self.db),
            lambda: rename_timetable(plan.id, RenameTimetableRequest(title="x"),
                                     current_user=self.other, db=self.db),
            lambda: add_timetable_items(plan.id, AddItemsRequest(offering_ids=[200]),
                                        current_user=self.other, db=self.db),
            lambda: remove_timetable_item(plan.id, 200, current_user=self.other, db=self.db),
            lambda: delete_timetable(plan.id, current_user=self.other, db=self.db),
        ):
            with self.assertRaises(HTTPException) as caught:
                call()
            self.assertEqual(404, caught.exception.status_code)

    def test_목록은_학기로_거르고_학점을_함께_준다(self):
        plan = self._create()
        add_timetable_items(plan.id, AddItemsRequest(offering_ids=[200, 201]),
                            current_user=self.user, db=self.db)
        rows = list_timetables(year="2026", semester="2학기",
                               current_user=self.user, db=self.db)
        self.assertEqual(1, len(rows))
        self.assertEqual(2, rows[0].item_count)
        self.assertEqual(6.0, rows[0].total_credits)
        # 다른 학기로 거르면 빈 목록
        self.assertEqual([], list_timetables(year="2027", semester="1학기",
                                             current_user=self.user, db=self.db))

    def test_없는_분반을_담으면_404(self):
        plan = self._create()
        with self.assertRaises(HTTPException) as caught:
            add_timetable_items(plan.id, AddItemsRequest(offering_ids=[999]),
                                current_user=self.user, db=self.db)
        self.assertEqual(404, caught.exception.status_code)


if __name__ == "__main__":
    unittest.main()
