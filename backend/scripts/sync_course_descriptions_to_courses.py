"""course_descriptions의 원문을, 이름이 정확히 일치하는 courses.description에 복사한다.

매칭 기준은 (department_id, normalized_name) — course_description_matching.normalize_course_name으로
양쪽 이름을 정규화해서 비교한다. major_id는 안 가린다: 같은 학과 안에서 이름이 같은 과목이 여러
major 단위 courses 행으로 중복 존재하는 게 정상이라, 매칭되는 courses 행이 여러 개면 전부 채운다.
이름이 다르면(개편으로 사라졌거나 바뀐 과목) 그냥 안 채운다 — 잘못된 과목에 억지로 붙이지 않는다.

멱등: 재실행하면 courses.description을 다시 덮어쓴다(course_descriptions 쪽 내용이 바뀐 경우 반영).

실행: python -m scripts.sync_course_descriptions_to_courses [--department 학과명] [--dry-run]
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.db import SessionLocal
from app.domains.academics.models import Department
from app.domains.courses.course_description_matching import normalize_course_name
from app.domains.courses.models import Course, CourseDescription


def sync(department_name: str | None = None, dry_run: bool = False) -> None:
    db = SessionLocal()
    try:
        desc_query = select(CourseDescription)
        if department_name:
            department = db.scalars(select(Department).where(Department.name == department_name)).first()
            if department is None:
                raise SystemExit(f"학과를 찾을 수 없음: {department_name!r}")
            desc_query = desc_query.where(CourseDescription.department_id == department.id)

        descriptions = db.scalars(desc_query).all()
        by_department: dict[int, list[CourseDescription]] = {}
        for d in descriptions:
            if d.department_id is not None:
                by_department.setdefault(d.department_id, []).append(d)

        total_matched_courses = 0
        for dept_id, dept_descriptions in by_department.items():
            desc_by_name = {d.normalized_name: d.description for d in dept_descriptions}
            courses = db.scalars(select(Course).where(Course.department_id == dept_id)).all()
            for course in courses:
                description = desc_by_name.get(normalize_course_name(course.course_name))
                if description is not None and course.description != description:
                    course.description = description
                    total_matched_courses += 1

        if dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()

    print(
        f"course_descriptions {len(descriptions)}건 대상 → courses.description 갱신 {total_matched_courses}건"
        + (" [dry-run, 롤백됨]" if dry_run else "")
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--department", default=None, help="생략하면 전체 학과 대상")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sync(args.department, dry_run=args.dry_run)
