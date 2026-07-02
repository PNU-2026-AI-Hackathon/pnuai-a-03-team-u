# Core (로그인/회원가입)

**미구현.** `User` 모델에 `email`/`password_hash` 필드는 있지만, 회원가입/로그인 API,
비밀번호 해싱, JWT 발급/검증, 인증 의존성(`get_current_user`) 중 아무것도 없다.

지금 다른 기능(비교과 활동 추천, 내 정보 페이지)의 API가 전부 `user_id`를 그냥
파라미터로 받아 동작하는 이유가 이것이다. 이 문서가 채워지고 나면 두 기능 문서의
"로그인 붙으면 교체 필요" 항목이 해소된다.

## 방향 (`docs/architecture.md` "Authentication Direction" 기반)

- 이메일/비밀번호 인증을 먼저 구현하고, 이후 소셜 로그인(Google/Kakao/Naver)을 provider 계정으로 추가
- 소셜 로그인을 위한 `auth_accounts` 테이블 설계는 되어 있으나 아직 마이그레이션에 반영 안 됨
  (`provider`, `provider_user_id`, `email`로 로컬/소셜 계정을 함께 식별)

## 현재 있는 것

- `app/domains/users/models.py`의 `User.password_hash` 컬럼 (아직 아무도 값을 채우지 않음)
- `app/core/security.py`의 Fernet 암호화 — 단, 이건 One-Stop 포털 비밀번호 저장용이지
  우리 앱 자체 로그인용 비밀번호 해싱이 아님 (혼동 주의: 회원가입 비밀번호는 bcrypt 등
  단방향 해시를 써야 하고, Fernet 같은 대칭키 암호화를 쓰면 안 됨)

## TODO

1. 회원가입 API — `passlib[bcrypt]`(이미 requirements.txt에 있음)로 비밀번호 해싱
2. 로그인 API — JWT 발급 (`python-jose[cryptography]`, 이미 requirements.txt에 있음)
3. `get_current_user` 의존성 — 각 기능 API의 `user_id` 파라미터를 이걸로 교체
4. `auth_accounts` 테이블 마이그레이션 + 소셜 로그인 (2순위)
