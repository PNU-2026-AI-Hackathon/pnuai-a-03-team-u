from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    PROJECT_NAME: str = "Plan U Backend"
    ENV: str = "local"

    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/planu"

    ANTHROPIC_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None

    # 로드맵 상담 에이전트가 쓸 LLM. langchain init_chat_model 형식으로,
    # "provider:model"(예: "openai:gpt-4o", "anthropic:claude-sonnet-4-5",
    # "google_genai:gemini-2.0-flash") 한 줄만 바꾸면 프로바이더가 교체된다.
    # 해당 프로바이더의 API 키(OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY)와
    # langchain 통합 패키지(langchain-openai / langchain-anthropic /
    # langchain-google-genai)가 함께 있어야 한다.
    ROADMAP_AGENT_MODEL: str = "openai:gpt-4o"

    PNU_LOGIN_ID: str | None = None
    PNU_LOGIN_PW: str | None = None

    # 학교 포털 비밀번호 등 민감정보 암호화에 사용하는 Fernet 키.
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 로 생성.
    CREDENTIAL_ENCRYPTION_KEY: str | None = None

    # 자체 로그인(JWT) 서명 키. `python -c "import secrets; print(secrets.token_urlsafe(32))"`로 생성.
    JWT_SECRET_KEY: str | None = None
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7일

    # 쉼표로 구분한 프론트엔드 origin 목록. 로컬과 배포 주소를 환경별로 덮어쓴다.
    CORS_ORIGINS: str = (
        "http://127.0.0.1:5173,http://localhost:5173,"
        "https://pnuai-a-03-team-u.vercel.app"
    )
    CORS_ORIGIN_REGEX: str | None = (
        r"^http://(localhost|127\.0\.0\.1):\d+$|"
        r"^https://pnuai-a-03-team-u(?:-[a-z0-9-]+)?\.vercel\.app$"
    )


settings = Settings()
