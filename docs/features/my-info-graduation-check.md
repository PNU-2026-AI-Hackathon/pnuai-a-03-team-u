# 내 정보 페이지 (졸업요건 확인)

사용자의 One-Stop 포털(`onestop.pusan.ac.kr`) 계정으로 로그인해 학적부/성적/졸업요건을
가져와 DB 모델로 매핑한다. "내 정보" 페이지에서 보여줄 학적/성적/졸업요건 데이터의
수집·저장 파이프라인이며, Playwright 기반으로 사용자 본인 계정으로만 동작한다.

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
- `graduation.py` — 졸업요건 판정 결과
- `table_extract.py` — 범용 `<table>` 추출 + `.b-row-item`(`.b-title-box` 라벨 + `.b-con-box` 값) 구조 추출
  - 학적부 기본정보는 `<table>`이 아니라 `.b-row-item` 구조라 `extract_row_items()`를 따로 씀
- `onestop_course_catalog.py` — 수강편람(과목 카탈로그) 크롤러, 로그인 불필요

## DB 매핑 (`app/ingestion/normalizers/pnu_normalizer.py`)

- `save_portal_credential` — 포털 계정 저장. 비밀번호는 평문 저장하지 않고
  `app/core/security.py`의 Fernet 암호화(`encrypt_secret`)로 저장
- `map_student_record`, `map_grades`, `map_graduation_requirement` — raw 크롤 결과를
  `User`, `UserAcademicProgram`, `StudentCourseRecord`, `GraduationAudit` 등으로 매핑

## Department FK ([core-auth.md](./core-auth.md)의 `departments` 테이블 재사용)

`Course.department_id`, `RequirementSet.department_id`가 `departments` 테이블을
가리키는 FK로 추가됐다 (department 자유 텍스트 컬럼은 표시용으로 유지).
부전공/복수전공 요건은 별도 테이블이 아니라 `RequirementSet.program_type`이
`minor`/`dual`인 행으로 표현한다.

## Academic Program FK

졸업요건은 회원가입 검증용 `departments`와 분리된 `academic_programs`를 기준으로
관리한다. `departments`는 사용자가 입력하는 학과/전공명을 검증하기 위한 이름 목록이고,
`academic_programs`는 학과코드(`academic_program_code`)가 있는 학사 프로그램 마스터다.

상세 설계는 [graduation-academic-programs.md](./graduation-academic-programs.md)에 정리했다.

- `academic_programs` — 2026학년도 활성 학사 프로그램 151개
- `academic_program_aliases` — 공식명/표시명/정규화명 등 매칭용 별칭
- `department_academic_program_mappings` — 로그인용 `departments`와 졸업요건용
  `academic_programs` 연결
- `RequirementSet.academic_program_code` — 졸업요건 세트가 어느 학사 프로그램 기준인지 명시
- `UserAcademicProgram.academic_program_code` — 사용자의 학적 프로그램이 코드 기준으로
  확정된 경우 연결

시드:

```
python -m scripts.seed_academic_programs
```

2026-07-02에 학과별 파싱 자료 기반으로 `requirement_sets`/`requirement_categories`/
`requirement_courses`/`requirement_text_rules`에 실제 시드가 들어갔다. 다만 자동 파싱
결과라 `needs_review`가 붙어있고, 학과/전공별 커버리지가 고르지 않다. 자세한 내용과
커버리지 수치는 [graduation-requirements-supabase-seeding.md](../progress/graduation-requirements-supabase-seeding.md) 참고.

## 졸업요건 판정 엔진 (`app/domains/academics/graduation_engine.py`)

시드된 요건 데이터를 학생의 `student_course_records`와 대조해 프로그램(주전공/복수전공/
부전공/연계전공)별 카테고리 충족 여부를 계산하는 MVP. `evaluate_graduation(db, user_id)`가
진입점이다. FastAPI 라우터로는 아직 노출되지 않았다.

현재 시드 데이터 한계 때문에 판정 범위가 제한적이다 (자세한 근거는 모듈 docstring 참고):

- 학생 이수내역의 `category`가 대분류 텍스트(전공필수/전공선택/교양 등)뿐이라 효원핵심/
  효원균형/효원창의 같은 세부 교양 영역, 전공 합계 같은 집계 카테고리는 판정 불가로 둔다
- `curriculum_year`가 시드 데이터에 "2026"만 있어 학생의 실제 입학연도와 다르면 최신
  연도로 대체 판정하고 warning을 남긴다
- 복수전공/부전공(`program_type=dual`/`minor`) 요건 데이터는 37개 학사 프로그램(45개
  요건 세트)에 있다. 학과 교육과정표의 ♤/◎류 범례 마커에서 자동 추출한 필수과목
  목록이라 **총 이수학점 기준(minimum_credits)이 없다** — 필수과목 존재 여부는 체크
  가능하지만 카테고리 학점 판정에는 아직 못 쓴다. 나머지 학사 프로그램은 여전히
  "요건 데이터 없음"으로 반환된다
- ~~`student_course_records`가 어느 `user_academic_programs`에 속한 과목인지 연결이
  없어서, 전과/복수전공/부전공 학생의 과목이 서로 다른 전공 요건에 섞여 합산된다~~
  2026-07-03에 `_evaluate_categories()`가 `StudentCourseRecord.course_id` ->
  `Course.department_id`/`department`를 요건 세트의 학과와 비교해 다른 학과 과목을
  전공필수/전공선택/전공기초/심화전공 집계에서 **제외**하도록 고쳤다. 이후, 그냥
  빼기만 하면 학점 자체가 사라지는 문제가 있어(타학과 과목도 보통 일반선택으로는
  인정되므로) 제외된 학점을 `free_elective`(일반선택)로 재분류해서 합산하도록 다시
  고쳤다 — 예: 컴공 학생이 수학과 개설 "전공선택" 과목을 들으면, 컴공 요건 기준으로는
  전공선택이 아니라 일반선택 학점으로 잡힌다
  (`backend/tests/run_golden_tests.py`의 7개 회귀 시나리오로 검증, 전부 통과 —
  TC07이 이 재분류를 전용으로 검증함).
  **단, `course_id`가 채워져 있을 때만 작동한다.** `courses`(수강편람 카탈로그) 테이블이
  아직 비어있어 실제 학생 데이터는 `course_id`가 매칭되지 않으므로, 이 필터는 로직상
  맞고 테스트도 통과하지만 **`courses`가 채워지기 전까지는 운영 환경에서 아직 효과가
  없다** (`backend/test_scenarios.py`로 재현 가능 — course_id 없이 돌리면 여전히 섞임).

## 알려진 한계 / TODO

- FastAPI 라우터로 노출되지 않음 (아직 API 엔드포인트 없음, 스크립트로만 실행 가능)
- 백그라운드 작업화 안 됨
- 사용자별 자격증명 입력 플로우(회원가입/설정 화면 연동) 없음
- `RequirementSet`/`Course`의 `department_id` FK는 연결만 됐고 `courses` 카탈로그
  테이블 자체가 비어있어 course_id 매칭이 안 되고 텍스트 매칭에만 의존한다.
  전과/복수전공/부전공 학과 필터링(위 항목)이 실제로 작동하려면 이 테이블부터 채워야 한다
- `backend/tests/`의 골든 테스트(`run_golden_tests.py`, `verify_calculation.py`)는
  `pytest` 컨벤션이 아니라 `python -m` 직접 실행 스크립트라 CI에 자동으로 안 걸린다.
  나중에 `assert` 기반 pytest 테스트로 옮기는 게 좋다
- 복수전공/부전공 요건 데이터, 입학연도별 요건, 전과 이력 모델링이 전부 미해결
  (위 "졸업요건 판정 엔진" 절 참고)
