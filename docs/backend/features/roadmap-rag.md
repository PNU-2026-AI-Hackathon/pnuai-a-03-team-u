# 로드맵 RAG (교육과정표 · 졸업요건 검색)

RAG 담당자(#69, `agent/rag-pgvector-retrieval`)가 만든 검색 시스템. AI 로드맵
상담 Agent(`docs/backend/features/growth-roadmap.md`의 "AI 로드맵 상담" 절)가
과목/졸업요건 후보를 찾을 때 이걸 쓴다.

## pgvector 임베딩은 기본으로 안 쓰기로 함 (2026-07-13)

원래 설계는 "벡터 검색 우선 시도 → 실패/결과없음 시 구조화 DB 필터로 폴백"이었지만,
**`use_vector` 기본값을 `false`로 바꿔서 구조화 DB 필터를 기본 경로로 삼기로 했다.**
이유: `courses`/`graduation_requirements`는 애초에 학과/전공/학년/학기/이수구분이
전부 정형 컬럼으로 있는 카탈로그 데이터라, 자유 텍스트 문서를 의미 기반으로
찾아야 하는 전형적인 RAG 상황이 아니다. 정형 필터 + 진로 키워드 확장
(`career_keywords.py`)만으로 이미 "학과 스코프 정확히 좁히기 + 진로 관련 과목
우선 랭킹"이 다 되는데, 그 위에 임베딩 검색 단계를 하나 더 얹는 건 비용(OpenAI
API 호출)과 미검증 코드 경로(아래 2·3·4번 이슈)만 늘리고 실익이 크지 않다고
판단했다.

`RagChunk.embedding`/pgvector 스키마 자체는 지우지 않고 남겨둔다 — 나중에
"과목 설명/강의계획서처럼 진짜 자유 텍스트를 검색해야 하는 요구"가 생기면
`use_vector=true`로 다시 켤 수 있다.

## 구조

- `app/ai/rag/models.py` — `RagChunk`: `document_type`(curriculum/graduation_requirement),
  `department_id`/`major_id`/`curriculum_year`/`category`/`grade`/`semester` 메타데이터 +
  `embedding`(pgvector, 1536차원) 컬럼. 현재 기본 검색 경로에서는 안 쓰임(위 참고)
- `app/ai/rag/curriculum_ingestion.py` — `CurriculumRagIngestionService`: courses/
  graduation_requirements를 chunk로 만들어 `rag_chunks`에 적재, 임베딩은 선택적
- `app/ai/rag/curriculum_retriever.py` — `CurriculumRetriever`(과목 후보),
  `GraduationRequirementRetriever`(졸업요건). `use_vector=false`(기본)면 바로
  courses/graduation_requirements 테이블 구조화 필터 + 키워드 랭킹만 실행
- `app/ai/rag/career_keywords.py` — 진로 키워드 확장(기본 경로의 키워드 랭킹용)
- `app/api/rag.py` — `POST /rag/curriculum/search`, `POST /rag/graduation-requirements/search`,
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
수정 + 회귀 테스트 추가 후 머지됨.

### 2~4. 벡터 검색 관련 이슈(테스트 부재/예외 처리/embed_missing 연도 미scope) — **보류(무의미해짐)**

전부 `_search_vector_chunks` 경로에서만 발생하는 문제인데, 위 결정으로
`use_vector` 기본값이 `false`가 되면서 이 경로가 기본 흐름에서 실행되지
않는다. 코드/스키마는 남아있으니 나중에 벡터 검색을 다시 켤 일이 생기면
그때 같이 손보면 된다 — 지금 우선순위로 고칠 필요는 없어졌다.

### 5. `career_keywords.py` 진로 키워드가 5개뿐 — **여전히 유효, 우선순위 상승**

ai/data/backend/security/bio 5개 버킷만 있고 프론트/모바일/기획/클라우드 등은
키워드 확장이 안 된다. `use_vector=false`가 기본이 되면서 **이 키워드 확장이
이제 랭킹 품질을 좌우하는 유일한 경로**가 됐으므로, 다른 진로 키워드를 못
받아내는 게 이전보다 더 직접적인 영향을 준다.

## TODO

- [ ] 5번: `career_keywords.py` 진로 카테고리 확장 (우선순위 높음 — 유일한 랭킹 경로가 됨)
- [ ] (보류) 2~4번: 벡터 검색을 다시 켜기로 결정하면 그때 테스트 인프라/예외 처리/
      embed_missing scope를 같이 정리
