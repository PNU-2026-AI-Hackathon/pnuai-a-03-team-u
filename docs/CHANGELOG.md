# Changelog

바이브코딩 세션이 끝날 때마다 맨 위에 새 항목을 추가하세요. 형식은 아래 예시 참고.

"기능이 지금 어떻게 동작하는지"는 여기가 아니라 `docs/features/`에 기능별로 정리합니다.
이 파일은 "언제 무엇을 왜 했는지" 시간순 기록입니다.

<!--
## YYYY-MM-DD (github아이디)

- 무엇을 했는지, 왜 했는지, 막혔던 부분/해결법 (필요한 만큼만)
- 관련 기능 문서를 바꿨다면 `docs/features/xxx.md` 갱신도 같이
-->

## 2026-07-09 (blackest21) - 3

- **DB seed 진행 기록을 `docs/CHANGELOG.md`로 통합**
  - 별도 `docs/progress.md` 파일과 `docs/progress/*` 폴더를 쓰지 않고, GitHub에서 바로 보이는
    이 changelog를 DB seed/졸업요건 진행상황의 단일 기록지로 사용한다.
  - 원칙: 2026 현행 학부/전공 계층은 AIS 2026 기준, `departments`는 학과/학부 단위,
    `majors`는 학부 아래 세부전공 단위, 전공을 가진 부모 학과 조회 시 `major_id IS NULL`
    조건 필수. 폐과/비학부/전문대학원 행은 별표에 졸업학점 기준이 있어도 2026 학부
    계층에 임의 추가하지 않는다.
  - 2026 계층/과목 seed 완료 상태: Supabase 기준 `schools` 1 / `colleges` 16 /
    `departments` 109 / `majors` 36 / `courses` 6,402. 재현 명령은 `cd backend` 후
    `python -m scripts.seed_school_hierarchy`, `python -m scripts.import_courses_from_ais`.
  - 주요 배치 결정: 핀테크융합전공은 경영대학 직속, 지능형헬스사이언스융합전공은
    자연과학대학 직속, EES융합전공은 학부대학 첨단융합학부 전공. 첨단융합학부 현행
    전공은 `미래에너지전공`, `나노소자첨단제조전공`, `광메카트로닉스공학전공`,
    `AI융합계산과학전공`, `EES융합전공`.
  - 별표의 `나노에너지공학과`, `나노메카트로닉스공학과`, `광메카트로닉스공학과`는
    2026 학과분류자료집에서 폐과로 확인되어 라이브 계층에 새 department로 추가하지 않았다.
  - 라이브 Supabase revision `e5f6a7b8c9d0` 기준 flat `graduation_requirements`에
    2026 주전공 졸업학점 기준 125행을 반영했다. 범위는 별표2 page 31-36 중 라이브
    계층 매칭 123행 + 별표2-2 page 38 융합전공 중 매칭 2행
    (`지능형헬스사이언스융합전공`, `핀테크융합전공`).
  - flat 컬럼 매핑: 총계 → `required_total_credits`, 전공필수 → `required_major_required`,
    전공선택+심화전공 → `required_major_elective`, 효원핵심교양 →
    `required_general_required`, 효원균형교양+효원창의교양 →
    `required_general_elective`, 일반선택 → `required_free_elective`.
  - 라이브 계층에 매칭하지 않은 별표 행: 폐과 학부 행
    (`나노에너지공학과`, `나노메카트로닉스공학과`, `광메카트로닉스공학과`,
    `식물생명과학과`, `동물생명자원과학과`), 전문대학원 학석사통합과정 학사과정
    (`치의학전문대학원`, `한의학전문대학원`), 라이브 계층 미존재 `미래자동차융합전공`,
    라이브 `majors` 미존재 `의생명융합공학부 첨단바이오공학전공`.
  - 재실행 명령: `cd backend` 후 page 31-36은
    `python -m scripts.seed_live_flat_graduation_requirements --replace --apply`, page 38
    융합전공은 `python -m scripts.seed_live_flat_graduation_requirements --only-annex2-2 --apply`.
    스크립트는 같은 `(program_type, curriculum_year, department_id, major_id)` 행을 먼저
    지우고 다시 넣어 중복을 만들지 않는다.
  - 새 `requirement_sets` 스키마는 flat `graduation_requirements`를 장기적으로 대체하기 위한
    작업이고 아직 라이브 DB에는 적용하지 않았다. 부전공/복수전공은
    `requirement_sets.program_type`, 교직은 primary 요건세트의
    `teacher_training_basic` / `teacher_training_pedagogy` 카테고리로 표현한다.
  - 남은 일: `의생명융합공학부 첨단바이오공학전공`을 2026 현행 계층에 포함할지 확인,
    live flat 테이블과 새 `requirement_sets` 스키마 중 PR 범위 확정, 부전공/복수전공/교직
    세부 요건 seed 완성, 새 스키마 적용 전 현재 flat 125행을 `requirement_categories`로
    이전하는 경로 마련.

## 2026-07-09 (blackest21) - 2

- **primary(주전공) 졸업요건 시드 준비 완료** (같은 브랜치, 로컬 검증까지 — Supabase 반영은 승인 대기)
  - `scripts/seed_academic_programs.py`: 프로그램 마스터 151 + 별칭 335 upsert + **계층 브리지 backfill**
    (departments 107/majors 36, school_hierarchy_mapping.csv 기반). 코드 하나가 계층 여러 행에
    걸치는 케이스 처리: 기계공학부(학부공통+세부전공 5행)는 학과 레벨 우선, 조선·해양공학과
    (`U...075;U...133` 세미콜론 이중코드)는 일반과정 코드 우선
  - `scripts/seed_graduation_requirements.py`: raw_data 후보 CSV + corrections(17,555건 검토 반영)
    → **primary 요건세트 148 / 카테고리 73 / 과목 11,321** 적재. `--program-types` 기본 primary —
    부전공/복수전공은 나중에 같은 스크립트로 확장, 교직 행은 어휘 재정리 전까지 제외.
    prune는 이번 실행 범위 세트로 한정(나중에 적재된 타 유형 행 보호)
  - 시드 CSV 4개(backend/seeds/)를 codex 브랜치에서 이관 (corrections 9.2MB 포함)
  - 로컬 검증: 두 시드 멱등(재실행 행 수 불변) / department_id 미해석은 의도된 제외 7건뿐
    (교양학부 5계열·기타모집단위·GSP) / 시드 실데이터로 엔진 스모크(핀테크융합전공 —
    학점 미달 False, 교양 영역 판정불가 None, 필수과목 10건 미이수 체크) / 골든테스트 통과
  - 반영 순서와 라이브 적용 현황은 이 changelog의 최신 DB seed 항목 참고

## 2026-07-09 (blackest21)

- **졸업요건 스키마 재설계: 부전공/복수전공/교직 표현 + codex 브랜치 main 통합**
  (브랜치 `feat/graduation-requirement-schema`, 스키마+마이그레이션까지 — 엔진 확장/시드는 다음 세션)
  - codex/graduation-academic-programs 브랜치(+stash 세션#15 정리분, 워크트리 `../planU-codex`에
    커밋 `6465c12`로 보존)의 판정 엔진·requirement_* 스키마·골든테스트를 main 계층 위로 포팅
  - 핵심 설계: ① 부전공/복수전공 = requirement_sets의 program_type 행(별도 테이블 아님),
    ② 교직 = primary 세트의 teacher_training_basic(△)/teacher_training_pedagogy(□, 8학점)
    카테고리(별도 program_type 아님), ③ 대학 공통 기본규칙 = scope='university_default' 행,
    ④ 부전공/복수전공 불가 학과 = offering_status='not_offered' 행,
    ⑤ 택N/M = requirement_condition_groups(+_courses) 2테이블 신규,
    ⑥ 계층↔요건 브리지 = departments/majors/user_academic_programs.academic_program_code,
    ⑦ flat graduation_requirements DROP
  - **`f1a2b3c4d5e6`(reset) 동결 수리**: 라이브 모델 import+create_all 구조를 도입 당시 DDL
    하드코딩으로 교체 — 빈 DB에서 `alembic upgrade head` 전체 체인 재생이 처음으로 성공
    (신규 팀원 로컬 셋업/CI 셋업 가능해짐. 기존 Supabase에는 무영향)
  - 신규 리비전 5개(`a1c3e5b7d9f2`→`e5a7c9d1f3b6`), 전부 plain DDL + downgrade 포함
  - 검증(로컬 Postgres, Supabase 미접촉): 빈 DB 전체 체인 upgrade ✓ / downgrade 왕복 ✓ /
    `alembic check` drift 0 ✓ / 골든테스트 TC01~TC10 전부 통과 ✓
  - 문서: 이 changelog의 최신 DB seed 항목(설계 근거·다음 TODO),
    `docs/features/db-schema-reference.md`(스키마 레퍼런스 갱신)

## 2026-07-08 (d0won) - 3

- 로드맵 항목(`course_roadmap_items`) 스냅샷 필드 축소: `department_name`/`major_name`/`category`/`credits` 컬럼 제거, `course_id` 있을 때 응답 시점에 `courses`(+`departments`+`majors`) join으로 채우는 방식으로 변경
  - 실제 계정 데이터로 확인해보니 동명 과목(예: "데이터베이스"가 5개 학과에 개설)이 흔해서, 이름만으로 매칭하면 `course_id`가 자주 비거나 모호(ambiguous)함 — 이 경우 스냅샷이었으면 애초에 못 채웠을 필드들이라 join 방식이 더 안전
  - `course_name`만 예외로 스냅샷 유지 (course_id 없어도 항상 표시해야 하는 값)
  - `app/domains/planning/history.py`도 같이 단순화

## 2026-07-08 (d0won) - 2

- 성장 로드맵 작성/수정 API 추가 (`app/api/roadmaps.py`, `app/api/courses.py`)
  - "AI 자동 생성 버튼" 없이 로드맵은 항상 존재(없으면 자동 생성)하게 만들어서, 프론트는 "수정하기" 버튼 하나로만 진입 (`GET /me/roadmaps/current`)
  - `app/domains/planning/history.py`: 이미 크롤링된 이수내역(`StudentCourseRecord`)을 로드맵 항목으로 자동 변환 — 2학년 이상 학생이 처음 로드맵을 만들어도 1학년 때 들은 과목이 빈칸으로 안 보이게. 교육과정적용년도 기준으로 정규 학기만 학년(1~4) 계산, 멱등적 upsert
  - `GET /courses/search`: 과목 자동완성, 사용자 본인 학과/전공 과목 우선 정렬
  - 로드맵 항목은 반드시 실제 존재하는 `course_id`로만 생성/수정 가능 — 자유 텍스트 과목명 입력 경로 자체가 없어서 오타로 저장하는 게 구조적으로 불가능
  - `course_roadmap_items`에 `course_name`/`department_name`/`major_name`/`category`/`credits`(스냅샷), `status`, `is_confirmed` 필드, `course_roadmaps`에 `summary` 필드 추가
  - `course_plans`/`course_plan_items`(시간표 추천)는 나중에 별도 구현 예정이라 이번엔 건드리지 않음
  - TestClient로 전체 흐름(자동완성 → 로드맵 자동생성+이수내역 반영 → 항목 추가/수정 → 권한 체크 → 오타 방지) 검증 완료
## 2026-07-08 (d0won)

- 비교과 활동/자격증/어학성적 CRUD API 추가 (`app/api/profile.py`)
  - `GET/POST /me/activities`, `/me/certifications`, `/me/language-scores` + 각 `PATCH/DELETE /{id}`
  - 크롤링 대상(성적/전공)과 달리 사용자가 직접 입력/편집하는 데이터라 별도 라우터로 분리
  - `get_current_user`로 본인 데이터만 접근, 남의 데이터 요청 시 404
- DB 정리: `user_external_activities` + `user_competitions` → `user_activities`(비교과 활동)로 통합
  - "내 정보" 페이지 UI가 외부활동/공모전을 구분 없이 기관명/설명/링크만 있는 하나의 리스트로 보여줘서 나눌 이유가 없었음
  - UI에 있던 링크(`url`) 필드 신규 추가, 기존 데이터는 마이그레이션에서 이관
- TestClient로 로그인 → 생성 → 조회 → 수정 → 삭제 전체 흐름 + 인증 없음(401)/존재하지 않는 리소스(404) 케이스 검증 완료

## 2026-07-08 (blackest21)

- **Supabase에 학교 계층 + 2026 교육과정 적재 완료**: schools 1 / colleges 16 / departments 109 /
  majors 36 / courses 6,402 (전공계열 6,345 + 공통 교양 57). 소스는 전부 AIS(수강신청 시스템)
  현행 편제 — 표기·배치를 AIS 기준으로 통일했고, 팀 확인으로 특수 케이스(자율전공형·핀테크·
  지능형헬스·EES·스마트시티·약학부 385세대·치의학과 추가·한의학과 제외)를 확정.
- 시드 파일 2개(`backend/seeds/school_hierarchy_mapping.csv`, `ais_courses_2026.csv`)와
  멱등 적재 스크립트 2개(`scripts/seed_school_hierarchy.py`, `scripts/import_courses_from_ais.py`) 추가.
- 이상 데이터·전원 숙지 컨벤션(학과 조회 시 `major_id IS NULL` 필수 등)·추후 검토 목록은
  이 changelog의 최신 DB seed 항목에 통합 — **꼭 한번 읽어주세요.**
- 주의: 원본 데이터 특이사항 다수 발견 — 행정학과 PA2700143은 AIS부터 과목명 공란,
  조선·해양공학과는 AIS 동명 코드 2개(342100이 진짜), 국악학과/음악학과 동명 전공 함정 등.
  상세는 이 changelog의 최신 DB seed 항목.

## 2026-07-07 (d0won)

- `schools → colleges → departments → majors` 4단 FK 계층 신설 (`app/domains/academics/models.py`, `hierarchy.py`)
  - `courses`/`graduation_requirements`/`users`/`user_academic_programs`에 자유 텍스트로 흩어져 있던 school/college/department/major 컬럼을 `department_id`/`major_id` FK로 교체
  - `departments` 시드 데이터(수강편람 크롤링 기반)는 폐기 — 대신 `hierarchy.py`의 get-or-create 헬퍼가 크롤링/회원가입 시점에 이름이 들어올 때마다 없으면 자동 생성. 회원가입 학과 검증(`_validate_department_names`)도 같이 제거됨
  - 이유: 팀 공유 DB(Supabase)가 여러 브랜치 마이그레이션이 뒤섞여 어지러운 상태였음 — 전체 스키마를 합의된 ERD로 리셋하면서 같이 정리
- 포털 자동 로그인/동기화 API 추가 (`POST /me/portal-sync`, `PATCH /me/advisor-consulted`, `app/api/portal_sync.py`)
  - 학번/비밀번호를 받아 서버가 직접 One-Stop에 로그인, 학적부/성적/졸업예정정보를 크롤링해 DB에 매핑
  - 졸업예정정보 테이블 0(학적신청 정보)에서 복수전공/부전공 신청 여부까지 자동으로 `UserAcademicProgram`에 반영
- 성적 크롤링 정규화/버그 수정 (`pnu_normalizer.py`)
  - 이수구분 정규화: `"전공기초(학부)"` → `"전공기초"`, `"기초교양"` → `"교양선택"`(동의어), `"교직이수"` → `"교직과목"`(실제 표기 오타 수정)
  - 재수강 가능(C+ 이하) 여부 자동 판정해 `is_retake`에 반영
  - 수강편람(`courses`)과 과목명 매칭해 `course_id`/`match_status` 채움 (동명 과목 여러 개면 `ambiguous`로 남기고 오매칭 방지)
  - **버그**: "전적학교성적"(입학 전 인정 학점) 행이 과목명과 이수구분명이 같다는 이유로 소계 행으로 오판되어 걸러지던 문제 발견·수정 (실 계정 테스트 시 10건 → 정확한 14건 저장으로 확인)
- 추천활동(비교과 크롤링+임베딩+추천) 기능 제거 — 나중에 재설계해서 다시 구현할 예정
  - `activities`/`user_activity_recommendations`/`extracurricular_programs` 테이블, `app/api/activities.py`,
    `app/ai/recommendations/extracurricular_recommender.py`, `app/ai/embeddings/activity_embeddings.py`,
    `app/ai/evaluation/recommendation_eval.py`, `app/ingestion/normalizers/{activity_normalizer,dedup_activities}.py` 삭제
  - `notice_board_crawler.py`/`notice_board_sources.py`(순수 크롤링 코드), `openai_client.py`(범용 임베딩 유틸)는 재구현 시 재사용 위해 남겨둠
  - `app/core/scheduler.py`는 빈 스케줄러로 정리 (잡 없음)
- ERD 합의 후 `courses`/`graduation_requirements`/`user_academic_programs` 등 도메인 모델 전면 재구성, `planning`(수강계획/로드맵)·`content`(학사정보 안내글) 도메인 신설 ([#44](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/44), [#45](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/45))
- 실 계정으로 전체 흐름(로그인 → 크롤링 → 계층 자동생성 → 저장) 검증 완료: 부산대학교 → 정보의생명공학대학 → 의생명융합공학부 → 데이터사이언스전공까지 정확히 연결됨

## 2026-07-02 (d0won) - 12

- 프론트엔드 연동 가이드 문서 추가 (`docs/frontend-api-guide.md`) — 지금 동작하는 API(회원가입/로그인/내정보/추천)만 요청·응답·에러 예시로 정리. 팀 검토 전이라 PR 머지는 보류 중
- 문서 작성 중 버그 발견 및 수정: `GET /activities/recommendations/{user_id}`에 존재하지 않는 user_id를 넣으면 404가 아니라 처리 안 된 500이 나던 문제 — 유저 존재 여부를 먼저 확인하도록 수정

## 2026-07-02 (d0won) - 11

- `Course.department_id`/`RequirementSet.department_id`를 `departments` 테이블 FK로 추가
  - 자유 텍스트 department 컬럼은 표시용으로 유지, 검증/조인은 FK 기준
  - 부전공/복수전공 요건은 별도 테이블 없이 `RequirementSet.program_type`("minor"/"dual")으로 표현
  - FK 연결만 하고 실제 졸업요건/과목 데이터는 채우지 않음 — 정식 학사요람 출처 없이 요건 내용(학점/필수과목)을 채우면 졸업 판단을 오도할 위험이 있어 보류

## 2026-07-02 (d0won) - 10

- 회원가입 시 학과/전공 정식 명칭 검증 (`departments` 테이블)
  - `department`, `academic_programs[].major`가 DB에 없는 값이면 400으로 회원가입 거부
  - `departments` 시드 데이터(163개)는 onestop 수강편람 크롤러로 2026-1학기 개설 과목의 개설 학과명을 모아 연구소/센터 등 비학사 조직 제외해 생성 (`backend/seeds/pnu_departments.json`, `scripts/seed_departments.py`)
  - 알려진 한계: 수강편람은 과목 개설 단위(대개 세부 전공)만 노출해서 상위 학부명(정보컴퓨터공학부, 전기전자공학부 등)이 누락되는 경우가 있었음 — 발견된 것만 수동 보강, 전체 16개 단과대학 전수 대조는 안 함

## 2026-07-02 (d0won) - 9

- 회원가입에 복수전공/부전공 입력 추가 (`SignupRequest.academic_programs`)
  - User 테이블에 컬럼 추가 대신 기존 `UserAcademicProgram` 테이블(One-Stop 크롤러용으로 이미 있던)을 재사용, 유저당 여러 행으로 저장
  - program_type은 primary/dual/minor/interdisciplinary만 허용
  - 추천 로직이 이미 유저의 모든 전공을 프로필에 반영하고 있어서 별도 연동 없이 바로 추천에 반영됨
  - `GET /auth/me` 응답에 academic_programs 목록 포함

## 2026-07-02 (d0won) - 8

- 이메일/비밀번호 로그인·회원가입 구현 (`app/api/auth.py`)
  - `POST /auth/signup`, `POST /auth/login`, `GET /auth/me`, 재사용 가능한 `get_current_user` 의존성
  - JWT(`python-jose`) 발급/검증, 만료 7일
  - 비밀번호 해싱은 `passlib[bcrypt]` 대신 `bcrypt` 직접 사용 — passlib이 최신 bcrypt(4.1+)와 호환이 깨져있어서 교체 (`requirements.txt` 반영)
  - `User` 모델에 이미 email/password_hash가 있어서 마이그레이션 불필요
  - 다른 기능 API(추천 등)는 아직 `user_id` 파라미터 방식 그대로, `get_current_user` 전환은 별도 작업

## 2026-07-02 (d0won) - 7

- 추천 기준 재조정: 신청기간 만료 필터 강화 + 최신성 가중치 강화
  - 마감일이 파싱된 공지는 11%뿐이라 나머지 89%는 마감이 지나도 계속 추천되던 문제 발견
  - 마감일 없는 공지는 게시일 45일 경과 시 만료로 간주해 제외 (현재 DB 154건 해당)
  - recency_weight를 선형 감쇠(90일 0.5)에서 지수 감쇠(반감기 30일, 최소 0.1)로 변경 — 최신 공지가 순위에 더 확실히 반영되도록
  - 평가 수치는 소폭 하락(P@10 0.583→0.567)했으나, judge가 관련성만 보고 최신성은 안 보기 때문 — 최신성 강화는 의도한 요구사항이라 트레이드오프로 받아들임

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
