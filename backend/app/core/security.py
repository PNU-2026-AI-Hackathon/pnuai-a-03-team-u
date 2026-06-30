from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import settings


class EncryptionKeyMissingError(Exception):
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
