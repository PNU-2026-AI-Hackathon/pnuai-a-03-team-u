"""이미 이수한 과목(StudentCourseRecord)을 로드맵 항목으로 채워 넣는다.

로드맵을 새로 만들 때, 미래 학기만 비워두면 2학년 이상인 학생은 "1학년 때
뭘 들었는지"가 로드맵에서 안 보여 전체 그림이 끊긴다. 이미 크롤링된 과거
이수 기록을 status="completed"인 로드맵 항목으로 변환해 넣으면, 로드맵이
"지나온 학기 + 앞으로 계획한 학기"를 하나의 타임라인으로 보여줄 수 있다.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.academics.models import StudentCourseRecord, UserAcademicProgram
from app.domains.planning.models import CourseRoadmapItem

# 실제 학기가 아니라 특수 구분이라 학년(1~4)을 계산할 수 없는 값들.
# 이런 행도 항목으로는 만들되 planned_grade는 비워둔다.
_NON_REGULAR_SEMESTERS = {"입학전성적"}


def _compute_planned_grade(curriculum_year: str | None, year: str | None, semester: str | None) -> int | None:
    if not curriculum_year or not year or semester in _NON_REGULAR_SEMESTERS or semester is None:
        return None
    if semester not in ("1학기", "2학기"):
        return None  # 계절수업 등은 특정 학년에 딱 떨어지지 않아 비워둔다
    try:
        grade = int(year) - int(curriculum_year) + 1
    except ValueError:
        return None
    return grade if 1 <= grade <= 4 else None


def sync_completed_courses_to_roadmap(db: Session, user_id: int, roadmap_id: int) -> list[CourseRoadmapItem]:
    """user_id의 StudentCourseRecord를 roadmap_id의 완료된 항목으로 upsert한다."""
    program = (
        db.query(UserAcademicProgram)
        .filter_by(user_id=user_id, program_type="primary")
        .one_or_none()
    )
    curriculum_year = program.curriculum_year if program else None

    records = db.query(StudentCourseRecord).filter_by(user_id=user_id).all()

    saved: list[CourseRoadmapItem] = []
    for record in records:
        existing = (
            db.query(CourseRoadmapItem)
            .filter_by(
                roadmap_id=roadmap_id,
                course_name=record.raw_course_name,
                planned_year=record.year,
                planned_semester=record.semester,
            )
            .one_or_none()
        )
        item = existing or CourseRoadmapItem(
            roadmap_id=roadmap_id,
            planned_year=record.year,
            planned_semester=record.semester,
        )
        item.course_id = record.course_id
        item.course_name = record.raw_course_name
        item.category = record.category
        item.credits = float(record.credits) if record.credits is not None else None
        item.planned_grade = _compute_planned_grade(curriculum_year, record.year, record.semester)
        item.status = "completed"
        item.source = "manual"
        db.add(item)
        saved.append(item)

    db.flush()
    return saved
