# PR: 졸업요건 학사 프로그램 기반 + Supabase seed 반영

## Summary

졸업요건을 회원가입용 학과명(`departments`)이 아니라 학사 프로그램 코드(`academic_programs`) 기준으로 관리할 수 있도록 기반 테이블을 추가하고, 학과별 홈페이지/교육과정 원문, 수강편람 과목 매칭, 부산대학교 교육과정 편성 및 운영규정 PDF에서 정리한 졸업요건 후보 데이터를 Supabase DB에 반영했습니다.

이번 PR은 자동 파싱 결과를 곧바로 확정 졸업판정 규칙으로 사용하는 것이 아니라, 원문 출처와 `needs_review` 상태를 함께 저장해 사람이 검토하며 확정할 수 있는 기반을 만드는 작업입니다.

## Changes

- 졸업요건 기준 학사 프로그램 마스터 추가
  - `academic_programs`
  - `academic_program_aliases`
  - `department_academic_program_mappings`
  - `UserAcademicProgram.academic_program_code`
  - `RequirementSet.academic_program_code`
- 2026학년도 활성 학사 프로그램 151개 seed 추가
- 회원가입 검증용 `departments`와 졸업요건 기준 `academic_programs` 역할 분리
- `requirement_categories`, `requirement_courses`, `requirement_text_rules` 테이블 추가
- `RequirementCategory`, `RequirementCourse`, `RequirementTextRule` SQLAlchemy 모델 추가
- `requirement_sets`에 `(academic_program_code, program_type, curriculum_year)` unique 제약 추가
- 과목번호 후보가 여러 개 붙는 경우를 위해 `requirement_courses.raw_course_code`, `matched_course_code`를 `Text`로 확장
- raw 파싱 결과를 seed 후보 CSV로 만드는 `build_graduation_requirement_seed_tables.py` 추가
- seed 후보 CSV를 DB에 upsert하는 `seed_graduation_requirements.py` 추가
- `seed_academic_programs.py` 보강
  - alias 중복 제거
  - active bachelor 프로그램에 없는 alias 제외
- 진행 상황/남은 작업 문서 추가
  - `docs/progress/graduation-requirements-supabase-seeding.md`

## Repository Correction

이 작업의 이전 PR이 실수로 `PNU-2026-AI-Hackathon/StarterTemplate`에 생성되어 닫았습니다.

- 닫은 잘못된 PR: `PNU-2026-AI-Hackathon/StarterTemplate#16`
- 올바른 PR: `PNU-2026-AI-Hackathon/pnuai-a-03-team-u#33`

## Supabase Applied

Supabase 프로젝트 `yuvumqzlglwhlpnecgqa`에 마이그레이션과 seed를 적용했습니다.

검증 결과:

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

`requirement_courses` 검토 상태:

- `needs_review=false`: 4,631
- `needs_review=true`: 4,451

아직 공식 원문이 추가로 필요한 대상:

- `T00000012631` 스마트가전공학과
- `U02030800044` Global Studies Program

## Validation

- `python3 -m py_compile`
  - `backend/app/domains/academics/models.py`
  - `backend/scripts/build_graduation_requirement_seed_tables.py`
  - `backend/scripts/seed_graduation_requirements.py`
  - 신규 migration 파일들
- `python3 -m csv`
  - `requirement_course_seed_candidates.csv`
- Supabase:
  - `alembic upgrade head`
  - `python -m scripts.seed_departments`
  - `python -m scripts.seed_academic_programs`
  - `python -m scripts.seed_graduation_requirements`
  - 원격 DB row count 검증

## Follow-Up

- `needs_review=true` 과목 후보 4,451개 검토 및 축소
- 선택 그룹 정규화 테이블 추가 여부 결정
- 교양 영역 규칙을 `general_education_area_tables`와 연결
- 스마트가전공학과/GSP 공식 원문 추가 확보
- 졸업판정 로직은 우선 `needs_review=false` 데이터만 사용
