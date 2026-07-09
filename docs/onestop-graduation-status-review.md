# One-Stop 졸업예정정보 저장 구조 검토 요청

이 문서는 Supabase 스키마를 바로 변경하지 않고, One-Stop 졸업예정정보 크롤링 결과를
어떻게 저장하고 서비스에서 활용할지 검토하기 위한 제안서다. 테이블 추가는 서비스 품질,
개인정보 보관, 운영 관리, 계산 엔진 책임 범위에 영향을 주는 결정이므로, 이 문서가 합의된
뒤 마이그레이션과 API 구현을 진행한다.

## 결론 요약

현재 구조만으로는 One-Stop이 학생별로 계산한 공식 졸업판정 상태를 정확히 보존하기 어렵다.
특히 편입/전적대 인정학점, 교양선택 영역별 이수 여부, 취득예정학점은
`student_course_records`와 공통 `requirement_sets`만으로 재현하기 어렵다.

추천 방향은 **One-Stop 졸업예정정보를 학생별 판정 스냅샷으로 저장하는 레이어를 추가**하는
것이다. 다만 MVP에서는 비학점 졸업요건(TOPCIT/외국어/졸업과제 등)은 보류하고, 학점
판정과 교양영역 판정에 필요한 최소 3개 테이블만 우선 검토한다.

```text
graduation_audits
student_graduation_category_statuses
student_general_education_area_statuses
```

선택적으로, 나중에 TOPCIT/외국어/졸업과제까지 서비스에서 다룰 때 아래 테이블을 추가한다.

```text
student_graduation_requirement_items
```

## 현재 서비스 코드에서 실제로 긁는 것

`POST /me/portal-sync`는 `backend/app/api/portal_sync.py`에서 One-Stop에 로그인한 뒤
아래 네 종류를 호출한다.

```text
fetch_student_record(page)                 # 학적부
fetch_all_grades(page)                     # 전체 성적
fetch_graduation_requirement(page)         # 졸업요건기준 및 충족여부조회
extract_graduation_expected_info(page)     # 졸업예정정보
```

중요한 점은 `extract_graduation_expected_info(page)`가 졸업예정정보 화면의 테이블 7개를
이미 모두 추출한다는 것이다. 즉, table 1/3/6은 **서비스 코드 경로에서 크롤링 자체는
되고 있다**. 다만 현재 DB 매핑은 table 0만 사용한다.

현재 저장되는 데이터:

- 학적부 → `users`, `user_academic_programs`
- 전체 성적 → `student_course_records`
- 졸업예정정보 table 0 → `user_academic_programs` 주전공/복수전공/부전공/연계전공
- 졸업예정정보 table 1/2/3/4/5/6 → 현재 저장하지 않음
- `fetch_graduation_requirement(page)` 결과 → 현재 저장하지 않고 응답에 table count만 사용

따라서 “서비스로 확실히 들어오도록 작업됐는가?”에 대한 답은 다음처럼 나뉜다.

- **크롤링/메모리 적재**: 졸업예정정보 7개 테이블은 현재 서비스 코드에서 이미 추출한다.
- **DB 저장**: 현재는 table 0만 저장하고, table 1/3 등 졸업판정 테이블은 저장하지 않는다.
- **검증 범위**: 2026-07-09 로컬 사용자 동의 테스트에서 동일한 크롤러 경로로 table 0~6이
  추출되는 것을 확인했다. 개인정보 raw는 `raw_data/user_data/...` 아래 gitignored 위치에만
  저장했고 커밋하지 않는다.

## 로컬 크롤링에서 확인한 데이터 형태

개인정보를 제외하고 구조만 요약한다.

### 전체 성적

전체 성적은 학기별 테이블로 들어오며, 행은 대략 아래 구조다.

```text
학년도 / 학기 / 성적분류 / 교과구분 / 교과목명 / 학점 / 성적등급 / 비고
```

편입/전적대 인정학점은 아래처럼 들어올 수 있다.

```text
2026 / 입학전성적 / 전적학교성적 / 교양선택 / 교양선택 / 15.0 / S / ...
```

이 경우 교양선택 영역별 이수 테이블에는 개별 영역이나 과목이 표시되지 않아도,
교과목구분별 이수구분 또는 전체 성적 기준으로는 교양선택 학점이 인정된다.
따라서 교양선택은 “총 학점 충족”과 “영역별 충족”을 분리해 저장하고 표시해야 한다.

### 졸업예정정보 table 1: 교과목구분별 이수구분

One-Stop table name 후보: `subject_category_completion`

확인된 컬럼:

```text
학적신청구분
사정구분
기준학점
취득학점
수강신청학점
취득예정학점
이수여부
졸업불가사유
```

예시 의미:

```text
교양선택 기준 12 / 취득 15 / 이수여부 Y
전공필수 기준 33 / 취득 26 / 이수여부 N / 전공필수학점미달
총이수학점 기준 133 / 취득 84 / 이수여부 N
```

이 테이블은 대분류 학점 판정의 공식 baseline으로 사용한다.

### 졸업예정정보 table 3: 교양선택 이수여부

One-Stop table name 후보: `general_education_area_completion`

확인된 컬럼:

```text
교양영역명
필수제외영역구분
중복가능영역구분
그룹번호
그룹별 이수 수
교과목명
등급
학점
이수여부
```

영역명 예시:

```text
1영역 : 사상과역사
2영역 : 사회와문화
3영역 : 문학과예술
4영역 : 과학과기술
5영역 : 건강과레포츠
6영역 : 외국어
7영역 : 융복합
8영역 : 효원브릿지
사상과역사
사회와문화
문학과예술
과학과기술
건강과레포츠
세계와 소통
융합과 창의
효원브릿지
감성과 체험
인성과 사회봉사
```

이 테이블은 교양선택 영역별 이수 상태를 저장하는 데 사용한다. 다만 전적대 인정학점처럼
영역에 배정되지 않은 교양선택 학점은 이 테이블에 과목이 나타나지 않을 수 있다.

### 졸업예정정보 table 6: 비학점 졸업요건

One-Stop table name 후보: `graduation_requirement_completion`

확인된 항목 예시:

```text
표준외국어능력시험 N
TOPCIT N
졸업과제 N
```

다만 현재 MVP의 핵심은 학점 판정과 교양영역 판정이다. 또한 별도 메뉴
`졸업요건기준 및 충족여부조회`는 로컬 확인 기준으로 “졸업요건이 확정되지 않았습니다”처럼
유효한 판정 데이터를 주지 않았다. 따라서 table 6은 크롤링은 되지만, 이번 스키마 결정에서는
보류 대상으로 둔다.

## 현재 구조로 해결하기 어려운 이유

현재 주요 구조:

```text
student_course_records
requirement_sets
requirement_categories
requirement_courses
graduation_requirements(flat, live 임시)
```

이 구조는 “학생이 들은 과목”과 “공통 졸업요건 기준”을 저장하기에는 적합하다.
하지만 아래 정보는 담기 어렵다.

1. One-Stop이 학생별 예외와 인정학점을 반영해 계산한 공식 `이수여부`
2. 편입/전적대 인정학점처럼 과목명은 대분류로만 들어오고 교양영역이 없는 학점
3. 취득학점과 수강신청학점, 취득예정학점의 구분
4. 교양선택 영역별 충족 상태
5. 크롤링 시점별 판정 이력

`student_course_records`에 이 정보를 억지로 넣으면 “성적표 원본 과목”과 “One-Stop 공식
판정 결과”가 섞인다. `requirement_categories`에 넣으면 “공통 기준”과 “학생별 결과”가
섞인다. 두 경우 모두 운영 중 디버깅과 데이터 삭제/재크롤링이 어려워진다.

## 제안 테이블 1: graduation_audits

목적: 한 번의 One-Stop 졸업예정정보 크롤링 결과를 묶는 스냅샷 단위.

```text
id
user_id
source_system                 # pnu_onestop
source_menu_code              # 000000000000089
source_url
crawled_at
curriculum_year
student_academic_program_id   # primary 기준, nullable
raw_snapshot_path             # 로컬/운영에서 raw 보관 시 경로. 운영에서는 null 가능
raw_metadata                  # JSONB, table counts/checksum/parser version 등
created_at
updated_at
```

운영 원칙:

- `POST /me/portal-sync` 한 번마다 새 audit을 만든다.
- 같은 유저의 최신 상태는 `crawled_at` 최신 audit을 사용한다.
- raw HTML/JSON 전체를 DB에 넣는 것은 피하고, 필요한 최소 파싱 결과만 저장한다.
- raw 보관 정책은 별도 결정한다. 개인정보가 있으므로 장기보관 기본값은 비추천이다.

## 제안 테이블 2: student_graduation_category_statuses

목적: 졸업예정정보 table 1의 교과목구분별 이수구분을 저장한다.

```text
id
audit_id
user_id
program_type                  # primary/dual/minor/interdisciplinary
student_academic_program_id   # nullable
category_name                 # 교양선택/교양필수/전공기초/전공필수/전공선택/일반선택/총이수학점 등
required_credits
earned_credits
registered_credits
expected_credits
completed_status              # Y/N/unknown
failure_reason
source_table_name             # subject_category_completion
source_row_index
raw_metadata                  # JSONB, 원본 row 일부/파서 보정 정보
created_at
updated_at
```

처리 규칙:

- `category_name`은 One-Stop 표기 원문을 보존한다.
- 필요하면 API 응답 단계에서 `general_elective`, `major_required` 같은 내부 코드로 매핑한다.
- `취득예정학점`은 `수강신청학점`과 분리 저장한다. One-Stop 컬럼이 둘 다 있으므로 섞지 않는다.
- 편입 인정 교양선택 학점은 table 1의 `earned_credits`에 반영된 공식 수치를 우선한다.

서비스 활용:

- 내 정보 페이지의 졸업요건 카드: “교양선택 15/12 충족”
- 계산 엔진 baseline: One-Stop `completed_status`를 우선 표시
- 로드맵 추천: `N`인 category를 기준으로 부족 영역 후보 생성
- 디버깅: 우리 자체 계산 결과와 One-Stop 공식 결과가 다르면 경고로 노출

## 제안 테이블 3: student_general_education_area_statuses

목적: 졸업예정정보 table 3의 교양선택 영역별 이수여부를 저장한다.

```text
id
audit_id
user_id
program_type
student_academic_program_id   # nullable
area_name                     # 사상과역사/사회와문화/...
area_label                    # 1영역 : 사상과역사 같은 원문 라벨
is_required_excluded          # 필수제외영역구분 해석값, nullable
is_repeatable_area            # 중복가능영역구분 해석값, nullable
group_no
required_count
completed_course_name
completed_grade
completed_credits
completed_status              # Y/N/unknown
source_table_name             # general_education_area_completion
source_row_index
raw_metadata                  # JSONB
created_at
updated_at
```

처리 규칙:

- `area_name`은 검색/집계용 정규화 이름, `area_label`은 One-Stop 원문 보존용이다.
- 한 영역에 여러 과목이 표시될 수 있으므로 `(audit_id, source_row_index)` 기준으로 보존한다.
- 학생이 전적대 교양선택 인정학점만 가진 경우, table 1의 교양선택은 `Y`일 수 있지만 table 3은
  과목/영역 이수 정보가 비어 있을 수 있다. 이 경우 교양선택 학점은 충족으로 보되, 영역별
  상세는 “One-Stop 영역 상세 없음” 또는 “전적대 인정학점 포함”으로 설명한다.

서비스 활용:

- 교양선택 상세 UI: 영역별 이수 여부/과목 표시
- 추천 엔진: 미충족 영역에 맞는 교양 과목 후보 추천
- 편입생 설명: “교양선택 총 학점은 인정되었으나 영역별 상세 과목은 One-Stop에 표시되지 않음”

## 보류 테이블: student_graduation_requirement_items

목적: 졸업예정정보 table 2/6의 필수교과목, TOPCIT, 외국어, 졸업과제 등을 저장한다.

보류 이유:

- 현재 논의의 핵심은 학점 대분류와 교양선택 영역별 판정이다.
- `졸업요건기준 및 충족여부조회` 메뉴는 로컬 확인 기준으로 유효 데이터를 주지 않았다.
- table 6은 추출되지만, TOPCIT/외국어/졸업과제는 학과별 운영과 프론트 UX 정책이 더 필요하다.
- 테이블을 먼저 만들면 저장은 되지만, 서비스에서 버려지는 필드가 될 가능성이 있다.

나중에 추가할 때의 후보 컬럼:

```text
id
audit_id
user_id
program_type
requirement_area              # required_course/non_credit_graduation_requirement 등
requirement_name              # TOPCIT/표준외국어능력시험/졸업과제
detail_name
passed_type
acquired_at
completed_status
note
source_table_name
source_row_index
raw_metadata
created_at
updated_at
```

## portal-sync 처리 흐름 제안

현재:

```text
1. One-Stop 로그인
2. 학적부 크롤링
3. 전체 성적 크롤링
4. 졸업요건기준 및 충족여부조회 크롤링
5. 졸업예정정보 크롤링
6. portal_credentials 저장
7. users / user_academic_programs 저장
8. student_course_records 저장
9. 졸업예정정보 table 0만 user_academic_programs에 반영
10. 로드맵 완료 과목 동기화
```

제안:

```text
1~8. 기존과 동일
9. graduation_audits 생성
10. 졸업예정정보 table 0은 기존처럼 user_academic_programs 반영
11. 졸업예정정보 table 1을 student_graduation_category_statuses에 저장
12. 졸업예정정보 table 3을 student_general_education_area_statuses에 저장
13. table 2/6은 이번 단계에서는 저장하지 않거나 raw_metadata summary만 audit에 기록
14. 로드맵 완료 과목 동기화
```

재크롤링 정책:

- 기존 audit은 유지하고 새 audit을 추가한다.
- 최신 상태 조회는 최신 audit 기준으로 한다.
- 개인정보 삭제 요청이 있으면 해당 user_id의 audit/status/raw snapshot을 함께 삭제한다.

## 계산 엔진과 서비스에서의 사용 방식

### 우선순위

```text
1. One-Stop category status(table 1)를 공식 baseline으로 표시
2. One-Stop general education area status(table 3)를 교양영역 상세 baseline으로 표시
3. student_course_records는 성적표 원본/학점 합산/로드맵 반영/설명 보조로 사용
4. requirement_sets는 학과별 기준 설명과 추천 후보 필터링에 사용
```

### 예시 응답 개념

```json
{
  "category": "교양선택",
  "requiredCredits": 12,
  "earnedCredits": 15,
  "completed": true,
  "source": "pnu_onestop",
  "notes": [
    "전적학교성적 인정학점이 교양선택 취득학점에 포함될 수 있습니다."
  ],
  "areas": [
    {
      "areaName": "사상과역사",
      "completed": null,
      "note": "One-Stop 영역 상세에 이수 과목이 표시되지 않았습니다."
    }
  ]
}
```

### 편입/전적대 인정학점 처리

- 전체 성적에서 `성적분류=전적학교성적`, `교과구분=교양선택`, `교과목명=교양선택`처럼 들어오는
  인정학점은 `student_course_records`에 그대로 저장한다.
- 교양선택 총 학점은 table 1의 One-Stop 공식 취득학점을 우선한다.
- 교양영역 상세는 table 3을 우선한다.
- table 1은 충족인데 table 3 상세가 비어 있으면 오류가 아니라 “영역 미표시 인정학점 포함 가능”
  상태로 해석한다.

## 운영/품질 영향

장점:

- 학생별 공식 판정을 보존하므로 편입/인정학점 케이스에 강하다.
- 우리 계산 결과와 One-Stop 결과를 비교할 수 있어 품질 검증이 가능하다.
- 교양선택 영역별 UI와 추천의 근거가 생긴다.
- 크롤링 시점별 이력을 남길 수 있어 “왜 어제와 오늘 결과가 다른지” 추적 가능하다.

비용:

- user-scoped 개인정보 테이블이 늘어난다.
- audit이 쌓이면 저장량과 삭제 정책을 관리해야 한다.
- One-Stop DOM/컬럼 변경 시 parser가 깨질 수 있으므로 fixture 기반 테스트가 필요하다.
- table 3이 빈 경우를 실패로 오판하지 않도록 UI/엔진 설명 정책이 필요하다.

개인정보/보안:

- raw user data는 커밋 금지, 운영 DB에는 최소 파싱 결과만 저장.
- raw HTML/JSON 장기보관은 기본 비활성으로 둔다.
- `portal_credentials.encrypted_password`와 audit/status 데이터 삭제 정책을 같이 정해야 한다.
- 로그에 학번, 이름, 성적표 원문, raw row 전체를 남기지 않는다.

## 대안 비교

### 대안 A: 새 테이블 없이 student_course_records만 사용

장점: 구현이 가장 적다.

단점: One-Stop 공식 이수여부, 취득예정학점, 교양영역 판정, 인정학점 예외를 재현하기 어렵다.
편입생/인정학점 케이스에서 실제 학생 화면과 다른 결과를 낼 위험이 크다.

### 대안 B: graduation_audits에 JSONB 하나로 전부 저장

장점: 마이그레이션이 작고 원본 구조 변화에 강하다.

단점: UI/API에서 교양선택 영역별 조회, 미충족 항목 필터링, 통계/운영 쿼리가 어려워진다.
결국 서비스 로직에서 매번 JSON 파싱이 필요하다.

### 대안 C: category/area status 2개 테이블로 정규화

장점: MVP에 필요한 학점 대분류와 교양영역 판정을 명확히 저장한다. 서비스 조회가 쉽다.

단점: table 2/6 같은 필수교과목/비학점 요건은 나중에 별도 확장이 필요하다.

현재 추천은 **대안 C**다.

## 검토가 필요한 결정사항

1. MVP에서 table 2 필수교과목 이수여부를 저장할지, 아니면 table 1/3만 우선 저장할지.
2. table 6 TOPCIT/외국어/졸업과제는 이번 단계에서 완전히 보류할지, audit metadata에 summary만 남길지.
3. raw snapshot을 운영에서 저장할지, 파싱 결과만 저장하고 raw는 즉시 폐기할지.
4. audit 보존 기간과 사용자 삭제 요청 시 cascade 범위.
5. `completed_status` 값을 문자열 `Y/N/unknown`으로 둘지 boolean+unknown enum으로 둘지.
6. 교양영역명이 교육과정 연도별로 달라질 때 area dictionary를 따로 둘지, One-Stop 원문 중심으로 갈지.

## 제안 구현 순서

1. parser 추가: `onestop_graduation_expected_info.py`에서 table 1/3을 typed dict로 변환
2. fixture 테스트 추가: 개인정보 제거 fixture로 table 1/3 파싱 테스트
3. 마이그레이션 추가: `graduation_audits`, `student_graduation_category_statuses`,
   `student_general_education_area_statuses`
4. portal-sync 저장 로직 추가
5. `GET /me/graduation` 응답에 One-Stop baseline 섹션 추가
6. UI에서 대분류 학점 카드와 교양영역 상세 표시
7. 우리 계산 엔진 결과와 One-Stop baseline 불일치 경고 추가

## 이번 검토 PR 범위

이번 PR은 문서 검토 요청만 포함한다.

- Supabase 마이그레이션 없음
- DB 테이블 생성 없음
- API 동작 변경 없음
- 로컬 사용자 raw 데이터 커밋 없음

