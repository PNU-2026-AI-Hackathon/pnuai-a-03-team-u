# 부산대 One-Stop 포털 크롤러

사용자의 One-Stop 포털(`onestop.pusan.ac.kr`) 계정으로 로그인해 학적부/성적/졸업요건을
가져와 DB 모델로 매핑한다. Playwright 기반이며 사용자 본인 계정으로만 동작한다.

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

## 알려진 한계 / TODO

- FastAPI 라우터로 노출되지 않음 (아직 API 엔드포인트 없음, 스크립트로만 실행 가능)
- 백그라운드 작업화 안 됨
- 사용자별 자격증명 입력 플로우(회원가입/설정 화면 연동) 없음
- `graduation_engine`(`domains/academics`)의 실제 판정 로직은 요건 규칙 시드 데이터가 필요해 미구현
