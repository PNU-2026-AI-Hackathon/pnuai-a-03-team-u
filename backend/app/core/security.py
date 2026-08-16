import datetime
import hashlib
from functools import lru_cache

import bcrypt
from cryptography.fernet import Fernet
from jose import JWTError, jwt

from app.core.config import settings


class EncryptionKeyMissingError(Exception):
    pass


class JwtSecretMissingError(Exception):
    pass


@lru_cache
def _fernet() -> Fernet:
    if not settings.CREDENTIAL_ENCRYPTION_KEY:
        raise EncryptionKeyMissingError(
            "CREDENTIAL_ENCRYPTION_KEY가 설정되지 않았습니다. "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
            "로 생성한 값을 .env에 넣으세요."
        )
    return Fernet(settings.CREDENTIAL_ENCRYPTION_KEY)


def encrypt_secret(plain_text: str) -> str:
    """학교 포털 비밀번호 등 민감정보를 암호화해 저장 가능한 문자열로 변환한다."""
    return _fernet().encrypt(plain_text.encode()).decode()


def decrypt_secret(encrypted_text: str) -> str:
    """encrypt_secret으로 암호화된 값을 평문으로 복호화한다."""
    return _fernet().decrypt(encrypted_text.encode()).decode()


# --- 회원가입 비밀번호 해싱 ---
#
# encrypt_secret/decrypt_secret(Fernet, 대칭키 암호화)과 혼동하지 말 것: 그건 One-Stop
# 포털 비밀번호처럼 나중에 평문이 다시 필요한 값에 쓴다. 회원가입 비밀번호는 평문이
# 다시 필요할 일이 없으므로 단방향 해시(bcrypt)를 쓴다.
#
# passlib[bcrypt] 대신 bcrypt를 직접 쓴다: passlib은 유지보수가 끊겨 최신 bcrypt(4.1+)와
# 호환이 깨져있다("password cannot be longer than 72 bytes" 같은 엉뚱한 에러가 남).


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), password_hash.encode())


# --- JWT ---


def _jwt_secret() -> str:
    if not settings.JWT_SECRET_KEY:
        raise JwtSecretMissingError(
            "JWT_SECRET_KEY가 설정되지 않았습니다. "
            "`python -c \"import secrets; print(secrets.token_urlsafe(32))\"` "
            "로 생성한 값을 .env에 넣으세요."
        )
    return settings.JWT_SECRET_KEY


# --- 토큰 무효화 ---
#
# 문제: 페이로드가 {sub, exp}뿐이고 서버측 세션 저장소가 없어서, 비밀번호를 바꾸거나
# 재설정해도 **기존 토큰이 만료(7일)까지 그대로 유효**했다. 토큰이 유출된 사용자가
# 비밀번호를 바꿔도 공격자는 계속 접근할 수 있다 (security-privacy-plan.md P0-2).
#
# 해결: 토큰에 현재 password_hash의 지문(`pv`)을 넣고 매 요청 대조한다. 비밀번호가
# 바뀌면 해시가 바뀌므로 지문이 어긋나 옛 토큰이 즉시 무효가 된다. **스키마 변경이
# 필요 없다** — 사용자 행은 인증 과정에서 어차피 로드하므로 추가 쿼리도 없다.
#
# 한계: "다른 기기 로그아웃"처럼 비밀번호 변경 없이 세션을 끊는 건 못 한다. 그건
# users.token_valid_after 컬럼이 필요하고, 공유 DB 마이그레이션이라 별도 승인 후에 한다.


def password_fingerprint(password_hash: str) -> str:
    """password_hash에서 파생한 12자 지문. 해시 원본을 토큰에 싣지 않기 위한 것."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:12]


def create_access_token(user_id: int, password_hash: str) -> str:
    expire = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "pv": password_fingerprint(password_hash),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> tuple[int, str] | None:
    """유효하면 (user_id, password_fingerprint), 아니면 None.

    `pv`가 없는 토큰은 이 방어가 생기기 전에 발급된 것이라 거절한다 — 통과시키면
    무효화가 최대 7일간 무의미해진다. 기존 로그인 세션은 한 번 끊기고 재로그인이 필요하다.
    """
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[settings.JWT_ALGORITHM])
        fingerprint = payload.get("pv")
        if not fingerprint:
            return None
        return int(payload["sub"]), str(fingerprint)
    except (JWTError, KeyError, ValueError):
        return None
