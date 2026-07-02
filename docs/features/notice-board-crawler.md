# 비교과 활동 공지사항 크롤러

로그인 없이 접근 가능한 부산대 공개 게시판 7곳을 크롤링해 `Activity` 테이블에 저장한다.
`my.pusan.ac.kr`의 개인화 비교과 페이지는 로그인이 필수라 사용하지 않는다.

## 출처 및 엔진

`app/ingestion/crawlers/notice_board_sources.py`에 소스를 등록하고,
`app/ingestion/crawlers/notice_board_crawler.py`가 4개 엔진 타입으로 파싱한다.

| 엔진 | 소스 | 방식 |
| --- | --- | --- |
| artclView | swedu, uitc, pnucounsel, ctl | `artclList.do`에 POST, `table.board-table` 파싱 |
| CMS Board | pusan_main | `CMS/Board.do`에 GET, `table.board-list-table` 파싱 |
| Pyxis JSON API | lib | Angular SPA라 정적 HTML 없음 → `/pyxis-api/1/bulletin-boards/2/bulletins` 내부 API 직접 호출 |
| Job board | job | `/ko/notice/notice/list/{page}` GET, `li.tbody` 파싱 |

## 수집 규칙

- 최근 90일(`DEFAULT_LOOKBACK_DAYS`) 게시물만 수집. 페이지네이션 중 비고정 게시물이 전부 90일 이전이면 그 출처는 중단
- 고정(pinned) 게시물은 1페이지에서만 수집 (중복 방지)
- 제목이 빈 문자열인 게시물은 제외 (예: job 게시판의 이미지 배너 전용 공지 — 텍스트 제목 자체가 없어 추천에 쓸 수 없음)
- `source + source_url` unique constraint로 같은 글 중복 저장 방지 (upsert)

## 중복 정리 (`app/ingestion/normalizers/dedup_activities.py`)

크롤러가 재게시/페이지네이션 경계 문제로 같은 공지를 다른 URL로 두 번 수집하는 경우를 정리한다.

- 조건: **같은 출처 + 제목 완전 일치 + 게시일 3일 이내**인 경우만 중복으로 판단, 조회수가 더 높은(또는 더 최신인) 쪽만 남김
- 제목 유사도(예: 80% 이상)만으로 판단하지 않는 이유: 회차별/재모집 공고(예: "하나은행" vs "한국은행" 채용설명회, "5월" vs "6월" 도서관 프로그램)는 제목이 비슷해도 실제로 다른 공지이기 때문
- 자정 크롤 직후 자동 실행

## 카테고리/마감일 자동 추론 (`app/ingestion/normalizers/activity_normalizer.py`)

- 제목 키워드로 카테고리 1차 분류: 공모전/인턴십/취업/장학금/스터디/교내활동/강연특강/교육프로그램/도서관/상담
- 제목에서 마감일 패턴 파싱: `~7/6`, `(7/10)`, `7/15마감`, `6월 30일까지` 등
- embedding 컬럼은 건드리지 않음 (별도 배치가 담당, [activity-recommendations.md](./activity-recommendations.md) 참고)

## 스케줄링

`app/core/scheduler.py`의 APScheduler가 매일 00:00 KST(`Asia/Seoul`)에 다음을 순서대로 실행한다.

1. 7개 출처 크롤 → JSON 백업(`raw_data/crawled_data/notice_boards/{date}.json`) → `Activity` upsert
2. 중복 정리
3. embedding 생성 (신규/미처리 Activity만)
4. 전체 사용자 추천 재계산

## 알려진 한계

- job 게시판에서 텍스트 제목 없는 이미지 배너 공지는 제외되므로 해당 공고는 노출되지 않음
- 90일 이전 게시물은 페이지네이션 중단 기준일 뿐 강제 삭제하지는 않음 (추천 API 쪽에서 필터링)
