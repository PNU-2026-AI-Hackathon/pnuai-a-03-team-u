import datetime

from sqlalchemy import JSON, ForeignKey, String, Text, Time
from sqlalchemy.dialects.postgresql import JSONB
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
    # 효원균형교양(6영역 중 2영역)·효원창의교양(3영역 중 2영역) 세부영역명(예: "사상과역사").
    # 규정 제9조가 영역 단위로 이수를 요구하는데, category만으로는 어느 영역인지 알 수 없어
    # 별도 컬럼으로 둔다. Onestop 수강편람 검색의 "세부구분(영역별)" 필터(공통코드 0001_AREA_GCD,
    # ZFz코드=Z+해당 공통코드)로만 얻을 수 있고, 그 외 카테고리 과목은 항상 NULL이다.
    general_education_area: Mapped[str | None] = mapped_column(String(50), nullable=True)
    credits: Mapped[float | None] = mapped_column()
    year: Mapped[str | None] = mapped_column(String(10))
    semester: Mapped[str | None] = mapped_column(String(20))
    # 학과 "교과목개요" 원문에서 이름 매칭된 항목을 옮겨온 서술.
    # scripts/import_course_descriptions.py가 raw md 파일에서 직접 채운다.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # description 원문 출처 (URL·파일명·수집 시점 등).
    source_document: Mapped[str | None] = mapped_column(String(255), nullable=True)


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


class CourseTime(TimestampMixin, Base):
    """강좌의 요일/시간/강의실."""

    __tablename__ = "course_times"

    id: Mapped[int] = mapped_column(primary_key=True)
    offering_id: Mapped[int] = mapped_column(ForeignKey("course_offerings.id"), index=True)
    day_of_week: Mapped[str | None] = mapped_column(String(10))
    start_time: Mapped[datetime.time | None] = mapped_column(Time)
    end_time: Mapped[datetime.time | None] = mapped_column(Time)
    classroom: Mapped[str | None] = mapped_column(String(100))


class CourseSyllabus(TimestampMixin, Base):
    """One-Stop 수강편람 "교수계획표"(강의계획서)에서 뽑은 분반별 상세.

    분반(offering) 단위다 — 같은 과목번호라도 담당교수마다 평가방법·선수과목·
    교수목표·개요를 전혀 다르게 채운다(2026-08-24 자료구조 CB1501019의 분반 4개를
    직접 대조해서 확인, 과목당 대표 분반 하나만 긁는 지름길은 못 쓴다는 근거).
    """

    __tablename__ = "course_syllabi"

    id: Mapped[int] = mapped_column(primary_key=True)
    offering_id: Mapped[int] = mapped_column(
        ForeignKey("course_offerings.id"), unique=True, index=True
    )
    office: Mapped[str | None] = mapped_column(String(100))
    office_hours: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    teaching_mode: Mapped[str | None] = mapped_column(String(255))
    evaluation_method: Mapped[str | None] = mapped_column(Text)
    # RAG의 선수과목 안내·`_compute_prereq_blocked`(courses.description 파싱) 보강 후보.
    prerequisites_text: Mapped[str | None] = mapped_column(Text)
    course_objectives: Mapped[str | None] = mapped_column(Text)
    # 진로 기반 추천(search_by_career)이 노릴 핵심 필드 — 실제로 다루는 주제를 서술한다.
    course_overview: Mapped[str | None] = mapped_column(Text)
    textbooks: Mapped[str | None] = mapped_column(Text)
    # 예: ["지식탐구", "혁신도전", "창의융합"]. SQLite(테스트)에서는 JSON, Postgres에서는
    # JSONB로 자동 dispatch(academics.models.special_rules와 같은 관행).
    core_competencies: Mapped[list | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    # 예: [{"week": 1, "content": "..."}, ...].
    weekly_plan: Mapped[list | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    # 구조화 파싱이 놓친 내용에 대한 안전망 — `pdftotext -layout` 원문 전체.
    raw_text: Mapped[str | None] = mapped_column(Text)
    # 재크롤링/재파싱 시 원본을 다시 열어봐야 할 때를 위해 PDF 저장 경로를 남긴다
    # (raw_data/ 아래, gitignore 대상 — DB에는 경로만).
    source_pdf_path: Mapped[str | None] = mapped_column(String(500))
