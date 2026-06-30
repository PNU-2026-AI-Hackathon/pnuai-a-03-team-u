from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    PROJECT_NAME: str = "Plan U Backend"
    ENV: str = "local"

    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/planu"

    ANTHROPIC_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None

    PNU_LOGIN_ID: str | None = None
    PNU_LOGIN_PW: str | None = None

    # 학교 포털 비밀번호 등 민감정보 암호화에 사용하는 Fernet 키.
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 로 생성.
    CREDENTIAL_ENCRYPTION_KEY: str | None = None


settings = Settings()
