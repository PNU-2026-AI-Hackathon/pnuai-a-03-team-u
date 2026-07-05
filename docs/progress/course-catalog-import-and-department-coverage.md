# 수강편람 -> courses 테이블 적재 + departments 커버리지 완성 (2026-07-05)

## 배경

`raw_data/README_department_curriculum_collection.md`/`docs/progress/graduation-requirements-supabase-seeding.md`에서 다루던 "카탈로그 추정에만 의존하는 37개 학과" 원문 조사를 이어서 하다가, 백엔드 관점에서 다음 질문으로 이어졌다: 졸업요건 판정 엔진(`graduation_engine.py`)은 이미 완성돼 있는데 `courses` 테이블이 비어있어서 `StudentCourseRecord.course_id` 매칭이 한 번도 실제 데이터로 검증된 적이 없었다(`docs/CHANGELOG.md` 2026-07-03 #5/#6 참고). 이 세션은 그 공백을 메우는 작업이다.

## 1) 부산대 학과별 커리큘럼 URL 조사 (37개 학과)

`raw_data/manual_staging/01_graduation_requirements/by_department/_collection_targets_index.csv` 기준 151개 학과 중, 자동 크롤러가 홈페이지를 못 찾거나 원문을 못 뽑아 "카탈로그 추정치만" 있던 37개 학과의 실제 교육과정 URL을 웹 검색 + 각 학과 사이트 실제 내비게이션 HTML 파싱(K2Web CMS 공용 구조, `pnuDomainChk.do` 리다이렉트 해석, 자료실 게시판까지 확인)으로 찾았다.

- 35개는 실제 URL 확정, 2개(스마트시티전공[2026학년도 신설, 사이트 자체 없음], 치의예과[2026학년도 학제 전환 전, 사이트가 아직 치의학전문대학원 구조])는 진짜 공백으로 확인.
- 조형학과처럼 기존에 AIS 위젯이 계속 빈 응답이라 막혀있던 케이스도 이번에 뚫림(`plarts.pusan.ac.kr`).
- 사용자가 직접 보내준 원문(환경공학과 2025 교육과정표 PDF, 불어불문학과 2026학년도 교육과정표 PDF, 경제학부 "펜토미노 교육과정" 가이드북, 기계공학부 학번별 교과과정 페이지)으로 자동 탐색이 못 찾던 것들을 보강.
- **이 URL 결과물은 아직 `raw_data/manual_staging/`의 기존 151개 학과 구조에 반영 안 됨** — `local.md`(개인 작업 노트, 커밋 안 됨)에 전체 표로 남겨뒀고, 다음 사람이 이어받으려면 그 파일을 참고해야 한다.

## 2) 수강편람(onestop) -> `courses` 테이블 적재 파이프라인

`raw_data/crawled_data/onestop_course_catalog/`에 2023학년도 1학기부터 2026학년도 겨울학기까지 17개 학기 수강편람 원본이 이미 크롤링돼 있었으나(학기당 4,000~4,400행), `courses` 테이블로 적재하는 코드가 없었다(`app/ingestion/csv_importers/`가 빈 껍데기).

### 설계 결정

- 시간표/분반/교수 등 학기별 개설(offering) 단위 정보는 이번에 다루지 않는다. 전수 확인 결과 과목명·학점은 course_code당 100% 안정적이고(17개 학기, 6,617개 고유 코드 중 drift 0건), 학기마다 바뀌는 건 교수/분반/시간표뿐이었다. 그건 나중에 시간표 추천 기능을 만들 때 같은 원본에서 다시 뽑기로 하고, 지금은 `course_code` 하나당 한 행으로 합친 과목 마스터만 만든다.
- department/category는 드물게 학기마다 다르게 찍힌다(조직개편, 커리큘럼 개정). 조용히 덮어쓰지 않고 최신 학기 값을 대표값으로 쓰되, drift가 있었던 이력은 `raw_data/reports/course_catalog_import_review.csv`에 남긴다.

### 추가한 파일

- `backend/migrations/versions/a1c47e0f9d52_make_courses_course_code_unique.py`: `courses.course_code`가 기존엔 non-unique 인덱스였음(재실행 시 중복 쌓임) — unique로 변경.
- `backend/app/ingestion/csv_importers/course_catalog_importer.py`: 17개 학기 CSV를 course_code로 dedup, department_id 매칭(정확 일치 -> 공백/기호 정규화 -> 학과/전공 접미사 stem 매칭[단일 학과에만 대응할 때만 채택] 순), drift/미매칭 리포트 출력.
- `backend/scripts/import_course_catalog.py`: CLI 래퍼(`python -m scripts.import_course_catalog`).

## 3) `departments` seed 커버리지 확장 (163 -> 201개, 3단계)

과목 적재 중 학과 매칭이 안 되는 이름들을 확인하다가 `backend/seeds/pnu_departments.json`(163개, onestop 크롤러 스냅샷 기준) 자체가 낡았다는 걸 발견해서 3단계로 보강했다.

1. **수강편람 실제 개설 이력 기준**: 매칭 안 되는 이름 678개 → 학과/전공 접미사 stem 매칭 로직 추가로 597개 → 실제 신설/누락 학과 15개(스마트해양모빌리티융합전공 등) 추가로 366개까지 줄임. 나머지는 교양교육원/학사과 등 원래도 비학사 조직이라 제외가 맞음.
2. **사용자가 준 전학과 2026학년도 졸업이수학점 요건표(부산대 규정집 rule_seq=84) 기준 교차검증**: 129개 프로그램 중 4개 누락 발견(광메카트로닉스공학과, AI융합계산과학전공, 그린바이오과학전공, 생명자원시스템공학전공) → 182개.
3. **「부산대학교 교육과정 편성 및 운영규정」 원문(사용자 제공 PDF, 47페이지, 2026.2.27. 규칙 제3099호) 전체 대조**: 별표2(주전공), 별표2-1(계약학과), 별표2-2(융합전공/복수전공/연계전공/학생자율전공), 별표2-4(부전공·복수전공 이수학점)까지 훑어서 19개 추가(Global Studies Program, Korean East Asian Studies Program, 의생명과학전공, 연계전공 6종, 학생자율전공 6종 등) → **201개**. 별표2-5(마이크로디그리)/별표2-6(트랙)은 전공 하위 세부이수증 개념이라 의도적으로 범위에서 제외.

### 확인된 사실 — 그린바이오과학전공 vs 그린바이오융합전공

둘 다 실재하는 별개 프로그램이다. 별표2엔 "그린바이오과학전공"(응용생명융합학부 소속 정식 주전공), 별표2-4엔 "그린바이오융합전공"(타학과생 대상 부전공/복수전공 전용 융합전공)이 각각 별도 이수학점으로 나온다. 병기 유지가 맞다(기존에 `환경공학과`/`환경공학전공`을 병기하던 것과 같은 처리).

### 확인된 사실 — 나노과학기술대학 조직개편

규정 부칙 제8조: 2026년 3월부터 나노과학기술대학(나노에너지공학과, 나노메카트로닉스공학과, 광메카트로닉스공학과) 재적생은 학부대학 첨단융합학부의 세부 전공(미래에너지전공, 나노소자첨단제조전공, 광메카트로닉스공학전공)으로 학적이 변동된다. 수강편람 데이터에서 관찰된 department drift(428건) 중 상당수가 바로 이 개편 때문이었다는 게 원문으로 확인됨.

## 4) 로컬 Postgres로 전체 파이프라인 끝까지 검증

`backend/.env`의 `DATABASE_URL`이 팀 공유 Supabase를 직접 가리키므로, 스키마 변경·대량 적재를 여러 번 나눠 시도하지 않기 위해 `infra/docker/compose.local.yml`(pgvector 포함 로컬 Postgres)을 새로 만들어 로컬에서 끝까지 돌렸다.

- 실행 순서: `alembic upgrade head` → `seed_departments` → `import_course_catalog` → `seed_academic_programs` → `seed_graduation_requirements` → `tests/run_golden_tests.py`.
- 이전 세션이 만든 `planu-postgres` 컨테이너가 고아 상태로 남아 있었는데, alembic 리비전이 현재 마이그레이션 체인과 안 맞는 stale 상태(`departments` 테이블도 없었음)라 볼륨을 지우고 새로 만듦.
- **결과**: `courses` 6,617행 적재(재실행해도 동일 — idempotent 확인), 학과 매칭 94.5%(6,251/6,617), `requirement_courses.matched_course_code` 13,176건 중 **11,849건(89.9%)이 이번에 처음으로 실제 `courses`와 조인됨**(이전엔 courses가 비어있어 0건). 골든테스트 7개 전부 통과.

## 5) 검수(자체 감사) — 발견한 문제와 즉시 조치

전체 파이프라인을 완성했다고 보고하기 전에, "부산대 학사관리 전문가/검사관" 관점에서 스스로 다시 훑었다. 발견한 것과 조치는 다음과 같다.

### 조치함 — `departments`에 넣은 규정 기반 항목 중 17개 제거 (201 -> 184개)

3단계(수강편람 실제 개설 이력 -> rule_seq=84 요건표 -> 「교육과정 편성 및 운영규정」 원문) 대조 중 넣은 23개를 실제 수강편람 데이터와 다시 대조해보니, **22개가 `offering_department`로 단 한 번도 등장하지 않았다.** `departments`는 회원가입 시 학과/전공 검증용 테이블인데, 이 중 상당수는 별표2-2/별표2-4에서 "최소전공을 구성하지 않는" 것으로 명시된 연계전공·학생자율전공·부전공전용 융합전공이었다 — 학생이 입학 시점에 주전공으로 선택할 수 없고, 이미 다른 학과에 재학 중인 학생이 나중에 추가로 취득하는 자격이다.

판단 기준: 별표2(주전공표) 또는 별표2-2의 "융합전공" 섹션처럼 **교양+전공 학점이 완전한 구조로 채워진 것**(EES융합전공, 핀테크융합전공과 같은 급)은 유지하고, 별표2-2의 복수전공/연계전공/학생자율전공 섹션과 별표2-4처럼 **교양 칸이 통째로 비어있고("-") 최소전공 개념 자체가 없는 것**은 제거했다. 제거 전 `courses.department_id`가 이 17개를 참조하는 행이 있는지 먼저 확인했고(0건), 안전하게 지웠다.

제거한 17개: Korean East Asian Studies Program, 의생명과학전공, 빅데이터연계전공, 산업사물소프트웨어연계전공, 임베디드소프트웨어연계전공, 차량용AI반도체연계전공, 산업AI연계전공, 탄소중립바이오기술연계전공, 공공거버넌스와법전공, 수리금융데이터과학전공, 부동산경영학전공, 도시관광경제기획전공, 경영AI기술전공, K-문화콘텐츠학전공, 디지털헬스케어융합전공, 의료인공지능융합전공(공백없는 규정명 중복분만 — 수강편람 태그인 "의료인공지능 융합전공"[공백있음]은 실제 과목이 있어서 유지), 임상시험코디네이터(CRC)융합전공.

유지한 5개(교양+전공 구조가 있거나 이미 `academic_programs`에 코드가 있음): 지능형서비스사이언스융합전공, 광메카트로닉스공학과, AI융합계산과학전공, 그린바이오과학전공, 생명자원시스템공학전공, Global Studies Program.

**이 17개가 실제로 갈 곳**: `academic_programs`(2026 활성 학사 프로그램, 151개, 정규 입학 코드 기준)에도 대부분 없다 — 확인해봄. 즉 지금 스키마엔 "부전공/복수전공/연계전공/학생자율전공 프로그램명" 자체를 담는 정식 테이블이 없다. `RequirementSet.program_type`이 이미 'primary'/'dual'/'minor' 등을 구분하고 있으니(EES융합전공이 이미 이 방식으로 부전공/복수전공 요건 2건을 갖고 있음, `raw_data/README_department_curriculum_collection.md` 참고), 이 17개도 나중에 실제 이수요건을 만들 때 같은 방식(department/academic_programs가 아니라 RequirementSet 레벨에서 program_type으로 구분)으로 다루면 된다. 지금 당장 새 테이블을 만들 필요는 없음 — 그냥 `departments`/`academic_programs`에 잘못 넣지만 않으면 된다.

### 조치 필요성 확인함 — `seed_departments.py`는 insert-only라 JSON에서 지워도 DB엔 안 지워짐

위 17개를 `pnu_departments.json`에서 지운 뒤 `seed_departments`를 재실행했는데, 로컬 DB의 `departments` 행 수가 201 그대로였다. `on_conflict_do_nothing`으로 upsert만 하고 삭제 로직이 없기 때문이다. 로컬 DB에서는 직접 `DELETE ... WHERE name IN (...)`으로 지워서 184로 맞췄다(사전에 `courses.department_id` 참조 0건 확인 후 실행). **Supabase에 반영할 때도 이 17개를 위해 별도 DELETE가 필요하다** — 다만 Supabase의 `departments`는 지금 비어있는(아예 seed 실행 전) 상태이므로 이번 최초 실행에서는 문제가 안 됨. 앞으로 seed 파일에서 이름을 지우는 변경을 할 때는 항상 이 점을 기억해야 한다.

### 확인함, 지금은 안전 — 같은 학기에 course_code 하나가 서로 다른 학과로 동시에 개설되는 케이스 27건

`XA`(교직과목, 여러 사범대 학과 공동 개설)와 `ZE1000043`("공학작문및발표", 공학교육인증 학과들이 각자 분반 개설) 유형이 대부분. 지금 dedup 로직은 이런 경우 "최신 학기 중 파일 읽는 순서상 먼저 나온 것"을 사실상 임의로 고른다. 다행히 `graduation_engine.py`의 학과 불일치 체크(`is_diff_dept`)는 학생 기록의 `category`가 전공필수/선택/심화전공(`is_major_code`)일 때만 작동하는데 XA/ZE는 교양·교직이라 이 분기를 안 타므로 **지금 졸업판정 로직엔 영향 없음을 코드로 확인했다.** 다만 `Course.department_id`를 나중에 "학과별 개설과목 조회" 같은 다른 용도로 쓰게 되면 이 27개 코드는 부정확한 학과로 보일 수 있다 — 그때 가서 참고할 것.

### 확인함 — course_code=course_name 안정성은 규정(제3조③)으로 보장되지만, credits drift 감지 로직 자체가 없음

"이미 편성된 과목과 같은 명칭의 과목을 편성할 경우에는 기존 과목 코드를 사용" 조항 확인 — course_name 안정성은 우연이 아니라 규정. 다만 학점까지 동일해야 한다는 조항은 못 찾았고, 지금 임포터는 department/category drift만 감지하지 course_name/credits drift는 감지하지 않는다(지금 데이터엔 0건이라 실사용엔 문제없지만, 향후 학점 변경이 생기면 조용히 최신값으로 덮어써지고 review CSV에도 안 잡힌다).

### 검증함 — stem(학과/전공 접미사) fallback 매칭은 안전

실제로 활성화된 건 4쌍(도시공학전공↔도시공학과, 전기공학과↔전기공학전공, 전자공학과↔전자공학전공, 화공생명공학전공↔화공생명공학과)뿐이었고, 전부 같은 학과가 맞는지 수동 검증함. 오매칭 없음.

### 고침 — 선택형(택1) 필수과목이 영원히 "미이수"로 판정되는 버그 (`_evaluate_required_courses`)

사용자가 요청한 경영학과 `courses`/`requirement_courses` 대조표를 만들다가 발견했다. `requirement_courses.matched_course_name`/`matched_course_code`는 하나의 요건을 여러 대체 과목 중 하나로 채울 수 있을 때(택1) `"캡스톤 디자인|캡스톤디자인"`처럼 파이프(`|`)로 여러 이름/코드를 한 행에 합쳐서 저장한다(예: 경영학과 "인공지능", "데이터베이스", "캡스톤디자인", "데이터마이닝", "재무관리특강" 6건). `graduation_engine.py`의 `_evaluate_required_courses()`는 이 필드를 파이프로 안 쪼개고 **문자열 그대로** 학생의 이수 과목명과 비교했기 때문에, 학생이 대체 과목 중 어떤 걸 들었어도 절대 일치하지 않아 항상 "미이수"로 잡혔을 것이다.

**실제 라이브 영향은 확인해보니 0건이었다** — 경영학과의 해당 6건은 전부 `needs_review=true`라서 애초에 `_evaluate_required_courses`의 쿼리(`needs_review.is_(False)`)에서 걸러져 지금 당장 오판정을 내고 있진 않았다. 하지만 사람이 나중에 검토해서 `needs_review=false`로 바꾸는 순간 터지는 잠재 버그였고, 근본 원인이 명확해서 바로 고쳤다.

- `backend/app/domains/academics/graduation_engine.py`: `_evaluate_required_courses()`가 `matched_course_name`을 `"|"` 기준으로 쪼개 대체 과목 목록을 만들고, 그중 하나라도 학생이 이수했으면 충족으로 인정하도록 수정. 표시용 이름은 `" / "`로 join(파이프를 사용자에게 그대로 보여주지 않기 위함).
- `backend/tests/test_golden_data.py`에 `TC08_REQUIRED_COURSE_CHOICE_GROUP` 시나리오 추가 — "캡스톤디자인\|종합설계" 중 "종합설계"만 이수한 학생이 충족으로 판정되는지 검증.
- `backend/tests/run_golden_tests.py`: `RequirementCourse` import 추가, TC08 전용 `CS03` 요건세트/카테고리/선택형 필수과목 행 추가, 검증 루프에 `required_courses_completed`/`required_courses_missing` 체크 추가(기존 시나리오는 이 키가 없으면 그냥 스킵되므로 하위호환).
- 8개 시나리오 전부 통과 확인.
- **참고**: `_evaluate_required_courses`는 이번에 처음으로 골든테스트 커버리지가 생겼다 — 지금까지 이 함수는 테스트가 전혀 없었다.

## 남은 일

- **Supabase(팀 공유 DB)에는 아직 아무것도 실행 안 함.** 위 순서(`alembic upgrade head` -> `seed_departments` -> `import_course_catalog`, 필요시 `seed_academic_programs`/`seed_graduation_requirements` 최신 여부 확인)를 실제 DB에 한 번에 반영할지 사용자 승인 대기 중.
- 37개 학과 URL 조사 결과를 `raw_data/manual_staging/` 기존 구조에 반영.
- `requirement_courses` 중 `matched_course_code`가 있는데도 `courses`와 안 맞는 1,327건(폐강/구커리큘럼 코드로 추정) 원인 조사.
- 한문학과(`hanmun/6069`), 실내환경디자인학과(`hid/10663`) 페이지는 정적 크롤링으로 내용 확인이 안 돼 브라우저로 직접 확인 필요.
- 부전공/복수전공/연계전공/학생자율전공 프로그램(이번에 `departments`에서 뺀 17개 포함)의 실제 이수요건을 만들 계획이 생기면, `RequirementSet.program_type`으로 구분하는 기존 방식(EES융합전공 사례)을 따를 것 — `departments`/`academic_programs`에 이름만 먼저 넣지 말 것.
