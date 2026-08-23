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
- **추천과 영역 완료 근거에는 반영된다.** 대체된 PNU 과목명은 "이미 이수한 과목"에
  들어가고, `ZFz…` 교양영역 placeholder는 내 정보·로드맵·시간표의 이수영역 판단에
  들어간다. 단, 묶음 인정 학점을 영역별 학점으로 임의 배분하지는 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.academics.models import StudentCourseRecord, StudentCourseSubstitution
from app.domains.courses.models import Course
from app.domains.users.admission import PRE_ADMISSION_SEMESTERS


@dataclass
class LiberalAreaCompletion:
    """효원균형교양 한 영역의 직접 이수·대체 인정 근거.

    ``direct_records``만 학점을 합산한다. 입학 전 인정 학점 한 행은 여러 영역을
    대체할 수 있어서 그 행의 전체 학점을 영역마다 더하면 학점이 중복되기 때문이다.
    """

    direct_records: list[StudentCourseRecord] = field(default_factory=list)
    substituted_records: list[StudentCourseRecord] = field(default_factory=list)

    @property
    def completed(self) -> bool:
        return bool(self.direct_records or self.substituted_records)

    @property
    def direct_credits(self) -> float:
        return sum(
            float(record.credits)
            for record in self.direct_records
            if record.credits is not None
        )

    @property
    def course_names(self) -> list[str]:
        names = {
            record.raw_course_name
            for record in self.direct_records
            if record.raw_course_name
        }
        names.update(
            f"{record.raw_course_name} (대체 인정)"
            for record in self.substituted_records
            if record.raw_course_name
        )
        return sorted(names)


def liberal_area_completions(
    db: Session,
    user_id: int,
    area_names: Sequence[str],
    *,
    records: Sequence[StudentCourseRecord] | None = None,
) -> dict[str, LiberalAreaCompletion]:
    """학교 판정 영역과 학생이 직접 지정한 영역 대체를 하나의 결과로 합친다.

    대체 대상은 ``ZFz…`` 교양영역 placeholder이면서 현재 판정 엔진이 아는 이름인
    경우만 받는다. 일반 과목 대체나 옛 ``융합과 창의``처럼 현재 균형교양 목록에
    없는 영역이 잘못 완료 처리되지 않게 하기 위함이다.
    """
    known_areas = tuple(area_names)
    known_set = set(known_areas)
    result = {area: LiberalAreaCompletion() for area in known_areas}
    course_records = (
        list(records)
        if records is not None
        else list(
            db.scalars(
                select(StudentCourseRecord).where(StudentCourseRecord.user_id == user_id)
            ).all()
        )
    )

    for record in course_records:
        area = record.liberal_area or (record.category if record.category in known_set else None)
        if area in known_set:
            result[area].direct_records.append(record)

    substitution_rows = db.execute(
        select(StudentCourseRecord, Course.course_name)
        .join(
            StudentCourseSubstitution,
            StudentCourseSubstitution.record_id == StudentCourseRecord.id,
        )
        .join(Course, Course.id == StudentCourseSubstitution.course_id)
        .where(
            StudentCourseRecord.user_id == user_id,
            Course.course_code.like("ZFz%"),
            Course.course_name.in_(known_areas),
        )
    ).all()
    for record, area in substitution_rows:
        completion = result[area]
        if all(existing.id != record.id for existing in completion.substituted_records):
            completion.substituted_records.append(record)

    return result


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


def substituting_record(
    db: Session, user_id: int, course_id: int
) -> StudentCourseRecord | None:
    """이 PNU 과목을 대체한 것으로 등록된 **바로 그 이수기록**.

    "이 과목이 대체됐나?"만 보면 차단 판정은 맞지만 학생에게 보여줄 근거를 못 고른다.
    "자료구조는 이미 이수했습니다(성적표 원문 '교양선택')"처럼 엉뚱한 행을 인용하면
    학생이 자기 성적표를 의심하게 된다 — 졸업요건에 관해 틀린 말을 하지 않는 게 이
    제품의 전제다.

    여러 이수기록이 같은 과목을 대체했으면(전적대 두 과목 → PNU 한 과목) 그중 하나를
    돌려준다. 어느 쪽이든 실제로 그 과목을 대체한 행이므로 근거로 옳다.
    """
    return db.scalars(
        select(StudentCourseRecord)
        .join(
            StudentCourseSubstitution,
            StudentCourseSubstitution.record_id == StudentCourseRecord.id,
        )
        .where(
            StudentCourseRecord.user_id == user_id,
            StudentCourseSubstitution.course_id == course_id,
        )
        .order_by(StudentCourseRecord.id)
    ).first()


def substituted_course_names(db: Session, user_id: int) -> list[str]:
    """이 학생의 이수기록이 대체한 것으로 등록된 PNU 과목명 목록.

    추천에서 "이미 이수한 과목"에 합치는 용도다. 학생이 아무것도 등록하지
    않았으면 빈 리스트이므로 기존 동작이 그대로 유지된다.

    교양 세부영역 placeholder(`ZFz…`)도 여기 섞여 나오지만 문제되지 않는다 —
    `사상과역사` 같은 영역명과 같은 이름의 실제 교과목이 없어서 추천에서 무엇도
    가려지지 않는다. 영역 완료 판단은 `liberal_area_completions`가 별도로 처리한다.
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
