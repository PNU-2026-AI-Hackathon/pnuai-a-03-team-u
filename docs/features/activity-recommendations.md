# 비교과 활동 추천

**2026-07-07 제거됨.** 아래는 예전에 구현했던 내용의 기록이며, 지금 코드베이스에는
없다. 나중에 이 기능을 다시 만들 때 무엇을 이미 시도해봤는지 참고하려고 남겨둔다.

## 제거 이유

DB 스키마를 새 ERD로 전면 리셋하면서, 추천활동 기능은 처음부터 다시 설계해서
구현하기로 결정했다. 기존 구현(`Activity`/`UserActivityRecommendation` 테이블,
pgvector 임베딩 기반 추천)을 통째로 삭제했다.

삭제된 것:

- 테이블: `activities`, `user_activity_recommendations`, `extracurricular_programs`
- `app/api/activities.py` (`GET /activities/recommendations/{user_id}`)
- `app/ai/recommendations/extracurricular_recommender.py`
- `app/ai/embeddings/activity_embeddings.py`
- `app/ai/evaluation/recommendation_eval.py`
- `app/ingestion/normalizers/activity_normalizer.py`, `dedup_activities.py`
- `app/core/scheduler.py`의 자정 크롤 잡

남겨둔 것 (재구현 시 재사용 가능):

- `app/ingestion/crawlers/notice_board_crawler.py`, `notice_board_sources.py` — 순수
  크롤링 코드, DB 모델에 의존하지 않아 그대로 재사용 가능
- `app/ai/embeddings/openai_client.py` — OpenAI 임베딩 얇은 래퍼, 범용

## 예전 구현 요약 (참고용)

부산대 공개 게시판 7곳(swedu/uitc/pnucounsel/ctl/pusan_main/lib/job)을 크롤링해
`Activity` 테이블에 저장하고, 사용자 프로필(전공+진로) 임베딩과 코사인 유사도로
매칭해 추천 그리드를 제공하는 방식이었다.

- **크롤링**: 4개 엔진 타입(artclView/CMS Board/Pyxis JSON API/Job board)으로 파싱,
  최근 90일 lookback, 고정 게시물 중복 방지, 빈 제목 공지 제외
- **중복 정리**: 제목 완전 일치 + 게시일 3일 이내면 출처 달라도 중복으로 판단
  (pusan_main이 전문 게시판 공지를 재게시하는 경우 대응)
- **임베딩**: OpenAI `text-embedding-3-small`. 프로필 원문만 쓰면 "채용/모집 형식"에
  편향되는 문제가 있어 `gpt-4o-mini`로 분야 키워드 확장 후 원본+확장 블렌딩
- **추천 점수**: `similarity_score * career_weight(1.2배) * recency_weight(지수감쇠, 반감기 30일)`
- **평가**: LLM-as-judge(가상 페르소나 6명) 오프라인 평가로 P@10/nDCG@10 측정,
  최종 mean P@10 0.583 / mean nDCG@10 0.733까지 개선
- **알려진 약점**: 비IT 진로(특히 행정직) 추천 품질이 낮았음 — 코퍼스 자체에 해당
  분야 공지가 적은 게 근본 원인으로 보임(학교 본부/취업 게시판 위주라 개별 학과
  게시판 미포함)

다시 만들 때 고려할 점:

- 이번 ERD엔 `academic_info_articles`(학사정보 안내글)만 있고 비교과 프로그램
  전용 테이블(`extracurricular_programs`)은 빠졌다 — 새로 설계할 때 다시 넣을지 결정 필요
- 임베딩 기반 추천이 정말 필요한지부터 재검토 — 구조화된 필터(전공/학년/카테고리)로
  충분할 수도 있음
