# Changelog

바이브코딩 세션이 끝날 때마다 맨 위에 새 항목을 추가하세요. 형식은 아래 예시 참고.

"기능이 지금 어떻게 동작하는지"는 여기가 아니라 `docs/features/`에 기능별로 정리합니다.
이 파일은 "언제 무엇을 왜 했는지" 시간순 기록입니다.

## 2026-07-06 (hyunwoocho) #12

- 검토 백로그 이어서(과목명 매칭 743건 confirm) + minor/dual/contract 0건 세트 3개 원문으로 채움
  - 과목명 매칭 major_required/major_foundation 743건: 표본 30건 검사(전부 raw_course_name=
    matched_course_name 완전 일치, 퍼지매칭 아님) 후 confirm. `needs_review=false` 4,322 ->
    5,065건, primary 148개 중 검토완료 학과 109 -> 128개
  - 전기공학전공 minor(0건 -> 3건): 기존 primary 66건에 쓴 동일 PDF의 범례 마커 ◎(부전공필수)
    3과목(전자기학(II)/전기회로(II)/기초전기전자실험, 8학점) 확인. 원문: "부전공 이수하려면
    ◎표시 과목 포함 전공 21학점"
  - EES융합전공 minor+dual(각 0건 -> 41건): 과거 세션에 "학점요약표뿐"으로 판단했던 게시판
    첨부 HWP를 재확인하니 실제로 41개 과목이 초급/중급/고급 tier로 전부 나열돼 있었음. 특정
    과목이 개별 필수가 아니라 "부전공 21학점(중/고급 9학점 포함)"/"복수전공 42학점(중/고급
    18학점 포함, 평점평균 3.5+)" 같은 학점+tier 기준 메뉴 구조라 major_elective/
    general_elective_area로 등록, 학점 규칙은 note에 텍스트로 보존(RequirementTextRule 수기
    보강 경로는 아직 없어서 추후 과제)
  - 조선・해양공학과 계약학과(0건 -> 65건): "전공교과소개" 탭은 졸업기준학점 요약표뿐이었지만,
    학부공지사항 게시판의 "2026년 신입생 수강지도 안내" PDF에 전체 교육과정표가 있었음.
    전공기초10/필수21/선택34건, 전공필수 학점 합계가 원문에 명시된 47과 정확히 일치해 전사
    정확성 검증됨
  - **발전공학과 계약학과는 못 찾음**: 공식 사이트 `meindustry.org`가 도메인 만료 후 도박
    스팸사이트로 넘어감. Wayback Machine에 학과소개 페이지 4개는 있지만 정확히 필요한
    "교육과정표" 페이지는 한 번도 크롤링된 적이 없어 복구 불가 — 브라우저 직접 탐색이나
    사용자가 원문을 알고 있어야 진행 가능
  - 버그 수정 관련 엔진 변경 없음(이번 배치는 전부 데이터/confirm 작업). 골든테스트 8개 매번
    재통과
  - 남은 zero-row 요건세트: 발전공학과(미해결) + 스마트가전공학과(2027 신설, 확정된 공백 —
    액션 불필요) 뿐

## 2026-07-06 (hyunwoocho) #11

- 사람 검토 백로그("확정 아닌 것들") 착수 — 버그 2개 발견/수정 + 고신뢰 데이터 2,999건 confirm
  - **버그 발견 1**: `_supplemental_course_values()`가 `needs_review`를 무조건 True로 하드코딩해서,
    `requirement_course_corrections.csv`로 confirm/fix/drop하는 사람 검토 워크플로우가 수기 전사
    데이터(`requirement_course_supplemental`, 1099건, #8~#10에서 실제 공식 문서 읽고 채운 것)에는
    전혀 적용이 안 되고 있었음 — 원문을 찾아 채워도 판정 엔진(`needs_review=false`만 씀)엔 반영 안 됨.
    corrections 워크플로우를 이 경로에도 적용하도록 수정 + 1057건 confirm(한문학과 원문 자체의
    과목코드 중복 오류 2건, 실내환경디자인학과 학년/학기 정보 없는 40건은 제외)
  - **버그 발견 2**: `_evaluate_required_courses()`가 category_code를 전혀 안 가리고 confirm된 행을
    전부 "특정 과목을 반드시 이수"로 취급하고 있었음 — `curriculum_course_candidates` 고신뢰 후보
    2,442건을 confirm하는 과정에서 그 중 1,259건이 전공선택/일반선택처럼 메뉴에서 학점만 채우면
    되는 이수구분이라, 그대로 뒀으면 학생이 다른 선택과목을 들었어도 "미이수"로 오판정할 뻔했음.
    `MANDATORY_COURSE_CATEGORIES`(major_required/major_foundation/general_required/teacher_training)
    필터 추가로 수정
  - **버그 발견 3**: `infer_requirement_category()`가 "교양필수"/"교양선택"이라는 문구 자체가 표에
    있어야만 인식하는데, 실제 부산대 교육과정표는 "효원핵심교양"/"효원균형교양"/"효원창의교양"
    브랜딩된 명칭만 쓰는 경우가 대부분이라 이 흔한 패턴이 전부 category_code=unknown으로 빠지고
    있었음(컴퓨터공학전공 등 여러 학과에 집중). 패턴 추가 후 raw_data 파이프라인 재실행 —
    재시딩 전 needs_review=false였던 3,822건이 ID 단위로 전부 그대로 유지됨을 확인(유실/재검토
    전환 0건), 새로 분류된 general_required/general_elective_area 중 매칭된 500건 추가 confirm
  - 매 단계 무작위 표본검사(25건)로 학과-과목 정합성 확인 후 진행, 골든테스트 8개 매번 재통과
  - 결과: `needs_review=false` 323 -> **4,322건**(13.3배), primary 148개 중 검토완료 데이터가
    있는 학과 4 -> **109개**. 노어노문학과/컴퓨터공학전공으로 `_evaluate_required_courses` 실제
    동작 검증(과거엔 no_data 또는 전공선택까지 오판정 대상 -> 이제 전공기초/필수만 정확히 판정)
  - 남은 backlog(각각 다른 방식 필요, 손 안 댐): `department_courses_from_catalog` 4,308건(원문
    자체가 카탈로그 추정이라 원칙상 계속 검토 상태 유지), 과목명 매칭 major_* 3,175건(표본검사
    필요), ambiguous 925+172건/unmatched 1,803+24건(매칭 자체 불확실, 케이스별 조사 필요), 범례
    기호 기반 복수전공/부전공 후보 671건, `department_curriculum_courses` 101건(파서가 택1 선택
    규칙 자체를 애매하다고 플래그한 것 — 제 전사가 맞는지가 아니라 파서의 선택규칙 해석이 맞는지
    봐야 하는 별개 문제)

## 2026-07-06 (hyunwoocho) #10

- 카탈로그 추정만 있던 primary 학과 마지막 3개 해결 — "카탈로그 추정 전용 primary 학과" 이슈 완전 종결 (141건)
  - "남은 학과도 마무리 짓자"는 지시로, #9에서 "브라우저 직접 접근 필요"로 보류했던 마지막 3개(사회기반시스템공학과/분자생물학과/실내환경디자인학과)를 이어서 처리. Chrome 브라우저 도구를 다시 시도했으나 이번에도 연결 안 됨 — 대신 curl만으로 전부 해결함
  - **사회기반시스템공학과(57건)·분자생물학과(44건)**: AIS `fnctId=curriculum` 위젯이 정적 POST에 계속 빈 응답을 준 이유는 폼의 `findUnivCd`/`findDeptCd` 히든 select가 JS로만 채워지는 값이었기 때문. 알고 보니 `backend/scripts/recover_ais_widget_curriculum.py`에 이 위젯을 리버스엔지니어링한 API가 이미 문서화돼 있었음(#2에서 무용학과/음악학과/조형학과 복구할 때 만든 것) — `POST /ais/getDeptInfoDeptList`로 단과대학 코드, `POST /ais/UNIV/{collegeCd}/getDeptInfoMajorList`로 학과 코드를 직접 조회한 뒤 `POST /curriculum/{siteId}/{fnctNo}/view.do`에 넘기면 실제 데이터가 나옴. "브라우저 필요"라고 판단했던 건 기존 스크립트를 먼저 찾아보지 않았던 탓
  - **실내환경디자인학과(40건)**: 게시판 첨부 PDF는 여전히 L7 보안필터에 차단되지만, 학과 사이트 nav에 별도로 있던 "상세과목소개" 탭(`hid/10663`)에 과목코드/과목명/학점/이수구분이 plain HTML로 노출돼 있어서 파싱. **한계**: 이 페이지는 학년/학기 배치가 없는 과목 설명 목록이라 `recommended_year`/`recommended_semester`는 공란 처리 — 다른 학과들처럼 완전한 연도별 표는 아님
  - 카탈로그 추정뿐인 primary 학과 6개(경제학부/스마트시티전공/치의예과 + 위 3개) -> **3개**로 감소, 그 3개는 전부 원문 자체가 없는 것으로 이미 확정된 공백이라 실질적으로 **0건 남음**. `requirement_courses` 16,620 -> 16,761. 매번 골든테스트 8개 재통과 확인
  - 남은 건 Supabase 재동기화뿐 — 마지막 배포 이후 노어노문학과부터 지금까지 638+141건 전부 로컬/git에만 있음 (사용자 확인 대기 중)

## 2026-07-06 (hyunwoocho) #9

- 카탈로그 추정만 있던 primary 학과 13개 추가 해결 (#8 이후 이어서, 638건)
  - "이어서 하자"는 지시로 #8에서 남은 19개(카탈로그 추정뿐인 primary 학과)를 한 개씩 원문 확인 → 수기 전사 → 재시딩 → 골든테스트 → 커밋 순서로 계속 처리. 13개 완료: 국제학부(pnudgs.com DGS 탭, 50건)/한국·동아시아학전공(같은 사이트 KEASP 탭, 31건)/사회학과(게시글 본문 이미지 7장, 48건)/조형학과(표에 과목번호 자체가 없어 이름만으로 50건, `raw_course_code` 공란)/수학교육과(게시판 HWP, 38건)/항공우주공학과(PDF, 61건)/의생명공학전공+데이터사이언스전공(같은 학부 공통 HWP를 두 전공에 동일 반영, 각 11건 — 3·4학년 세부전공은 미반영 상태로 남음)/미디어커뮤니케이션학과(게시글 본문이 `<table>`이 아니라 일반 HTML 텍스트라 정규식으로 직접 파싱, 52건)/의학과(학과 사이트 상단 탭 "교육과정"에 표가 있었음, 139건)/국어교육과(discovered 폴더가 크롤러 버그로 완전히 다른 학과 내용이라 게시판에서 원문 재탐색, HWP로 위장된 첨부파일 발견, 40건)/재료공학부(국어교육과와 동일한 크롤러 버그, 게시판 최신 PDF 재탐색 — 이번엔 예외적으로 `pdftotext -layout`이 표를 깔끔히 읽어냄, 69건)/식품자원경제학과(discovered엔 행정서식뿐이었지만 학과 nav에 직접 "교육과정" 메뉴가 있었음, 38건 — 원문 표 자체에 과목번호 오타 1건 있어 뒤쪽 교과요목 설명으로 대조 후 수정)
  - 카탈로그 추정뿐인 primary 학과 19개 -> **6개**로 감소(경제학부/스마트시티전공/치의예과는 기존에 이미 "원문 자체가 없는 확정된 공백"으로 확인 종결된 건이라 실질 액션 필요 학과는 3개만 남음). 매 학과마다 골든테스트 8개 재통과 확인, `requirement_courses` 16,334 -> 16,620
  - 남은 3개는 전부 curl로는 못 뚫는 블로커: 사회기반시스템공학과(AIS `fnctId=curriculum` 위젯이 모든 연도에 빈 응답 — 학과 폼에 `findUnivCd`/`findDeptCd` 같은 JS로만 채워지는 히든 필드가 있어서 정적 요청으론 값을 못 채움), 분자생물학과(같은 AIS 위젯이 전부 연도 빈 응답인 데다, 대체 경로로 찾은 게시판 글도 "접근 권한이 없습니다" — Referer/쿠키를 흉내내도 안 뚫림), 실내환경디자인학과(L7 보안필터 차단, #8에서 이미 확인된 것과 동일) — 셋 다 이번 세션에서 시도한 Chrome 브라우저 도구가 연결 안 돼 있어서 브라우저 기반 접근도 못 함. 사람이 직접 브라우저로 접근해서 자료를 받아줘야 진행 가능
  - Supabase에는 아직 미반영(로컬 검증만 완료, 이번 배치 638건 포함) — 상세: `local.md`(개인 노트, 미커밋)

## 2026-07-05 (hyunwoocho) #8

- 카탈로그 추정만 있던 primary 학과 5개에 공식 원문 데이터 반영
  - "primary+0건" gap 12개를 다 닫았다고 확인했는데, 사용자가 "공식 학과 원문 다 뽑으라고 했잖아"라고 지적해서 재확인 — 행이 있어도 전부 `department_courses_from_catalog`(수강편람 카탈로그 태그 추정, 학과 공식 문서 아님) 소스뿐인 primary 학과가 **24개** 더 있었음. "0건 gap"보다 실질적으로 더 큰 문제(데이터가 있어 보이지만 전부 신뢰 불가)였는데 처음엔 놓쳤던 부분
  - 학과 홈페이지 원문을 직접 찾아 읽어서 5개 반영: 노어노문학과(PDF, 42건)/일어일문학과(PDF, 33건)/환경공학과(게시글 첨부 PDF가 다운로드 자체가 안 돼있어서 curl로 받음, 55건)/불어불문학과(최신 "2026학년도 1차" PDF, 31건 추가)/사회복지학과(게시글 첨부파일 없고 본문 이미지 2장으로 표가 있어서 이미지 다운로드해서 읽음, 42건)
  - 전부 `pdftotext` 자동 추출은 0건이었던 것들 — `Read` 툴(멀티모달)로 PDF/이미지를 직접 읽으면 표를 정확히 읽어낼 수 있다는 걸 다시 확인함(한문학과/전기공학전공 때와 동일한 패턴)
  - 카탈로그 추정뿐인 primary 학과 24개 -> 19개로 감소. 골든테스트 8개 재통과
  - 남은 19개 중 일부는 이번엔 못 뚫음: 실내환경디자인학과(학과 사이트 다운로드가 L7 보안필터에 차단됨, 브라우저 직접 접근 필요), 사회기반시스템공학과(AIS `fnctId=curriculum` 위젯이 어느 연도로 조회해도 빈 응답), 국어교육과·재료공학부(크롤러가 완전히 다른 학과 페이지를 저장해놓은 별도 버그 발견, 원문 재탐색 필요)
  - 경제학부는 의도적으로 스킵 — 펜토미노 모듈/트랙 구조라 이전 세션에 "핵심 필수 6과목만 확인, 나머지 트랙별 전공선택은 판정에 불필요"로 이미 사용자 확인 완료된 건이라 추가 작업 안 함
  - Supabase에는 아직 미반영(로컬 검증만 완료) — 상세: `local.md`(개인 노트, 미커밋)

## 2026-07-05 (hyunwoocho) #7

- 수강편람 -> `courses` 테이블 적재 파이프라인 신설 + `departments` seed 163 -> 201개로 확장
  - `courses`가 계속 비어있어서 졸업요건 엔진의 학과 필터링 로직이 실데이터로 검증된 적이 없었음(2026-07-03 #5/#6 한계). `raw_data/crawled_data/onestop_course_catalog/`(17개 학기, 이미 크롤링돼 있었음)를 course_code 기준으로 dedup해서 적재하는 `app/ingestion/csv_importers/course_catalog_importer.py` + `scripts/import_course_catalog.py` 작성. 시간표/분반/교수 등 학기별 개설 정보는 이번엔 안 다룸(과목명/학점은 전수 확인상 학기별 drift 0건이라 마스터 하나면 충분, 개설 단위 정보는 나중에 시간표 기능 만들 때 같은 원본에서 별도로 다루기로 함)
  - `courses.course_code`에 unique 제약 추가(`migrations/versions/a1c47e0f9d52_...`) — 기존엔 non-unique라 재실행 시 중복 쌓이는 문제가 있었음
  - `departments` seed(`backend/seeds/pnu_departments.json`)가 낡아서 매칭 실패가 많았음 — 수강편람 실제 개설 이력, 사용자가 준 전학과 졸업이수학점 요건표, 「부산대학교 교육과정 편성 및 운영규정」 원문(47페이지) 3단계로 대조해서 163 -> 201개로 확장. "그린바이오과학전공"과 "그린바이오융합전공"이 서로 다른 실재 프로그램이라는 것 등 확인
  - **자체 검수 후 재조정**: 201개 중 17개가 사실 "최소전공을 구성하지 않는" 연계전공/학생자율전공/부전공전용 융합전공(별표2-2, 별표2-4)이었음 — 회원가입 학과 검증용인 `departments`엔 안 맞아서 제거, 184개로 정리. 제거 전 `courses.department_id` 참조 0건 확인. `seed_departments.py`가 insert-only(`on_conflict_do_nothing`)라 JSON에서 지워도 이미 seed된 DB에선 안 지워진다는 것도 확인 — 로컬 DB는 직접 DELETE로 정리함. 상세: `docs/progress/course-catalog-import-and-department-coverage.md` "5) 검수" 절
  - 자체 검수 중 추가로 확인: 같은 학기에 course_code 하나가 여러 학과로 동시 개설되는 케이스 27건(교직과목/공학교육인증 공통과목) — 다행히 졸업판정 로직은 전공 카테고리일 때만 학과를 비교해서 지금은 영향 없음. course_code=course_name 안정성은 규정 제3조③으로 보장되는 걸 확인했지만 credits drift 감지 로직은 없음(지금 데이터엔 0건). stem 매칭 fallback은 실제 활성화된 4쌍 전부 수동 검증 완료
  - **버그 수정**: `graduation_engine.py`의 `_evaluate_required_courses()`가 선택형(택1) 필수과목("캡스톤디자인\|종합설계"처럼 파이프로 여러 대체 과목이 묶인 행)을 문자열 그대로 비교해서 학생이 뭘 들었든 항상 "미이수"로 판정하는 버그 발견 및 수정 — 경영학과 요건표 확인하다가 발견함. 파이프로 쪼개서 대체 과목 중 하나라도 이수하면 충족으로 인정하도록 고침. 지금 데이터(경영학과 6건)는 전부 `needs_review=true`라 실제 오판정을 내고 있진 않았지만(잠재 버그), 사람이 검토해서 `needs_review=false`로 바꾸는 순간 터질 뻔했음. `test_golden_data.py`/`run_golden_tests.py`에 TC08 추가 — 이 함수는 이번에 처음 테스트 커버리지가 생김
  - `infra/docker/compose.local.yml` 신설 — `.env`의 `DATABASE_URL`이 팀 공유 Supabase를 직접 가리키므로, 마이그레이션/대량 적재를 로컬 Postgres에서 끝까지 검증한 뒤 한 번에 반영하는 걸 원칙으로 함(`CLAUDE.md`에도 명시)
  - 로컬 검증 결과: `courses` 6,617행(idempotent 확인), 학과 매칭 94.5%, `requirement_courses.matched_course_code` 13,176건 중 11,849건(89.9%)이 처음으로 실제 `courses`와 조인됨(이전 0건). 골든테스트 7개 전부 통과
  - ~~Supabase(팀 공유 DB)엔 아직 미반영~~ **2026-07-05 반영 완료** — 아래 마지막 항목 참고
- `requirement_sets`(primary) 중 과목 행이 0건이던 12개 gap 전부 해소/확인 종결
  - 사용자가 실제 학과 홈페이지 원문(URL/HWP/PDF)을 직접 찾아 하나씩 제공 — 전기전자공학부 전기공학전공(PDF 자동파싱 실패해서 수기 66건), 정보컴퓨터공학부 디자인테크놀로지전공(HWP 자동 89건), 약학전공/제약학전공(교육과정표 페이지로 재발견 후 각 39/36건), 지능형헬스사이언스융합전공(HWP 자동 85건)까지 5개를 실제 데이터로 채움
  - 나머지 7개(교양학부 5종 + 기타모집단위 + 약학부 통합6년제 wrapper)는 규정/스키마상 원래 별도 커리큘럼이 없는 게 정상인 단위로 확인 종결(액션 불필요)
  - 재생성 파이프라인(`build_department_curriculum_structured_candidates.py` -> `build_graduation_requirement_seed_tables.py` -> `seed_graduation_requirements.py`)을 이 세션에서 여러 번 반복 실행하면서, `backend/seeds/requirement_course_supplemental.csv`/`requirement_course_corrections.csv`의 수기 데이터가 raw_data 재생성에도 안 지워진다는 설계가 실제로 계속 검증됨. 골든테스트 8개(TC08 포함) 매번 재통과
  - 덤으로 핀테크융합전공(HWP가 기존 HTML 소스보다 풍부, 20->153건 primary), EES융합전공(HWP는 참고자료용, 변화 없음) 확인
  - 스코프 밖(151개 활성 프로그램 인덱스에 없는) 순수 부전공/복수전공 전용 융합전공 4개(미래자동차/의료인공지능/디지털헬스케어/반도체) 원문 파일은 `raw_data/manual_staging/01_graduation_requirements/_unscoped_convergence_majors/`에 보관만 해두고 편입 여부는 보류 — 사용자 확인 필요
  - 상세: `raw_data/WORKLOG_department_curriculum_collection.md` "2026-07-05 업데이트 (4)~(7)"
- **버그 수정**: minor/dual 요건세트 51개 중 24개가 과목 0건이던 원인이 대부분 실제 데이터 부재가 아니라 파이프라인 버그였음
  - `build_graduation_requirement_seed_tables.py`의 `build_course_rows()`가 minor/dual 후보를 `(code, program_type, curriculum_year)`로 못 찾으면 무조건 `(code, "primary", "2026")`로 폴백하던 버그. minor/dual 요건세트는 항상 `curriculum_year="2026"`으로 생성되는데 후보 행 자체 연도는 원문 표지 연도(2023/2024 등) 그대로라 1차 매치가 항상 실패해서, **minor/dual 과목이 통째로 primary 요건세트에 잘못 붙고 있었음**(중어중문학과 primary 세트에 `program_type='minor'` 12건이 숨어있는 것까지 확인). 폴백을 `(code, program_type, "2026")`로 수정 → 24개 중 19개가 실제 데이터로 채워짐(독어독문학과/경영학과/사회복지학과/생물교육과/유기소재시스템공학과/원예생명과학과/통계학과/물리학과/중어중문학과/유아교육과/사회기반시스템공학과/산업공학과/미생물학과/분자생물학과/식품공학과/실내환경디자인학과/음악학과 3전공)
  - 이 과정에서 별개의 콘텐츠 오염도 발견: 전기공학전공 폴더에 남아있던 반도체융합전공 안내 HWP 2개가 만드는 후보 375건 중 372건이 실은 반도체융합전공 문서 내용이 전기공학전공에 잘못 태깅된 것이었음. 파일을 `_unscoped_convergence_majors/`로 이동 → 전기공학전공 primary가 314 -> **66건으로 정정**(퇴보 아니라 교정 — 248건이 오염분이었고 진짜 데이터는 원래 66건)
  - 골든테스트 8개 재통과, primary+0 gap 7개로 회귀 없음 확인. 남은 것: 계약학과 3개(스마트가전공학과/조선・해양공학과/발전공학과), EES융합전공 dual/minor는 아직 원문 미확보
  - 상세: `raw_data/WORKLOG_department_curriculum_collection.md` "2026-07-05 업데이트 (8)"
- 위 변경사항 전부 Supabase(팀 공유 DB)에 반영 완료
  - `backend/.env`의 `DATABASE_URL`(direct connection, `db.<project>.supabase.co`)이 IPv6(AAAA)만 있고 IPv4(A) 레코드가 없어서 이 작업 환경(IPv6 라우팅 없음)에서 접속 자체가 안 됐음. Supabase 대시보드의 Transaction pooler 연결 정보(`aws-1-ap-northeast-2.pooler.supabase.com:6543`)로 우회해서 반영 — `.env` 자체는 안 바꿈, 이번 실행에만 환경변수로 넘김
  - 순서: `alembic upgrade head`(8f4c1d7b2a90 -> a1c47e0f9d52) → `seed_departments` → `import_course_catalog` → `seed_academic_programs` → `seed_graduation_requirements`, 반영 후 로컬 검증값과 전부 일치 확인(`departments` 184, `courses` 6,617, `requirement_sets` 201[primary 148·minor 31·dual 19·contract 3], `requirement_courses` 15,779, `needs_review=false` 323건). 골든테스트 8개 재통과
  - `.env`를 pooler로 영구 전환할지는 별도 결정 필요 — transaction-mode pooler는 prepared statement/세션 상태를 커넥션 간 공유하지 않아 앱 런타임에 쓰려면 SQLAlchemy 커넥션 풀 설정을 같이 점검해야 함(이번 마이그레이션/시딩 스크립트에서는 문제 없었음)

## 2026-07-03 (hyunwoocho) #6

- 졸업요건 판정 엔진: 타학과 과목은 일반선택으로 재분류
  - `_evaluate_categories()`가 다른 학과 과목을 전공필수/선택 집계에서 "제외"만 하고 있었는데, 그러면 학점 자체가 사라지는 문제가 있었음(타학과 과목도 보통 일반선택으로는 인정됨). 제외 대신 `free_elective`(일반선택)로 재분류해서 합산하도록 수정
  - `backend/tests/test_golden_data.py`에 TC07 시나리오 추가(전용 검증), `run_golden_tests.py`에 TC07용 별도 요건세트(CS02) 추가 — 기존 CS01 시나리오들에 영향 안 주도록 분리. 7개 시나리오 전부 통과
  - 여전히 `course_id`가 채워져 있을 때만 작동 (courses 테이블이 비어있어 운영 환경 미적용은 그대로)

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

## 2026-07-02 (d0won) - 12

- 프론트엔드 연동 가이드 문서 추가 (`docs/frontend-api-guide.md`) — 지금 동작하는 API(회원가입/로그인/내정보/추천)만 요청·응답·에러 예시로 정리. 팀 검토 전이라 PR 머지는 보류 중
- 문서 작성 중 버그 발견 및 수정: `GET /activities/recommendations/{user_id}`에 존재하지 않는 user_id를 넣으면 404가 아니라 처리 안 된 500이 나던 문제 — 유저 존재 여부를 먼저 확인하도록 수정

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
