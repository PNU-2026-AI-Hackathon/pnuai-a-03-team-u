# 로드맵 RAG (교육과정표 · 졸업요건 검색)

RAG 담당자(#69, `agent/rag-pgvector-retrieval`)가 만든 검색 시스템. AI 로드맵
상담 Agent(`docs/backend/features/growth-roadmap.md`의 "AI 로드맵 상담" 절)가
과목/졸업요건 후보를 찾을 때 이걸 쓴다.

## pgvector 임베딩은 기본으로 안 쓰기로 함 (2026-07-13)

원래 설계는 "벡터 검색 우선 시도 → 실패/결과없음 시 구조화 DB 필터로 폴백"이었지만,
**`use_vector` 기본값을 `false`로 바꿔서 구조화 DB 필터를 기본 경로로 삼기로 했다.**
이유: `courses`/`graduation_requirements`는 애초에 학과/전공/학년/학기/이수구분이
전부 정형 컬럼으로 있는 카탈로그 데이터라, 자유 텍스트 문서를 의미 기반으로
찾아야 하는 전형적인 RAG 상황이 아니다. 정형 필터 + 진로 목표 원문 토큰 랭킹
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
- `app/ai/rag/career_keywords.py` — 진로 목표 원문 토큰화(기본 경로의 키워드 랭킹용)
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

### 5. `career_keywords.py` 진로 키워드가 5개뿐 — **수정 완료(카테고리 확장이 아니라 폐기)**

ai/data/backend/security/bio 5개 버킷만 있고 프론트/모바일/기획/클라우드 등은
키워드 확장이 안 됐다. 이 TODO는 원래 "카테고리를 더 추가하자"는 방향이었는데,
실제 사고([PR #244](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/244),
2026-08-25)를 계기로 다른 결론에 도달했다: 컴퓨터공학전공 학생(career_goal=
"시스템 프로그래머")에게 로드맵 챗이 심리학과 전공선택 과목을 "AI/웹응용
계열로 선택"이라는 사실과 다른 사유와 함께 제안한 사고를 조사하다가,
"시스템 프로그래머"가 5개 버킷 어디에도 안 걸려서 원문 토큰 2개로만
폴백했고 그 결과 실제 후보 15개 중 13개가 키워드 점수 0으로 나오는 걸
실측했다. 카테고리를 몇 개 더 추가해도 "학생이 실제로 입력하는 진로 문구는
사실상 무한"이라는 근본 문제는 안 풀린다 — 그래서 5개 버킷 확장 대신
**버킷 시스템 자체를 없애고 원문 토큰 매칭만 남겼다**(`expand_career_query`가
이제 `CAREER_ALIASES`를 안 거치고 항상 원문을 그대로 토큰화한다).

동시에 `_course_evidence`가 description을 150자로 자르던 것도 없앴다 —
2026-08-24 강의계획서 크롤링 파일럿([PR #241~#248](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/248))
이후 `courses.description`이 짧은 카탈로그 문구가 아니라 실제 교수목표/
강의개요 전문(수백 자)으로 바뀐 과목이 많아져서, 150자 컷이 그 내용 대부분을
매칭에서 잘라내고 있었다.

## 평가 — Precision@10 / nDCG@10 (2026-08-25)

`비교과 추천 평가`(`docs/backend/features/activity-recommendations.md`)와 같은
방법론(가상 페르소나 × LLM-as-judge)으로 이 검색 경로도 오프라인 평가했다 —
스크립트: `backend/scripts/eval_syllabus_rag.py`.

**방법**: 강의계획서 파일럿 대상 6개 학과/전공에서 페르소나 7명(학과/전공 +
진로 목표), 각각 `CurriculumRetriever.search()`(실제 서비스 기본 경로) 상위
10개 결과를 gpt-4o-mini로 관련성 판정.

**결과**(N=7 페르소나, 70개 후보):

| 지표 | 값 |
|---|---|
| 평균 Precision@10 | 0.529 |
| 평균 nDCG@10 | 0.903 |

**강의계획서 기반 description이 실제로 랭킹 품질을 끌어올리는지** — 후보를
"실제 강의계획서 크롤링 출처(source_document에 '교수계획표' 포함)"와 "그 외
(옛 카탈로그 문구 또는 설명 없음)"로 나눠 정밀도를 따로 냈다:

| 후보군 | 후보 수 | 관련 판정 | Precision |
|---|---:|---:|---:|
| 강의계획서 기반 | 23 | 19 | **83%** |
| 그 외 | 47 | 18 | 38% |

강의계획서 기반 후보가 전체의 33%(23/70)에 불과한데도 "관련 있음" 판정
전체의 51%(19/37)를 차지한다 — 실제 크롤링한 강의계획서 내용이 관련성
판정에서 카탈로그 문구/무설명보다 2배 이상 정밀하게 걸린다는 것을 정량으로
확인했다.

**낮게 나온 페르소나**(백엔드개발자 P@10=0.20, 사회조사전문가 P@10=0.20)의
원인은 둘 다 같았다 — 강의계획서로 안 채워진 후보(공학미적수학·대학영어·
생명의료윤리 등 기초/교양 과목)가 원문 토큰 매칭에서 우연히 걸려 상한선
근처까지 밀고 올라온다. 근본 해결은 진짜 의미 기반 매칭(임베딩)인데, 위
"pgvector 임베딩은 기본으로 안 쓰기로 함" 절 + 아래 TODO 참고.

## TODO

- [x] 5번: `career_keywords.py` 카테고리 확장 대신 폐기(원문 토큰 매칭만 사용) — PR #244
- [ ] `rag_chunks` 임베딩이 2026-07-13 마지막 적재(강의계획서 크롤링보다 한 달
      이상 전, 내용도 실제 description이 아니라 정형 메타데이터 문장)라 지금
      `use_vector=true`를 켜도 이 개선을 못 쓴다 — 재임베딩 파이프라인이 필요한
      더 큰 작업. 위 평가에서 확인한 "부분문자열 매칭의 한계"(낮은 P@10 케이스)를
      풀려면 결국 이 작업이 필요하다.
- [ ] (보류) 2~4번: 벡터 검색을 다시 켜기로 결정하면 그때 테스트 인프라/예외 처리/
      embed_missing scope를 같이 정리
