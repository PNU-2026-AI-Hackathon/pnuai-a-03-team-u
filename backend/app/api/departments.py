"""학과/학부 검색(자동완성). 회원가입·프로필 편집에서 학과를 고를 때 쓴다.

과목 입력을 `GET /courses/search`로만 하게 막아 오타를 구조적으로 차단한 것과
같은 이유다. 학과명을 자유 텍스트로 받으면 정식 편제에 없는 이름(예: 부산대
정식 명칭은 "경제학부"인데 "경제학과"로 입력)이 그대로 들어오고,
`resolve_hierarchy`가 "미지정" 단과대 아래에 과목 0개·졸업요건 0행짜리 학과를
새로 만들어 버린다. 그 계정은 과목 검색·졸업요건 조회·로드맵 추천이 전부 빈
결과가 된다.

회원가입은 로그인 전에 일어나므로 이 라우터는 인증을 요구하지 않는다.
노출되는 정보는 학교 공개 편제(단과대/학과/전공 이름)뿐이다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.domains.academics.hierarchy import UNASSIGNED_COLLEGE
from app.domains.academics.models import College, Department, Major

router = APIRouter(prefix="/departments", tags=["departments"])

# 자동완성에서 감출 편제.
#
# SW융합트랙·SW연계전공은 학생이 소속된 학과가 아니라 기존 학과 위에 얹는 부가
# 과정이다(항상 원 소속 학과가 따로 있다). "내 학과"를 고르는 자리에 20개 넘게
# 섞여 나오면 정작 찾으려는 학과가 묻힌다(예: "데이터"로 검색하면 SW융합트랙만
# 잔뜩 나온다).
#
# 반면 핀테크융합전공처럼 "OO융합전공"은 그 자체가 독립된 모집단위(자체
# department 행, 별도 college_id)라 얹는 부가 과정이 아니라 학생의 주전공이 될
# 수 있다 — 2026-08-25 확인: department_id로 course/course_offering이 정상
# 연결돼 있고 RAG 스코프 필터(major_id=None)도 정상 동작해서, 이 학과를 주전공
# 으로 등록해도 과목 검색·시간표가 깨지지 않는다. 그래서 융합전공은 더 이상
# 안 감춘다.
#
# 목록에서 감출 뿐 입력 자체를 막지는 않는다. 실제로 SW융합트랙/SW연계전공
# 소속인 학생은 이름을 직접 적으면 되고, 서버는 그 값을 그대로 받는다.
#
# "융합"만으로 거르면 의생명융합공학부·첨단융합학부·AI융합계산과학전공 같은
# 정식 학과까지 사라진다. 반드시 뒤 단어까지 붙여서 판단한다.
_HIDDEN_NAME_KEYWORDS = ("융합트랙", "연계전공")


def _visible_name(column):
    """이름에 부가 과정 키워드가 없는 행만 남기는 조건."""
    condition = column.notilike(f"%{_HIDDEN_NAME_KEYWORDS[0]}%")
    for keyword in _HIDDEN_NAME_KEYWORDS[1:]:
        condition = condition & column.notilike(f"%{keyword}%")
    return condition


class DepartmentSearchResult(BaseModel):
    id: int
    name: str
    college: str
    # 학부제라 세부 전공이 나뉘는 경우의 선택지. "OO과"처럼 학과 자체가 전공
    # 단위면 빈 리스트이고, 이때 사용자는 전공을 따로 고르지 않는다.
    majors: list[str]


@router.get("/search", response_model=list[DepartmentSearchResult])
def search_departments(
    q: str = "",
    limit: int = 20,
    db: Session = Depends(get_db),
) -> list[DepartmentSearchResult]:
    """학과/학부명으로 검색한다. q가 비면 전체 목록을 앞에서부터 돌려준다.

    "미지정" 단과대 소속은 제외한다 — 과거 자유 입력으로 잘못 생성된 껍데기라
    사용자가 새로 고르면 안 되는 값이다. SW융합트랙 같은, 기존 학과 위에 얹는
    부가 과정도 뺀다(_HIDDEN_NAME_KEYWORDS 참고) — 단 핀테크융합전공처럼 그
    자체가 독립 모집단위인 "OO융합전공"은 빼지 않는다.
    """
    query = (
        select(Department, College)
        .join(College, College.id == Department.college_id)
        .where(College.name != UNASSIGNED_COLLEGE, _visible_name(Department.name))
    )
    q = q.strip()
    if q:
        query = query.where(Department.name.ilike(f"%{q}%"))

    rows = db.execute(query.order_by(Department.name).limit(limit)).all()
    if not rows:
        return []

    department_ids = [department.id for department, _ in rows]
    majors_by_department: dict[int, list[str]] = {}
    for major in db.scalars(
        select(Major).where(
            Major.department_id.in_(department_ids), _visible_name(Major.name)
        )
    ).all():
        majors_by_department.setdefault(major.department_id, []).append(major.name)

    return [
        DepartmentSearchResult(
            id=department.id,
            name=department.name,
            college=college.name,
            majors=sorted(majors_by_department.get(department.id, [])),
        )
        for department, college in rows
    ]
