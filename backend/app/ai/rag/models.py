from __future__ import annotations

from sqlalchemy import ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pgvector.sqlalchemy import Vector

from app.core.db import Base, TimestampMixin


class RagChunk(TimestampMixin, Base):
    """Agent 추천 근거 검색용 RAG chunk.

    구조화 DB 필터를 먼저 적용하고, query가 자연어일 때 embedding similarity로
    ranking을 보강한다.
    """

    __tablename__ = "rag_chunks"
    __table_args__ = (
        UniqueConstraint("document_type", "source_table", "source_id", "category", name="uq_rag_chunk_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_type: Mapped[str] = mapped_column(String(50), index=True)
    source_table: Mapped[str] = mapped_column(String(100), index=True)
    source_id: Mapped[int] = mapped_column(index=True)

    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)
    major_id: Mapped[int | None] = mapped_column(ForeignKey("majors.id"), nullable=True, index=True)
    curriculum_year: Mapped[str | None] = mapped_column(String(10), index=True)
    category: Mapped[str | None] = mapped_column(String(50), index=True)
    grade: Mapped[str | None] = mapped_column(String(10), index=True)
    semester: Mapped[str | None] = mapped_column(String(20), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)

    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(255))
    chunk_metadata: Mapped[dict | None] = mapped_column("metadata", JSON)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
