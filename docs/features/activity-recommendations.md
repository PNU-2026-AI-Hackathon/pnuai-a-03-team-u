# 비교과 활동 추천

부산대 공개 게시판에서 비교과 활동 공지를 크롤링하고, 사용자의 전공/진로 프로필과
임베딩 유사도로 매칭해 개인화 추천 그리드를 제공한다.

## 1. 크롤링 (`app/ingestion/crawlers/notice_board_crawler.py`)

로그인 없이 접근 가능한 부산대 공개 게시판 7곳을 크롤링해 `Activity` 테이블에 저장한다.
`my.pusan.ac.kr`의 개인화 비교과 페이지는 로그인이 필수라 사용하지 않는다.

`app/ingestion/crawlers/notice_board_sources.py`에 소스를 등록하고, 4개 엔진 타입으로 파싱한다.

| 엔진 | 소스 | 방식 |
| --- | --- | --- |
| artclView | swedu, uitc, pnucounsel, ctl | `artclList.do`에 POST, `table.board-table` 파싱 |
| CMS Board | pusan_main | `CMS/Board.do`에 GET, `table.board-list-table` 파싱 |
| Pyxis JSON API | lib | Angular SPA라 정적 HTML 없음 → `/pyxis-api/1/bulletin-boards/2/bulletins` 내부 API 직접 호출 |
| Job board | job | `/ko/notice/notice/list/{page}` GET, `li.tbody` 파싱 |

### 수집 규칙

- 최근 90일(`DEFAULT_LOOKBACK_DAYS`) 게시물만 수집. 페이지네이션 중 비고정 게시물이 전부 90일 이전이면 그 출처는 중단
- 고정(pinned) 게시물은 1페이지에서만 수집 (중복 방지)
- 제목이 빈 문자열인 게시물은 제외 (예: job 게시판의 이미지 배너 전용 공지 — 텍스트 제목 자체가 없어 추천에 쓸 수 없음)
- `source + source_url` unique constraint로 같은 글 중복 저장 방지 (upsert)

### 중복 정리 (`app/ingestion/normalizers/dedup_activities.py`)

크롤러가 재게시/페이지네이션 경계 문제로 같은 공지를 다른 URL로 두 번 수집하는 경우를 정리한다.

- 조건: **같은 출처 + 제목 완전 일치 + 게시일 3일 이내**인 경우만 중복으로 판단, 조회수가 더 높은(또는 더 최신인) 쪽만 남김
- 제목 유사도(예: 80% 이상)만으로 판단하지 않는 이유: 회차별/재모집 공고(예: "하나은행" vs "한국은행" 채용설명회, "5월" vs "6월" 도서관 프로그램)는 제목이 비슷해도 실제로 다른 공지이기 때문
- 자정 크롤 직후 자동 실행

### 카테고리/마감일 자동 추론 (`app/ingestion/normalizers/activity_normalizer.py`)

- 제목 키워드로 카테고리 1차 분류: 공모전/인턴십/취업/장학금/스터디/교내활동/강연특강/교육프로그램/도서관/상담
- 제목에서 마감일 패턴 파싱: `~7/6`, `(7/10)`, `7/15마감`, `6월 30일까지` 등
- embedding 컬럼은 건드리지 않음 (별도 배치가 담당, 아래 참고)

## 2. 임베딩

- `app/ai/embeddings/openai_client.py` — OpenAI `text-embedding-3-small`(1536차원) 얇은 래퍼
- `app/ai/embeddings/activity_embeddings.py` — `Activity.embedding`이 비어있는 행을 찾아
  `title + category + description`을 합쳐 100개씩 배치로 임베딩 생성
- 제목이 빈 문자열인 행은 배치에서 제외 (OpenAI API가 빈 입력을 거부함)
- 사용자 프로필 임베딩은 요청 시점에 즉석으로 생성 (department + `UserAcademicProgram.major` + career_goal)

## 3. 추천 점수 계산 (`app/ai/recommendations/extracurricular_recommender.py`)

```
final_score = similarity_score * career_weight * recency_weight
```

- `similarity_score`: 사용자 프로필 임베딩과 Activity 임베딩의 코사인 유사도 (pgvector `cosine_distance`)
- `career_weight`: `career_goal`이 설정되어 있으면 1.2배, 없으면 1.0배
- `recency_weight`: 게시일 기준 90일 선형 감쇠 (게시 당일 1.0 → 90일 경과 시 0.5)
- 마감일이 지난 활동, 게시일이 90일보다 오래된 활동은 후보에서 제외
- 상위 50개(`_TOP_K`)를 계산해 `UserActivityRecommendation`에 upsert (user_id + activity_id unique)
- `UserActivityRecommendation.user_id`/`activity_id`는 `ForeignKey(ondelete="CASCADE")` — 유저/활동이 삭제되면 추천 레코드도 같이 삭제됨

## 4. API

`GET /activities/recommendations/{user_id}` (`app/api/activities.py`)

- 캐시된 추천이 있으면 즉시 반환, 없으면 그 자리에서 계산 후 반환 (최초 요청은 지연 있음)
- 응답 필드: `title`, `category`, `source`, `deadline`, `d_day`, `recommendation_score`(0~100%)
- **로그인 시스템이 아직 없어서 `user_id`를 그냥 경로 파라미터로 받는다.** 인증이 붙으면
  `get_current_user` 의존성으로 교체 필요

## 스케줄링

`app/core/scheduler.py`의 APScheduler가 매일 00:00 KST(`Asia/Seoul`)에 다음을 순서대로 실행한다.

1. 7개 출처 크롤 → JSON 백업(`raw_data/crawled_data/notice_boards/{date}.json`) → `Activity` upsert
2. 중복 정리
3. embedding 생성 (신규/미처리 Activity만)
4. 전체 사용자 추천 재계산

## 알려진 한계 / TODO

- job 게시판에서 텍스트 제목 없는 이미지 배너 공지는 제외되므로 해당 공고는 노출되지 않음
- 90일 이전 게시물은 페이지네이션 중단 기준일 뿐 강제 삭제하지는 않음 (추천 API 쪽에서 필터링)
- 추천 정확도 정량 평가 없음 (현재는 카테고리 감으로만 확인)
- 프론트엔드 그리드 UI 미연동
- 로그인 붙기 전까지 추천 API는 인증 없이 `user_id`로 직접 조회 가능
