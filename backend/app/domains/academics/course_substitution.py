"""편입생이 직접 등록한 "전적대 과목 ↔ PNU 과목" 대체 관계.

## 왜 학생이 직접 고르는가

편입 학점 인정은 학칙에 표로 정해져 있지 않다. 학과가 편입생 개개인에게
"이 과목은 인정, 저건 불인정"을 통보하는 방식이라 **학생 본인만 안다.**
성적표에도 근거가 없다 — 전적대 과목은 `*I0600368 컴퓨터프로그래밍 Ⅰ` 처럼
PNU 교과목번호와 무관한 별도 코드로 들어오고, 우리 `courses`와 이어지는
어떤 키도 없다.

그래서 **이름 유사도로 추측하지 않는다.** `데이터구조`와 `자료구조`가 아무리
같아 보여도 학교가 실제로 그렇게 인정했는지는 데이터에 없고, 틀리면 학생이
졸업요건을 잘못 믿게 된다. `StudentCourseSubstitution`에는 학생이 화면에서
직접 고른 값만 들어간다.

## 왜 한 줄에 여러 개인가 (N:M)

전적대 `교양선택 15학점` 한 줄은 개별 과목이 아니라 **여러 세부영역**을 채운
것으로 인정받는다(부산대는 균형·창의교양의 영역 자체를 `courses`에 `ZFz…`
placeholder 행으로 넣어둔다). 반대로 전적대 두 과목이 PNU 한 과목을 대체하는
경우도 있어, 이수기록↔과목을 조인 테이블로 잇는다.

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

from app.domains.academics.models import StudentCourseRecord, StudentCourseSubstitution
from app.domains.courses.models import Course
from app.domains.users.admission import PRE_ADMISSION_SEMESTERS


def is_transfer_credit_record(record: StudentCourseRecord) -> bool:
    """이 이수기록이 "입학 전 인정 학점"(전적대/조기이수) 행인가.

    성적표 원문의 학기 칸이 정규 학기(1학기/2학기)가 아니라 `입학전성적`으로
    오는 것이 유일한 신호다. `raw_course_code`는 크롤러가 채우지 않아 실제
    데이터에서 늘 비어 있으므로 `*I` 접두사로는 판별할 수 없다.
    """
    return (record.semester or "") in PRE_ADMISSION_SEMESTERS


def substituted_course_ids(db: Session, record_id: int) -> list[int]:
    """이 이수기록이 대체한 것으로 등록된 PNU 과목 id 목록(오름차순)."""
    return list(
        db.scalars(
            select(StudentCourseSubstitution.course_id)
            .where(StudentCourseSubstitution.record_id == record_id)
            .order_by(StudentCourseSubstitution.course_id)
        ).all()
    )


def set_substitutions(db: Session, record_id: int, course_ids: list[int]) -> None:
    """이 이수기록의 대체 관계를 주어진 집합으로 **통째로 교체**한다(commit은 호출자).

    화면이 체크박스 전체 상태를 보내므로 부분 추가/삭제가 아니라 치환이다. 통보를
    나중에 받거나 잘못 골랐을 때 다시 부를 수 있게 멱등으로 만든다 — 같은 집합을
    두 번 보내면 두 번째는 아무것도 바꾸지 않는다.
    """
    wanted = set(course_ids)
    existing = {
        row.course_id: row
        for row in db.scalars(
            select(StudentCourseSubstitution).where(
                StudentCourseSubstitution.record_id == record_id
            )
        ).all()
    }
    for course_id, row in existing.items():
        if course_id not in wanted:
            db.delete(row)
    for course_id in wanted - set(existing):
        db.add(StudentCourseSubstitution(record_id=record_id, course_id=course_id))


def substituted_course_ids_for_user(db: Session, user_id: int) -> set[int]:
    """이 학생이 대체 대상으로 등록한 PNU 과목 id 전체.

    "이 과목 이미 인정받았나?"를 이수기록마다 관계로 캐물으면 N+1이 된다.
    한 번에 모아서 집합으로 들고 판정한다.
    """
    return set(
        db.scalars(
            select(StudentCourseSubstitution.course_id)
            .join(
                StudentCourseRecord,
                StudentCourseRecord.id == StudentCourseSubstitution.record_id,
            )
            .where(StudentCourseRecord.user_id == user_id)
        ).all()
    )


def substituted_course_names(db: Session, user_id: int) -> list[str]:
    """이 학생의 이수기록이 대체한 것으로 등록된 PNU 과목명 목록.

    추천에서 "이미 이수한 과목"에 합치는 용도다. 학생이 아무것도 등록하지
    않았으면 빈 리스트이므로 기존 동작이 그대로 유지된다.

    교양 세부영역 placeholder(`ZFz…`)도 여기 섞여 나오지만 문제되지 않는다 —
    `사상과역사` 같은 영역명과 같은 이름의 실제 교과목이 없어서 추천에서 무엇도
    가려지지 않는다. 영역 단위 요건 반영은 졸업요건 엔진 쪽 별도 과제다.
    """
    names = db.scalars(
        select(Course.course_name)
        .join(
            StudentCourseSubstitution,
            StudentCourseSubstitution.course_id == Course.id,
        )
        .join(
            StudentCourseRecord,
            StudentCourseRecord.id == StudentCourseSubstitution.record_id,
        )
        .where(StudentCourseRecord.user_id == user_id)
    ).all()
    return sorted({name for name in names if name})
