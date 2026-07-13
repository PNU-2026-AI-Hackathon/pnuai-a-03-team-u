from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.embeddings.openai_client import embed_texts
from app.ai.rag.models import RagChunk
from app.domains.academics.models import GraduationRequirement
from app.domains.courses.models import Course


@dataclass(frozen=True)
class RagChunkDraft:
    document_type: str
    source_table: str
    source_id: int
    department_id: int | None
    major_id: int | None
    curriculum_year: str | None
    category: str | None
    grade: str | None
    semester: str | None
    course_id: int | None
    title: str
    content: str
    evidence: str
    source: str
    chunk_metadata: dict


class CurriculumRagIngestionService:
    """Builds RAG chunks from structured curriculum and graduation DB tables."""

    REQUIREMENT_FIELDS = {
        "총학점": "required_total_credits",
        "전공기초": "required_major_foundation",
        "전공필수": "required_major_required",
        "전공선택": "required_major_elective",
        "교양필수": "required_general_required",
        "교양선택": "required_general_elective",
        "일반선택": "required_free_elective",
    }

    def __init__(self, db: Session):
        self.db = db

    def rebuild_all(self, *, curriculum_year: int | str = 2026, with_embeddings: bool = True) -> dict[str, int | bool]:
        year = str(curriculum_year)
        self.db.execute(delete(RagChunk).where(RagChunk.curriculum_year == year))
        drafts = [
            *self._curriculum_course_drafts(curriculum_year=year),
            *self._graduation_requirement_drafts(curriculum_year=year),
        ]
        chunks = self._persist_drafts(drafts)
        embedded = self.embed_missing() if with_embeddings else 0
        self.db.commit()
        return {
            "chunks_created": len(chunks),
            "embeddings_created": embedded,
            "embedding_enabled": with_embeddings,
        }

    def ingest_curriculum(self, *, curriculum_year: int | str = 2026, with_embeddings: bool = True) -> dict[str, int | bool]:
        year = str(curriculum_year)
        self.db.execute(
            delete(RagChunk).where(
                RagChunk.curriculum_year == year,
                RagChunk.document_type == "curriculum",
            )
        )
        chunks = self._persist_drafts(self._curriculum_course_drafts(curriculum_year=year))
        embedded = self.embed_missing(document_type="curriculum") if with_embeddings else 0
        self.db.commit()
        return {"chunks_created": len(chunks), "embeddings_created": embedded, "embedding_enabled": with_embeddings}

    def ingest_graduation_requirements(
        self, *, curriculum_year: int | str = 2026, with_embeddings: bool = True
    ) -> dict[str, int | bool]:
        year = str(curriculum_year)
        self.db.execute(
            delete(RagChunk).where(
                RagChunk.curriculum_year == year,
                RagChunk.document_type == "graduation_requirement",
            )
        )
        chunks = self._persist_drafts(self._graduation_requirement_drafts(curriculum_year=year))
        embedded = self.embed_missing(document_type="graduation_requirement") if with_embeddings else 0
        self.db.commit()
        return {"chunks_created": len(chunks), "embeddings_created": embedded, "embedding_enabled": with_embeddings}

    def embed_missing(self, *, document_type: str | None = None, batch_size: int = 96) -> int:
        query = select(RagChunk).where(RagChunk.embedding.is_(None))
        if document_type:
            query = query.where(RagChunk.document_type == document_type)

        chunks = self.db.scalars(query.order_by(RagChunk.id)).all()
        embedded = 0
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            embeddings = embed_texts([chunk.content for chunk in batch])
            for chunk, embedding in zip(batch, embeddings, strict=True):
                chunk.embedding = embedding
                embedded += 1
            self.db.flush()
        return embedded

    def _persist_drafts(self, drafts: Iterable[RagChunkDraft]) -> list[RagChunk]:
        chunks: list[RagChunk] = []
        for draft in drafts:
            chunk = RagChunk(
                document_type=draft.document_type,
                source_table=draft.source_table,
                source_id=draft.source_id,
                department_id=draft.department_id,
                major_id=draft.major_id,
                curriculum_year=draft.curriculum_year,
                category=draft.category,
                grade=draft.grade,
                semester=draft.semester,
                course_id=draft.course_id,
                title=draft.title,
                content=draft.content,
                evidence=draft.evidence,
                source=draft.source,
                chunk_metadata=draft.chunk_metadata,
            )
            self.db.add(chunk)
            chunks.append(chunk)
        self.db.flush()
        return chunks

    def _curriculum_course_drafts(self, *, curriculum_year: str) -> list[RagChunkDraft]:
        courses = self.db.scalars(select(Course).order_by(Course.department_id, Course.major_id, Course.id)).all()
        drafts: list[RagChunkDraft] = []
        for course in courses:
            evidence_parts = [
                "2026 교육과정표",
                f"{course.year}학년" if course.year else None,
                f"{course.semester}학기" if course.semester else None,
                course.category,
                f"{course.credits:g}학점" if course.credits is not None else None,
            ]
            evidence = " / ".join(part for part in evidence_parts if part)
            title = f"{course.course_name} ({course.category or '이수구분 미상'})"
            content = (
                f"{evidence}. 과목명: {course.course_name}. "
                f"과목코드: {course.course_code or '미상'}. "
                f"학과 ID: {course.department_id or '공통'}, 전공 ID: {course.major_id or '공통'}."
            )
            drafts.append(
                RagChunkDraft(
                    document_type="curriculum",
                    source_table="courses",
                    source_id=course.id,
                    department_id=course.department_id,
                    major_id=course.major_id,
                    curriculum_year=curriculum_year,
                    category=course.category,
                    grade=course.year,
                    semester=course.semester,
                    course_id=course.id,
                    title=title,
                    content=content,
                    evidence=evidence,
                    source="courses:2026_curriculum",
                    chunk_metadata={
                        "course_code": course.course_code,
                        "course_name": course.course_name,
                        "credits": course.credits,
                    },
                )
            )
        return drafts

    def _graduation_requirement_drafts(self, *, curriculum_year: str) -> list[RagChunkDraft]:
        requirements = self.db.scalars(
            select(GraduationRequirement)
            .where(GraduationRequirement.curriculum_year == curriculum_year)
            .order_by(GraduationRequirement.department_id, GraduationRequirement.major_id, GraduationRequirement.id)
        ).all()
        drafts: list[RagChunkDraft] = []
        for requirement in requirements:
            for category, field_name in self.REQUIREMENT_FIELDS.items():
                credits = getattr(requirement, field_name)
                if credits is None:
                    continue
                evidence = (
                    f"{curriculum_year} 교육과정 {requirement.program_type or 'program'} "
                    f"{category} 기준학점 {credits}학점"
                )
                content = (
                    f"{evidence}. 학과 ID: {requirement.department_id or '공통'}, "
                    f"전공 ID: {requirement.major_id or '공통'}."
                )
                drafts.append(
                    RagChunkDraft(
                        document_type="graduation_requirement",
                        source_table="graduation_requirements",
                        source_id=requirement.id,
                        department_id=requirement.department_id,
                        major_id=requirement.major_id,
                        curriculum_year=curriculum_year,
                        category=category,
                        grade=None,
                        semester=None,
                        course_id=None,
                        title=f"{category} 졸업요건",
                        content=content,
                        evidence=evidence,
                        source="graduation_requirements",
                        chunk_metadata={
                            "program_type": requirement.program_type,
                            "required_credits": credits,
                        },
                    )
                )
        return drafts
