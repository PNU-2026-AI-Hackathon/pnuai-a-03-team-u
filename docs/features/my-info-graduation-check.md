# 내 정보 페이지 (졸업요건 확인)

사용자의 One-Stop 포털(`onestop.pusan.ac.kr`) 계정으로 로그인해 학적부/성적/졸업요건을
가져와 DB 모델로 매핑한다. "내 정보" 페이지에서 보여줄 학적/성적/졸업요건 데이터의
수집·저장 파이프라인이며, Playwright 기반으로 사용자 본인 계정으로만 동작한다.

## API (`app/api/portal_sync.py`)

| 메서드/경로 | 설명 |
| --- | --- |
| `POST /me/portal-sync` | body로 학번/포털 비밀번호를 받아 서버가 One-Stop에 직접 로그인, 학적부/성적/졸업예정정보를 크롤링해 DB에 저장. 로그인 실패 시 401 |
| `PATCH /me/advisor-consulted` | 지도교수 상담 여부를 사용자가 직접 체크/해제 (크롤링 대상 아님, 단순 토글) |

인증은 `get_current_user`(`app/api/auth.py`) 재사용. 크롤링은 Playwright 동기 API로
몇 초 걸리므로 엔드포인트를 `def`(동기)로 선언해 FastAPI가 스레드풀에서 처리하게 한다.

## 로그인 (`app/ingestion/crawlers/pnu_session.py`)

- 로그인 레이어의 기본 활성 탭이 "스마트 로그인"이라 `#idpwTab > a`를 먼저 클릭해야
  `#login_id` 입력창이 보임 (애니메이션 대기 필요)
- 비밀번호 변경 주기가 지난 계정은 로그인 직후 `UpdatePassword`로 리다이렉트됨.
  "다음에 변경하기" 링크는 `href="javascript:onclick=changeNextPw();"` 형태라
  클릭이 아니라 `page.evaluate("changeNextPw()")`로 직접 호출해야 넘어감
- `selectMenu('menuCD')`는 AJAX가 아니라 실제 페이지 네비게이션이라
  `page.expect_navigation()`으로 감싸야 함 (안 그러면 "Execution context was destroyed")

## 데이터 추출

- `student_info.py` — 학적부 (학번/이름/소속학과 등)
- `grades.py` — 전체 성적
- `graduation.py` — 졸업요건기준 및 충족여부 원본 (아직 DB 매핑 안 함, raw 확인용)
- `graduation_expected_info.py` — 졸업예정정보 페이지 테이블 7개. 그중 테이블 0
  ("주전공 및 학적신청(부전공,복수전공,연합전공) 정보")만 실제로 매핑한다 —
  나머지 6개는 성적표 카테고리 + 졸업요건표 조합으로 내부 계산 가능해 중복 저장 안 함
- `table_extract.py` — 범용 `<table>` 추출 + `.b-row-item`(`.b-title-box` 라벨 + `.b-con-box` 값) 구조 추출
  - 학적부 기본정보는 `<table>`이 아니라 `.b-row-item` 구조라 `extract_row_items()`를 따로 씀
- `onestop_course_catalog.py` — 수강편람(과목 카탈로그) 크롤러, 로그인 불필요

## DB 매핑 (`app/ingestion/normalizers/pnu_normalizer.py`)

- `save_portal_credential` — 포털 계정 저장. 비밀번호는 평문 저장하지 않고
  `app/core/security.py`의 Fernet 암호화(`encrypt_secret`)로 저장
- `map_student_record` — 학적부 → `User`(이름/학번/department_id/major_id) 갱신 +
  `UserAcademicProgram`(주전공) upsert
- `map_academic_program_registrations` — 졸업예정정보 테이블 0의 학적신청 행 →
  `UserAcademicProgram`(주전공/복수전공/부전공/연합전공)에 upsert. 성적표·졸업요건표
  어디에도 없는 정보라 이 페이지에서만 얻을 수 있음
- `map_grades` — 전체 성적 → `StudentCourseRecord`. 아래 "성적 정규화" 참고

### 성적 정규화 (`map_grades`)

- **이수구분 정규화**(`_normalize_category`): `"전공기초(학부)"` → `"전공기초"`처럼 붙는 괄호
  주석 제거, `"기초교양"` → `"교양선택"` 같은 동의어 치환. 허용 카테고리(`_ALLOWED_CATEGORIES`)는
  전공기초/전공필수/전공선택/일반선택/교양필수/교양선택/교직과목 7개뿐 — 여기 없는 값(소계/요약
  행 등)은 저장하지 않는다
  - **주의**: 과목명이 이수구분명과 같은 행(예: 과목명="교양선택")을 예전엔 소계 행으로 오판해
    걸렀는데, 실제로는 "전적학교성적"(입학 전 인정 학점, 편입생 등)의 정상 데이터였다. 지금은
    과목명만으로는 거르지 않고, `len(row) < _GRADE_DATA_COLUMNS`(8열 미만)로만 실제 소계/요약
    행을 구분한다
- **재수강 가능 판정**(`_is_retake_eligible`): 성적이 C+ 이하(C+, C0, D+, D0, F)면 `is_retake=True`
- **수강편람 매칭**(`_link_course_catalog`): 성적표 원본엔 course_code가 없어 과목명으로만
  `courses`와 매칭. 동일 과목명이 여러 강좌로 존재하면 오매칭 방지를 위해 `course_id`는 비우고
  `match_status="ambiguous"`로만 표시 (matched/ambiguous/unmatched)

## 학교/단과대/학과/전공 계층 (`app/domains/academics/hierarchy.py`)

`schools → colleges → departments → majors` 4단 FK 계층. `courses`, `graduation_requirements`,
`users`, `user_academic_programs`가 전부 이 계층을 `department_id`/`major_id`로 참조한다
(자유 텍스트 컬럼 없음).

미리 시드하지 않는다 — `resolve_hierarchy()`가 크롤링/회원가입에서 이름이 들어올 때마다
없으면 만들고 있으면 재사용한다(get-or-create). `_split_college_department_major()`가
학적부 "소속학과" 원문(예: `"정보의생명공학대학 의생명융합공학부 데이터사이언스전공"`)을
단과대/학부·학과/전공으로 분리한다 — 마지막 단어가 "전공"으로 끝나면 major, 그 앞 단어가
"대학"으로 끝나면 college로 판단. `"OO과"`처럼 세부 전공이 없는 학과는 major가 null.

**`graduation_requirements`도 department_id/major_id로 이 계층을 참조**하지만, 아직
실제 요건 데이터(전공별 필수 학점, 필수과목 목록 등)는 채워지지 않았다 — 정식 학사요람
출처 없이 채우면 졸업 판단을 오도할 위험이 있어 보류 중.

## 학교 계층 / 교육과정 시드 데이터

`schools`(1) / `colleges`(16) / `departments`(109) / `majors`(36) / `courses`(6,402 —
전공계열 6,345 + 공통 교양 57)까지 AIS(수강신청 시스템) 2026 교육과정 기준으로
전부 시드되어 있다 (`backend/seeds/school_hierarchy_mapping.csv`,
`ais_courses_2026.csv`, `scripts/seed_school_hierarchy.py`,
`scripts/import_courses_from_ais.py`). 이상 데이터 케이스와 컨벤션(학과 조회 시
`major_id IS NULL` 필수 등)은 [CHANGELOG.md](../CHANGELOG.md)의 최신 DB seed 항목 참고.

**라이브 flat `graduation_requirements`에는 2026 주전공 졸업학점 기준 125행이 채워져 있다** —
다만 새 `requirement_sets` 스키마의 부전공/복수전공/교직 세부 요건 seed는 아직 완성 전이다.

## 사용자 직접 입력 프로필 (`app/api/profile.py`)

크롤링 대상이 아니라 사용자가 직접 CRUD로 관리하는 데이터. 전부 `get_current_user`로
본인 데이터만 접근 가능(남의 데이터 요청 시 404).

| 메서드/경로 | 설명 |
| --- | --- |
| `GET/POST /me/activities` | 비교과 활동 목록 조회/생성 |
| `PATCH/DELETE /me/activities/{id}` | 비교과 활동 수정/삭제 |
| `GET/POST /me/certifications` | 자격증 목록 조회/생성 |
| `PATCH/DELETE /me/certifications/{id}` | 자격증 수정/삭제 |
| `GET/POST /me/language-scores` | 어학성적 목록 조회/생성 |
| `PATCH/DELETE /me/language-scores/{id}` | 어학성적 수정/삭제 |

`user_activities`는 `user_external_activities`(외부활동)와 `user_competitions`
(공모전/수상)를 합친 테이블이다 — "내 정보" 페이지 UI가 이 둘을 구분 없이 기관명/설명/
링크만 있는 하나의 리스트로 보여줘서 나눌 이유가 없었다. UI에 있던 링크(`url`) 필드도
이때 새로 추가했다.

## 알려진 한계 / TODO

- 실제 충족 여부 판정 로직 미구현 (`graduation_requirements`에 요건 데이터 자체가 없음)
- `graduation.py`(졸업요건기준 및 충족여부 원본)는 크롤링만 되고 아직 DB 매핑 안 함
- 프론트엔드 미연동 (버튼 눌러서 크롤링 트리거하는 UI, 프로필 CRUD 폼 UI 없음)
