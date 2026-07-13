# 내 정보 페이지 (졸업요건 확인)

사용자의 One-Stop 포털(`onestop.pusan.ac.kr`) 계정으로 로그인해 학적부/성적/졸업요건을
가져와 DB 모델로 매핑한다. "내 정보" 페이지에서 보여줄 학적/성적/졸업요건 데이터의
수집·저장 파이프라인이며, Playwright 기반으로 사용자 본인 계정으로만 동작한다.

## API (`app/api/portal_sync.py`)

| 메서드/경로 | 설명 |
| --- | --- |
| `POST /me/portal-sync` | body로 학번/포털 비밀번호를 받아 서버가 One-Stop에 직접 로그인, 학적부/성적/졸업예정정보를 크롤링해 DB에 저장. 로그인 실패 시 401 |
| `GET /me/graduation` | flat `graduation_requirements` 기준학점과 `student_course_records` 합계를 대조해 졸업까지 남은 학점을 계산. 기본은 주전공만(`include_non_primary=true`로 복수전공/부전공까지 확장). 자세한 내용은 아래 "졸업요건" 절 참고 |
| `PATCH /me/advisor-consulted` | 지도교수 상담 여부를 사용자가 직접 체크/해제 (크롤링 대상 아님, 단순 토글) |

인증은 `get_current_user`(`app/api/auth.py`) 재사용. 크롤링은 Playwright 동기 API로
몇 초 걸리므로 엔드포인트를 `def`(동기)로 선언해 FastAPI가 스레드풀에서 처리하게 한다.

`POST /me/portal-sync`는 성공하면 사용자의 모든 로드맵에도
`sync_completed_courses_to_roadmap()`을 자동 실행한다 — 자세한 내용은
[growth-roadmap.md](./growth-roadmap.md) 참고.

### 실제 계정으로 API 엔드투엔드 검증하며 발견한 버그 3건

스키마를 계속 바꾸면서(학교 계층 도입, user_activities 통합 등) `portal_sync.py`의
응답 모델이 실제 모델 필드와 어긋난 채로 방치돼 있었다. `TestClient`로 함수를
직접 호출하는 테스트만으로는 못 잡고, 실제 `POST /me/portal-sync` 엔드포인트를
호출해봐야 드러나는 문제들이었다.

1. **`.env` 마지막 줄 줄바꿈 누락**: `CREDENTIAL_ENCRYPTION_KEY`를 `echo >>`로
   추가했더니 이전 줄(`JWT_SECRET_KEY=...`) 끝에 그대로 붙어 두 값이 합쳐진 문자열이
   됨 → `EncryptionKeyMissingError`. `.env` 파일을 스크립트로 수정할 때는 항상
   마지막 줄에 개행이 있는지 먼저 확인할 것
2. **`CourseRecordResponse.course_name`**: `StudentCourseRecord`의 실제 컬럼명은
   `raw_course_name`인데 응답 스키마는 `course_name`을 기대해서 `model_validate`가
   실패함 → `Field(validation_alias="raw_course_name")`로 매핑
3. **`AcademicProgramResponse.major`**: 오늘 학교 계층 리팩토링으로
   `UserAcademicProgram.major`(텍스트) → `major_id`(FK)로 바뀐 걸 이 응답 스키마만
   반영 못 하고 있었음 → `major_id`로 `Major`를 조회해서 이름을 채우도록 수정

**교훈**: DB 스키마를 바꿀 때 그 모델을 참조하는 Pydantic 응답 스키마까지 전부
찾아서 고쳐야 하는데, import 에러 없이 그냥 `model_validate` 시점에만 조용히
실패하는 필드 불일치는 실제로 엔드포인트를 호출해보기 전엔 안 잡힌다.

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
- **수강편람 매칭은 하지 않는다**: `StudentCourseRecord.course_id`는 항상 `null`,
  `match_status`는 모델 기본값(`"unmatched"`)으로 고정된다. 원래는 과목명으로
  `courses`와 매칭을 시도했었는데(`_link_course_catalog`), 과거 이수 과목은
  크롤링 시점 기준 예전 교육과정 소속이라 현재 카탈로그(2026 교육과정 기준)에
  아예 이름이 없는 경우가 실제로 있었다(예: 개편/폐지된 "의생명융합입문"). 실제
  계정으로 검증했을 때도 20과목 전부 `unmatched`로 나와서 매칭 자체가 의미
  없다고 판단해 제거했다. 로드맵에 보여주는 `course_name`/`category`/`credits`는
  애초에 이 매칭과 무관한 성적표 원본 스냅샷이라 영향 없다

## 학교/단과대/학과/전공 계층 (`app/domains/academics/hierarchy.py`)

`schools → colleges → departments → majors` 4단 FK 계층. `courses`, `graduation_requirements`,
`users`, `user_academic_programs`가 전부 이 계층을 `department_id`/`major_id`로 참조한다
(자유 텍스트 컬럼 없음). 졸업요건 전용 코드 체계(`academic_programs` 마스터 + 브리지 컬럼)는
없다 — 아래 "졸업요건" 절 참고.

미리 시드하지 않는다 — `resolve_hierarchy()`가 크롤링/회원가입에서 이름이 들어올 때마다
없으면 만들고 있으면 재사용한다(get-or-create). `_split_college_department_major()`가
학적부 "소속학과" 원문(예: `"정보의생명공학대학 의생명융합공학부 데이터사이언스전공"`)을
단과대/학부·학과/전공으로 분리한다 — 마지막 단어가 "전공"으로 끝나면 major, 그 앞 단어가
"대학"으로 끝나면 college로 판단. `"OO과"`처럼 세부 전공이 없는 학과는 major가 null.

## 학교 계층 / 교육과정 시드 데이터

`schools`(1) / `colleges`(16) / `departments`(109) / `majors`(36) / `courses`(6,402 —
전공계열 6,345 + 공통 교양 57)까지 AIS(수강신청 시스템) 2026 교육과정 기준으로
전부 시드되어 있다 (`backend/seeds/school_hierarchy_mapping.csv`,
`ais_courses_2026.csv`, `scripts/seed_school_hierarchy.py`,
`scripts/import_courses_from_ais.py`). 이상 데이터 케이스와 컨벤션(학과 조회 시
`major_id IS NULL` 필수 등)은 [CHANGELOG.md](../CHANGELOG.md)의 최신 DB seed 항목 참고.

## 졸업요건: flat `graduation_requirements`만 남기고 나머지 방향은 전부 철회

지금까지 졸업요건 확인 페이지를 위해 검토했던 방향들:

1. One-Stop 졸업예정정보 페이지의 "교과목구분별 이수구분" 표를 그대로 크롤링해서 저장 —
   실제 계정으로 검증한 결과 이 표의 "기준학점" 값이 실제 학과가 요구하는 기준학점과
   다른 경우가 확인되어 철회
2. 팀원이 별도 브랜치(`feat/graduation-requirement-schema`, PR #59)에서 만든
   `academic_programs`/`academic_program_aliases`(학사 프로그램 코드 마스터) +
   `requirement_sets`/`requirement_categories`/`requirement_courses`/
   `requirement_condition_groups`/`requirement_condition_group_courses`(과목 단위
   상세 규칙) + `graduation_engine.py`(판정 엔진) + `GET /me/graduation` — 팀원과
   상의 후 **전체 철회**하기로 결정. 관련 모델 클래스, 마이그레이션 5개
   (`a1c3e5b7d9f2`~`e5a7c9d1f3b6`), 엔진/API 코드, seed 스크립트 3개, seed CSV 6개를
   전부 삭제했다. 이 마이그레이션들은 애초에 라이브 Supabase에 한 번도 적용된 적이
   없어서(alembic head가 이 5개 리비전 이전인 `f6a7b8c9d0e1`에 머물러 있었음) 되돌릴
   실제 데이터가 없었고, 그래서 파일을 삭제하는 것만으로 로컬 마이그레이션 head가
   라이브 DB의 실제 상태와 다시 정확히 일치하게 됐다(`alembic check` 통과 확인).

**남는 건 flat `graduation_requirements` 하나뿐이다** — `department_id`/`major_id`/
`program_type`/`curriculum_year`별 이수구분 기준학점(전공기초/전공필수/전공선택/
교양필수/교양선택/일반선택/총계) 테이블. 라이브에 2026 주전공 기준 125행 존재.
`app/domains/academics/models.py`의 `GraduationRequirement` 모델로 복구해뒀다.

### 매칭 로직 (`app/domains/academics/graduation_progress.py`)

1. 사용자의 활성 `UserAcademicProgram`(주전공/복수전공/부전공)마다
2. `program_type` + `curriculum_year` + (`major_id` 있으면 그걸로, 없으면
   `department_id`)로 `graduation_requirements`에서 가장 맞는 행 하나를 찾는다
   (정확한 연도가 없으면 같은 학과/전공의 최신 연도 행으로 폴백)
3. `student_course_records`를 `category`(전공기초/전공필수/전공선택/교양필수/
   교양선택/일반선택)별로 학점을 합산
4. 이수구분별로 기준학점 vs 합산학점을 대조해 카테고리별 남은 학점 + 총 남은
   학점을 계산

API는 `app/api/graduation.py`의 `GET /me/graduation`. `docs/CHANGELOG.md`의
관련 항목 참고.

### 실제 계정 E2E 테스트 (2026-07-11)

크롤링 데이터를 지우고 `POST /me/portal-sync`로 재크롤링 → `GET /me/graduation` 순서로
전체 플로우를 검증했다. 매칭 로직 자체는 정상 동작한다.

2023년 입학생(`curriculum_year="2023"`) 계정으로 테스트했는데 `graduation_requirements`에는
2026년 기준만 있어서 정확한 연도 매칭이 안 되고 최신 연도(2026) 폴백으로 대체되는 게 실제로
확인됐다. **일단 2026년 기준 하나만 지원하기로 하고, 다른 연도 seed는 나중으로 미룬다** —
폴백 로직이 이미 이 상황을 처리하고 있어서(경고 메시지로 노출) 추가 코드 변경은 없음.

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

- 부전공/복수전공/교직 세부 요건 seed는 아직 우선순위에서 제외되어 기본 계산에 포함하지 않음
- 효원핵심/효원균형/효원창의처럼 성적표 대분류만으로 분리할 수 없는 세부 교양 영역은 판정 불가로 노출
- `graduation.py`(졸업요건기준 및 충족여부 원본)는 크롤링만 되고 아직 DB 매핑 안 함
- 프론트엔드 미연동 (버튼 눌러서 크롤링/졸업계산을 트리거하는 UI, 프로필 CRUD 폼 UI 없음)
