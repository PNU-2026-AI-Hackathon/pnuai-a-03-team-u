# 졸업요건 스키마 재설계: 부전공/복수전공/교직 + codex 브랜치 main 통합

2026-07-09, blackest21. 브랜치 `feat/graduation-requirement-schema`.

## 배경 / 문제

1. 졸업요건 판정 엔진과 상세 요건 스키마(`requirement_sets`/`requirement_categories`/
   `requirement_courses` + 골든테스트 10개)는 미머지 브랜치
   `codex/graduation-academic-programs`에만 있었고, main과 **계층 작업(PR #45/#46) 이전
   시점에서 갈라져** 있었다. 라이브 Supabase는 main 라인 계층(schools/colleges/departments/
   majors + courses 6,402행)으로 이미 시드된 상태.
2. 수집 중인 부전공/복수전공/교직 요건은 주전공과 **인코딩이 근본적으로 다르다**:
   - **부전공**: 대학 공통 기본규칙(학사운영규정 제21·22조 — 21학점, 필수 9학점 포함) +
     학과별 필수과목 리스트(확정 34개 학과, `raw_data/manual_staging/00_university_regulations/marker_summaries/01_부전공_필수과목_전체현황.md`) +
     택N/M 조건그룹("부전공필수 9과목 중 3과목"). 37개 학과는 규정상 부전공/복수전공
     자체가 불가 — "제공 안 함"도 표현해야 함.
   - **복수전공**: 과목 리스트가 아니라 학점총량 규칙(대상 학과의 최소전공 소계 =
     전공기초+전공필수+전공선택) + 융합전공별 고정 오버라이드
     (`curriculum_operation/dual_major_minor_credit_requirements_2026.csv`).
   - **교직**: 교육과정표의 과목 단위 마커 — △기본이수과목(체크리스트),
     □교과교육영역(합계 ≥8학점). 적성·인성검사 같은 무이수 요건은 성적표로 확인
     불가(데이터 없음).

## 결정 사항

### 통합 방식
- **main에서 새 브랜치를 파고 codex 브랜치 내용을 새 커밋으로 포팅** (rebase/merge 금지 —
  분기점이 hierarchy 이전이라 마이그레이션 라인이 근본 충돌).
- 포팅 기준은 브랜치 HEAD가 아니라 **stash@{0}(세션#15 정리분) 적용 후 형태**. 이 정리분은
  codex 브랜치 워크트리(`../planU-codex`)에 커밋 `6465c12`로 보존했다(stash 원본도 유지).
- 포팅하지 않은 것: flat `Department`(main 계층으로 대체),
  `DepartmentAcademicProgramMapping`(읽는 코드 0, 세션#15 폐기 결정),
  `GraduationAudit`/`GraduationAuditProgramResult`(main 코드 참조 0),
  `RequirementTextRule`(세션#15에서 해석·통합 후 삭제), seed/build 스크립트(다음 세션).

### 스키마 핵심 결정 5가지

1. **교직은 program_type이 아니다.** 학과 primary 요건세트의 카테고리 2종으로 표현:
   - `teacher_training_basic` (△ 기본이수과목, `rule_type="required_courses"` +
     requirement_courses 행들)
   - `teacher_training_pedagogy` (□ 교과교육영역, `rule_type="minimum_credits"`,
     minimum_credits='8')
   - 마커 중첩(◎△ = 부전공필수 + 교직기본이수)은 부전공 세트 행 1개 + primary 세트
     teacher_training 행 1개로 자연 표현되므로 별도 course_markers 테이블은 만들지 않음.
   - 무이수 요건(적성검사, 제22조제5항 교원자격 배제 등)은 `rule_type="manual_check"`
     카테고리 행 + notes로 남겨 엔진이 satisfied=None(판정 불가)으로 노출.
2. **대학 공통 기본규칙** = `requirement_sets.scope='university_default'` +
   `academic_program_code IS NULL` 행(부전공 21/필수9, 복수전공=최소전공소계).
   프로그램별 행 우선, 없으면 default 폴백(폴백 로직은 다음 세션 엔진 작업).
   NULL 코드는 UNIQUE 제약을 타지 않으므로 부분 인덱스
   `uq_requirement_sets_default (program_type, curriculum_year) WHERE code IS NULL`로
   default 행 중복을 방지.
3. **복수전공 학점총량** = dual 세트의 `category_code='minimum_major_total'` 행
   (엔진의 기존 전기+전필+전선 합산 판정과 정합). 융합전공 고정값(EES 42학점 등)은
   같은 행의 minimum_credits로.
4. **부전공/복수전공 불가(37개 학과)** = 해당 프로그램의 minor/dual 세트 행
   `offering_status='not_offered'` + `offering_note`(근거 규정) — 룩업 경로를
   requirement_sets 하나로 단일화.
5. **택N/M 조건그룹은 2-테이블로 일반화**: `requirement_condition_groups`
   (condition_type/min_courses/min_credits/max.../excess_allowed) +
   `requirement_condition_group_courses`(candidate/required/excluded 역할).
   부전공에서 출발했지만 전 program_type 공통. 원본 shape은 canonical CSV
   (`raw_data/parsed_experiments/pnu_2026_curriculum_canonical/minor_requirement_condition_groups_2026.csv` 등).
   행 단위 external_id가 원본에 없어 group_courses에는 행 unique를 두지 않고, 시드가
   그룹 단위 delete-and-reinsert로 멱등성을 확보한다.

추가로:
- **계층 ↔ 요건 브리지**: `departments.academic_program_code` /
  `majors.academic_program_code` (nullable FK + 부분 unique 인덱스). PR #45 리뷰에서
  제안했던 방식. `user_academic_programs.academic_program_code`도 추가 —
  portal-sync/가입 시 브리지에서 resolve해 채운다(후속 작업).
- **flat `graduation_requirements` 테이블 DROP** — 코드 참조 0, 라이브 빈 테이블,
  requirement_sets가 대체.
- `requirement_sets`에 `department_id` + `major_id` FK — 학과 단위 조회는
  `major_id IS NULL` 필터 필수(계층 시드 컨벤션과 동일).
- 데이터 시드 시 원칙(마커 정리본에서 확립): ① 표(마커) 원문이 프로즈 안내문보다 항상
  우선, ② "구버전/변경전" 규정은 DB에 시드하지 않고 원문 문서에만 남긴다(경과조치 존재는
  notes/rule_metadata로만 표시).

### 세션#15 재설계안(v2)과의 관계

codex 브랜치의 `docs/progress/db-schema-redesign.md`(15테이블 전면 재설계안)는 이번에
구현하지 않았다. 이번 작업은 그 제안 중 **main 계층과의 통합에 필요한 최소 부분집합**
(정리된 requirement_* 3테이블 + academic_programs/aliases + 브리지)에 부전공/복수전공/교직
표현을 얹은 것이다. v2의 나머지(규칙 트리, KEDI 메타 JSONB 접기, 서빙/파이프라인 분리)는
여전히 유효한 백로그.

## 마이그레이션

### 선행: `f1a2b3c4d5e6` (reset) 동결 수리

원래 이 리비전은 upgrade()에서 **현재 시점의** 도메인 모델을 import해
`Base.metadata.create_all()`을 호출했다. 모델이 진화할수록 미래 리비전이 만들 테이블을
미리 생성해 **빈 DB에서 `alembic upgrade head` 전체 체인 재생이 깨지는** 구조
(hierarchy 리비전의 schools 생성과 충돌 + `users.advisor_consulted` 이중 add_column).
도입 당시(커밋 b8e7734) 모델이 만들던 DDL을 하드코딩해 동결하고(IF NOT EXISTS =
create_all checkfirst 의미론), 이후 리비전이 add_column 하는 컬럼
(advisor_consulted/major/college)은 동결 DDL에서 제외 + advisor_consulted는 명시적
drop으로 a2b3c4d5e6f7의 전제를 복원했다. **이미 이 리비전을 지난 팀 Supabase에는 무영향.**

### 신규 리비전 5개 (main head `f7a8b9c0d1e2` 이후)

1. `a1c3e5b7d9f2` — academic_programs + aliases + departments/majors 브리지 컬럼
2. `b2d4f6a8c0e3` — requirement_sets(+scope/offering_status CHECK/부분 인덱스) +
   requirement_categories + requirement_courses
3. `c3e5a7b9d1f4` — 조건그룹 2테이블
4. `d4f6b8c0e2a5` — user_academic_programs.academic_program_code
5. `e5a7c9d1f3b6` — flat graduation_requirements DROP (downgrade는 재생성, 무손실)

전부 plain DDL(모델 import 없음), downgrade 포함.

### 부수 수정

- `School.name`: 모델의 `unique=True, index=True`(단일 unique 인덱스)를
  `UniqueConstraint("schools_name_key") + 일반 인덱스`로 변경 — e6f7a8b9c0d1 마이그레이션이
  실제로 만든(=라이브의) 형태와 일치시켜 `alembic check` drift를 0으로. 의미 동일, DDL 없음.
- 엔진 포팅 시 기계적 어댑테이션 2건(판정 로직 무변경):
  - main `Course`에는 `department` 텍스트 컬럼이 없어 타학과 판별의 텍스트 fallback 제거
    (department_id FK 비교만 유지 — courses가 빈 환경에서는 필터가 동작하지 않는 알려진
    한계 그대로).
  - main `UserAcademicProgram`에는 `major` 문자열이 없어 표시명을 major_id/department_id로
    resolve(`_resolve_program_display_name`).
  - `MANDATORY_COURSE_CATEGORIES`의 `teacher_training` → `teacher_training_basic`
    (카테고리 코드 어휘 변경 반영).
- 골든테스트 러너: 픽스처의 학과명 텍스트를 School/College/Department FK로 해석하도록
  수정("교양교육원"은 컨벤션대로 department_id=None). 골든 데이터 파일 자체는 무수정.

## 검증 (2026-07-09, 로컬 Postgres `planu_schema_v2` — Supabase 미접촉)

- 빈 DB에서 `alembic upgrade head` **전체 체인 최초 성공** (동결 수리 이전에는 불가능했음)
- `alembic downgrade f7a8b9c0d1e2` → `upgrade head` 왕복 성공 (신규 5개 리비전 downgrade 검증)
- `alembic check`: **drift 0** ("No new upgrade operations detected")
- 골든테스트 `backend/tests/run_golden_tests.py`: **TC01~TC10 전부 통과** (sqlite in-memory)
- 알려진 기존 이슈(이번 작업과 무관, 미수정): backend venv에 `email-validator` 미설치라
  `app.api.auth` import 불가(EmailStr). 골든테스트/마이그레이션에는 영향 없음.

## 다음 세션 TODO (엔진/시드)

1. 엔진 어댑테이션: `_find_requirement_set`에 university_default 폴백 +
   `offering_status='not_offered'` 즉시 "이수 불가" 판정, `RAW_CATEGORY_TO_CODES`에
   "교직과목"→teacher_training_* 매핑, 조건그룹(choose_at_least_n_courses) 판정 로직.
2. 시드: codex 브랜치의 seed/build 스크립트 포팅 + 시드 소스를 marker_summaries 정리본
   (`01_부전공_필수과목_전체현황.md`, `04_전체151개_수집상태_트래킹.csv`) + canonical CSV로
   전환. 01 정리본이 참조하는 원본 CSV
   (`outputs/pnu_2026_curriculum_excel/minor_required_courses_claude_verified_2026.csv`)는
   현재 main 워킹트리에 없음 — codex 워크트리(`../planU-codex`)의 outputs/에서 복구 필요.
3. departments/majors/user_academic_programs의 academic_program_code backfill
   (`_hierarchy_mapping.csv` 기반).
4. 교직 골든테스트 시나리오 추가(현재 교직 케이스 0).
5. Supabase 반영(사용자 승인 후, 로컬 전체 재검증 → 한 번에).
