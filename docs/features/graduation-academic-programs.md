# Graduation Academic Programs

졸업요건 데이터는 회원가입 검증용 `departments`와 분리해서
`academic_programs` 기준으로 관리한다. 이유는 두 테이블의 목적이 다르기 때문이다.

- `departments`: 사용자가 회원가입/내 정보에서 입력하는 학과·학부·전공명이 유효한지
  검증하는 이름 목록
- `academic_programs`: 졸업요건, 교육과정, 학과별 교과목을 학과코드 기준으로 연결하기
  위한 학사 프로그램 마스터

## 왜 분리했나

수강편람의 개설부서명, 회원가입에서 사용자가 선택하는 소속명, 졸업요건 기준 학과코드는
항상 1:1로 맞지 않는다.

예시:

- `정보컴퓨터공학부`는 1학년 학부 소속으로 필요하지만, 수강편람 과목은
  `컴퓨터공학전공`, `인공지능전공`처럼 세부 전공 단위로 개설될 수 있다.
- `약학부`는 회원가입 입력명으로 자연스럽지만, 학사 프로그램 마스터에는
  `약학부(통합6년제)`, `약학전공(통합6년제)`, `제약학전공(통합6년제)`처럼 더 구체적인
  코드 단위가 있다.
- 융합전공/자율전공은 수강편람에는 보이지만 졸업요건 수집 대상과 정확히 일치하지
  않는 경우가 있다.

따라서 로그인 검증용 이름 목록과 졸업요건 계산용 코드 마스터를 하나로 합치면,
1학년 학부제, 세부전공 배정, 복수전공/부전공, 융합전공을 안정적으로 표현하기 어렵다.

## 추가된 테이블

### `academic_programs`

2026학년도 활성 학사 프로그램 151개를 저장한다. 주요 컬럼:

- `academic_program_code`: 학사 프로그램 코드, PK
- `college_name`
- `program_name`
- `display_name`
- `normalized_program_name`
- `parent_department_name`
- `major_name`
- `program_feature_name`
- `duration_name`
- `status_name`
- `education_ministry_5_category`
- `degree_level`
- `first_admission_year`
- `is_active`
- `is_bachelor`

이 테이블이 졸업요건/교육과정/학과별 과목 정리의 기준점이다.

### `academic_program_aliases`

학사 프로그램을 여러 이름으로 찾기 위한 별칭 테이블이다. 공식명, 표시명, 정규화명,
상위 학부명, 세부 전공명 등을 저장한다.

주요 컬럼:

- `academic_program_code`
- `alias_type`
- `alias_name`
- `normalized_alias_name`
- `source`

현재 seed 기준 별칭은 1222개다.

### `department_academic_program_mappings`

회원가입 검증용 `departments`와 졸업요건용 `academic_programs`를 연결한다.

주요 컬럼:

- `department_id`
- `academic_program_code`
- `relation_type`
  - `same`: department 이름과 program 이름이 같음
  - `parent`: department가 상위 학부명
  - `major_track`: department가 세부 전공명
  - `display_name`: 단과대 포함 표시명으로 연결
  - `alias`: 그 외 별칭 매칭
- `source`
- `confidence`

이 테이블 덕분에 사용자가 `정보컴퓨터공학부`로 가입해도, 나중에
`컴퓨터공학전공` 또는 `인공지능전공` 졸업요건과 연결할 수 있다.

## 기존 테이블 변경

### `UserAcademicProgram.academic_program_code`

사용자의 학적 프로그램이 코드 기준으로 확정된 경우 연결한다.

1학년 학부제처럼 세부전공이 아직 정해지지 않은 경우에는 다음처럼 저장할 수 있다.

```text
department = 정보컴퓨터공학부
major = null 또는 미정
academic_program_code = U04080300126
program_type = primary
```

세부전공이 정해진 뒤에는 다음처럼 더 구체적인 코드로 연결할 수 있다.

```text
department = 정보컴퓨터공학부
major = 컴퓨터공학전공
academic_program_code = U04080100419
program_type = primary
```

### `RequirementSet.academic_program_code`

졸업요건 세트가 어느 학사 프로그램 기준인지 명시한다.

기존 `department_id`는 회원가입 검증용 `departments`와의 연결이고,
`academic_program_code`는 실제 졸업요건/교육과정 기준 코드다. 둘 다 nullable로 두어
기존 데이터와 점진적으로 연결할 수 있게 했다.

## Seed

추가된 seed 파일:

- `backend/seeds/academic_programs_2026_active_bachelor.csv`
- `backend/seeds/academic_program_aliases_2026.csv`

실행:

```bash
cd backend
python -m scripts.seed_academic_programs
```

이 스크립트는 다음을 upsert한다.

1. `academic_programs` 151개
2. `academic_program_aliases` 1222개
3. 현재 DB의 `departments`와 별칭이 일치하는 `department_academic_program_mappings`

`department_academic_program_mappings`는 `departments`가 먼저 seed되어 있어야 생성된다.
따라서 빈 DB에서는 다음 순서로 실행한다.

```bash
cd backend
alembic upgrade head
python -m scripts.seed_departments
python -m scripts.seed_academic_programs
```

Supabase 팀 공유 DB는 원본 DB이므로, 적용 전에는 현재 migration 상태와 seed 적용 여부를
먼저 확인해야 한다.

## 데이터 출처

초기 seed는 기존 raw 실험 결과를 백엔드 seed로 승격한 것이다.

- 원본: `raw_data/parsed_experiments/academic_programs_2026_master/`
- 백엔드 seed: `backend/seeds/`

raw 실험 파일에만 의존하지 않도록, 실제 서비스가 사용하는 seed 파일은 `backend/seeds`
아래에 둔다.

## 아직 하지 않은 것

- 실제 졸업요건 규칙 내용은 채우지 않았다.
- 전공별 필수학점, 필수과목, 교양 영역 규칙은 별도 테이블/seed로 이어서 넣어야 한다.
- `department_academic_program_mappings`는 별칭 exact match 기반이다. 상위 학부와 세부전공
  관계가 복잡한 경우 수동 검토 또는 추가 규칙이 필요하다.
- 회원가입 API가 아직 `academic_program_code`를 직접 받지는 않는다. 현재는 이름 검증을
  `departments` 기준으로 하고, 코드 연결은 후속 작업에서 붙인다.

