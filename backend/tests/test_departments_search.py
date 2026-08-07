"""학과/학부 자동완성에서 감추는 편제.

SW융합트랙·SW연계전공·융합전공은 소속 학과가 아니라 그 위에 얹는 부가 과정이다.
"내 학과"를 고르는 자리에 20개 넘게 섞여 나오면 정작 찾으려는 학과가 묻힌다.

여기서 지키려는 선은 하나다: 감추는 건 부가 과정뿐이고, 이름에 "융합"이 들어가는
정식 학과(의생명융합공학부 등)는 반드시 남아야 한다.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.departments import search_departments
from app.core.db import Base
from app.domains.academics.hierarchy import UNASSIGNED_COLLEGE
from app.domains.academics.models import College, Department, Major, School


class DepartmentSearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            cls.engine,
            tables=[
                School.__table__,
                College.__table__,
                Department.__table__,
                Major.__table__,
            ],
        )

    def setUp(self):
        self.db = Session(self.engine)
        for model in (Major, Department, College, School):
            self.db.query(model).delete()
        self.db.commit()

        self.db.add(School(id=1, name="부산대학교"))
        self.db.flush()
        self.db.add_all([
            College(id=1, school_id=1, name="정보의생명공학대학"),
            College(id=2, school_id=1, name="경영대학"),
            College(id=3, school_id=1, name=UNASSIGNED_COLLEGE),
        ])
        self.db.add_all([
            Department(id=10, name="의생명융합공학부", college_id=1),
            Department(id=11, name="정보컴퓨터공학부", college_id=1),
            Department(id=12, name="핀테크융합전공", college_id=2),
            Department(id=13, name="자유입력학과", college_id=3),
        ])
        self.db.add_all([
            Major(id=100, name="데이터사이언스전공", department_id=10),
            Major(id=101, name="바이오메디컬디바이스&데이터(SW융합트랙)", department_id=10),
            Major(id=102, name="빅데이터(SW연계전공)", department_id=11),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _names(self, q=""):
        return [item.name for item in search_departments(q=q, limit=50, db=self.db)]

    def test_융합전공_학과는_후보에서_빠진다(self):
        self.assertNotIn("핀테크융합전공", self._names())

    def test_이름에_융합이_들어가는_정식_학과는_남는다(self):
        """'융합'만으로 거르면 이 학과들이 같이 사라진다."""
        self.assertIn("의생명융합공학부", self._names())

    def test_SW융합트랙_전공은_후보에서_빠진다(self):
        result = search_departments(q="의생명", limit=50, db=self.db)
        self.assertEqual(["데이터사이언스전공"], result[0].majors)

    def test_SW연계전공도_빠진다(self):
        result = search_departments(q="정보컴퓨터", limit=50, db=self.db)
        self.assertEqual([], result[0].majors)

    def test_미지정_단과대_소속은_계속_빠진다(self):
        """과거 자유 입력으로 잘못 생성된 껍데기. 기존 동작이 유지되는지 확인."""
        self.assertNotIn("자유입력학과", self._names())


if __name__ == "__main__":
    unittest.main()
