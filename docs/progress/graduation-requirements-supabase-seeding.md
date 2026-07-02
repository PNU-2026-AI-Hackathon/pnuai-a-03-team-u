# Graduation Requirements Supabase Seeding Progress

작성일: 2026-07-02 (최종 갱신: 2026-07-03)

## 현재 상태 요약 (2026-07-03 기준)

이 문서는 시간순 작업 기록이라 아래로 갈수록 최신인데, 처음 보는 사람을 위해 최종
상태만 먼저 요약한다. 세부 근거는 각 날짜별 절 참고.

**Supabase 현재 수치**: `requirement_sets` 196(primary 148 · minor 28 · dual 17 · contract 3) /
`requirement_categories` 554 / `requirement_courses` 14,374 /
`requirement_text_rules` 868. `needs_review=false`(신뢰 가능)는 courses 기준 4,631건,
나머지는 검토 대기.

**됨:**
- 153개 학사 프로그램(주전공 기준) 중 대부분이 `ready_for_human_review`(실제 과목 데이터 있음)
- 사람 검토 → 재시딩 back-propagation 워크플로우 (`export_requirement_course_review_queue.py` + `backend/seeds/requirement_course_corrections.csv`)
- HWP 추출을 `pyhwp`/`hwp5html`로 교체 (기존 `textutil`/`strings`는 거의 다 실패하고 있었음)
- 과목코드-수강편람 카탈로그 대조 검증 완료 (표본 기준, 전수는 아님) — 전기공학전공의 소스 오염 버그 1건 발견/수정
- **복수전공/부전공 요건을 학과 교육과정표의 범례 마커(♤/◎ 등)에서 구조화 추출** — 예전엔
  운영규정 PDF에 별도 학점표가 있는 EES융합전공 1곳에만 데이터가 있었는데, 실제로는
  32개 학과의 교육과정표 자체에 "이 과목은 복수전공/부전공 필수"라는 마커가 붙어있었다.
  이를 파싱해 37개 학사 프로그램에 걸쳐 45개 복수전공/부전공 요건 세트, 900개 필수과목
  후보(매칭 742건)를 새로 만들었다. 상세: 아래 "복수전공/부전공 범례 마커 구조화" 절
- 졸업요건 판정 엔진 MVP (`backend/app/domains/academics/graduation_engine.py`)

**안 됨 / 다음에 할 일 (우선순위순):**
1. **사람 검토**: `requirement_courses.needs_review=true`. `export_requirement_course_review_queue.py` 실행 → 학과별로 훑어서 `backend/seeds/requirement_course_corrections.csv`에 `confirm`/`fix`/`drop` 기록 → 재시딩. 컴퓨터공학전공/인공지능전공처럼 과목 수가 많은 인기 학과부터 우선순위.
2. **미해결 학과 9개**:
   - 약학전공/제약학전공/약학부(통합6년제) 3개 — "이수체계도" 이미지뿐, 상세 과목표를 못 찾음. 약학대학에 직접 문의하거나 학사요람 PDF 확인 필요.
   - 스마트가전공학과(2027 첫 모집)/정보컴퓨터공학부(디자인테크놀로지전공)(2026 이관 예정) — 아직 공식 발표 전이라 원문 자체가 없음. 시간 지나면 재시도.
   - 교양학부(인문사회/공학/자연과학/의학/예체능계열)+기타모집단위 6개 — 자유전공학부 계열별 모집단위라 애초에 전공 교육과정이 없음. **해당없음으로 확정, 더 찾을 필요 없음.**
3. **GSP(Global Studies Program) 전공선택 12과목** 미반영 (전공필수/전공기초만 반영함)
4. **과목코드-학과 매핑 전수 검증**: 표본(상위 몇 개 학과) 확인만 했다. 나머지도 전기공학전공 같은 소스 오염이 있을 수 있으니, 사람 검토 워크플로우를 돌릴 때 "요청 학과와 무관한 학과 과목이 매칭되지 않았는지"도 같이 확인할 것.
5. 새로 만든 복수전공/부전공 요건 세트(45개)는 필수과목 목록만 있고 **총 이수학점 기준(minimum_credits)이 없다** — 범례 옆에 "부전공: ◎ 과목 필수이수 + 전공필수 ♤ 과목 중 추가 이수하여 총 21학점"처럼 텍스트로만 있어서, 구조화하려면 `requirement_text_rules`를 사람이 읽고 카테고리를 만들어야 한다.
6. **`requirement_text_rules`(868건)**: 아직 검토 워크플로우가 없다 (`requirement_courses`만 있음). 선택규칙("N개 중 M개 이수")과 위 5번의 복수전공/부전공 총학점 기준이 여기 텍스트로만 남아있다.
7. **졸업요건 판정 엔진**(`graduation_engine.py`) 자체의 한계: FastAPI 엔드포인트로 노출 안 됨, 전과 이력 모델링 안 됨(학생이 이전 전공에서 딴 학점이 현재 전공 요건에 그대로 합산됨), `curriculum_year`가 전부 "2026"뿐이라 입학연도별 요건 차이 미반영, 새로 생긴 dual/minor 카테고리에 minimum_credits가 없어 엔진의 카테고리 판정 자체는 아직 못 씀(필수과목 체크는 가능). 자세한 내용은 [my-info-graduation-check.md](../features/my-info-graduation-check.md).
7. `courses`(수강편람 과목 카탈로그) 테이블 자체가 비어 있어 `course_id` FK 매칭이 안 되고 텍스트 매칭에만 의존.
8. Supabase RLS/권한 정책 정리 (아직 안 함).

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
8. ~~스마트가전공학과와 Global Studies Program 공식 원문을 추가 확보한다.~~ 2026-07-03:
   Global Studies Program은 `pnudgs.com`에서 실제 교육과정표를 찾아 전공필수/전공기초
   12개 과목을 수기 반영함 (아래 "사람 검토 워크플로우" 절 참고). 스마트가전공학과는
   2026-04 발표된 LG전자 채용연계형 신설 계약학과로 **2027학년도 첫 신입생 모집** —
   아직 교육과정 자체가 존재하지 않아 확보 불가 (2027년 이후 재시도 필요, 추측으로
   채우지 않음)
9. Supabase RLS/권한 정책을 정리한다.

## 후속 수정: 과목코드 추출 정규식 버그 (2026-07-02)

`build_department_curriculum_structured_candidates.py`/`build_department_curriculum_courses.py`의
`COURSE_CODE_RE`가 `Z[A-Z]z?\d{6}` 패턴도 과목코드로 인식하고 있었다. 실제로는 "효원균형"
교양영역 표에 나오는 `ZFz000091`~`ZFz000110` 같은 소영역 placeholder 라벨까지 과목코드로
잘못 추출해서, 카탈로그에 없는 "과목"으로 unmatched 처리되고 있었다 (261개 학과 페이지에서
반복 등장, 전체 unmatched의 약 21%).

실제 수강편람 과목코드는 항상 대문자 2~3자 + 숫자 7자리(9~10자)이고 소문자를 포함하지
않는다는 걸 카탈로그 6,617개 코드 전수 확인 후, 정규식을 `[A-Z]{2,3}\d{7}`로 단순화했다.
(참고로 이름 표기 차이(반각/전각 괄호 등)로 인한 매칭 실패는 실측해보니 0건이라 별도
정규화 강화는 하지 않았다.)

재실행 + Supabase 재시딩 결과:

| 지표 | 이전 | 이후 |
| --- | ---: | ---: |
| `requirement_courses` 총 행수 | 9,082 | 8,820 (DB에서 잔여 262개 직접 삭제) |
| unmatched | 1,216 (13.4%) | 954 (10.9%) |
| ambiguous | 394 (4.3%) | 394 (4.4%, 비율만 변화) |
| needs_review = true | 4,451 | 4,189 |

남은 unmatched(954)를 표본 조사한 결과:
- 587행은 curriculum_year가 "2026"으로 태깅돼 있지만 실제로는 학번별 교육과정 비교표에서
  옛 과목코드가 섞여 있는 것으로 보인다 (`infer_year()`가 문서 제목의 연도를 문서 내 모든
  구간에 동일하게 붙이는 한계)
- 나머지는 2023~2026 수강편람 크롤 범위 밖의 구 교육과정 과목코드이거나(예: 2000~2021년대
  코드), 수강편람에 없는 실습 과목(`학교현장실습`, `종합실습` 등 교직/임상 실습성 과목)으로
  보인다
- 즉 정규식 버그로 인한 오탐(262개)은 제거했지만, 나머지는 대부분 "2023-2026 수강편람
  크롤 범위가 구 교육과정 코드를 포함하지 않는다"는 근본적인 데이터 한계이며, 이 세션에서
  다루지 않은 추가 크롤링/과거 카탈로그 확보가 필요하다

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

## 사람 검토 워크플로우 + HWP 추출 개선 + 학과 원문 보강 (2026-07-03)

### 사람 검토 → 재시딩 back-propagation

이전까지는 `needs_review=true` 행을 사람이 확인해도 그 결과를 저장할 곳이 없어서,
raw_data/ 파이프라인을 다시 돌리면(재크롤링/재파싱) 검토 결과가 사라졌다. 이번에
back-propagation 루프를 만들었다:

1. `python scripts/export_requirement_course_review_queue.py` — 현재
   `requirement_course_seed_candidates.csv`에서 `needs_review=Y`인 행만 대학/학과/
   카테고리 순으로 정렬해 `requirement_course_review_queue.csv`로 뽑는다.
2. 검토자가 확인이 끝난 행만 `backend/seeds/requirement_course_corrections.csv`
   (git 버전관리, raw_data/와 분리)에 옮겨 적는다. `resolution` 값:
   - `confirm`: 자동 매칭 결과가 맞음 -> `needs_review=false`로만 바뀜
   - `fix`: `corrected_matched_course_code`/`corrected_matched_course_name`/
     `corrected_match_status`로 덮어씀 -> `needs_review=false`
   - `drop`: 애초에 과목이 아니었음(표 서식 부스러기 등) -> `requirement_courses`에서
     아예 제거
   - `needs_source`: 아직 확실한 근거가 없음 -> `needs_review`는 그대로, review_reason만 갱신
3. `python -m scripts.seed_graduation_requirements`를 실행할 때마다 `corrections.csv`가
   자동 파싱 결과 위에 적용된다. `requirement_course_id`가 (카테고리, 매칭된 과목코드,
   원문 과목명, 소스파일)의 해시라, 매칭 로직이 개선되면 같은 행이라도 해시가 바뀔 수
   있는데 이번에 stale-row 정리(prune) 로직도 추가해 DB가 항상 최신 CSV와 정확히
   일치하도록 했다.
4. 첫 적용 사례로 27개 행(효원균형 placeholder 라벨, "N영역:" 안내문, 표 서식 부스러기)을
   `drop`으로 처리해 실제로 DB에서 제거함 (자동 패턴 분류, `reviewed_by=claude`로 기록).

일반 자동 파이프라인이 다루기 어려운 원문(짧은 과목코드, 영문 rowspan 표 등)은
`backend/seeds/requirement_course_supplemental.csv`에 수기로 추가하고
`seed_graduation_requirements.py`가 이것도 함께 병합한다 (Global Studies Program 사례 참고).

### HWP 추출 방식 교체 (핵심 개선)

기존 HWP 추출은 `textutil`/`strings` 폴백만 썼는데, HWP5는 압축 바이너리 포맷이라
`strings`로는 본문이 거의 안 나오고, `textutil`도 표는 통째로 날아갔다
(72개 HWP 소스 전부 `extracted_partial` 상태). `pip install pyhwp`로 설치되는
`hwp5html`을 1순위로 쓰도록 바꾸니 72개 전부 표 내용까지 온전히 뽑혔다
(`extracted_partial` -> `extracted`).

재실행 결과 (규칙 데이터 전체):

| 지표 | 이전 (2026-07-02 오후) | 이후 (2026-07-03) |
| --- | ---: | ---: |
| `requirement_categories` | 493 | 511 |
| `requirement_courses` | 8,766 | 13,851 |
| matched | 7,450 | 11,334 |
| unmatched | 935 | 1,520 |
| ambiguous | 381 | 997 |
| `requirement_text_rules` | 706 | 860 |

`needs_review=false`(신뢰 가능)는 4,631건으로 그대로다 — 새로 들어온 데이터는 전부
아직 검토 전이라 위 사람 검토 워크플로우로 걸러야 한다. unmatched/ambiguous 절대값이
늘어난 건 데이터 품질이 나빠진 게 아니라, 이전엔 아예 없던 학과들의 실제 과목이 처음
들어오면서 그중 일부가 catalog와 안 맞는 게 드러난 것이다.

### 학과 원문 직접 보강

`requirement_seed_coverage_report.csv`에서 `no_parsed_requirements_yet`/
`missing_source`였던 항목을 학과 홈페이지에서 직접 찾아 보강했다:

- **정보컴퓨터공학부 컴퓨터공학전공/인공지능전공** (`U04080100419`/`U04080100429`):
  기존에 다운로드돼 있던 소스가 전부 졸업서류 제출 안내/부전공 신청 안내 같은
  공지사항이었고 실제 교육과정표가 아니었다. `cse.pusan.ac.kr/cse/14222/subview.do`
  (교육과정 메뉴)에서 `2026교육과정표(컴퓨터공학전공).hwp`/`(인공지능전공).hwp`를
  찾아 받았고, 위 HWP 추출 개선과 합쳐져 두 전공 모두 0건 -> 1,054건/1,042건으로
  올라갔다.
- **Global Studies Program** (`U02030800044`): 경제통상대학 국제학부 산하 프로그램
  전용 사이트(`pnudgs.com/page/03_02.php`)에서 실제 GSP 교육과정표(전공필수 6개,
  전공기초 6개, 전공선택 12개, 과목코드 `GP`+5자리)를 찾았다. 다만 이 페이지는 표가
  rowspan으로 카테고리를 표시하고 과목코드가 9자리가 아닌 7자리(`GP29277`)라 일반
  추출 파이프라인의 휴리스틱(`likely_curriculum_context`/`COURSE_CODE_RE`)에 걸리지
  않는다. 파이프라인을 이 한 학과를 위해 억지로 일반화하기보다, 전공필수+전공기초
  12개 과목만 `requirement_course_supplemental.csv`에 수기로 옮겨 확실한 데이터만
  반영했다 (전공선택 12개는 아직 미반영, `note`에 출처 URL 남겨둠).
- **스마트가전공학과** (`T00000012631`): 2026-04 발표된 부산대-LG전자 채용연계형
  신설 계약학과로 **2027학년도부터 첫 신입생을 모집**한다. 즉 아직 교육과정 자체가
  공식적으로 존재하지 않아 원문을 확보할 수 없음을 확인했다 (추측으로 채우지 않음,
  2027년 이후 공식 교육과정표가 나오면 재시도).

### 남은 일

- `requirement_courses.needs_review=true` 9,220건 (이번에 새로 들어온 학과 데이터가
  대부분) — 위 export/corrections 워크플로우로 우선순위 학과부터 줄여나갈 것
- `no_parsed_requirements_yet` 26개 학과(대부분 무용학과/음악학과/조형학과 세부 전공,
  교양학부 계열별 placeholder, 약학전공 등)는 이번에 다루지 않음 — 개별 학과 홈페이지
  탐색이 더 필요하다
- GSP 전공선택 12개 과목 미반영
- 여전히 `courses`(수강편람 과목 카탈로그) 테이블 자체가 비어 있어 `course_id` FK
  매칭이 안 되고 텍스트 매칭에만 의존한다

## 남은 26개 학과 전수조사 + 수집 (2026-07-03)

`no_parsed_requirements_yet`/`missing_source` 상태였던 28개(26+GSP+스마트가전) 학과를
하나씩 실제로 확인했다. 부산대 학과 홈페이지는 양식이 통일돼 있지 않아 케이스마다
전혀 다른 방식이 필요했다.

### 발견한 사실: 위험한 오탐 사례

**첨단융합학부 나노소자첨단제조전공**(`T00000012660`)의 기존 소스는 검색으로 찾은
`nanomecha` 도메인 페이지였는데, 확인해보니 **동일 이름의 대학원 학과 커리큘럼**이었다
("...특론" 과목명, 본문에 "대학원" 명시, 짧은 7자리 과목코드 `NP75768` 등). 다행히
정규식이 짧은 코드를 안 걸러줘서 seed에는 안 들어갔지만(우연), 코드 형식을 조금만
관대하게 바꿨으면 학부생 졸업요건에 대학원 과목이 섞여 들어갈 뻔했다. **검색으로 찾은
소스는 다운로드 전에 반드시 "대학원/특론/graduate" 같은 키워드가 있는지 확인해야 한다.**
`pharmacy.pusan.ac.kr/pharmacy/5629`에서도 같은 패턴(약학과 페이지인데 전 행이
"전공(대학원)")을 발견해 걸러냈다.

### 발견한 사실: 부산대 학과 홈페이지 원문 형식 4가지

같은 대학(예술대학) 안에서도 학과마다 메커니즘이 완전히 달랐다:

1. **정적 파일 다운로드** — 컴퓨터공학전공/인공지능전공/GSP/건축학과/화공생명공학과/
   디자인학과. `curl`로 hwp/pdf를 그냥 받으면 됨. 검색엔진에 걸린 페이지 ID가 종종
   오래돼서(`메뉴이(가) 존재 하지 않습니다`) 학과 홈페이지 GNB를 다시 파싱해 최신
   subview ID를 찾아야 하는 경우가 많았다.
2. **페이지에 표가 그대로 박혀있음** — 화공생명공학과, 첨단융합학부(미래에너지전공/
   AI융합계산과학전공/나노소자첨단제조전공)는 별도 파일 없이 페이지 HTML 자체에
   연도별 졸업기준학점 표가 있었다.
3. **약학대학 "이수체계도"** — 실제 과목표가 아니라 교육철학을 설명하는 인포그래픽
   **이미지**였다. macOS Vision OCR로 텍스트는 뽑았지만 ("단계적/체계적/통합적..."),
   과목명·학점 같은 상세 표는 원래 없는 이미지라 못 얻었다. 약학전공/제약학전공/
   약학부(통합6년제) 3개는 이번에 미해결로 남음.
4. **AIS 공용 동적 위젯** — 무용학과, 음악학과, 조형학과는 학과 페이지에 표가 없고
   `등록된 데이터가 없습니다`만 보이는 검색 위젯이었다. 페이지 JS(`/Web-home/fnct/
   curriculum/JW_curriculum_bass/js/view.js`)를 읽어서, 이게 부산대 여러 사이트가
   공유하는 학사정보시스템(AIS) API를 쓴다는 걸 확인했다:
   - `POST /ais/UNIV/{collegeCd}/getDeptInfoMajorList` — 단과대학 코드로 학과/전공
     코드 전체 목록을 준다 (예: 예술대학=420000 → 조형학과=422300, 가구목조형전공=422304 등)
   - `POST /curriculum/{siteId}/{fnctNo}/view.do` (`.do` 확장자 필수, 없으면 404) +
     `findYear`, `findUnivType=UNIV`, `findUnivCd`, `findDeptCd` 폼 데이터로 실제
     과목 표를 받는다
   - `findYear=2026`은 아직 등록 안 된 학과가 많아서 `2025`로 시도하는 게 안전했다
   - **이 API는 사이트별이 아니라 부산대 학사시스템 전체 공용**으로 보인다. 다른
     `k2web` 기반 학과 사이트(플랫폼이 같은 곳)에서도 동일 패턴으로 쓸 수 있을 것이다
   - 이 방식으로 무용학과 3개 전공, 음악학과 4개 전공, 조형학과 3개 전공 = 10개를
     전공별로 정확하게 수집했다 (부모 학과 코드가 아니라 각 전공 고유 코드로 조회해서
     전공별 실기 과목까지 정확히 구분됨)

### 최종 결과 (28개 대상)

| 처리 결과 | 수 | 목록 |
| --- | ---: | --- |
| 정상 수집 완료 (`ready_for_human_review`) | 19 | 컴퓨터공학전공, 인공지능전공, 건축학과(5년제), 화공생명·환경공학부, 디자인학과(시각디자인/애니메이션), 무용학과×3, 음악학과×4, 조형학과×3, 첨단융합학부(미래에너지/AI융합계산과학/나노소자첨단제조) |
| 수기 반영 (`requirement_course_supplemental.csv`) | 1 | Global Studies Program (전공필수+전공기초 12과목만; rowspan 표라 자동 파이프라인 통과 못함) |
| 정상적으로 데이터 없음 (전공 미확정 모집단위) | 6 | 교양학부(인문사회/공학/자연과학/의학/예체능계열), 기타모집단위 — 1학년 계열별 모집 후 2학년에 전공 선택하는 구조라 자체 교육과정이 없음 |
| 미해결 — 이미지뿐, 상세 표 없음 | 3 | 약학전공/제약학전공/약학부(통합6년제) — "이수체계도" 인포그래픽 이미지만 존재 |
| 미해결 — 신설/전환 예정이라 원문 자체가 없음 | 2 | 스마트가전공학과(2027학년도 첫 모집), 정보컴퓨터공학부(디자인테크놀로지전공)(2026학년도 예술대학에서 이관 예정, 아직 미공개) |

### Supabase 최종 반영 결과

| 지표 | 이번 세션 시작 시점 | 최종 |
| --- | ---: | ---: |
| `requirement_sets` | 153 | 153 |
| `requirement_categories` | 511 | 550 |
| `requirement_courses` | 13,851 | 14,401 |
| `requirement_text_rules` | 860 | 903 |
| `review_status = ready_for_human_review` | 118/153 | 136/153 |
| `review_status = no_parsed_requirements_yet` | 26 | 9 (그중 6개는 원래 해당 없음) |

재시딩 2회 연속 실행해 멱등성 확인 완료.

### 남은 일

1. 약학전공/제약학전공/약학부(통합6년제) 상세 교과목표 확보 — 약학대학에 별도 요청
   또는 학사요람 PDF 확인 필요 (이번엔 못 찾음)
2. 스마트가전공학과(2027 첫 모집), 디자인테크놀로지전공(2026 이관)은 대학 공식 발표
   전이라 재시도 시점을 기다려야 함
3. GSP 전공선택 12과목 미반영
4. `no_parsed_requirements_yet`에서 이번에 벗어난 학과들도 여전히 `needs_review=true`
   상태 — 위 사람 검토 워크플로우로 계속 검증 필요
5. AIS 동적 위젯 방식(`/ais/`, `/curriculum/.../view.do`)을 발견했으니, 향후
   `download_discovered_curriculum_sources.py` 계열 스크립트에 이 API 호출을
   정식으로 통합하면 비슷한 위젯을 쓰는 다른 학과도 자동화할 수 있을 것

## 과목코드-수강편람 대조 검증 (2026-07-03)

`matched_course_code`가 실제 수강편람 카탈로그(`course_catalog_multi_term`)와 잘
맞는지 전체 11,500건(matched)을 코드 기준으로 대조했다.

**검증 결과:**
- 코드 존재 여부: matched로 표시된 모든 행의 `matched_course_code`가 카탈로그에
  실제로 존재함 (0건 불일치) — `match_course()`가 카탈로그 인덱스에서만 매칭하므로
  구조적으로 보장됨
- 학과 소속 정합성: 자동 검사(요청 학과명과 카탈로그 개설학과명 부분일치)로 1,841건이
  "의심"으로 잡혔지만, 상위 몇 개를 직접 까보니 대부분은 **오탐**이었다 — "정보컴퓨터공학부"
  요청분이 "컴퓨터공학전공"/"인공지능전공"(그 학부의 하위 전공) 이름으로 카탈로그에 찍혀서
  문자열이 겹치지 않았을 뿐, 실제로는 정보컴퓨터공학부 764건 중 708건(93%)이 자기 자신
  또는 하위전공 또는 교양이었다. 디자인학과/물리학과/화공생명공학과/생물교육과도 표본
  확인 결과 90% 이상이 정상.

**실제로 발견한 버그(수정함):**
- **전기전자공학부 전기공학전공**: 매칭된 358건 중 정작 전기공학전공 소속은 8건뿐이고
  유기소재시스템공학과/기계공학부/화공생명공학전공 등 무관한 학과 과목이 대거 섞여
  있었다. 원인 두 가지를 모두 고쳤다:
  1. `match_course()`의 학과 매칭이 접두어(`startswith`)만 확인해서 "전기전자공학부
     전기공학전공"처럼 구체 전공명이 **뒤에** 붙는 경우(접미어)를 못 잡았음 —
     부분 문자열 포함(`in`) 검사로 일반화 (`build_department_curriculum_courses.py`)
  2. 소스 폴더에 `2024-2학기_반도체융합전공_안내_학생용...hwp`(전기공학전공이 아니라
     **반도체융합전공**이라는 별도 연계전공 안내자료)가 섞여 들어가 있었음 —
     `00_sources_excluded/`로 이동해 파이프라인 대상에서 제외
  - 수정 후: 68건이 정확히 전기공학과/전기공학전공으로 재매칭됨 (기존 8건 대비)
- 이 두 버그 중 특히 2번(엉뚱한 학과 안내자료가 소스 폴더에 섞여 들어가는 것)은
  나노소자첨단제조전공 사례(지난 세션, 대학원 커리큘럼 오귀속)와 같은 패턴이라,
  **소스 폴더에 새 파일을 추가할 때는 파일명에 대상 학과와 다른 전공/프로그램명이
  있는지 확인하는 습관**이 필요하다

**재시딩 결과:** `requirement_courses` 14,401 → 13,837 (해시 재계산으로 재정렬),
matched 11,791 → 11,500, ambiguous 1,048 → 792(접미어 매칭 개선으로 다수가 ambiguous에서
matched로 전환), 재시딩 2회 연속 실행으로 멱등성 확인.

**결론**: 표본 검증 결과 과목코드-학과 매핑은 전반적으로 건전하다. 발견된 실제 오류는
1개 학과(전기공학전공)에 국한된 소스 오염 문제였고 수정 완료했다. 다만 이번 검증은
표본 확인(상위 몇 개 학과)이었지 153개 전체를 낱낱이 확인한 건 아니므로, 사람 검토
워크플로우(`export_requirement_course_review_queue.py`)로 `needs_review=true` 9천여
건을 학과별로 훑을 때 이런 오염 패턴이 또 있는지 계속 주의해서 봐야 한다.

## 복수전공/부전공 범례 마커 구조화 (2026-07-03)

### 문제

기존에는 복수전공/부전공 요건이 EES융합전공 1개 학과에만 있었다(`requirement_sets.
program_type = dual/minor` 행이 딱 2개). 원인은 이 요건이 운영규정 PDF의 별도 학점표에서만
왔기 때문인데, 실제로는 **학과 자체 교육과정표 안에서 과목명 앞에 기호를 붙여 복수전공/
부전공 필수과목을 표시하는 방식이 훨씬 널리 쓰인다.** 예를 들어 정보컴퓨터공학부:

```
※ 범례 : ♤ 최소전공(복수전공) 필수 과목, ◎ 부전공 필수과목
```

교과목 표에서 "♤ ◎ 인터넷과웹기초"처럼 과목명 앞에 기호가 붙어있으면, 그 과목은 원래
소속 카테고리(전공기초/전공필수 등)와 무관하게 복수전공/부전공 학생에게는 필수과목이라는
뜻이다. 학과마다 기호와 그 의미가 다르다 (예: 디자인학과는 ◎=부전공, ★=연계전공, △=교직
과정, □=교직교과교육영역, ◇=융복합교과, ◆=산학협력교과, ♧=윤리및봉사, ♣=캡스톤디자인).

기존 파이프라인은 이 기호를 원문 텍스트(`context`)에는 담았지만 구조화된 필드로 뽑지
않아서 그냥 버려지고 있었다. 32개 학과, 2,051개 과목 후보 행에 이 마커가 있었다.

### 구현

`backend/scripts/build_department_curriculum_structured_candidates.py`:
- `parse_legend(doc_text)`: 문서에서 "범례" 텍스트를 찾아 기호->의미 텍스트를 파싱
- `legend_symbol_program_types(legend)`: 의미 텍스트에 "복수전공"/"다중전공"이 있으면
  `dual_major`, "부전공"이 있으면 `minor`로 매핑 (그 외 기호는 무시 — 연계전공/교직과정/
  캡스톤디자인 등은 현재 스키마의 program_type으로 표현할 대상이 아님)
- 과목 후보를 만들 때, 그 과목이 속한 context 안에 마커 기호가 있으면 원래 프로그램
  타입(primary 등) 행과 **별개로** dual_major/minor 행을 추가로 만든다. 카테고리는
  원래 분류와 무관하게 "전공필수"로 강제한다 (마커 자체가 "이 과목은 필수"라는 뜻이므로)

`backend/scripts/build_graduation_requirement_seed_tables.py`:
- 기존에는 운영규정 PDF(`regulation_rows`)에서만 dual/minor `requirement_sets`를
  만들었다. 이제 학과 교육과정표 후보(`candidate_rows`)에서 마커로 발견된 dual_major/minor
  조합도 규정표 없이 최소 요건 세트를 만들도록 `build_requirement_sets()`에 3번째 패스를 추가
- `build_course_rows()`가 `program_type="dual_major"`를 DB 컨벤션인 `"dual"`로 정규화하지
  않던 버그를 고쳤다 (기존에는 조용히 `primary` 세트로 잘못 귀속되고 있었을 것)
- `CATEGORY_MAP`에 `복수전공기초/필수/선택`, `부전공기초/필수/선택`, 그리고 카테고리
  키워드를 못 찾은 폴백(`졸업요건`/`복수전공요건`/`부전공요건`/`기초교양`) 매핑 추가

`backend/scripts/seed_graduation_requirements.py`:
- stale-row 정리(prune)를 courses에만 적용하던 걸 categories/text_rules에도 동일하게
  적용 (매칭 로직이 바뀌면 세 테이블 다 해시가 바뀌므로)

### 결과

| 지표 | 이전 | 이후 |
| --- | ---: | ---: |
| `requirement_sets` | 153 | 196 |
| `requirement_sets` (dual+minor) | 2 (EES융합전공만) | 45 |
| dual/minor 요건 있는 학사 프로그램 수 | 1 | 37 |
| `requirement_courses` (dual+minor) | ~0 | 900 (matched 742 · ambiguous 112 · unmatched 46) |
| `requirement_categories` | 550 | 554 |
| `requirement_courses` 전체 | 13,837 | 14,374 |

### 한계

- 새로 생긴 45개 dual/minor 요건 세트는 **필수과목 목록만 있고 총 이수학점 기준이 없다**.
  "부전공: ◎ 과목 필수이수, 전공필수 ♤ 과목 중에서 추가 이수하여 총 21학점"같은 총학점
  규칙은 과목표가 아니라 별도 문장으로 적혀있어서 `requirement_text_rules`에 텍스트로만
  들어가고, `requirement_categories`의 `minimum_credits`로는 구조화하지 않았다. 즉
  `graduation_engine`의 카테고리 판정에는 아직 못 쓰고, 필수과목 존재 여부 체크에만 쓸 수 있다.
- 마커 인식은 문맥(context) 단위(표의 한 행)에 기호가 있으면 그 행의 모든 과목에 적용하는
  방식이라, 한 행에 여러 과목이 나열된 경우 기호가 실제로 어느 과목에 붙은 건지 정밀하게
  구분하지 못할 수 있다. 사람 검토 시 확인 필요.
- ♤/◎ 외의 기호(★연계전공, △/□교직과정, ◇융복합, ◆산학협력, ♧윤리봉사, ♣캡스톤디자인)는
  의도적으로 무시했다. 연계전공은 현재 `program_type`에 없는 개념이라 별도 설계가 필요하다.
