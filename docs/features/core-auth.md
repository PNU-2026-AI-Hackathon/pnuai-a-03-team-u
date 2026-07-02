# Core (로그인/회원가입)

이메일/비밀번호 회원가입·로그인 + JWT 발급/검증까지 구현됨. 소셜 로그인은 아직 없음.

**다른 기능 API는 아직 이걸 안 쓴다** — [activity-recommendations.md](./activity-recommendations.md)의
`GET /activities/recommendations/{user_id}`는 여전히 `user_id`를 경로 파라미터로 받는다.
`get_current_user` 의존성으로 교체하는 건 별도 작업.

## API (`app/api/auth.py`)

| 메서드/경로 | 설명 |
| --- | --- |
| `POST /auth/signup` | 이메일/비밀번호/이름(+선택적으로 학번/학교/학과/진로/복수전공·부전공) 가입. 비밀번호 8자 미만이면 400, 이메일 중복이면 409 |
| `POST /auth/login` | 이메일/비밀번호 검증 후 JWT access token 발급 |
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
  {"major": "컴퓨터공학", "program_type": "primary"},
  {"major": "경영학", "program_type": "dual"},
  {"major": "심리학", "program_type": "minor"}
]
```

`program_type`은 `primary`/`dual`/`minor`/`interdisciplinary` 중 하나만 허용(422 검증).
`GET /auth/me` 응답의 `academic_programs`에서 확인 가능. 추천 로직
(`extracurricular_recommender.py`)은 이미 유저의 모든 전공을 프로필 텍스트에 반영하고
있어서 이 데이터가 들어오면 별도 연동 작업 없이 바로 추천에 쓰인다.

### 학과/전공 검증 (`departments` 테이블)

`department`, `academic_programs[].major`로 들어온 값은 `departments` 테이블에
있는 정식 명칭이어야 한다 — 없으면 400으로 회원가입 자체가 거부된다
(`_validate_department_names`, `app/api/auth.py`).

`departments` 시드 데이터(`backend/seeds/pnu_departments.json`, 163개)는 onestop
수강편람 크롤러(`app/ingestion/crawlers/onestop_course_catalog.py`)로 2026-1학기
개설 과목의 개설 학과명(`MNG_DEPT_NM`)을 전부 모아, 연구소/센터 같은 비학사 조직을
제외해 만들었다. `scripts/seed_departments.py`로 upsert한다.

```
python -m scripts.seed_departments
```

**1학년(세부전공 미배정) 대응**: 수강편람은 과목을 실제로 개설하는 단위(대개 세부
전공)만 보여줘서, 학부제 신입생이 쓰는 상위 학부명(예: "정보컴퓨터공학부")이
처음엔 빠져있었다. 부산대 2026학년도 수시모집요강(모집단위별 입학정원 표 —
학부제 신입생이 실제로 선택하는 정식 단위)과 대조해 "정보컴퓨터공학부",
"전기전자공학부", "디자인학과"를 보강했고, 그 외 학부제 모집단위
(기계공학부/재료공학부/경제학부/무역학부/공공정책학부/의생명융합공학부/
자유전공학부/첨단융합학부/약학부 등)는 전부 이미 포함되어 있음을 확인함.

**알려진 한계**: 전체 16개 단과대학의 모집단위를 한 줄씩 전수 대조하지는 않았다 —
회원가입 시 "등록되지 않은 학과" 에러가 자주 나오면 그 학과명을
`pnu_departments.json`에 추가하고 `seed_departments.py`를 재실행하면 된다.

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
- **모델 변경 없음**: `User.email`/`password_hash`가 이미 있어서 마이그레이션 불필요

## 방향 (`docs/architecture.md` "Authentication Direction" 기반)

- 이메일/비밀번호 인증 완료, 이후 소셜 로그인(Google/Kakao/Naver)을 provider 계정으로 추가 예정
- 소셜 로그인을 위한 `auth_accounts` 테이블 설계는 되어 있으나 아직 마이그레이션에 반영 안 됨
  (`provider`, `provider_user_id`, `email`로 로컬/소셜 계정을 함께 식별)

## TODO

1. 다른 기능 API(`GET /activities/recommendations/{user_id}` 등)를 `get_current_user` 기반으로 전환
2. `auth_accounts` 테이블 마이그레이션 + 소셜 로그인
3. 비밀번호 재설정/이메일 인증 (범위 밖으로 보류 중)
4. `departments` 목록에서 빠진 상위 학부명 보강 (위 "알려진 한계" 참고)
