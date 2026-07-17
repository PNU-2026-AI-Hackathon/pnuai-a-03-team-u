# Core (로그인/회원가입)

학번/비밀번호 회원가입·로그인 + JWT 발급/검증까지 구현됨. 소셜 로그인은 아직 없음.

**2026-07-14부로 로그인 식별자가 이메일 → 학번(student_id)으로 바뀌었다** — 와이어프레임
"1b. 로그인 → 학생정보 입력(포털 계정 자동 크롤링 온보딩)"에 맞춰서, 앱 계정 자체(학번+
비밀번호)와 One-Stop 포털 계정(`POST /me/portal-sync`용 크롤링 자격증명)을 분리 유지하되
로그인 화면에 보이는 식별자를 이메일 대신 학번 하나로 통일했다. `SignupRequest`/
`LoginRequest`에서 `email` 필드를 아예 뺐다 — **프론트엔드 `AuthPage.tsx`도 이메일 입력칸을
학번 입력칸으로 바꿔야 함(브레이킹 체인지)**.

[내 정보 페이지(졸업요건 확인)](./my-info-graduation-check.md)의 `POST /me/portal-sync`,
`PATCH /me/advisor-consulted`가 `get_current_user`를 재사용하는 첫 사례다.

## API (`app/api/auth.py`)

| 메서드/경로 | 설명 |
| --- | --- |
| `POST /auth/signup` | 학번/비밀번호/이름(+선택적으로 학교/학과/진로/복수전공·부전공) 가입. 비밀번호 8자 미만이면 400, 학번 중복이면 409 |
| `POST /auth/login` | 학번/비밀번호 검증 후 JWT access token 발급 |
| `GET /auth/me` | `Authorization: Bearer <token>` 헤더로 현재 유저 + 전공 목록 조회 |

`get_current_user` 의존성(`app/api/auth.py`)이 다른 라우터에서도 재사용 가능 —
`Depends(get_current_user)`로 가져다 쓰면 됨.

### 복수전공/부전공

`SignupRequest.academic_programs`로 회원가입 시점에 여러 전공을 한 번에 등록한다.
`User` 테이블에 컬럼을 추가하지 않고 기존 `UserAcademicProgram`(`domains/academics/models.py`)
테이블에 유저당 여러 행으로 저장 — 원래 One-Stop 크롤러(주전공만 upsert)를 위해 설계된
테이블을 그대로 재사용한다.

```json
"academic_programs": [
  {"major": "컴퓨터공학", "department": "정보컴퓨터공학부", "program_type": "primary"},
  {"major": "경영학", "program_type": "dual"},
  {"major": "심리학", "program_type": "minor"}
]
```

`program_type`은 `primary`/`dual`/`minor`/`interdisciplinary` 중 하나만 허용(422 검증).
각 항목의 `school`/`college`/`department`는 생략하면 `SignupRequest` 최상위 값을
그대로 쓴다. `GET /auth/me` 응답의 `academic_programs`에서 확인 가능.

### 학과/전공 계층 (`schools → colleges → departments → majors`)

**2026-07-07부로 방식이 바뀌었다.** 예전엔 미리 시드해둔 `departments` 테이블에
있는 정식 명칭인지 검증해서 없으면 400으로 거부했는데, 지금은 검증 없이
[`resolve_hierarchy()`](../../backend/app/domains/academics/hierarchy.py)가
회원가입 입력값으로 학교/단과대/학과/전공을 자동 생성(get-or-create)한다.
자세한 계층 구조는 [my-info-graduation-check.md](./my-info-graduation-check.md) 참고.

`User.department_id`/`major_id`, `UserAcademicProgram.department_id`/`major_id`가
이 계층을 FK로 참조한다 — 더 이상 자유 텍스트 컬럼이 아니다.

## 구현 세부사항

- **비밀번호 해싱**: `bcrypt`를 직접 사용 (`app/core/security.py`의 `hash_password`/`verify_password`).
  `passlib[bcrypt]`를 쓰지 않은 이유 — passlib은 유지보수가 끊겨 최신 bcrypt(4.1+)와 호환이
  깨져있음("password cannot be longer than 72 bytes" 같은 엉뚱한 에러가 남). requirements.txt도
  `passlib[bcrypt]` → `bcrypt`로 교체함
  - `app/core/security.py`의 `encrypt_secret`/`decrypt_secret`(Fernet)과 혼동 금지: 그건
    One-Stop 포털 비밀번호처럼 평문이 나중에 다시 필요한 값 전용. 회원가입 비밀번호는
    평문이 다시 필요할 일이 없으므로 단방향 해시(bcrypt)를 쓴다
- **JWT**: `python-jose`. `JWT_SECRET_KEY`(`.env`, 각자 로컬에서 생성)로 서명, 기본 만료 7일
  (`ACCESS_TOKEN_EXPIRE_MINUTES`)
- **`User.email`은 nullable로 남겨둠**: 로그인/가입에서 더 이상 안 받지만, 컬럼 자체를
  지우진 않았다(과거 데이터 호환 + 나중에 알림용으로 쓸 수도 있어서). 마이그레이션
  `d0e1f2a3b4c5`가 `email` NOT NULL 제약만 제거함. `student_id`는 원래도 nullable+unique
  컬럼이었어서 DB 스키마 변경은 없고, 애플리케이션(`SignupRequest.student_id: str`)에서
  항상 채우도록 강제하는 식으로 처리했다 — 기존 라이브 데이터에 `student_id`가 비어있는
  행이 있으면 그 계정은 로그인 식별자가 없어 로그인 불가능해진다(직접 정리 필요)

## 방향 (`docs/backend/architecture.md` "Authentication Direction" 기반)

- 이메일/비밀번호 인증 완료, 이후 소셜 로그인(Google/Kakao/Naver)을 provider 계정으로 추가 예정
- 소셜 로그인을 위한 `auth_accounts` 테이블 설계는 되어 있으나 아직 마이그레이션에 반영 안 됨
  (`provider`, `provider_user_id`, `email`로 로컬/소셜 계정을 함께 식별)

## TODO

1. 다른 기능 API(`GET /activities/recommendations/{user_id}` 등)를 `get_current_user` 기반으로 전환
2. `auth_accounts` 테이블 마이그레이션 + 소셜 로그인
3. 비밀번호 재설정/이메일 인증 (범위 밖으로 보류 중)
4. `departments` 목록에서 빠진 상위 학부명 보강 (위 "알려진 한계" 참고)
