"""핀테크융합전공의 타 학과 교차 인정과목을 ``program_courses``에 적재한다.

핀테크융합전공 교육과정에는 경영학과와 컴퓨터공학전공이 실제로 개설하는 과목이
함께 포함된다. ``courses.department_id``는 개설 주체를 하나만 표현하므로, 핀테크
학생의 검색·수강계획 후보로도 노출하려면 ``program_courses`` 다대다 연결이 필요하다.

기준은 추정이 아닌 다음의 교집합이다.
  1. 핀테크융합전공 2026 교육과정에 있는 과목명
  2. 해당 연도·학기에 경영학과 또는 컴퓨터공학전공이 실제로 개설한 분반

사용:
  DATABASE_URL=... python -m scripts.seed_fintech_cross_listed_courses
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domains.academics.models import Department, Major, ProgramCourse
from app.domains.courses.models import Course, CourseOffering

FINTECH = "핀테크융합전공"
BUSINESS = "경영학과"
CS_DEPARTMENT = "정보컴퓨터공학부"
CS_MAJOR = "컴퓨터공학전공"
CURRICULUM_YEAR = "2026"


def seed(year: str, semester: str, dry_run: bool = False) -> tuple[int, int]:
    db = SessionLocal()
    try:
        fintech = db.scalar(select(Department).where(Department.name == FINTECH))
        business = db.scalar(select(Department).where(Department.name == BUSINESS))
        cs_department = db.scalar(select(Department).where(Department.name == CS_DEPARTMENT))
        cs_major = db.scalar(
            select(Major).where(Major.name == CS_MAJOR, Major.department_id == cs_department.id)
        ) if cs_department else None
        if not all((fintech, business, cs_department, cs_major)):
            raise RuntimeError("핀테크·경영·컴퓨터공학 계층을 모두 찾지 못했습니다.")

        fintech_categories = dict(
            db.execute(
                select(Course.course_name, Course.category).where(Course.department_id == fintech.id)
            ).all()
        )
        matching_courses = db.scalars(
            select(Course)
            .join(CourseOffering, CourseOffering.course_id == Course.id)
            .where(
                CourseOffering.year == year,
                CourseOffering.semester == semester,
                Course.course_name.in_(fintech_categories),
                (
                    (Course.department_id == business.id)
                    | ((Course.department_id == cs_department.id) & (Course.major_id == cs_major.id))
                ),
            )
            .distinct()
        ).all()

        created = unchanged = 0
        for course in matching_courses:
            existing = db.scalar(
                select(ProgramCourse).where(
                    ProgramCourse.department_id == fintech.id,
                    ProgramCourse.major_id.is_(None),
                    ProgramCourse.course_id == course.id,
                    ProgramCourse.curriculum_year == CURRICULUM_YEAR,
                )
            )
            if existing:
                unchanged += 1
                continue
            db.add(
                ProgramCourse(
                    department_id=fintech.id,
                    major_id=None,
                    course_id=course.id,
                    requirement_group="핀테크융합전공 교차인정과목",
                    category=fintech_categories[course.course_name],
                    curriculum_year=CURRICULUM_YEAR,
                )
            )
            created += 1
        if dry_run:
            db.rollback()
        else:
            db.commit()
        return created, unchanged
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", default="2026")
    parser.add_argument("--semester", default="1학기")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    created, unchanged = seed(args.year, args.semester, dry_run=args.dry_run)
    print(f"핀테크 교차 인정과목: 신규 {created} / 기존 {unchanged}" + (" [dry-run]" if args.dry_run else ""))
