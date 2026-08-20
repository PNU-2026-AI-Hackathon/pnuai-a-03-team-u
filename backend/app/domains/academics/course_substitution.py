"""편입생이 직접 등록한 "전적대 과목 ↔ PNU 과목" 대체 관계.

## 왜 학생이 직접 고르는가

편입 학점 인정은 학칙에 표로 정해져 있지 않다. 학과가 편입생 개개인에게
"이 과목은 인정, 저건 불인정"을 통보하는 방식이라 **학생 본인만 안다.**
성적표에도 근거가 없다 — 전적대 과목은 `*I0600368 컴퓨터프로그래밍 Ⅰ` 처럼
PNU 교과목번호와 무관한 별도 코드로 들어오고, 우리 `courses`와 이어지는
어떤 키도 없다.

그래서 **이름 유사도로 추측하지 않는다.** `데이터구조`와 `자료구조`가 아무리
같아 보여도 학교가 실제로 그렇게 인정했는지는 데이터에 없고, 틀리면 학생이
졸업요건을 잘못 믿게 된다. `StudentCourseRecord.substitutes_course_id`에는
학생이 화면에서 직접 고른 값만 들어간다.

## 무엇이 바뀌고 무엇이 안 바뀌는가

- **학점 계산은 그대로다.** 전적대 학점은 그 이수기록 행에 이미 있고,
  졸업요건 엔진(`graduation_progress`)은 `category`별 합계만 대조한다.
  대체 관계를 등록해도 합계가 달라지지 않는다 — 애초에 과목 단위 매칭이
  없는 엔진이라 졸업요건 판정 숫자는 이 기능과 무관하다.
- **바뀌는 건 추천이다.** 대체된 PNU 과목명이 "이미 이수한 과목"에 들어가서
  시간표/로드맵이 `자료구조`를 더는 추천하지 않는다.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.academics.models import StudentCourseRecord
from app.domains.courses.models import Course
from app.domains.users.admission import PRE_ADMISSION_SEMESTERS


def is_transfer_credit_record(record: StudentCourseRecord) -> bool:
    """이 이수기록이 "입학 전 인정 학점"(전적대/조기이수) 행인가.

    성적표 원문의 학기 칸이 정규 학기(1학기/2학기)가 아니라 `입학전성적`으로
    오는 것이 유일한 신호다. `raw_course_code`는 크롤러가 채우지 않아 실제
    데이터에서 늘 비어 있으므로 `*I` 접두사로는 판별할 수 없다.
    """
    return (record.semester or "") in PRE_ADMISSION_SEMESTERS


def substituted_course_names(db: Session, user_id: int) -> list[str]:
    """이 학생의 이수기록이 대체한 것으로 등록된 PNU 과목명 목록.

    추천에서 "이미 이수한 과목"에 합치는 용도다. 학생이 아무것도 등록하지
    않았으면 빈 리스트이므로 기존 동작이 그대로 유지된다.
    """
    course_ids = db.scalars(
        select(StudentCourseRecord.substitutes_course_id).where(
            StudentCourseRecord.user_id == user_id,
            StudentCourseRecord.substitutes_course_id.is_not(None),
        )
    ).all()
    if not course_ids:
        return []
    names = db.scalars(
        select(Course.course_name).where(Course.id.in_(set(course_ids)))
    ).all()
    return [name for name in names if name]
