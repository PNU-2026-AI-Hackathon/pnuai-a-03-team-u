"""현재 사용자의 학과/전공에 맞는 이수체계도 API."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.academics.models import Department, Major, StudentCourseRecord, UserAcademicProgram
from app.domains.courses.models import Course
from app.domains.planning.models import CourseRoadmap, CourseRoadmapItem
from app.domains.users.models import User

router = APIRouter(prefix="/me", tags=["curriculum"])


class CurriculumCourseResponse(BaseModel):
    id: int
    course_name: str
    course_code: str | None
    category: str | None
    credits: float | None
    semester: str | None
    description: str | None
    status: str


class CurriculumGroupResponse(BaseModel):
    grade: str
    title: str
    courses: list[CurriculumCourseResponse]


class CurriculumResponse(BaseModel):
    department: str | None
    major: str | None
    curriculum_year: str | None
    groups: list[CurriculumGroupResponse]


def _grade_sort_key(value: str | None) -> tuple[int, str]:
    if value and value.isdigit():
        return int(value), value
    return 99, value or "공통"


@router.get("/curriculum", response_model=CurriculumResponse)
def get_my_curriculum(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> CurriculumResponse:
    department = db.get(Department, current_user.department_id) if current_user.department_id else None
    major = db.get(Major, current_user.major_id) if current_user.major_id else None
    primary = db.scalars(
        select(UserAcademicProgram).where(
            UserAcademicProgram.user_id == current_user.id,
            UserAcademicProgram.program_type == "primary",
        )
    ).first()

    if current_user.department_id is None:
        return CurriculumResponse(
            department=None,
            major=None,
            curriculum_year=primary.curriculum_year if primary else None,
            groups=[],
        )

    conditions = [
        or_(
            Course.department_id == current_user.department_id,
            Course.department_id.is_(None),
        )
    ]
    if current_user.major_id is not None:
        conditions.append(
            or_(Course.major_id == current_user.major_id, Course.major_id.is_(None))
        )

    courses = db.scalars(
        select(Course)
        .where(*conditions)
        .order_by(Course.year, Course.semester, Course.category, Course.course_name)
    ).all()
    completed_names = set(
        db.scalars(
            select(StudentCourseRecord.raw_course_name).where(
                StudentCourseRecord.user_id == current_user.id
            )
        ).all()
    )
    planned_names = set(
        db.scalars(
            select(CourseRoadmapItem.course_name)
            .join(CourseRoadmap, CourseRoadmap.id == CourseRoadmapItem.roadmap_id)
            .where(
                CourseRoadmap.user_id == current_user.id,
                CourseRoadmapItem.status != "dropped",
            )
        ).all()
    )

    grouped: dict[str, list[CurriculumCourseResponse]] = defaultdict(list)
    for course in courses:
        grade = course.year or "공통"
        status = (
            "done"
            if course.course_name in completed_names
            else "planned"
            if course.course_name in planned_names
            else "available"
        )
        grouped[grade].append(
            CurriculumCourseResponse(
                id=course.id,
                course_name=course.course_name,
                course_code=course.course_code,
                category=course.category,
                credits=float(course.credits) if course.credits is not None else None,
                semester=course.semester,
                description=course.description,
                status=status,
            )
        )

    groups = [
        CurriculumGroupResponse(
            grade=grade,
            title=f"{grade}학년" if grade.isdigit() else grade,
            courses=grouped[grade],
        )
        for grade in sorted(grouped, key=_grade_sort_key)
    ]
    return CurriculumResponse(
        department=department.name if department else None,
        major=major.name if major else None,
        curriculum_year=primary.curriculum_year if primary else "2026",
        groups=groups,
    )
