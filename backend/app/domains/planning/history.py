"""이미 이수한 과목(StudentCourseRecord)을 로드맵 항목으로 채워 넣는다.

로드맵을 새로 만들 때, 미래 학기만 비워두면 2학년 이상인 학생은 "1학년 때
뭘 들었는지"가 로드맵에서 안 보여 전체 그림이 끊긴다. 이미 크롤링된 과거
이수 기록을 status="completed"인 로드맵 항목으로 변환해 넣으면, 로드맵이
"지나온 학기 + 앞으로 계획한 학기"를 하나의 타임라인으로 보여줄 수 있다.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.domains.academics.models import StudentCourseRecord
from app.domains.planning.models import CourseRoadmapItem
from app.domains.users.admission import (
    PRE_ADMISSION_SEMESTERS,
    entry_grade as admission_entry_grade,
)
from app.domains.users.models import User

_REGULAR_SEMESTERS = ("1학기", "2학기")


def _semester_order(year: str, semester: str) -> tuple[int, int]:
    return (int(year), 1 if semester == "1학기" else 2)


def _build_semester_rank(records: Iterable[StudentCourseRecord]) -> dict[tuple[str, str], int]:
    """실제 등록된 정규 학기(1/2학기)만 시간순으로 정렬해 1-based 순번을 매긴다.

    휴학 학기는 등록 기록 자체가 없으므로 자연스럽게 순번에서 빠진다 → 복학 후
    학기가 달력상 밀려도 학년이 함께 밀리지 않는다.
    """
    keys: set[tuple[str, str]] = set()
    for record in records:
        if not record.year or record.semester not in _REGULAR_SEMESTERS:
            continue
        try:
            _semester_order(record.year, record.semester)
        except (TypeError, ValueError):
            continue
        keys.add((record.year, record.semester))
    ordered = sorted(keys, key=lambda k: _semester_order(*k))
    return {key: idx + 1 for idx, key in enumerate(ordered)}


def _curriculum_term(
    semester_rank: dict[tuple[str, str], int],
    year: str | None,
    semester: str | None,
    entry_grade: int = 1,
) -> tuple[int | None, str | None]:
    """정규 학기 record 하나에 대응하는 (planned_grade, planned_semester)를 돌려준다.

    planned_grade: 재학 학기 순번 기준 학년. entry_grade에서 시작해 두 학기마다
    하나씩 오른다. 편입생은 첫 재학 학기가 3학년 1학기다. 4학년을 넘으면 None.
    planned_semester: 순번의 홀/짝으로 도출한 커리큘럼 상 학기. 정규 학기가 아니면
    원본 semester를 그대로 돌려준다 — 계절수업 같은 값은 유지해야 표시·필터링이 깨지지 않는다.

    특수 케이스: `입학전성적`(편입/조기이수 인정)은 어느 학년에도 속하지 않는
    lump-sum이라 planned_grade를 None으로 두고 semester를 원본 그대로 남긴다.
    화면은 이 값을 학년 슬롯이 아니라 "입학 전 인정 학점" 칸으로 따로 그린다.

    예전에는 이걸 3학년 1학기로 못 박았는데, 그러면 편입생의 실제 3학년 1학기와
    같은 칸에 합쳐져 버린다. 실제로 그렇게 겹쳐 있었다.
    """
    if year is None or semester is None:
        return None, semester
    if semester in PRE_ADMISSION_SEMESTERS:
        return None, semester
    if semester not in _REGULAR_SEMESTERS:
        return None, semester
    rank = semester_rank.get((year, semester))
    if rank is None:
        return None, semester
    grade = entry_grade + (rank - 1) // 2
    if not (1 <= grade <= 4):
        return None, semester
    curriculum_semester = "1학기" if rank % 2 == 1 else "2학기"
    return grade, curriculum_semester


def sync_completed_courses_to_roadmap(db: Session, user_id: int, roadmap_id: int) -> list[CourseRoadmapItem]:
    """user_id의 StudentCourseRecord를 roadmap_id의 완료된 항목으로 upsert한다.

    upsert 키는 (course_name, planned_year) + status="completed" + source="manual"이다.
    planned_semester를 키에 넣지 않는 이유: 휴학 반영 이전 코드가 저장해 둔 항목은
    달력 학기 기준이고, 이 함수가 새로 쓰는 값은 커리큘럼 학기 기준이라 그대로
    매칭시키면 옛 행이 그대로 남고 새 행이 중복 생성된다. 학생이 같은 과목을 같은
    달력 연도의 1·2학기 모두 이수하는 케이스는 실질적으로 발생하지 않아 이 키로도
    충돌하지 않는다.
    """
    records = db.query(StudentCourseRecord).filter_by(user_id=user_id).all()
    semester_rank = _build_semester_rank(records)
    # 편입생은 첫 재학 학기가 3학년 1학기다. 신입생 기준으로 세면 1학년으로 찍힌다.
    user = db.get(User, user_id)
    entry_grade = admission_entry_grade(user.admission_type if user else None)

    saved: list[CourseRoadmapItem] = []
    for record in records:
        planned_grade, planned_semester = _curriculum_term(
            semester_rank, record.year, record.semester, entry_grade
        )

        existing = (
            db.query(CourseRoadmapItem)
            .filter_by(
                roadmap_id=roadmap_id,
                course_name=record.raw_course_name,
                planned_year=record.year,
                status="completed",
                source="manual",
            )
            .first()
        )
        item = existing or CourseRoadmapItem(
            roadmap_id=roadmap_id,
            planned_year=record.year,
        )
        item.planned_year = record.year
        item.planned_semester = planned_semester
        item.planned_grade = planned_grade
        item.course_id = record.course_id
        item.course_name = record.raw_course_name
        item.category = record.category
        item.credits = float(record.credits) if record.credits is not None else None
        item.status = "completed"
        item.source = "manual"
        db.add(item)
        saved.append(item)

    db.flush()
    return saved
