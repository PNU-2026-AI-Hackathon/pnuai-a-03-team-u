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
    """정규 학기 record 하나가 커리큘럼상 몇 학년 몇 학기인지 돌려준다.

    grade: 재학 학기 순번 기준 학년. entry_grade에서 시작해 두 학기마다
    하나씩 오른다. 편입생은 첫 재학 학기가 3학년 1학기다. 4학년을 넘으면 None.
    semester: 순번의 홀/짝으로 도출한 커리큘럼 학기.

    커리큘럼 축으로 환산할 수 없는 학기는 (None, None)이다 — 계절수업, 그리고
    `입학전성적`(편입/조기이수 인정)처럼 어느 학년에도 속하지 않는 lump-sum.
    이 경우 호출부는 달력 학기 원본만 남기고, 화면은 학년 슬롯 대신 "입학 전
    인정 학점"이나 계절학기 칸으로 따로 그린다.

    예전에는 입학전성적을 3학년 1학기로 못 박았는데, 그러면 편입생의 실제
    3학년 1학기와 같은 칸에 합쳐져 버린다. 실제로 그렇게 겹쳐 있었다.
    """
    if year is None or semester is None:
        return None, None
    if semester in PRE_ADMISSION_SEMESTERS:
        return None, None
    if semester not in _REGULAR_SEMESTERS:
        return None, None
    rank = semester_rank.get((year, semester))
    if rank is None:
        return None, None
    grade = entry_grade + (rank - 1) // 2
    if not (1 <= grade <= 4):
        return None, None
    return grade, "1학기" if rank % 2 == 1 else "2학기"


def _absolute_semester(year: str, semester: str) -> int:
    """달력상 학기를 하나의 정수 축에 올린다. 이웃한 정규 학기끼리 1 차이가 난다."""
    return int(year) * 2 + (0 if semester == "1학기" else 1)


def project_curriculum_term(
    db: Session, user_id: int, year: str, semester: str
) -> tuple[int | None, str | None]:
    """아직 이수하지 않은 학기가 커리큘럼상 몇 학년 몇 학기인지 추정한다.

    시간표 추천을 로드맵에 반영할 때 쓴다. 이수 기록이 없는 미래 학기라
    _build_semester_rank만으로는 순번을 매길 수 없어서, 마지막으로 등록한 학기의
    순번에 달력상 거리를 더해 이어 붙인다.

    커리큘럼 축으로 환산할 수 없으면 (None, None)이다. planned_grade를 채우지
    않으면 로드맵 화면이 그 항목을 학년 슬롯에 넣지 못하고 "2026년 2학기" 같은
    기타 칸으로 떨어뜨린다.

    앞으로 휴학할지는 알 수 없으므로 쉬지 않고 다닌다고 본다. 실제로 휴학하면
    다음 포털 동기화가 이수 기록 기준으로 다시 계산해 바로잡는다.
    """
    if semester not in _REGULAR_SEMESTERS:
        return None, None
    try:
        target = _absolute_semester(year, semester)
    except (TypeError, ValueError):
        return None, None

    records = db.query(StudentCourseRecord).filter_by(user_id=user_id).all()
    semester_rank = _build_semester_rank(records)
    user = db.get(User, user_id)
    entry_grade = admission_entry_grade(user.admission_type if user else None)

    rank = semester_rank.get((year, semester))
    if rank is None:
        if semester_rank:
            last_key = max(semester_rank, key=lambda key: _semester_order(*key))
            steps = target - _absolute_semester(*last_key)
            if steps <= 0:
                # 기록된 학기보다 과거인데 기록이 없다 — 근거가 없어 비워 둔다.
                return None, None
            rank = semester_rank[last_key] + steps
        else:
            # 이수 기록이 아예 없으면 이번이 첫 학기다.
            rank = 1

    grade = entry_grade + (rank - 1) // 2
    if not (1 <= grade <= 4):
        return None, None
    return grade, "1학기" if rank % 2 == 1 else "2학기"


def project_calendar_term(
    db: Session, user_id: int, grade: int | None, curriculum_semester: str | None
) -> tuple[str | None, str | None]:
    """project_curriculum_term의 역방향 — 커리큘럼 학기가 달력상 언제인지 추정한다.

    로드맵 화면은 "4학년 1학기" 같은 커리큘럼 슬롯만 보여주므로, 사용자가 거기에
    과목을 끌어다 놓으면 그게 달력상 몇 년 몇 학기인지는 서버가 알아야 한다.
    쉬지 않고 다닌다는 가정은 정방향과 같다.
    """
    if grade is None or curriculum_semester not in _REGULAR_SEMESTERS:
        return None, None

    records = db.query(StudentCourseRecord).filter_by(user_id=user_id).all()
    semester_rank = _build_semester_rank(records)
    user = db.get(User, user_id)
    entry_grade = admission_entry_grade(user.admission_type if user else None)

    rank = (grade - entry_grade) * 2 + (1 if curriculum_semester == "1학기" else 2)
    if rank < 1:
        return None, None

    # 이미 등록한 학기면 실제 달력값이 있다 — 추정할 필요가 없다.
    for key, existing_rank in semester_rank.items():
        if existing_rank == rank:
            return key

    if not semester_rank:
        return None, None
    last_key = max(semester_rank, key=lambda key: _semester_order(*key))
    steps = rank - semester_rank[last_key]
    if steps <= 0:
        # 등록 기록 사이에 뚫린 순번 — 휴학 배치를 알 수 없어 비워 둔다.
        return None, None
    absolute = _absolute_semester(*last_key) + steps
    return str(absolute // 2), "1학기" if absolute % 2 == 0 else "2학기"


def sync_completed_courses_to_roadmap(db: Session, user_id: int, roadmap_id: int) -> list[CourseRoadmapItem]:
    """user_id의 StudentCourseRecord를 roadmap_id의 완료된 항목으로 upsert한다.

    학기는 두 축을 각각 채운다: planned_year/planned_semester는 성적표에 적힌
    달력 학기 그대로, planned_grade/curriculum_semester는 재학 순번으로 환산한
    커리큘럼 학기다(CourseRoadmapItem 주석 참고).

    upsert 키는 (course_name, planned_year) + status="completed" + source="manual"이다.
    planned_semester를 키에 넣지 않는 이유: 커리큘럼 학기를 planned_semester에
    잘못 넣던 시절의 행이 남아 있어, 달력 학기로 매칭하면 옛 행을 못 찾고 새 행이
    중복 생성된다. 학생이 같은 과목을 같은 달력 연도의 1·2학기 모두 이수하는
    케이스는 실질적으로 발생하지 않아 이 키로도 충돌하지 않는다.
    """
    records = db.query(StudentCourseRecord).filter_by(user_id=user_id).all()
    semester_rank = _build_semester_rank(records)
    # 편입생은 첫 재학 학기가 3학년 1학기다. 신입생 기준으로 세면 1학년으로 찍힌다.
    user = db.get(User, user_id)
    entry_grade = admission_entry_grade(user.admission_type if user else None)

    saved: list[CourseRoadmapItem] = []
    for record in records:
        planned_grade, curriculum_semester = _curriculum_term(
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
        item.planned_semester = record.semester
        item.curriculum_semester = curriculum_semester
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
