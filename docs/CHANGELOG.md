# Changelog

바이브코딩 세션이 끝날 때마다 맨 위에 새 항목을 추가하세요. 형식은 아래 예시 참고.

"기능이 지금 어떻게 동작하는지"는 여기가 아니라 `docs/features/`에 기능별로 정리합니다.
이 파일은 "언제 무엇을 왜 했는지" 시간순 기록입니다.

<!--
## YYYY-MM-DD (github아이디)

- 무엇을 했는지, 왜 했는지, 막혔던 부분/해결법 (필요한 만큼만)
- 관련 기능 문서를 바꿨다면 `docs/features/xxx.md` 갱신도 같이
-->

## 2026-07-03 (hyunwoocho) #6

- 카탈로그 추정 데이터가 검토완료로 잘못 표시되던 문제 수정 + 원문 9개 학과 복구
  - 경제학부 데이터를 직접 확인하다가 "전공선택에 일반선택이 섞인 것 같다"는 지적을 받고 조사 — 학과 공식 졸업요건 문서가 아니라 수강편람 카탈로그의 교과목구분 태그를 그대로 가져다 쓴 `department_courses_from_catalog` 소스였음. 106개 학과·4,314개 과목 행이 이 소스였고(45개는 유일한 소스), 전부 `needs_review=false`(검토완료)로 잘못 표시돼 있었음
  - `build_graduation_requirement_seed_tables.py`: 이 소스는 무조건 `needs_review=true`로 강제하도록 수정. `needs_review=false` 4,631 -> 317건으로 정직하게 감소
  - 45개 카탈로그 전용 학과 중 11개는 로컬에 AIS 동적 위젯(부산대 여러 단과대가 쓰는 `fnctId=curriculum` 컴포넌트)이 크롤링 당시 빈 응답을 줘서 저장된 흔적이 있었음. 같은 요청을 재시도(최대 8회)하는 방식으로 9개 학과(경영학과/고고학과/무용학과/식품영양학과/아동가족학과/음악학과/의류학과/조경학과) 실제 원문 복구, 1개(조형학과)는 계속 실패
  - `requirement_courses` 14,374 -> 14,807
  - 상세: `docs/progress/graduation-requirements-supabase-seeding.md`

## 2026-07-03 (hyunwoocho) #5

- 졸업요건 판정 엔진에 학과 필터링 추가 (antigravity로 작업)
  - `_evaluate_categories()`가 `StudentCourseRecord.course_id` -> `Course.department_id`/`department`를 요건 세트의 학과와 비교해, 전공필수/전공선택/전공기초/심화전공 집계에서 다른 학과 과목을 제외하도록 수정. 전과/복수전공/부전공 학생의 과목이 서로 다른 전공 요건에 섞여 합산되던 문제를 고침
  - `backend/tests/test_golden_data.py` + `run_golden_tests.py`: 6개 시나리오 회귀 테스트 추가, 전부 통과 확인
  - `backend/tests/verify_calculation.py`: 컴공/수학 전필이 서로 안 섞이는지 보여주는 검증 스크립트
  - **한계**: `course_id`가 채워져 있을 때만 필터가 작동하는데, `courses`(수강편람 카탈로그) 테이블이 아직 비어있어 실제 학생 데이터는 매칭이 안 됨 — 로직/테스트는 맞지만 운영 환경에서는 아직 효과 없음. `backend/test_scenarios.py`(course_id 미설정)로 재현 가능
  - 테스트가 pytest 컨벤션이 아니라 스크립트 직접 실행이라 CI에 안 걸림 — 추후 개선 필요

## 2026-07-03 (hyunwoocho) #4

- 복수전공/부전공 요건을 학과 교육과정표 범례 마커(♤/◎ 등)에서 구조화 추출
  - 기존엔 운영규정 PDF 학점표가 있는 EES융합전공 1곳에만 복수전공/부전공 요건 데이터가 있었는데, 실제로는 32개 학과 교육과정표 자체에 "이 과목은 복수전공/부전공 필수"라는 범례 마커가 붙어있고 지금까지 이걸 버리고 있었음
  - `build_department_curriculum_structured_candidates.py`에 학과별 범례 파싱(`parse_legend`) + 마커 기호를 dual_major/minor 추가 후보로 뽑는 로직 추가
  - `build_graduation_requirement_seed_tables.py`: 운영규정 PDF 없이도 마커 증거만으로 dual/minor `requirement_sets`를 만드는 3번째 패스 추가, `program_type="dual_major"`가 DB 컨벤션 `"dual"`로 정규화되지 않던 버그 수정(기존엔 조용히 primary로 잘못 귀속됐을 것), 복수전공/부전공 카테고리 매핑 보강
  - `seed_graduation_requirements.py`: stale-row prune을 courses뿐 아니라 categories/text_rules에도 동일 적용
  - 결과: `requirement_sets` 153→196, dual/minor 요건 세트 2→45개(37개 학사 프로그램), dual/minor `requirement_courses` ~0→900건(matched 742)
  - 한계: 필수과목 목록만 있고 총 이수학점 기준은 아직 텍스트로만 있음 (`requirement_text_rules`), 판정 엔진 카테고리 체크에는 아직 못 씀
  - 상세: `docs/progress/graduation-requirements-supabase-seeding.md`

## 2026-07-03 (hyunwoocho) #3

- 과목코드-수강편람 카탈로그 대조 검증 (matched 11,500건 전수)
  - 코드 존재 여부는 100% 정상(구조적으로 보장됨). 학과 소속 정합성은 자동 검사로 1,841건이 의심됐지만 표본 확인 결과 대부분(90%+)은 "학부 요청분이 하위 전공 이름으로 카탈로그에 찍힌" 오탐이었음
  - **실제 버그 발견 및 수정**: 전기전자공학부 전기공학전공의 매칭 358건 중 8건만 실제 전기공학전공 소속이고 나머지는 무관한 학과 과목이었음. 원인 (1) `match_course()`가 학과명 접두어만 확인해서 "학부 전공"처럼 구체 전공명이 뒤에 붙는 접미어 패턴을 못 잡음 → 부분 문자열 포함 검사로 일반화, (2) 소스 폴더에 반도체융합전공(별도 연계전공) 안내자료가 잘못 섞여 있었음 → 제외 처리. 수정 후 68건이 정확히 재매칭됨
  - 나노소자첨단제조전공(지난 세션 대학원 오귀속)과 같은 패턴 — "소스 폴더에 새 파일 추가 시 대상 학과와 다른 전공명이 있는지 확인" 원칙을 문서화
  - 재시딩 결과: `requirement_courses` 14,401→13,837, ambiguous 1,048→792 (접미어 매칭 개선으로 다수 해소). 멱등성 확인
  - 상세: `docs/progress/graduation-requirements-supabase-seeding.md`

## 2026-07-03 (hyunwoocho) #2

- 남은 26개 미해결 학과(no_parsed_requirements_yet) 전수조사 + 직접 수집
  - 부산대 학과 홈페이지 원문 형식이 4가지로 완전히 달랐음: 정적 파일 다운로드 / 페이지에 표 내장 / 이미지(약학대학 이수체계도) / AIS 공용 동적 검색 위젯(무용·음악·조형학과)
  - AIS 동적 위젯의 실제 API를 리버스엔지니어링: `POST /ais/UNIV/{collegeCd}/getDeptInfoMajorList`로 전공코드 조회 후 `POST /curriculum/{siteId}/{fnctNo}/view.do`(`.do` 필수)로 실제 과목표 획득. 이 방식으로 무용학과 3개, 음악학과 4개, 조형학과 3개 전공을 정확히 수집
  - **위험한 오탐 발견**: 첨단융합학부 나노소자첨단제조전공의 기존 소스가 동명의 대학원 학과(`nanomecha`) 커리큘럼이었음. 짧은 과목코드(7자리)라 우연히 정규식에 안 걸려 seed엔 안 들어갔지만, 검색으로 찾은 소스는 "대학원/특론" 키워드 확인 후 써야 함을 확인. 올바른 학부 소스로 교체
  - 건축학과(5년제)/화공생명·환경공학부/디자인학과(시각디자인·애니메이션)/첨단융합학부(미래에너지·AI융합계산과학) 등도 정식 원문으로 보강
  - 교양학부(인문사회/공학/자연과학/의학/예체능계열)+기타모집단위 6개는 조사 결과 "학부대학 자유전공학부"의 계열별 모집단위로, 1학년 탐색 후 2학년에 전공 선택하는 구조라 애초에 자체 교육과정이 없음을 확인 (정상적으로 데이터 없음 처리)
  - 약학전공/제약학전공/약학부(통합6년제) 3개, 스마트가전공학과(2027 첫 모집)/디자인테크놀로지전공(2026 이관 예정) 2개는 원문을 못 찾거나 아직 공식 발표 전이라 미해결로 남음
  - 결과: `requirement_categories` 511→550, `requirement_courses` 13,851→14,401, `ready_for_human_review` 118/153→136/153, `no_parsed_requirements_yet` 26→9(그중 6개는 해당없음 확정)
  - 상세: `docs/progress/graduation-requirements-supabase-seeding.md`

## 2026-07-03 (hyunwoocho)

- 졸업요건 사람 검토 워크플로우 구축 + HWP 추출 방식 교체 + 학과 원문 직접 보강
  - `export_requirement_course_review_queue.py`(검토 대상 export) + `backend/seeds/requirement_course_corrections.csv`(검토 결과, git 버전관리) + `seed_graduation_requirements.py`가 매번 재시딩 시 corrections를 자동 반영하도록 연결. 재크롤링/재파싱을 다시 돌려도 사람 검토 결과가 유실되지 않음
  - stale-row prune 로직 추가: `requirement_course_id`가 매칭 결과를 포함한 해시라 매칭 로직 개선 시 해시가 바뀌는데, 재시딩할 때마다 DB를 최신 CSV와 정확히 동기화하도록 함
  - HWP 추출을 `textutil`/`strings` 폴백에서 `pyhwp`의 `hwp5html`로 교체 (HWP 소스 72개 전부 `extracted_partial`→`extracted`). `requirement_courses` 8,766→13,851, `requirement_categories` 493→511
  - 정보컴퓨터공학부 컴퓨터공학전공/인공지능전공: 기존 소스가 전부 공지사항이었던 걸 확인하고 학과 홈페이지에서 실제 2026 교육과정표(hwp) 재확보 (0건→1,054/1,042건)
  - Global Studies Program: 전용 사이트(pnudgs.com)에서 실제 교육과정표를 찾아 전공필수/전공기초 12과목을 `backend/seeds/requirement_course_supplemental.csv`로 수기 반영 (일반 파이프라인이 처리 못하는 rowspan 표/7자리 과목코드 형식이라 예외 처리)
  - 스마트가전공학과: 2027학년도 첫 신입생 모집 예정인 신설 계약학과로, 교육과정 자체가 아직 없음을 확인 (추측으로 채우지 않음)
  - 상세 수치와 남은 일: `docs/progress/graduation-requirements-supabase-seeding.md`

## 2026-07-02 (hyunwoocho)

- 졸업요건 판정 엔진 MVP 작성 + 가상 학생 시나리오 검증
  - `backend/app/domains/academics/graduation_engine.py` 신규 작성 (기존에는 모델만 있고 판정 로직 없었음)
  - 단일전공/전과/복수전공/부전공 등 7개 가상 학생 시나리오를 Supabase 실데이터에 대고 트랜잭션 rollback으로 검증
  - 발견한 구조적 한계: `student_course_records`가 어느 `user_academic_programs`에 속하는지 연결이 없어 전과 시 과목이 잘못 합산됨, 복수전공/부전공 요건 데이터가 151개 프로그램 중 1개(EES융합전공)에만 존재, `curriculum_year`가 전부 "2026"뿐이라 입학연도별 요건 미반영
- 학과별 교육과정 과목코드 추출 정규식 버그 수정 + 재시딩
  - `COURSE_CODE_RE`가 `Z[A-Z]z?\d{6}` 패턴도 과목코드로 인식해, "효원균형" 교양영역 표의 placeholder 라벨(예: `ZFz000091`)을 실제 과목코드로 잘못 추출하던 버그 수정 (`backend/scripts/build_department_curriculum_courses.py`, `backend/scripts/build_department_curriculum_structured_candidates.py`)
  - 실제 수강편람 과목코드는 항상 대문자 2~3자 + 숫자 7자리라는 사실을 확인 후 정규식을 `[A-Z]{2,3}\d{7}`로 단순화
  - 재실행 결과: `requirement_courses` 후보 9,082 -> 8,799행, unmatched 1,216(13.4%) -> 954(10.9%), needs_review=Y 4,451 -> 4,168행으로 감소. Supabase에서 잔여 placeholder 행 262개 직접 삭제
  - 남은 unmatched(954)의 상당수는 버그가 아니라 2023-2026 수강편람 크롤 범위 밖의 구(舊) 교육과정 과목코드로 확인됨 (`docs/progress/graduation-requirements-supabase-seeding.md` 참고)

## 2026-07-02 (hyunwoocho)

- 졸업요건 세부 테이블 추가 및 Supabase seed 반영
  - `requirement_categories`, `requirement_courses`, `requirement_text_rules` 모델/마이그레이션 추가
  - 학과별 파싱 자료, 수강편람, 교육과정 운영규정 PDF 기반 seed 후보를 `requirement_sets` 및 세부 테이블에 upsert
  - Supabase 검증 결과: `requirement_sets` 153개, `requirement_categories` 493개, `requirement_courses` 9,082개, `requirement_text_rules` 706개
  - 진행 상황과 남은 작업: `docs/progress/graduation-requirements-supabase-seeding.md`

## 2026-07-02 (hyunwoocho)

- 졸업요건용 학사 프로그램 마스터를 raw 실험 파일에서 백엔드 DB 구조로 승격
  - 회원가입 검증용 `departments`와 졸업요건 기준 `academic_programs`를 분리
  - `academic_programs`, `academic_program_aliases`, `department_academic_program_mappings` 모델/마이그레이션 추가
  - `UserAcademicProgram.academic_program_code`, `RequirementSet.academic_program_code` nullable FK 추가
  - 2026학년도 활성 학사 프로그램 151개와 별칭 1222개를 `backend/seeds/`로 이동
  - `scripts/seed_academic_programs.py`로 프로그램/별칭/department 매핑 upsert 가능하게 함
  - 상세 설계: `docs/features/graduation-academic-programs.md`
  - PR 본문 초안: `docs/pr-drafts/academic-programs-graduation-requirements.md`

## 2026-07-02 (d0won) - 11

- `Course.department_id`/`RequirementSet.department_id`를 `departments` 테이블 FK로 추가
  - 자유 텍스트 department 컬럼은 표시용으로 유지, 검증/조인은 FK 기준
  - 부전공/복수전공 요건은 별도 테이블 없이 `RequirementSet.program_type`("minor"/"dual")으로 표현
  - FK 연결만 하고 실제 졸업요건/과목 데이터는 채우지 않음 — 정식 학사요람 출처 없이 요건 내용(학점/필수과목)을 채우면 졸업 판단을 오도할 위험이 있어 보류

## 2026-07-02 (d0won) - 10

- 회원가입 시 학과/전공 정식 명칭 검증 (`departments` 테이블)
  - `department`, `academic_programs[].major`가 DB에 없는 값이면 400으로 회원가입 거부
  - `departments` 시드 데이터(163개)는 onestop 수강편람 크롤러로 2026-1학기 개설 과목의 개설 학과명을 모아 연구소/센터 등 비학사 조직 제외해 생성 (`backend/seeds/pnu_departments.json`, `scripts/seed_departments.py`)
  - 알려진 한계: 수강편람은 과목 개설 단위(대개 세부 전공)만 노출해서 상위 학부명(정보컴퓨터공학부, 전기전자공학부 등)이 누락되는 경우가 있었음 — 발견된 것만 수동 보강, 전체 16개 단과대학 전수 대조는 안 함

## 2026-07-02 (d0won) - 9

- 회원가입에 복수전공/부전공 입력 추가 (`SignupRequest.academic_programs`)
  - User 테이블에 컬럼 추가 대신 기존 `UserAcademicProgram` 테이블(One-Stop 크롤러용으로 이미 있던)을 재사용, 유저당 여러 행으로 저장
  - program_type은 primary/dual/minor/interdisciplinary만 허용
  - 추천 로직이 이미 유저의 모든 전공을 프로필에 반영하고 있어서 별도 연동 없이 바로 추천에 반영됨
  - `GET /auth/me` 응답에 academic_programs 목록 포함

## 2026-07-02 (d0won) - 8

- 이메일/비밀번호 로그인·회원가입 구현 (`app/api/auth.py`)
  - `POST /auth/signup`, `POST /auth/login`, `GET /auth/me`, 재사용 가능한 `get_current_user` 의존성
  - JWT(`python-jose`) 발급/검증, 만료 7일
  - 비밀번호 해싱은 `passlib[bcrypt]` 대신 `bcrypt` 직접 사용 — passlib이 최신 bcrypt(4.1+)와 호환이 깨져있어서 교체 (`requirements.txt` 반영)
  - `User` 모델에 이미 email/password_hash가 있어서 마이그레이션 불필요
  - 다른 기능 API(추천 등)는 아직 `user_id` 파라미터 방식 그대로, `get_current_user` 전환은 별도 작업

## 2026-07-02 (d0won) - 7

- 추천 기준 재조정: 신청기간 만료 필터 강화 + 최신성 가중치 강화
  - 마감일이 파싱된 공지는 11%뿐이라 나머지 89%는 마감이 지나도 계속 추천되던 문제 발견
  - 마감일 없는 공지는 게시일 45일 경과 시 만료로 간주해 제외 (현재 DB 154건 해당)
  - recency_weight를 선형 감쇠(90일 0.5)에서 지수 감쇠(반감기 30일, 최소 0.1)로 변경 — 최신 공지가 순위에 더 확실히 반영되도록
  - 평가 수치는 소폭 하락(P@10 0.583→0.567)했으나, judge가 관련성만 보고 최신성은 안 보기 때문 — 최신성 강화는 의도한 요구사항이라 트레이드오프로 받아들임

## 2026-07-02 (d0won) - 6

- 시설 운영/행정성 공지 제외 필터 추가 (`_is_excluded`, `activity_normalizer.py`)
  - 도서관 개관시간 변경, 학자금대출 안내 등 "활동"이 아닌 공지가 섞여있는 걸 발견해 크롤링 단계에서 제외
  - 부수적으로 카테고리 분류 버그도 수정: "대출" 키워드가 너무 넓어서 "학자금대출"까지 "도서관" 카테고리로 잘못 분류되고 있었음 → "도서 대출/반납"으로 한정
  - 기존 DB에서 11건 정리

## 2026-07-02 (d0won) - 5

- 사용자 프로필 확장(query expansion) + 블렌딩 임베딩
  - 프로필 원문만 임베딩하면 유사도가 진로 분야보다 "채용/모집 형식"에 끌리는 문제 대응
  - gpt-4o-mini로 프로필을 분야 키워드 15~20개로 확장 후 임베딩 (프로세스 내 캐시)
  - 확장 임베딩만 쓰면 코퍼스에 해당 분야 공지가 없는 경우(화학) 순위가 노이즈化 → 원본+확장 벡터 평균(블렌딩)으로 해결
  - 평가: mean P@10 0.55 → 0.583, mean nDCG@10 0.713 → 0.733 (IT 계열 P@10 0.9 도달)

## 2026-07-02 (d0won) - 4

- 출처 간(cross-source) 중복 공지 정리
  - pusan_main이 전문 게시판(job, pnucounsel) 공지를 재게시해 추천 top-10에 같은 공지가 두 번 노출되던 문제
  - dedup 그룹핑 키를 (source, title) → title로 확장, 유지 우선순위에 "임베딩 보유" 추가(매일 밤 재임베딩 순환 방지)
  - 평가 수치: mean P@10 0.533 → 0.55, mean nDCG@10 0.711 → 0.713

## 2026-07-02 (d0won) - 3

- 추천 정확도 오프라인 평가 도입 (`app/ai/evaluation/recommendation_eval.py`)
  - 가상 페르소나 6명 × LLM-as-judge(gpt-4o-mini) 채점 → Precision@10 / nDCG@10
  - 기준선: mean P@10 = 0.533, mean nDCG@10 = 0.711 (활동 458건)
  - 발견: 출처 간 동일 공지 중복 노출, 비IT 진로에서 무관한 취업 공지 혼입

## 2026-07-02 (d0won) - 2

- docs 구조 개편: 날짜별 작업 기록 → 단일 `CHANGELOG.md` + `docs/features/` 기능별 문서
  - `docs/features/`를 기술 모듈(크롤러/추천엔진) 대신 제품 기능 4가지로 재편: 비교과 활동 추천, 내 정보 페이지(졸업요건 확인), core(로그인/회원가입, 미구현), 성장 로드맵(미구현)
  - `backend-db-infra-architecture.md` → `docs/architecture.md`로 이름 정리
- 원본에서 내려간 공지 자동 정리 (`remove_stale_activities`)
  - 기존엔 upsert만 해서 원본에서 삭제된 공지가 DB에 계속 남는 문제 발견
  - 전체 삭제 후 재삽입은 매일 전체 재임베딩 비용 + 추천 캐시(FK) 소실 문제로 배제
  - 출처별로 이번 크롤에서 안 보인 URL만 90일 lookback 안에서 부분 삭제하도록 구현

## 2026-07-02 (d0won)

- 비교과 활동 임베딩 + 추천 파이프라인 구현 ([#21](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/21))
  - OpenAI `text-embedding-3-small`로 Activity/사용자 프로필 임베딩
  - 코사인 유사도 × career_goal 가중치(1.2배) × 최신성 가중치(90일 선형 감쇠)로 추천 점수 계산
  - `GET /activities/recommendations/{user_id}` API 추가
  - 자정 크롤 → 임베딩 생성 → 중복 정리 → 추천 재계산까지 스케줄러에 연결
- 크롤러 중복 공지 자동 정리 추가
  - 제목 80% 유사도만으로는 회차별/재모집 공고(예: 다른 은행 채용설명회)까지 지워질 위험 발견
  - 같은 출처 + 제목 완전 일치 + 게시일 3일 이내인 경우만 중복으로 판단하도록 조건 강화
- `UserActivityRecommendation`에 FK(`ondelete=CASCADE`) 추가 — 유저/활동 삭제 시 추천 레코드가 고아로 남는 문제 해결
- job 게시판 빈 제목 공지 크롤링 버그 조사 → 크롤러 버그가 아니라 원본 게시글이 텍스트 없이 이미지 배너만 있는 공지였음, 크롤링 단계에서 제외 처리
- Supabase 팀 공유 DB로 전환, `alembic upgrade head`로 스키마 적용

## 2026-07-01 (d0won)

- 비교과 활동 공지사항 크롤러 구현 ([#19](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/19))
  - 7개 공개 게시판(swedu/uitc/pnucounsel/ctl/pusan_main/lib/job) 4개 엔진 타입으로 크롤링, 90일 lookback 기준 878건 수집 확인
  - `Activity`/`UserActivityRecommendation` 모델, 카테고리·마감일 자동 파싱 normalizer
  - APScheduler로 매일 00:00 KST 자동 크롤
  - `my.pusan.ac.kr` 개인화 페이지는 로그인 필수라 포기하고 로그인 없이 접근 가능한 공개 게시판으로 방향 전환
  - `lib.pusan.ac.kr`은 Angular SPA라 정적 크롤링 불가 → Playwright로 네트워크 캡처해 내부 JSON API(Pyxis) 발견 후 직접 호출

## 2026-06-30 (d0won)

- FastAPI 프로젝트 골격 구축 ([#11](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/11))
- 부산대 One-Stop 포털 크롤러 구현 ([#12](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/12)) — 학적부/성적/졸업요건 추출
- 크롤러 raw 데이터 → DB 모델 매핑 ([#13](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/13))
- 백엔드 폴더 구조를 도메인 기반(`domains`/`ingestion`/`ai`/`api`/`core`)으로 정리 ([#14](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/14))
