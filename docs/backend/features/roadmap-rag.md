# 로드맵 RAG (교육과정표 · 졸업요건 검색)

RAG 담당자(#69, `agent/rag-pgvector-retrieval`)가 만든 pgvector 기반 검색
시스템. AI 로드맵 상담 Agent(`docs/backend/features/growth-roadmap.md`의 "AI 로드맵
상담" 절)가 과목/졸업요건 후보를 찾을 때 이걸 쓴다.

## 구조

- `app/ai/rag/models.py` — `RagChunk`: `document_type`(curriculum/graduation_requirement),
  `department_id`/`major_id`/`curriculum_year`/`category`/`grade`/`semester` 메타데이터 +
  `embedding`(pgvector, 1536차원) 컬럼
- `app/ai/rag/curriculum_ingestion.py` — `CurriculumRagIngestionService`: courses/
  graduation_requirements를 chunk로 만들어 `rag_chunks`에 적재, 임베딩은 선택적
- `app/ai/rag/curriculum_retriever.py` — `CurriculumRetriever`(과목 후보),
  `GraduationRequirementRetriever`(졸업요건). 둘 다 **벡터 검색 우선 시도 →
  실패/결과없음 시 courses/graduation_requirements 테이블 구조화 필터로 폴백**
- `app/ai/rag/career_keywords.py` — 진로 키워드 확장(DB 폴백 경로의 키워드 랭킹용)
- `app/api/rag.py` — `GET /rag/curriculum/search`, `GET /rag/graduation-requirements/search`,
  `POST /rag/ingest`

## 코드 리뷰에서 확인한 이슈

머지 후 리뷰([PR #69](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/69))에서
발견한 것들. 심각도 순.

### 1. `major_id` 미지정 시 전공별 과목이 전부 빠지는 비대칭 필터 — **수정 완료**

`_major_scope_filter`/`_chunk_scope_filter`가 `major_id`가 있을 때는
"그 전공 것 + 학과 공통(major_id NULL) 것"을 보여주면서, `major_id`가 없을 때는
`major_id IS NULL`인 것만 보여줘서 학부제 학과에서 전공 미확정 학생은 전공별
과목을 하나도 못 보는 문제였다. `department_id`는 이미 상위에서 걸러지므로
`major_id`가 없을 때는 전공 조건 자체를 두지 않도록 고쳤다. AI 로드맵 상담
Agent의 `search_courses` 도구가 바로 이 리트리버를 호출하기 때문에 실사용
경로에서 걸릴 수 있는 버그였다.

[PR #72](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/72)에서
수정 + 회귀 테스트 추가(머지 대기 중).

### 2. 벡터 검색 경로가 사실상 테스트가 안 되어 있음 — **미수정**

`tests/test_rag_retriever.py`는 테스트 DB에 `RagChunk` 테이블 자체를 안
만들고, `use_vector=True`도 (OPENAI 키가 없는 테스트 환경이라) 항상 예외가 나서
DB 폴백 경로로만 빠진다. `_search_vector_chunks`(cosine_distance 정렬, scope
조건, `program_type` JSON 필터)는 커버리지 0%.

**막힌 지점**: `RagChunk.embedding`이 `pgvector.sqlalchemy.Vector` 타입이라
기존 테스트가 쓰는 SQLite 인메모리 엔진에서 테이블 생성이 안 된다(pgvector
확장 필요). 제대로 테스트하려면 실제 Postgres+pgvector 테스트 DB(예:
testcontainers)가 필요한데, 지금 테스트 스위트는 그런 인프라가 없다. 별도로
테스트 DB 구성을 정하고 나서 처리하는 게 맞아 보임.

### 3. 벡터 검색 실패를 너무 넓게 삼킴 — **미수정**

```python
except (RuntimeError, SQLAlchemyError, ValueError):
    return []
```

"API 키 없음"(예상된 상황, `RuntimeError`)과 "필터 로직 버그"(`SQLAlchemyError`/
`ValueError`, 진짜 버그)를 구분 안 하고 둘 다 조용히 DB 폴백으로 넘어간다.
2번(테스트 부재)과 겹쳐서, 벡터 경로가 배포 후 깨져도 로그 하나 없이 발견이
안 될 수 있다. 최소한 `RuntimeError`(키 없음) 외의 예외는 로깅하고 넘어가는
정도로 고치는 게 좋겠다.

### 4. `embed_missing()`이 연도로 안 좁혀짐 — **미수정**

`curriculum_ingestion.py`의 `embed_missing()`이 `embedding IS NULL`인 chunk를
연도 구분 없이 전역으로 가져온다. 특정 연도만 재구축(`rebuild_all(curriculum_year=2026,
with_embeddings=True)`)해도 다른 연도의 임베딩 안 된 잔여 chunk까지 같이
임베딩 비용을 쓰게 된다.

### 5. `career_keywords.py` 진로 키워드가 5개뿐 — **미수정**

ai/data/backend/security/bio 5개 버킷만 있고 프론트/모바일/기획/클라우드 등은
키워드 확장이 안 돼서, DB 폴백 경로(2·3번 때문에 실질적으로 자주 타는 경로)의
랭킹 품질이 진로에 따라 들쭉날쭉하다.

## TODO

- [ ] 2번: Postgres+pgvector 테스트 인프라 결정 후 벡터 검색 경로 테스트 추가
- [ ] 3번: 벡터 검색 예외 처리 세분화 + 로깅
- [ ] 4번: `embed_missing()`에 `curriculum_year` 파라미터 추가
- [ ] 5번: `career_keywords.py` 진로 카테고리 확장
