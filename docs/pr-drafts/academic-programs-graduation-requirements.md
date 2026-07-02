# PR Draft: 졸업요건용 학사 프로그램 마스터 추가

## 요약

졸업요건/교육과정 데이터를 raw CSV 실험에만 두지 않고, 백엔드 DB에서 직접 관리할 수
있도록 학사 프로그램 마스터 테이블과 seed를 추가했습니다. 또한 현재 확보한 학과별
raw 교과과정 자료를 공통 포맷으로 정규화하고, 수강편람 기반 학과별 과목/교양 영역
테이블을 재생성할 수 있는 스크립트를 함께 추가했습니다.

기존 `departments` 테이블은 회원가입 검증용 이름 목록으로 유지하고, 졸업요건 계산에
필요한 학과코드 기반 마스터는 `academic_programs`로 분리했습니다. 두 기준은
`department_academic_program_mappings`로 연결합니다.

## 배경

PR #32에서 추가된 `departments`는 회원가입 시 사용자가 입력하는 `department`,
`academic_programs[].major` 값이 부산대 정식 학과/전공명인지 검증하는 용도입니다.
하지만 졸업요건을 정확히 저장하려면 이름만으로는 부족합니다.

문제가 되는 경우:

- 1학년 학부제 학생은 `정보컴퓨터공학부`처럼 상위 학부 소속이지만, 실제 과목과
  졸업요건은 `컴퓨터공학전공`, `인공지능전공`처럼 세부 전공으로 갈라질 수 있음
- 수강편람 개설부서명과 학사 프로그램 코드가 1:1로 맞지 않음
- 융합전공, 자율전공, 통합6년제 약학 계열처럼 표시명과 코드 기준명이 다를 수 있음
- 졸업요건은 입학년도, 전형, 프로그램 유형, 학과코드 기준으로 연결되어야 함

그래서 로그인/회원가입 검증용 `departments`와 졸업요건용 `academic_programs`를
분리했습니다.

## 변경 사항

### 1. DB 모델 추가

`backend/app/domains/academics/models.py`

추가 모델:

- `AcademicProgram`
  - 졸업요건 기준 학사 프로그램 마스터
  - PK: `academic_program_code`
  - 2026학년도 활성 학사 프로그램 151개를 seed
- `AcademicProgramAlias`
  - 학사 프로그램 검색/매칭용 별칭
  - 공식명, 표시명, 정규화명, 상위 학부명, 세부 전공명 등을 저장
- `DepartmentAcademicProgramMapping`
  - 회원가입용 `departments`와 졸업요건용 `academic_programs`의 연결
  - relation type으로 `same`, `parent`, `major_track`, `display_name`, `alias` 구분

기존 모델 변경:

- `UserAcademicProgram.academic_program_code` nullable FK 추가
- `RequirementSet.academic_program_code` nullable FK 추가

### 2. Alembic migration 추가

`backend/migrations/versions/7a1d9c2f4b30_add_academic_programs_for_graduation.py`

생성/변경 내용:

- `academic_programs` 테이블 생성
- `academic_program_aliases` 테이블 생성
- `department_academic_program_mappings` 테이블 생성
- `user_academic_programs.academic_program_code` 추가
- `requirement_sets.academic_program_code` 추가
- 각 FK/index/unique constraint 추가

### 3. Seed 파일 추가

`backend/seeds/`

- `academic_programs_2026_active_bachelor.csv`
  - 151 rows
- `academic_program_aliases_2026.csv`
  - 1222 rows

기존 raw 실험 결과를 서비스 seed로 승격했습니다.

원본:

```text
raw_data/parsed_experiments/academic_programs_2026_master/
```

백엔드 seed:

```text
backend/seeds/
```

### 4. Seed 스크립트 추가

`backend/scripts/seed_academic_programs.py`

실행:

```bash
cd backend
python -m scripts.seed_academic_programs
```

동작:

1. `academic_programs` upsert
2. `academic_program_aliases` upsert
3. 기존 `departments`와 alias exact match를 이용해
  `department_academic_program_mappings` upsert

빈 DB 기준 권장 순서:

```bash
cd backend
alembic upgrade head
python -m scripts.seed_departments
python -m scripts.seed_academic_programs
```

### 5. 학과별 졸업요건 raw 정규화 도구 추가

`backend/app/ingestion/normalizers/graduation_requirement_normalizer.py`

학과 홈페이지에서 수집한 HTML 교과과정표를 공통 JSON 구조로 정규화하는 normalizer를
추가했습니다.

지원 내용:

- HTML table의 rowspan/colspan을 grid 형태로 복원
- 문서별 교육과정 연도/신입생·편입생 구분 추정
- 학년/학기별 교과목 row 추출
- `중 1`, `1과목 수강` 같은 선택 규칙을 `choice_rules`로 별도 추출
- 원문 구조가 불완전한 항목은 `needs_review`로 표시

CLI:

```bash
cd backend
python -m scripts.normalize_graduation_requirements \
  ../raw_data/manual_staging/01_graduation_requirements/by_department/간호대학/U06020100004__간호학과/00_sources \
  --output ../raw_data/manual_staging/01_graduation_requirements/by_department/간호대학/U06020100004__간호학과/01_normalized/graduation_requirements.normalized.json
```

### 6. 수강편람 기반 검토 테이블 생성 스크립트 추가

추가 스크립트:

- `backend/scripts/build_department_curriculum_courses.py`
  - 학과별 공식 교과과정표 HTML/TXT에서 과목 row를 추출하고 수강편람 과목코드와 매칭
  - PDF/HWP 등 미지원 원본은 `unsupported_sources.csv`로 분리
- `backend/scripts/build_department_courses_from_catalog.py`
  - 2023~2026 multi-term 수강편람을 기준으로 학과별 provisional course table 생성
  - 공식 졸업요건이 아니라 검토/대조용 reference table
- `backend/scripts/build_general_education_area_tables.py`
  - 교양 선택 영역을 과목 전체 나열이 아니라 영역 규칙으로 분리
  - `general_education_areas`, `department_general_education_area_rules`,
    `department_general_education_area_rule_areas`, `course_general_education_area_map`
    형태로 산출

이 스크립트들은 아직 DB에 직접 insert하지 않고, raw/parsed 실험 산출물을 재현하기 위한
중간 단계입니다. 학과별 교과과정표 원문이 더 확보되면 같은 파이프라인으로 검토 테이블을
늘릴 수 있습니다.

## 1학년 학부제 처리

이번 구조에서는 세부전공 미배정 1학년도 처리할 수 있습니다.

예: 정보컴퓨터공학부 1학년

```text
department = 정보컴퓨터공학부
major = null 또는 미정
academic_program_code = U04080300126
program_type = primary
```

세부전공 확정 후:

```text
department = 정보컴퓨터공학부
major = 컴퓨터공학전공
academic_program_code = U04080100419
program_type = primary
```

즉 회원가입/내 정보에서는 사용자가 느끼는 소속명을 유지하고, 졸업요건 계산에서는
학사 프로그램 코드로 연결할 수 있습니다.

## 왜 `departments`에 코드를 바로 붙이지 않았나

`departments`는 회원가입 검증과 UI 선택지에 가까운 이름 목록입니다. 반면
`academic_programs`는 학사 분류 자료의 코드 체계를 보존해야 합니다.

두 개념을 합치면 다음 문제가 생깁니다.

- 개설부서명, 모집단위명, 졸업요건 기준 학과명이 섞임
- 상위 학부와 세부 전공을 한 행에 표현하기 어려움
- 1학년 학부제 상태와 세부전공 확정 상태를 구분하기 어려움
- 복수전공/부전공/융합전공 연결이 불명확해짐

따라서 역할을 분리하고 mapping 테이블로 연결하는 쪽을 선택했습니다.

## 검증

실행한 검증:

```bash
cd backend
.venv/bin/python -m py_compile \
  app/domains/academics/models.py \
  app/ingestion/normalizers/graduation_requirement_normalizer.py \
  scripts/normalize_graduation_requirements.py \
  scripts/build_department_curriculum_courses.py \
  scripts/build_department_courses_from_catalog.py \
  scripts/build_general_education_area_tables.py \
  scripts/seed_academic_programs.py \
  migrations/versions/7a1d9c2f4b30_add_academic_programs_for_graduation.py
```

```bash
cd backend
.venv/bin/alembic heads
```

결과:

- Python compile 성공
- Alembic head: `7a1d9c2f4b30`
- seed CSV row count 확인
  - `academic_programs_2026_active_bachelor.csv`: 151
  - `academic_program_aliases_2026.csv`: 1222
- `build_general_education_area_tables.py` 재실행 확인
  - area master: 9
  - department area rules: 10
  - rule-area links: 32
  - course-area mappings: 8

## 적용 주의사항

- Supabase 팀 공유 DB는 원본 DB이므로, migration/seed 실행 전 현재 상태를 먼저 확인해야 합니다.
- 이 PR은 실제 졸업요건 내용까지 채우지 않습니다.
- 전공별 필수학점, 필수과목, 교양 영역 규칙은 후속 작업에서 별도 테이블/seed로 추가해야 합니다.
- `department_academic_program_mappings`는 alias exact match 기반 자동 매핑입니다. 복잡한
  상위 학부/세부전공 관계는 추가 검토가 필요합니다.
- raw 정규화 도구는 현재 HTML/TXT 중심입니다. PDF/HWP 원본은 별도 parser 또는 수동 검토가
  필요합니다.

## 후속 작업

- 회원가입/내 정보 API에서 `academic_program_code`를 받을 수 있게 확장
- `RequirementSet`을 `academic_program_code` 기준으로 seed
- 학과별 교과목 테이블을 `academic_program_code` 기준으로 연결
- 교양 영역 규칙 테이블을 `RequirementSet`과 연결
- 상위 학부와 세부전공 관계를 수동 검토 가능한 관리 테이블로 정리
