# Graduation Requirements Supabase Seeding Progress

작성일: 2026-07-02

## 목적

학과별 홈페이지, 수강편람, 부산대학교 교육과정 편성 및 운영규정 PDF에서 정리한 졸업요건 후보 데이터를 Supabase DB에 넣어, 이후 졸업요건 검증/마이페이지/추천 로직에서 `academic_program_code` 기준으로 조회할 수 있게 한다.

이번 작업은 자동 파싱 결과를 곧바로 확정 졸업판정 규칙으로 사용하는 것이 아니다. 원문 형식이 학과마다 다르고 일부 행은 선택 규칙/중복 후보/부정확한 과목 매칭이 있을 수 있으므로, DB에는 `needs_review`와 원문 출처를 함께 저장했다.

## 적용한 DB 구조

기존 테이블:

- `departments`: 회원가입 입력값 검증용 학과/학부/전공명 목록
- `academic_programs`: 졸업요건 기준 학사 프로그램 마스터
- `requirement_sets`: 학과/전공/교육과정연도/program_type별 졸업요건 세트

새로 추가한 테이블:

- `requirement_categories`: 교양필수, 효원균형, 전공기초, 전공필수, 전공선택, 심화전공, 일반선택, 부전공/복수전공 총학점 등 카테고리별 요건 후보
- `requirement_courses`: 학과별 교육과정 원문 및 수강편람에서 뽑은 과목 후보
- `requirement_text_rules`: 과목 행으로 바로 정규화하기 어려운 문장형 졸업요건 후보

## 추가한 코드

- `backend/migrations/versions/2d8a6f1c9b40_add_graduation_requirement_detail_tables.py`
- `backend/migrations/versions/8f4c1d7b2a90_widen_requirement_course_code_fields.py`
- `backend/app/domains/academics/models.py`
- `backend/scripts/build_graduation_requirement_seed_tables.py`
- `backend/scripts/seed_graduation_requirements.py`
- `backend/scripts/seed_academic_programs.py`

`seed_academic_programs.py`는 alias seed 중복 제거와 active bachelor 프로그램 외 alias 제외 로직을 보강했다.

## Supabase 적용 결과

적용 대상:

- Project: `yuvumqzlglwhlpnecgqa`
- 연결 방식: Supabase Transaction pooler
- 적용 일시: 2026-07-02

실행 순서:

1. `alembic upgrade head`
2. `python -m scripts.seed_departments`
3. `python -m scripts.seed_academic_programs`
4. `python -m scripts.seed_graduation_requirements`

Supabase 검증 쿼리 결과:

| table | rows |
| --- | ---: |
| `departments` | 163 |
| `academic_programs` | 151 |
| `academic_program_aliases` | 335 |
| `department_academic_program_mappings` | 119 |
| `requirement_sets` | 153 |
| `requirement_categories` | 493 |
| `requirement_courses` | 9,082 |
| `requirement_text_rules` | 706 |

추가 검증:

- `requirement_sets` 중 `rule_metadata.coverage_status = source_still_unresolved`: 2개
- `requirement_courses.needs_review = false`: 4,631개
- `requirement_courses.needs_review = true`: 4,451개

## 현재 남은 원문 확인 대상

1. `T00000012631` 스마트가전공학과
   - 2026 학과분류자료집 기준 학사/공과대학/계약학과/신설/4년제 항목
   - 대학원 `스마트가전공조시스템학과`와 합치지 않는다
   - 신설 계약학과 안내 또는 2026 이후 계약학과 교육과정 원문이 필요하다
2. `U02030800044` Global Studies Program
   - `글로벌자유전공학부`가 아니라 경제통상대학 국제학부의 영문 트랙/프로그램 후보
   - 국제학부 전체 졸업이수학점은 운영규정 PDF에서 확인됨
   - GSP 단독 교육과정/복수전공 요건은 국제학부 원문 또는 수강편람 세부 문서에서 추가 확인해야 한다

## 데이터 해석 규칙

`requirement_sets.program_type`:

- `primary`: 일반 주전공/학사 프로그램
- `contract`: 계약학과
- `minor`: 부전공 요건
- `dual`: 복수전공 요건

`requirement_courses.match_status`:

- `matched`: 수강편람 과목번호와 매칭됨
- `ambiguous`: 과목명은 같지만 여러 과목번호 후보가 있음
- `unmatched`: 수강편람에서 과목번호를 찾지 못함

`needs_review`:

- `false`: 자동 매칭 결과를 우선 검토 대상으로 사용할 수 있음
- `true`: 원문 검토 전에는 확정 졸업판정에 사용하지 않는다

## 해야 할 일

1. `requirement_courses.needs_review = true`인 4,451개를 우선순위별로 줄인다.
2. `match_status = ambiguous`인 과목은 학과/개설학기/과목코드 후보를 보고 하나로 좁힌다.
3. `choice_rule_types`가 있는 행은 선택 그룹 단위로 묶는다.
4. `requirement_categories`의 `parsed_course_presence` 행을 실제 최소학점 규칙으로 승격할지 결정한다.
5. 선택 규칙 정규화 테이블 추가 여부를 결정한다.
6. 교양 영역 규칙을 `general_education_area_tables` 결과와 연결한다.
7. 졸업판정 로직은 우선 `needs_review=false` 데이터만 사용한다.
8. 스마트가전공학과와 Global Studies Program 공식 원문을 추가 확보한다.
9. Supabase RLS/권한 정책을 정리한다.

## 재실행 방법

로컬에서 Supabase 연결 문자열을 `DATABASE_URL`에 넣은 뒤 다음을 실행한다.

```bash
cd backend
alembic upgrade head
python -m scripts.seed_departments
python -m scripts.seed_academic_programs
python -m scripts.seed_graduation_requirements
```

raw CSV를 다시 만들 경우:

```bash
python3 backend/scripts/build_graduation_requirement_seed_tables.py
```
