# 비교과 활동 추천

크롤링된 `Activity`(→ [notice-board-crawler.md](./notice-board-crawler.md))를 사용자의
전공/진로 프로필과 임베딩 유사도로 매칭해 개인화 추천 그리드를 제공한다.

## 임베딩

- `app/ai/embeddings/openai_client.py` — OpenAI `text-embedding-3-small`(1536차원) 얇은 래퍼
- `app/ai/embeddings/activity_embeddings.py` — `Activity.embedding`이 비어있는 행을 찾아
  `title + category + description`을 합쳐 100개씩 배치로 임베딩 생성
- 제목이 빈 문자열인 행은 배치에서 제외 (OpenAI API가 빈 입력을 거부함)
- 사용자 프로필 임베딩은 요청 시점에 즉석으로 생성 (department + `UserAcademicProgram.major` + career_goal)

## 추천 점수 계산 (`app/ai/recommendations/extracurricular_recommender.py`)

```
final_score = similarity_score * career_weight * recency_weight
```

- `similarity_score`: 사용자 프로필 임베딩과 Activity 임베딩의 코사인 유사도 (pgvector `cosine_distance`)
- `career_weight`: `career_goal`이 설정되어 있으면 1.2배, 없으면 1.0배
- `recency_weight`: 게시일 기준 90일 선형 감쇠 (게시 당일 1.0 → 90일 경과 시 0.5)
- 마감일이 지난 활동, 게시일이 90일보다 오래된 활동은 후보에서 제외
- 상위 50개(`_TOP_K`)를 계산해 `UserActivityRecommendation`에 upsert (user_id + activity_id unique)
- `UserActivityRecommendation.user_id`/`activity_id`는 `ForeignKey(ondelete="CASCADE")` — 유저/활동이 삭제되면 추천 레코드도 같이 삭제됨

## API

`GET /activities/recommendations/{user_id}` (`app/api/activities.py`)

- 캐시된 추천이 있으면 즉시 반환, 없으면 그 자리에서 계산 후 반환 (최초 요청은 지연 있음)
- 응답 필드: `title`, `category`, `source`, `deadline`, `d_day`, `recommendation_score`(0~100%)
- **로그인 시스템이 아직 없어서 `user_id`를 그냥 경로 파라미터로 받는다.** 인증이 붙으면
  `get_current_user` 의존성으로 교체 필요

## 스케줄링

자정 크롤 → 중복 정리 → embedding 생성 → 전체 사용자 추천 재계산 순으로
`app/core/scheduler.py`가 매일 자동 실행한다.

## 알려진 한계 / TODO

- 추천 정확도 정량 평가 없음 (현재는 카테고리 감으로만 확인)
- 프론트엔드 그리드 UI 미연동
- 로그인 붙기 전까지 추천 API는 인증 없이 `user_id`로 직접 조회 가능
