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

같은 공지가 두 번 이상 수집되는 경우를 정리한다. 두 가지 경로가 있다:
같은 출처 안에서 다른 URL로 재게시된 경우, 그리고 pusan_main(대학 본부 포털)이
전문 게시판(job, pnucounsel 등)의 공지를 재게시해 **출처가 달라도 같은 공지**인 경우.

- 조건: **제목 완전 일치 + 게시일 3일 이내**인 경우만 중복으로 판단 (출처 무관)
- 유지 우선순위: 임베딩 보유 > 조회수 > 게시일. 임베딩 보유를 최우선으로 두는 이유 —
  삭제된 쪽 출처는 다음 크롤에서 새 행으로 다시 upsert되는데, 임베딩 유무를 안 보면
  매일 밤 "기존 임베딩된 행을 지우고 새 행을 다시 임베딩"하는 순환이 생김
- 제목 유사도(예: 80% 이상)만으로 판단하지 않는 이유: 회차별/재모집 공고(예: "하나은행" vs "한국은행" 채용설명회, "5월" vs "6월" 도서관 프로그램)는 제목이 비슷해도 실제로 다른 공지이기 때문
- 자정 크롤 직후 자동 실행

### 시설 운영/행정성 공지 제외 (`_is_excluded`, `activity_normalizer.py`)

학생이 "참여"할 수 있는 활동이 아닌 공지(도서관 개관시간 변경, 학자금대출 안내 등)는
`upsert_activity`에서 아예 저장하지 않는다. 도서관(`lib`) 출처에서 특히 많이 나온다
(운영 공지 게시판이 활동 공지판과 분리돼 있지 않음). 학과 게시판을 나중에 추가하면
이런 행정성 공지 비중이 더 늘어날 것으로 예상되어 미리 마련해뒀다.

부수적으로 카테고리 분류 버그도 같이 고쳤다: `도서관` 카테고리가 제목의 "대출"만
보고 매칭해서 "학자금대출"(재정 지원 공지)까지 도서관으로 잘못 분류되고 있었음
→ "도서 대출/반납"으로 패턴 한정.

### 원본에서 내려간 공지 정리 (`remove_stale_activities`, `activity_normalizer.py`)

upsert는 추가/갱신만 하고 삭제는 안 하므로, 별도 정리가 없으면 원본 사이트에서
지워진 공지가 DB에 영구히 남는다. 매일 전체 삭제 후 재삽입하는 방식은 배제했다 —
Activity id가 매번 바뀌면 임베딩을 전부 다시 계산해야 하고 추천 캐시(FK)도 다 날아가기 때문.

대신 부분 삭제로 처리한다: 출처별로 이번 크롤에서 실제로 보인 `source_url` 집합을 구하고,
90일 lookback 안에 있으면서 이번에 안 보인 Activity만 삭제한다. lookback 밖의 글은
크롤러가 애초에 다시 방문하지 않으므로 "안 보였다"고 지우면 안 되어 대상에서 제외한다.
내용이 그대로인 Activity는 id/embedding을 건드리지 않는다.

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

### 프로필 확장 (query expansion)

프로필 원문("행정학과 행정직 공무원")만 임베딩하면 유사도가 진로 분야보다 "채용/모집"
같은 공지 형식에 끌리는 문제가 오프라인 평가에서 확인됐다. 그래서 임베딩 전에
`gpt-4o-mini`로 프로필을 분야 키워드 15~20개로 확장한다(예: 공무원 시험, 공공기관,
행정체험, NCS...). 같은 프로필은 프로세스 내 캐시로 한 번만 확장한다.

단, **확장 임베딩만 쓰면 역효과 케이스가 있다**: 코퍼스에 해당 분야 공지가 거의 없으면
(평가에서 화학 연구원이 P@10 0.6 → 0.1로 붕괴) 쿼리만 구체화되고 매칭이 없어 순위가
노이즈가 된다. 그래서 **원본 임베딩과 확장 임베딩을 평균(블렌딩)**해서, 확장이 잘 맞는
분야는 이득을 유지하고 매칭 없는 분야는 원본 신호를 안전망으로 삼는다.

## 3. 추천 점수 계산 (`app/ai/recommendations/extracurricular_recommender.py`)

```
final_score = similarity_score * career_weight * recency_weight
```

- `similarity_score`: 사용자 프로필 임베딩과 Activity 임베딩의 코사인 유사도 (pgvector `cosine_distance`)
- `career_weight`: `career_goal`이 설정되어 있으면 1.2배, 없으면 1.0배
- `recency_weight`: 게시일 기준 지수 감쇠, 반감기 30일(`_RECENCY_HALF_LIFE_DAYS`) —
  최신 공지일수록 순위가 확실히 위로 오도록 함 (최솟값 0.1, 게시일 없으면 0.1)
- 게시일이 90일(`_LOOKBACK_DAYS`)보다 오래된 활동은 후보에서 제외

### 신청 기간이 끝난 공지 필터링

- 마감일이 파싱된 공지(전체의 약 11%, 제목에서 정규식으로 추출됨)는 마감일이 지나면 정확히 제외
- 마감일이 파싱되지 않은 나머지(약 89%)는 게시일이 45일(`_NO_DEADLINE_ACTIVE_DAYS`) 지나면
  신청 기간이 끝났다고 보고 제외한다. 대부분의 비교과 활동 신청 기간이 길어야 한두 달이라는
  가정에 기반한 휴리스틱 — 실제로 이 규칙으로 현재 DB에서 154건이 제외됨
- 상위 50개(`_TOP_K`)를 계산해 `UserActivityRecommendation`에 upsert (user_id + activity_id unique)
- `UserActivityRecommendation.user_id`/`activity_id`는 `ForeignKey(ondelete="CASCADE")` — 유저/활동이 삭제되면 추천 레코드도 같이 삭제됨

## 4. API

`GET /activities/recommendations/{user_id}` (`app/api/activities.py`)

- 캐시된 추천이 있으면 즉시 반환, 없으면 그 자리에서 계산 후 반환 (최초 요청은 지연 있음)
- 응답 필드: `title`, `category`, `source`, `deadline`, `d_day`, `recommendation_score`(0~100%)
- **아직 `get_current_user`로 전환 안 됨** — [core-auth.md](./core-auth.md)의 로그인/회원가입은
  구현됐지만, 이 API는 여전히 `user_id`를 그냥 경로 파라미터로 받는다. 전환은 별도 작업

## 스케줄링

`app/core/scheduler.py`의 APScheduler가 매일 00:00 KST(`Asia/Seoul`)에 다음을 순서대로 실행한다.

1. 7개 출처 크롤 → JSON 백업(`raw_data/crawled_data/notice_boards/{date}.json`) → `Activity` upsert
2. 원본에서 내려간 공지 정리 (부분 삭제)
3. 중복 정리
4. embedding 생성 (신규/미처리 Activity만)
5. 전체 사용자 추천 재계산

## 정확도 평가 (`app/ai/evaluation/recommendation_eval.py`)

실사용 데이터가 없으므로 오프라인 평가로 측정한다. 전공/진로가 다른 가상 페르소나
6명(백엔드/데이터/UX디자인/화학연구/마케팅/행정공무원)별로 추천 top-k를 뽑고,
LLM-as-judge(`gpt-4o-mini`)가 관련성을 0~2점으로 채점해 Precision@k / nDCG@k를 계산한다.

```
python -m app.ai.evaluation.recommendation_eval --top-k 10 --output raw_data/eval/날짜.json
```

가중치 튜닝 시 이 수치를 전후 비교 기준선으로 쓴다.

**측정 이력 (2026-07-02, 활동 455~458건):**

| 시점 | mean P@10 | mean nDCG@10 |
| --- | --- | --- |
| 최초 기준선 | 0.533 | 0.711 |
| 출처 간 중복 정리 적용 후 | 0.55 | 0.713 |
| 프로필 확장(확장 임베딩만) | 0.55 | 0.705 |
| 프로필 확장(원본+확장 블렌딩) | 0.583 | 0.733 |
| 신청기간 만료 필터 + recency 지수 감쇠(반감기 30일) | 0.567 | 0.693 |

LLM judge 특성상 run 간 ±0.1 정도 변동이 있으므로 소수점 둘째 자리 차이는 과신하지 말 것.
recency 강화는 judge가 "관련성"만 채점하고 "최신성"은 채점하지 않기 때문에 이 지표상으로는
약간 손해로 보일 수 있다 — 최신 공지를 우선하는 건 요구사항이라 의도적으로 받아들인 트레이드오프.

페르소나별 최신 수치 (블렌딩 적용 후):

| 페르소나 | P@10 | nDCG@10 |
| --- | --- | --- |
| backend_dev | 0.9 | 0.886 |
| data_scientist | 0.9 | 0.892 |
| marketer | 0.6 | 0.719 |
| chem_researcher | 0.5 | 0.550 |
| ux_designer | 0.4 | 0.867 |
| public_officer | 0.2 | 0.484 |

평가에서 드러난 개선 포인트:

- ~~출처가 다른 동일 공지가 top-10에 중복 등장~~ → 출처 간 중복 정리로 해결 (위 "중복 정리" 참고)
- ~~임베딩이 진로 분야보다 "취업/모집 형식"에 끌림~~ → 프로필 확장+블렌딩으로 완화 (위 "프로필 확장" 참고)
- public_officer는 여전히 최약 구간 — 코퍼스 자체에 행정 분야 공지가 적은 것이 근본 원인으로 보임. 지금 7개 출처가 전부 학교 본부/취업 계열 게시판이라 개별 단과대·학과(예: 행정학과, 화학과) 게시판이 크롤 대상에 없는 게 원인일 가능성이 큼 → 학과별 게시판 URL 확보되면 [notice-board-sources.py](../../backend/app/ingestion/crawlers/notice_board_sources.py)에 추가 예정. LLM 재랭킹(임베딩 top-30 → judge로 재정렬)도 후보

## 알려진 한계 / TODO

- job 게시판에서 텍스트 제목 없는 이미지 배너 공지는 제외되므로 해당 공고는 노출되지 않음
- 90일 이전 게시물은 페이지네이션 중단 기준일 뿐 강제 삭제하지는 않음 (추천 API 쪽에서 필터링)
- 비IT 진로(특히 행정직) 추천 품질이 낮음 — 임베딩만으로는 한계, 카테고리 필터/가중치 조정 검토 필요
- 프론트엔드 그리드 UI 미연동
- 로그인 붙기 전까지 추천 API는 인증 없이 `user_id`로 직접 조회 가능
