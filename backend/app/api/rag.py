from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.rag.curriculum_ingestion import CurriculumRagIngestionService
from app.ai.rag.curriculum_retriever import CurriculumRetriever, GraduationRequirementRetriever
from app.api.auth import get_current_user
from app.core.db import get_db
from app.domains.users.models import User

router = APIRouter(prefix="/rag", tags=["rag"])


class RagSearchRequest(BaseModel):
    query: str = ""
    department_id: int
    major_id: int | None = None
    curriculum_year: int | str = 2026
    filters: dict[str, Any] = Field(default_factory=dict)
    # 기본 false: 정형 courses/graduation_requirements를 그대로 구조화 필터링하면
    # 되는 데이터라 pgvector 임베딩 검색을 굳이 앞단에 둘 필요가 없다고 판단했다.
    # 벡터 검색 코드/rag_chunks.embedding 컬럼 자체는 남겨둔다(필요해지면 true로 켬).
    use_vector: bool = False


class GraduationRequirementSearchRequest(RagSearchRequest):
    program_type: str | None = "primary"


class RagSearchResult(BaseModel):
    course_id: int | None
    course_name: str | None
    category: str | None
    credits: float | None
    grade: str | None
    semester: str | None
    evidence: str
    source: str
    score: float
    document_type: str


class RagSearchResponse(BaseModel):
    query: str
    department_id: int
    major_id: int | None
    curriculum_year: int | str
    filters: dict[str, Any]
    results: list[RagSearchResult]


class RagIngestionRequest(BaseModel):
    curriculum_year: int | str = 2026
    target: str = "all"
    with_embeddings: bool = False


class RagIngestionResponse(BaseModel):
    chunks_created: int
    embeddings_created: int
    embedding_enabled: bool


@router.post("/curriculum/search", response_model=RagSearchResponse)
def search_curriculum(
    payload: RagSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RagSearchResponse:
    """Search 2026 curriculum courses with strict department/major filters."""
    results = CurriculumRetriever(db).search(
        query=payload.query,
        department_id=payload.department_id,
        major_id=payload.major_id,
        curriculum_year=payload.curriculum_year,
        filters=payload.filters,
        use_vector=payload.use_vector,
    )
    return RagSearchResponse(
        query=payload.query,
        department_id=payload.department_id,
        major_id=payload.major_id,
        curriculum_year=payload.curriculum_year,
        filters=payload.filters,
        results=results,
    )


@router.post("/graduation-requirements/search", response_model=RagSearchResponse)
def search_graduation_requirements(
    payload: GraduationRequirementSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RagSearchResponse:
    """Search flat graduation requirement credits in the same RAG-shaped response."""
    results = GraduationRequirementRetriever(db).search(
        query=payload.query,
        department_id=payload.department_id,
        major_id=payload.major_id,
        curriculum_year=payload.curriculum_year,
        filters=payload.filters,
        program_type=payload.program_type,
        use_vector=payload.use_vector,
    )
    return RagSearchResponse(
        query=payload.query,
        department_id=payload.department_id,
        major_id=payload.major_id,
        curriculum_year=payload.curriculum_year,
        filters=payload.filters,
        results=results,
    )


@router.post("/ingest", response_model=RagIngestionResponse)
def ingest_rag_chunks(
    payload: RagIngestionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RagIngestionResponse:
    """Build RAG chunks from courses/graduation_requirements.

    with_embeddings=false is useful for local/dev environments without an
    OPENAI_API_KEY. Vector search becomes active after embeddings are generated.
    """
    service = CurriculumRagIngestionService(db)
    options = {
        "curriculum_year": payload.curriculum_year,
        "with_embeddings": payload.with_embeddings,
    }
    if payload.target == "curriculum":
        result = service.ingest_curriculum(**options)
    elif payload.target == "graduation-requirements":
        result = service.ingest_graduation_requirements(**options)
    elif payload.target == "all":
        result = service.rebuild_all(**options)
    else:
        raise HTTPException(status_code=400, detail="target은 all, curriculum, graduation-requirements 중 하나여야 합니다")
    return RagIngestionResponse(**result)
