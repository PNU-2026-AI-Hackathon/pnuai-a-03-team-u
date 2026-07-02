# Changelog

바이브코딩 세션이 끝날 때마다 맨 위에 새 항목을 추가하세요. 형식은 아래 예시 참고.

"기능이 지금 어떻게 동작하는지"는 여기가 아니라 `docs/features/`에 기능별로 정리합니다.
이 파일은 "언제 무엇을 왜 했는지" 시간순 기록입니다.

<!--
## YYYY-MM-DD (github아이디)

- 무엇을 했는지, 왜 했는지, 막혔던 부분/해결법 (필요한 만큼만)
- 관련 기능 문서를 바꿨다면 `docs/features/xxx.md` 갱신도 같이
-->

## 2026-07-02 (d0won) - 6

- 시설 운영/행정성 공지 제외 필터 추가 (`_is_excluded`, `activity_normalizer.py`)
  - 도서관 개관시간 변경, 학자금대출 안내 등 "활동"이 아닌 공지가 섞여있는 걸 발견해 크롤링 단계에서 제외
  - 부수적으로 카테고리 분류 버그도 수정: "대출" 키워드가 너무 넓어서 "학자금대출"까지 "도서관" 카테고리로 잘못 분류되고 있었음 → "도서 대출/반납"으로 한정
  - 기존 DB에서 11건 정리

## 2026-07-02 (d0won) - 5

- 사용자 프로필 확장(query expansion) + 블렌딩 임베딩
  - 프로필 원문만 임베딩하면 유사도가 진로 분야보다 "채용/모집 형식"에 끌리는 문제 대응
  - gpt-4o-mini로 프로필을 분야 키워드 15~20개로 확장 후 임베딩 (프로세스 내 캐시)
  - 확장 임베딩만 쓰면 코퍼스에 해당 분야 공지가 없는 경우(화학) 순위가 노이즈化 → 원본+확장 벡터 평균(블렌딩)으로 해결
  - 평가: mean P@10 0.55 → 0.583, mean nDCG@10 0.713 → 0.733 (IT 계열 P@10 0.9 도달)

## 2026-07-02 (d0won) - 4

- 출처 간(cross-source) 중복 공지 정리
  - pusan_main이 전문 게시판(job, pnucounsel) 공지를 재게시해 추천 top-10에 같은 공지가 두 번 노출되던 문제
  - dedup 그룹핑 키를 (source, title) → title로 확장, 유지 우선순위에 "임베딩 보유" 추가(매일 밤 재임베딩 순환 방지)
  - 평가 수치: mean P@10 0.533 → 0.55, mean nDCG@10 0.711 → 0.713

## 2026-07-02 (d0won) - 3

- 추천 정확도 오프라인 평가 도입 (`app/ai/evaluation/recommendation_eval.py`)
  - 가상 페르소나 6명 × LLM-as-judge(gpt-4o-mini) 채점 → Precision@10 / nDCG@10
  - 기준선: mean P@10 = 0.533, mean nDCG@10 = 0.711 (활동 458건)
  - 발견: 출처 간 동일 공지 중복 노출, 비IT 진로에서 무관한 취업 공지 혼입

## 2026-07-02 (d0won) - 2

- docs 구조 개편: 날짜별 작업 기록 → 단일 `CHANGELOG.md` + `docs/features/` 기능별 문서
  - `docs/features/`를 기술 모듈(크롤러/추천엔진) 대신 제품 기능 4가지로 재편: 비교과 활동 추천, 내 정보 페이지(졸업요건 확인), core(로그인/회원가입, 미구현), 성장 로드맵(미구현)
  - `backend-db-infra-architecture.md` → `docs/architecture.md`로 이름 정리
- 원본에서 내려간 공지 자동 정리 (`remove_stale_activities`)
  - 기존엔 upsert만 해서 원본에서 삭제된 공지가 DB에 계속 남는 문제 발견
  - 전체 삭제 후 재삽입은 매일 전체 재임베딩 비용 + 추천 캐시(FK) 소실 문제로 배제
  - 출처별로 이번 크롤에서 안 보인 URL만 90일 lookback 안에서 부분 삭제하도록 구현

## 2026-07-02 (d0won)

- 비교과 활동 임베딩 + 추천 파이프라인 구현 ([#21](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/21))
  - OpenAI `text-embedding-3-small`로 Activity/사용자 프로필 임베딩
  - 코사인 유사도 × career_goal 가중치(1.2배) × 최신성 가중치(90일 선형 감쇠)로 추천 점수 계산
  - `GET /activities/recommendations/{user_id}` API 추가
  - 자정 크롤 → 임베딩 생성 → 중복 정리 → 추천 재계산까지 스케줄러에 연결
- 크롤러 중복 공지 자동 정리 추가
  - 제목 80% 유사도만으로는 회차별/재모집 공고(예: 다른 은행 채용설명회)까지 지워질 위험 발견
  - 같은 출처 + 제목 완전 일치 + 게시일 3일 이내인 경우만 중복으로 판단하도록 조건 강화
- `UserActivityRecommendation`에 FK(`ondelete=CASCADE`) 추가 — 유저/활동 삭제 시 추천 레코드가 고아로 남는 문제 해결
- job 게시판 빈 제목 공지 크롤링 버그 조사 → 크롤러 버그가 아니라 원본 게시글이 텍스트 없이 이미지 배너만 있는 공지였음, 크롤링 단계에서 제외 처리
- Supabase 팀 공유 DB로 전환, `alembic upgrade head`로 스키마 적용

## 2026-07-01 (d0won)

- 비교과 활동 공지사항 크롤러 구현 ([#19](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/19))
  - 7개 공개 게시판(swedu/uitc/pnucounsel/ctl/pusan_main/lib/job) 4개 엔진 타입으로 크롤링, 90일 lookback 기준 878건 수집 확인
  - `Activity`/`UserActivityRecommendation` 모델, 카테고리·마감일 자동 파싱 normalizer
  - APScheduler로 매일 00:00 KST 자동 크롤
  - `my.pusan.ac.kr` 개인화 페이지는 로그인 필수라 포기하고 로그인 없이 접근 가능한 공개 게시판으로 방향 전환
  - `lib.pusan.ac.kr`은 Angular SPA라 정적 크롤링 불가 → Playwright로 네트워크 캡처해 내부 JSON API(Pyxis) 발견 후 직접 호출

## 2026-06-30 (d0won)

- FastAPI 프로젝트 골격 구축 ([#11](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/11))
- 부산대 One-Stop 포털 크롤러 구현 ([#12](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/12)) — 학적부/성적/졸업요건 추출
- 크롤러 raw 데이터 → DB 모델 매핑 ([#13](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/13))
- 백엔드 폴더 구조를 도메인 기반(`domains`/`ingestion`/`ai`/`api`/`core`)으로 정리 ([#14](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/14))
