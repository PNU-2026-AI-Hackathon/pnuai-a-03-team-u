from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_, or_, select, true
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


def _semester_for_display(value: str | None) -> str | None:
    """courses.semester 원시값을 사용자·LLM에게 보여줄 정규 형태로 바꾼다.

    DB에는 `"1"`, `"2"`, `"1,2"`, `"전학기"`, `"여름계절수업"` 등이 섞여 있는데,
    로드맵 항목(planned_semester)과 이수기록(StudentCourseRecord.semester)은
    `"1학기"`/`"2학기"` 형태로 저장돼 있다. 에이전트가 `search_courses` 결과의
    학기값을 그대로 `propose_change.planned_semester`로 흘려도 이 두 계열이
    일치하도록 여기서 맞춰준다. `"1,2"`는 "학기 무관" 의미라 별도 문구로 바꾼다.
    """
    if value is None:
        return None
    v = value.strip()
    if v in ("1", "2"):
        return f"{v}학기"
    if v == "1,2":
        return "1학기 또는 2학기"
    return v


# 졸업요건 표기(교양필수/교양선택)와 courses.category 원시값(효원핵심교양 등) 사이의
# 매핑. LLM/사용자는 요건 표기로 필터하고, DB는 원시 카테고리로 저장돼 있어 exact match만
# 하면 아무것도 안 잡히던 문제를 여기서 흡수한다. 판정 엔진의 CATEGORY_FIELDS와 정합.
_CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "교양필수": ("효원핵심교양", "기초교양"),
    "교양선택": ("효원균형교양", "효원창의교양"),
}


def _category_condition(category: str):
    """카테고리 필터를 실제 DB 값들의 OR 조건으로 확장한다.
    매핑에 없는 값(전공기초/전공필수/전공선택 등)은 exact match 그대로 유지한다.
    """
    aliases = _CATEGORY_ALIASES.get(category)
    if not aliases:
        return Course.category == category
    return Course.category.in_((category, *aliases))


def _major_scope_filter(model: type[Course] | type[GraduationRequirement], major_id: int | None):
    """major_id가 없으면(전공 미확정/미세분 학과) 전공 조건으로 좁히지 않는다.

    major_id가 있을 때는 "그 전공 것 + 학과 공통(major_id NULL) 것"을 모두 보여주는데,
    major_id가 없다고 해서 major_id IS NULL인 행만 보여주면 학부제 학과에서 전공을
    아직 정하지 않은 학생은 전공별 과목을 하나도 못 보는 비대칭이 생긴다(department_id는
    이미 상위에서 걸러졌으므로 여기서는 제한을 두지 않는 것이 맞다).
    """
    if major_id is None:
        return true()
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
    """_major_scope_filter와 동일한 이유로 major_id 미지정 시 제한을 두지 않는다."""
    if major_id is None:
        return true()
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
        use_vector: bool = False,
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
            # 학년 필터에 특정 학년(1~4)을 넣으면 courses.year가 정확히 그 값이거나
            # "전학년"(학년 무관 개설)인 과목을 함께 반환한다. 후자를 배제해버리면
            # 사실상 언제나 이수 가능한 과목들이 결과에서 통째로 빠져 검색 결과가
            # 필요 이상으로 좁아진다(3학년 2학기 추천을 요청했는데 "전학년" 과목이
            # 아예 안 나오는 회귀 사례가 관측됨).
            normalized_grade = _normalize_grade(parsed_filters.grade)
            if normalized_grade in {"1", "2", "3", "4", "5", "6"}:
                conditions.append(or_(Course.year == normalized_grade, Course.year == "전학년"))
            else:
                conditions.append(Course.year == normalized_grade)
        if parsed_filters.semester:
            # 학기 필터도 같은 이유로 정규 1/2학기를 지정하면 학기 무관 개설
            # ("1,2"/"전학기") 과목도 함께 반환한다. 계절수업/도약수업 등 방학 세션
            # 값은 그대로 exact match — 정규 학기 요청에 계절수업 과목이 섞이면
            # 안 되고, 계절수업 요청에 정규 과목이 섞이면 안 된다.
            normalized_semester = _normalize_semester(parsed_filters.semester)
            if normalized_semester in {"1", "2"}:
                conditions.append(
                    or_(
                        Course.semester == normalized_semester,
                        Course.semester == "1,2",
                        Course.semester == "전학기",
                    )
                )
            else:
                conditions.append(Course.semester == normalized_semester)
        if parsed_filters.category:
            conditions.append(_category_condition(parsed_filters.category))

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
        # 같은 개념 과목이 학과별 서로 다른 course_code로 여러 행 시딩된 경우(주로 교양:
        # ZE1000119/DM1100179/CB1000119/ZE1000118 = 모두 "공학작문및발표") LLM에 중복
        # 후보를 밀어넣지 않도록 (이름, 카테고리) 기준 dedup. 순위상 먼저 나온 걸 남긴다.
        deduped: list[Course] = []
        seen: set[tuple[str, str | None]] = set()
        for course in ranked:
            key = (course.course_name, course.category)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(course)
        return [self._course_to_result(course, query) for course in deduped[: parsed_filters.limit]]

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
            "semester": _semester_for_display(chunk.semester),
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
            "semester": _semester_for_display(course.semester),
            "evidence": evidence,
            "source": "courses:2026_curriculum",
            "score": _keyword_score(query, evidence),
            "document_type": "curriculum",
            "description": course.description,
        }

    @staticmethod
    def _course_evidence(course: Course) -> str:
        parts = [
            f"{course.year}학년" if course.year else None,
            course.semester,
            course.category,
            f"{course.course_name}({course.credits}학점)" if course.credits is not None else course.course_name,
        ]
        evidence = " ".join(part for part in parts if part)
        if course.description:
            snippet = course.description if len(course.description) <= 150 else f"{course.description[:150]}…"
            evidence = f"{evidence} — {snippet} (※ 과목명이 같은 개편 이전 자료 기반 설명, 현재 내용과 다를 수 있음)"
        return evidence


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
        use_vector: bool = False,
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
