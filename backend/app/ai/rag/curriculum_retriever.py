from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.ai.embeddings.openai_client import embed_text
from app.ai.rag.career_keywords import expand_career_query
from app.ai.rag.models import RagChunk
from app.domains.academics.models import GraduationRequirement
from app.domains.courses.models import Course


@dataclass(frozen=True)
class RagSearchFilters:
    grade: int | str | None = None
    semester: str | None = None
    category: str | None = None
    limit: int = 20

    @classmethod
    def from_dict(cls, filters: dict[str, Any] | None) -> "RagSearchFilters":
        filters = filters or {}
        return cls(
            grade=filters.get("grade"),
            semester=filters.get("semester"),
            category=filters.get("category"),
            limit=int(filters.get("limit") or 20),
        )


def _number_to_float(value: float | Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _stringify(value: int | str | None) -> str | None:
    return str(value) if value is not None else None


def _normalize_grade(value: int | str | None) -> str | None:
    if value is None:
        return None
    return str(value).replace("학년", "").strip()


def _normalize_semester(value: str | None) -> str | None:
    if value is None:
        return None
    return value.replace("학기", "").replace(" ", "").strip()


def _major_scope_filter(model: type[Course] | type[GraduationRequirement], major_id: int | None):
    if major_id is None:
        return model.major_id.is_(None)
    return or_(model.major_id == major_id, model.major_id.is_(None))


def _keyword_score(query: str, text: str) -> float:
    terms = expand_career_query(query)
    if not terms:
        return 0.0

    text = text.lower()
    hits = sum(1 for term in terms if term.lower() in text)
    exact_bonus = 1 if query.strip().lower() in text else 0
    return (hits / len(terms)) + exact_bonus


def _chunk_scope_filter(model: type[RagChunk], major_id: int | None):
    if major_id is None:
        return model.major_id.is_(None)
    return or_(model.major_id == major_id, model.major_id.is_(None))


class CurriculumRetriever:
    """DB-first curriculum retriever exposed through a RAG-shaped interface.

    The first version intentionally uses structured DB filtering instead of vector
    search. This keeps department/major/year boundaries strict while preserving a
    stable contract for a later semantic ranking layer.
    """

    def __init__(self, db: Session):
        self.db = db

    def search(
        self,
        *,
        query: str,
        department_id: int,
        major_id: int | None,
        curriculum_year: int | str,
        filters: RagSearchFilters | dict[str, Any] | None = None,
        use_vector: bool = True,
    ) -> list[dict[str, Any]]:
        parsed_filters = filters if isinstance(filters, RagSearchFilters) else RagSearchFilters.from_dict(filters)
        if use_vector and query.strip():
            vector_results = self._search_vector_chunks(
                query=query,
                department_id=department_id,
                major_id=major_id,
                curriculum_year=curriculum_year,
                filters=parsed_filters,
            )
            if vector_results:
                return vector_results

        # courses currently stores the imported 2026 curriculum rows, while
        # Course.year means recommended grade. Keep curriculum_year in the
        # public contract, but enforce the actual academic scope with
        # department/major metadata here.
        conditions = [
            or_(Course.department_id == department_id, Course.department_id.is_(None)),
            _major_scope_filter(Course, major_id),
        ]
        if parsed_filters.grade is not None:
            conditions.append(Course.year == _normalize_grade(parsed_filters.grade))
        if parsed_filters.semester:
            conditions.append(Course.semester == _normalize_semester(parsed_filters.semester))
        if parsed_filters.category:
            conditions.append(Course.category == parsed_filters.category)

        courses = self.db.scalars(
            select(Course)
            .where(and_(*conditions))
            .order_by(Course.year, Course.semester, Course.category, Course.course_name)
            .limit(max(max(parsed_filters.limit, 1) * 10, 100))
        ).all()

        ranked = sorted(
            courses,
            key=lambda course: (
                -_keyword_score(query, self._course_evidence(course)),
                course.year or "",
                course.semester or "",
                course.course_name,
            ),
        )
        return [self._course_to_result(course, query) for course in ranked[: parsed_filters.limit]]

    def _search_vector_chunks(
        self,
        *,
        query: str,
        department_id: int,
        major_id: int | None,
        curriculum_year: int | str,
        filters: RagSearchFilters,
    ) -> list[dict[str, Any]]:
        try:
            query_embedding = embed_text(" ".join(expand_career_query(query)))
            distance = RagChunk.embedding.cosine_distance(query_embedding)
            conditions = [
                RagChunk.document_type == "curriculum",
                RagChunk.curriculum_year == _stringify(curriculum_year),
                RagChunk.embedding.is_not(None),
                or_(RagChunk.department_id == department_id, RagChunk.department_id.is_(None)),
                _chunk_scope_filter(RagChunk, major_id),
            ]
            if filters.grade is not None:
                conditions.append(RagChunk.grade == _normalize_grade(filters.grade))
            if filters.semester:
                conditions.append(RagChunk.semester == _normalize_semester(filters.semester))
            if filters.category:
                conditions.append(RagChunk.category == filters.category)

            rows = self.db.execute(
                select(RagChunk, distance.label("distance"))
                .where(and_(*conditions))
                .order_by(distance)
                .limit(filters.limit)
            ).all()
        except (RuntimeError, SQLAlchemyError, ValueError):
            return []

        return [self._chunk_to_result(chunk, distance_value) for chunk, distance_value in rows]

    @staticmethod
    def _chunk_to_result(chunk: RagChunk, distance_value: float | None) -> dict[str, Any]:
        metadata = chunk.chunk_metadata or {}
        return {
            "course_id": chunk.course_id,
            "course_name": metadata.get("course_name") or chunk.title,
            "category": chunk.category,
            "credits": _number_to_float(metadata.get("credits")),
            "grade": chunk.grade,
            "semester": chunk.semester,
            "evidence": chunk.evidence,
            "source": chunk.source,
            "score": 1 - float(distance_value or 0),
            "document_type": chunk.document_type,
        }

    def _course_to_result(self, course: Course, query: str) -> dict[str, Any]:
        evidence = self._course_evidence(course)
        return {
            "course_id": course.id,
            "course_name": course.course_name,
            "category": course.category,
            "credits": _number_to_float(course.credits),
            "grade": course.year,
            "semester": course.semester,
            "evidence": evidence,
            "source": "courses:2026_curriculum",
            "score": _keyword_score(query, evidence),
            "document_type": "curriculum",
        }

    @staticmethod
    def _course_evidence(course: Course) -> str:
        parts = [
            f"{course.year}학년" if course.year else None,
            course.semester,
            course.category,
            f"{course.course_name}({course.credits}학점)" if course.credits is not None else course.course_name,
        ]
        return " ".join(part for part in parts if part)


class GraduationRequirementRetriever:
    """Graduation requirement lookup normalized for Agent consumption."""

    CATEGORY_FIELDS = {
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

    def search(
        self,
        *,
        query: str,
        department_id: int,
        major_id: int | None,
        curriculum_year: int | str,
        filters: RagSearchFilters | dict[str, Any] | None = None,
        program_type: str | None = "primary",
        use_vector: bool = True,
    ) -> list[dict[str, Any]]:
        parsed_filters = filters if isinstance(filters, RagSearchFilters) else RagSearchFilters.from_dict(filters)
        if use_vector and query.strip():
            vector_results = self._search_vector_chunks(
                query=query,
                department_id=department_id,
                major_id=major_id,
                curriculum_year=curriculum_year,
                filters=parsed_filters,
                program_type=program_type,
            )
            if vector_results:
                return vector_results

        conditions = [
            GraduationRequirement.department_id == department_id,
            _major_scope_filter(GraduationRequirement, major_id),
            GraduationRequirement.curriculum_year == _stringify(curriculum_year),
        ]
        if program_type:
            conditions.append(GraduationRequirement.program_type == program_type)

        requirements = self.db.scalars(select(GraduationRequirement).where(and_(*conditions))).all()
        if major_id is not None:
            exact_major = [requirement for requirement in requirements if requirement.major_id == major_id]
            requirements = exact_major or [requirement for requirement in requirements if requirement.major_id is None]

        results: list[dict[str, Any]] = []
        for requirement in requirements:
            for category, field_name in self.CATEGORY_FIELDS.items():
                if parsed_filters.category and parsed_filters.category != category:
                    continue
                credits = getattr(requirement, field_name)
                if credits is None:
                    continue
                evidence = (
                    f"{requirement.curriculum_year} 교육과정 {requirement.program_type or 'program'} "
                    f"{category} 기준학점 {credits}학점"
                )
                results.append(
                    {
                        "course_id": None,
                        "course_name": None,
                        "category": category,
                        "credits": float(credits),
                        "grade": None,
                        "semester": None,
                        "evidence": evidence,
                        "source": "graduation_requirements",
                        "score": _keyword_score(query, evidence),
                        "document_type": "graduation_requirement",
                    }
                )

        return sorted(results, key=lambda result: (-result["score"], result["category"]))

    def _search_vector_chunks(
        self,
        *,
        query: str,
        department_id: int,
        major_id: int | None,
        curriculum_year: int | str,
        filters: RagSearchFilters,
        program_type: str | None,
    ) -> list[dict[str, Any]]:
        try:
            query_embedding = embed_text(" ".join(expand_career_query(query)))
            distance = RagChunk.embedding.cosine_distance(query_embedding)
            conditions = [
                RagChunk.document_type == "graduation_requirement",
                RagChunk.curriculum_year == _stringify(curriculum_year),
                RagChunk.embedding.is_not(None),
                RagChunk.department_id == department_id,
                _chunk_scope_filter(RagChunk, major_id),
            ]
            if filters.category:
                conditions.append(RagChunk.category == filters.category)
            if program_type:
                conditions.append(RagChunk.chunk_metadata["program_type"].as_string() == program_type)

            rows = self.db.execute(
                select(RagChunk, distance.label("distance"))
                .where(and_(*conditions))
                .order_by(distance)
                .limit(filters.limit)
            ).all()
        except (RuntimeError, SQLAlchemyError, ValueError):
            return []

        results: list[dict[str, Any]] = []
        for chunk, distance_value in rows:
            metadata = chunk.chunk_metadata or {}
            results.append(
                {
                    "course_id": None,
                    "course_name": None,
                    "category": chunk.category,
                    "credits": _number_to_float(metadata.get("required_credits")),
                    "grade": None,
                    "semester": None,
                    "evidence": chunk.evidence,
                    "source": chunk.source,
                    "score": 1 - float(distance_value or 0),
                    "document_type": chunk.document_type,
                }
            )
        return results
