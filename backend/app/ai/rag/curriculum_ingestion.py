from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.embeddings.openai_client import embed_texts
from app.ai.rag.models import RagChunk
from app.domains.academics.models import GraduationRequirement
from app.domains.courses.models import Course, CourseOffering, CourseSyllabus


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
    """Builds RAG chunks from structured curriculum, graduation, and syllabus tables."""

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
            *self._syllabus_drafts(curriculum_year=year),
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

    def ingest_syllabi(
        self, *, curriculum_year: int | str = 2026, with_embeddings: bool = True
    ) -> dict[str, int | bool]:
        """One-Stop 교수계획표의 핵심 내용을 분반 단위 RAG 청크로 적재한다."""
        year = str(curriculum_year)
        self.db.execute(
            delete(RagChunk).where(
                RagChunk.curriculum_year == year,
                RagChunk.document_type == "syllabus",
            )
        )
        chunks = self._persist_drafts(self._syllabus_drafts(curriculum_year=year))
        embedded = self.embed_missing(document_type="syllabus") if with_embeddings else 0
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

    def _syllabus_drafts(self, *, curriculum_year: str) -> list[RagChunkDraft]:
        """강의계획서에서 RAG에 의미 있는 필드만 라벨을 붙여 한 청크로 묶는다.

        ``raw_text`` 전문은 파싱 재검증용 안전망으로 DB에 남긴다. 검색 청크에 그대로
        넣으면 PDF 표 레이블과 서식 노이즈가 의미 신호를 압도하므로, 여기에는 검증된
        구조화 필드(개요·목표·평가·선수과목·주차계획)만 넣는다.
        """
        rows = self.db.execute(
            select(CourseSyllabus, CourseOffering, Course)
            .join(CourseOffering, CourseOffering.id == CourseSyllabus.offering_id)
            .join(Course, Course.id == CourseOffering.course_id)
            .where(CourseOffering.year == curriculum_year)
            .order_by(Course.department_id, Course.major_id, CourseOffering.semester, CourseSyllabus.id)
        ).all()
        drafts: list[RagChunkDraft] = []
        for syllabus, offering, course in rows:
            parts = [
                f"강의개요: {syllabus.course_overview}" if syllabus.course_overview else None,
                f"교수목표: {syllabus.course_objectives}" if syllabus.course_objectives else None,
                f"선수과목/사전지식: {syllabus.prerequisites_text}" if syllabus.prerequisites_text else None,
                f"수업방식: {syllabus.teaching_mode}" if syllabus.teaching_mode else None,
                f"평가방법: {syllabus.evaluation_method}" if syllabus.evaluation_method else None,
                f"교재: {syllabus.textbooks}" if syllabus.textbooks else None,
                f"핵심역량: {', '.join(syllabus.core_competencies)}" if syllabus.core_competencies else None,
            ]
            if syllabus.weekly_plan:
                weekly = "; ".join(
                    f"{item.get('week')}: {item.get('content')}"
                    for item in syllabus.weekly_plan
                    if item.get("week") and item.get("content")
                )
                if weekly:
                    parts.append(f"주차계획: {weekly}")
            detail = "\n".join(part for part in parts if part)
            if not detail:
                # 연락처만 있는 빈 계획서는 검색 근거가 되지 않는다.
                continue
            term = offering.semester or "학기 미상"
            professor = offering.professor or "교수 미상"
            evidence = (
                f"One-Stop 교수계획표 / {curriculum_year}년 {term} / "
                f"{course.course_name} {offering.section or '분반 미상'}분반 / {professor}"
            )
            content = (
                f"{evidence}. 과목명: {course.course_name}. "
                f"과목코드: {course.course_code or '미상'}. {detail}"
            )
            drafts.append(
                RagChunkDraft(
                    document_type="syllabus",
                    source_table="course_syllabi",
                    source_id=syllabus.id,
                    department_id=course.department_id,
                    major_id=course.major_id,
                    curriculum_year=curriculum_year,
                    category=course.category,
                    grade=course.year,
                    semester=(term.replace("학기", "") if term in {"1학기", "2학기"} else term),
                    course_id=course.id,
                    title=f"{course.course_name} 강의계획서 ({offering.section or '분반 미상'})",
                    content=content,
                    evidence=evidence,
                    source=f"course_syllabi:{curriculum_year}_{term}",
                    chunk_metadata={
                        "course_name": course.course_name,
                        "course_code": course.course_code,
                        "credits": course.credits,
                        "offering_id": offering.id,
                        "section": offering.section,
                        "professor": offering.professor,
                    },
                )
            )
        return drafts
