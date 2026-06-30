# Backend 진행 상황 (2026-06-30 기준)

각자 바이브코딩 하기 전에 이 폴더를 먼저 읽어주세요. 이미 만들어진 걸 중복으로
다시 만들지 않기 위한 참고 문서입니다.

설계 원칙/스키마 전체는 [docs/backend-db-infra-architecture.md](../backend-db-infra-architecture.md)를
먼저 보세요. 이 문서는 "그 설계 중 실제로 뭘 구현했는지"를 기록합니다.

## 현재 PR 상태

| PR | 내용 | 상태 |
|----|------|------|
| [#11](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/11) | FastAPI 프로젝트 골격 | Merged |
| [#12](https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/pull/12) | PNU 포털 크롤러 + DB 매핑 | Open (리뷰 대기) |

## 1. FastAPI 프로젝트 골격

- [`backend/app/main.py`](../../backend/app/main.py) — 앱 엔트리포인트, `/health`
- [`backend/app/core/config.py`](../../backend/app/core/config.py) — `pydantic-settings` 기반 환경변수
- [`backend/app/core/db.py`](../../backend/app/core/db.py) — SQLAlchemy `Base`, `TimestampMixin`, `get_db()`
- `backend/migrations/` — Alembic 초기화, `env.py`가 모든 도메인 모델을 import해 `Base.metadata`에 등록
- 도메인 폴더 전부 `__init__.py`로 실제 패키지화 완료 (`academic_profile`, `course_catalog`, `curriculum`, `graduation_engine`, `identity`, `llm`, `rag`, `recommendation`, `data_ingestion/*`)

실행:
```bash
cd backend
source .venv/bin/activate
.venv/bin/uvicorn app.main:app --reload
```
(`.venv/bin/python`처럼 venv 경로를 직접 써야 함 — zsh alias가 `python`을 시스템 파이썬으로 가로챔)

## 2. PNU One-Stop 포털 크롤러

위치: `backend/app/data_ingestion/crawlers/`

| 파일 | 역할 |
|------|------|
| `pnu_session.py` | 로그인 + 메뉴 이동 (`login()`, `goto_menu()`, `pnu_session()` 컨텍스트매니저) |
| `menu_codes.py` | `menuCD` 상수 (학적부, 성적, 졸업요건, 수강편람 등) |
| `table_extract.py` | 페이지 내 `<table>` 범용 추출 + `.b-row-item` 구조 추출 |
| `student_info.py` | 학적부 기본정보 |
| `grades.py` | 금학기/전체 성적 |
| `graduation.py` | 졸업요건 충족여부 |

### 로그인 흐름에서 막혔던 부분 (다시 겪지 않도록 기록)

1. 로그인 레이어를 열어도 기본 활성 탭이 "스마트 로그인"이라 `#login_id`가 안 보임
   → `#idpwTab > a`를 먼저 클릭해야 함 (애니메이션 대기 필요, `wait_for_timeout(500)`)
2. 비밀번호 변경 주기가 지난 계정은 로그인 직후 `UpdatePassword` 페이지로 리다이렉트됨
   → "다음에 변경하기" 링크는 `href="javascript:onclick=changeNextPw();"` 형태라 클릭이 아니라
   `page.evaluate("changeNextPw()")`로 직접 호출해야 함
3. `selectMenu('menuCD')`는 AJAX가 아니라 실제 페이지 네비게이션
   → `page.expect_navigation()`으로 감싸야 함 (안 그러면 "Execution context was destroyed" 에러)
4. 학적부 기본정보(학번/이름/소속학과 등)는 `<table>`이 아니라
   `.b-row-item` > `.b-title-box`(라벨) + `.b-con-box`(값) 구조
   → `table_extract.extract_row_items()` 사용

### 사용 예시

```python
from app.data_ingestion.crawlers.pnu_session import pnu_session
from app.data_ingestion.crawlers.student_info import fetch_student_record
from app.data_ingestion.crawlers.graduation import fetch_graduation_requirement
from app.data_ingestion.crawlers.grades import fetch_all_grades

with pnu_session() as page:  # .env의 PNU_LOGIN_ID / PNU_LOGIN_PW 사용
    student = fetch_student_record(page)
    requirement = fetch_graduation_requirement(page)
    grades = fetch_all_grades(page)
```

### 실제 검증 완료 항목

본인 계정(202355699)으로 학적부 / 졸업요건 / 전체성적 3개 모두 실제 데이터 추출 확인함.

### 아직 안 한 것

- 비교과 활동 (`my.pusan.ac.kr`) 크롤러 — 미구현
- FastAPI 라우터로 노출 (지금은 standalone 함수만 있음)
- 비동기/백그라운드 실행 (Playwright 크롤링은 몇 초 걸리므로 API 요청을 막으면 안 됨)
- 사용자별 자격증명 입력 플로우 (지금은 `.env` 전역 값 하나로만 테스트)

## 3. DB 모델 & 크롤러 → DB 매핑

`docs/backend-db-infra-architecture.md`에서 설계한 스키마 중, 크롤러가 실제로
가져오는 데이터에 대응하는 부분만 우선 구현함.

| 모델 | 파일 | 비고 |
|------|------|------|
| `User` | `app/identity/models.py` | 이메일/이름/학번/소속학과 |
| `PortalCredential` | `app/identity/models.py` | 학교 포털 ID/PW — **비밀번호는 암호화 저장** |
| `UserAcademicProgram` | `app/academic_profile/models.py` | 주전공/복수전공/부전공 등 |
| `StudentCourseRecord` | `app/academic_profile/models.py` | 이수 과목 기록 |
| `Course` | `app/course_catalog/models.py` | FK 대상 최소 모델 (수강편람 크롤러 붙을 때 채워질 예정) |
| `RequirementSet` | `app/curriculum/models.py` | FK 대상 최소 모델 (졸업요건 규칙은 아직 시드 데이터 없음) |
| `GraduationAudit` | `app/graduation_engine/models.py` | 크롤링한 졸업요건 원본을 `summary_json`에 스냅샷으로 보관 |

### 비밀번호 저장 방식 (중요)

학교 포털 비밀번호는 **절대 평문 저장하지 않음**. `app/core/security.py`의
Fernet 기반 `encrypt_secret()` / `decrypt_secret()`으로 암호화해서
`PortalCredential.encrypted_password`에 저장.

- `.env`에 `CREDENTIAL_ENCRYPTION_KEY` 필요
- 키 생성: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- 이 키를 잃어버리면 이미 저장된 비밀번호는 복호화 불가 (재로그인 필요)

### 크롤러 raw 데이터 → DB 매핑 함수

위치: [`backend/app/data_ingestion/normalizers/pnu_normalizer.py`](../../backend/app/data_ingestion/normalizers/pnu_normalizer.py)

| 함수 | 입력 | 출력 |
|------|------|------|
| `save_portal_credential(db, user_id, login_id, password)` | 평문 ID/PW | `PortalCredential` (암호화 저장) |
| `map_student_record(db, user_id, record)` | `fetch_student_record()` 결과 | `User` 갱신 + `UserAcademicProgram` upsert |
| `map_grades(db, user_id, grades_tables)` | `fetch_all_grades()` 결과 | `StudentCourseRecord` 목록 |
| `map_graduation_requirement(db, user_id, graduation_tables)` | `fetch_graduation_requirement()` 결과 | `GraduationAudit` 스냅샷 |

### 아직 안 한 것

- 실제 PostgreSQL에 연결해서 `alembic revision --autogenerate` → `upgrade head` 실행 (모델 코드만 작성됨, 마이그레이션 파일은 아직 없음)
- FastAPI 라우터에서 `pnu_normalizer` 호출하는 엔드포인트
- `graduation_engine`의 실제 결정론적 판정 로직 (지금은 크롤링 원본을 그대로 저장만 함)

## 4. 환경변수 (.env) 전체 목록

`backend/.env.example` 참고. 실제 값은 `.env`에만 작성하고 `.env.example`에는
절대 실제 값을 넣지 말 것 (커밋되는 템플릿 파일임).

```text
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/planu
PNU_LOGIN_ID=
PNU_LOGIN_PW=
CREDENTIAL_ENCRYPTION_KEY=
```

## 5. 다음 후보 작업

1. PostgreSQL 로컬 실행(Docker) + Alembic 마이그레이션 적용
2. 크롤러를 FastAPI 라우터로 노출 + 백그라운드 작업화
3. 사용자별 자격증명 입력 플로우 (회원가입/설정 화면 연동)
4. 비교과 활동 크롤러 (`my.pusan.ac.kr`)
5. `graduation_engine`의 실제 판정 로직 (요건 규칙 시드 데이터 필요)
