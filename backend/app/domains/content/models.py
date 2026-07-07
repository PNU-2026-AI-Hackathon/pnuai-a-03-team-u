import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class AcademicInfoArticle(TimestampMixin, Base):
    """수강신청/휴복학/졸업/장학/복수전공 등 학사정보 안내 글."""

    __tablename__ = "academic_info_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    school: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ExtracurricularProgram(TimestampMixin, Base):
    """비교과 프로그램(취업/창업/AI/어학/상담 등)."""

    __tablename__ = "extracurricular_programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    school: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(500))
    category: Mapped[str | None] = mapped_column(String(100))
    organizer: Mapped[str | None] = mapped_column(String(255))
    apply_start_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    apply_end_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    program_start_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    program_end_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    target: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(500))
