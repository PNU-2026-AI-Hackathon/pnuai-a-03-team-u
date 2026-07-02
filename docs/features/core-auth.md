# Core (로그인/회원가입)

이메일/비밀번호 회원가입·로그인 + JWT 발급/검증까지 구현됨. 소셜 로그인은 아직 없음.

**다른 기능 API는 아직 이걸 안 쓴다** — [activity-recommendations.md](./activity-recommendations.md)의
`GET /activities/recommendations/{user_id}`는 여전히 `user_id`를 경로 파라미터로 받는다.
`get_current_user` 의존성으로 교체하는 건 별도 작업.

## API (`app/api/auth.py`)

| 메서드/경로 | 설명 |
| --- | --- |
| `POST /auth/signup` | 이메일/비밀번호/이름(+선택적으로 학번/학교/학과/진로) 가입. 비밀번호 8자 미만이면 400, 이메일 중복이면 409 |
| `POST /auth/login` | 이메일/비밀번호 검증 후 JWT access token 발급 |
| `GET /auth/me` | `Authorization: Bearer <token>` 헤더로 현재 유저 조회 |

`get_current_user` 의존성(`app/api/auth.py`)이 다른 라우터에서도 재사용 가능 —
`Depends(get_current_user)`로 가져다 쓰면 됨.

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
