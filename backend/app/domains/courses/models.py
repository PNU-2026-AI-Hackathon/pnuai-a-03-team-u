import datetime

from sqlalchemy import ForeignKey, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class Course(TimestampMixin, Base):
    """과목 자체(강좌 개설과 무관한 과목 정의). 학년/학기는 처음 확인된 개설
    시점 기준 참고값이며, 실제 학기별 개설 정보는 CourseOffering이 담당한다.
    """

    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_code: Mapped[str | None] = mapped_column(String(50), index=True)
    course_name: Mapped[str] = mapped_column(String(255))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    major_id: Mapped[int | None] = mapped_column(ForeignKey("majors.id"), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(50))
    credits: Mapped[float | None] = mapped_column()
    year: Mapped[str | None] = mapped_column(String(10))
    semester: Mapped[str | None] = mapped_column(String(20))
    # course_descriptions에서 이름이 정확히 일치하는 것만 골라 복사해 넣은 값(있으면).
    # scripts/sync_course_descriptions_to_courses.py가 채운다 — 직접 수정하지 말 것.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class CourseOffering(TimestampMixin, Base):
    """특정 학기에 실제 개설된 강좌(수강편람)."""

    __tablename__ = "course_offerings"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    school: Mapped[str | None] = mapped_column(String(100))
    year: Mapped[str | None] = mapped_column(String(10))
    semester: Mapped[str | None] = mapped_column(String(20))
    section: Mapped[str | None] = mapped_column(String(20))
    professor: Mapped[str | None] = mapped_column(String(100))
    capacity: Mapped[int | None] = mapped_column()
    enrolled_count: Mapped[int | None] = mapped_column()


class CourseDescription(TimestampMixin, Base):
    """학과가 예전에 공개한 "교과목개요" 원문에서 옮긴 과목 설명 — 원본 그대로 보존하는 테이블.

    courses.id에 직접 FK로 고정하지 않는다 — 원문 자체가 개편 이전 자료라 현재
    courses.course_name과 이름이 바뀌었거나 사라진 과목이 섞여 있고(0%~100% 확신 불가),
    같은 과목명이 학과 내 여러 major 단위 courses 행으로 중복 존재하는 것도 정상이라
    1:1로 못 묶는다. 대신 (department_id, major_id, normalized_name)으로 저장해두고,
    이름이 정확히 일치하는 것만 골라 `scripts/sync_course_descriptions_to_courses.py`가
    `Course.description`에 복사한다 — 실제 조회/추천 경로(CurriculumRetriever,
    course_roadmap_agent.py)는 이 테이블이 아니라 `Course.description`을 읽는다. 이
    테이블은 원문 출처·매칭 안 된 것까지 포함한 원본 기록용으로 남겨둔다.
    """

    __tablename__ = "course_descriptions"
    __table_args__ = (
        UniqueConstraint(
            "department_id", "major_id", "normalized_name",
            name="uq_course_description_dept_major_name",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    major_id: Mapped[int | None] = mapped_column(ForeignKey("majors.id"), nullable=True, index=True)
    source_course_name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(Text)
    source_document: Mapped[str] = mapped_column(String(255))


class CourseTime(TimestampMixin, Base):
    """강좌의 요일/시간/강의실."""

    __tablename__ = "course_times"

    id: Mapped[int] = mapped_column(primary_key=True)
    offering_id: Mapped[int] = mapped_column(ForeignKey("course_offerings.id"), index=True)
    day_of_week: Mapped[str | None] = mapped_column(String(10))
    start_time: Mapped[datetime.time | None] = mapped_column(Time)
    end_time: Mapped[datetime.time | None] = mapped_column(Time)
    classroom: Mapped[str | None] = mapped_column(String(100))
