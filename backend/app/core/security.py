import datetime
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


def create_access_token(user_id: int) -> str:
    expire = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, _jwt_secret(), algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """토큰이 유효하면 user_id를, 아니면 None을 반환한다."""
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[settings.JWT_ALGORITHM])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None
