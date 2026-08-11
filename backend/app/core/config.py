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
    #
    # 2026-08 golden dataset N=3 벤치 결과 gpt-5.4-nano(Luna)를 기본으로 채택:
    # gpt-4o-mini 대비 pass율 55%→79% (+24%p), median latency 10.2s→7.2s (-30%),
    # 총 비용은 1.2배로 소폭 상승만. 특히 부전공 필수과목 판정 회귀(case 08)가
    # 모델 업그레이드로 자동 해결됨. 상세: backend/tests/eval/.
    ROADMAP_AGENT_MODEL: str = "openai:gpt-5.4-nano"

    PNU_LOGIN_ID: str | None = None
    PNU_LOGIN_PW: str | None = None

    # 학교 포털 비밀번호 등 민감정보 암호화에 사용하는 Fernet 키.
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 로 생성.
    CREDENTIAL_ENCRYPTION_KEY: str | None = None

    # 자체 로그인(JWT) 서명 키. `python -c "import secrets; print(secrets.token_urlsafe(32))"`로 생성.
    JWT_SECRET_KEY: str | None = None
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7일

    # --- 비밀번호 재설정 메일 (Resend SMTP) ---
    #
    # SMTP_HOST가 비어 있으면 메일을 실제로 보내지 않고 재설정 링크를 로그에 남긴다.
    # 로컬 개발에서 메일 서버 없이 흐름 전체를 확인하기 위한 것이고, 실제 발송이
    # 필요하면 .env에 값을 채운다.
    #
    # Resend를 쓰는 이유: 메일 계정(사서함)이 아니라 API 키 하나로 보낼 수 있어
    # 개인 웹메일 비밀번호를 배포 환경에 두지 않아도 된다.
    #   SMTP_HOST=smtp.resend.com / SMTP_PORT=587 / SMTP_USER=resend
    #   SMTP_PASSWORD=<Resend API 키(re_로 시작)>
    #
    # SMTP_FROM은 반드시 Resend에서 인증한 도메인이어야 한다. 도메인 인증 전에는
    # 샌드박스 주소(onboarding@resend.dev)만 쓸 수 있고, 이때는 Resend 계정을
    # 만든 본인 메일 주소로만 발송된다.
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_USE_TLS: bool = True
    SMTP_FROM: str = "Plan U <onboarding@resend.dev>"

    # 메일에 담을 재설정 화면 주소. 프론트 배포 주소로 덮어쓴다.
    PASSWORD_RESET_URL_BASE: str = "http://localhost:5173/reset-password"
    PASSWORD_RESET_TOKEN_TTL_MINUTES: int = 30

    # 쉼표로 구분한 프론트엔드 origin 목록. 로컬과 배포 주소를 환경별로 덮어쓴다.
    CORS_ORIGINS: str = (
        "http://127.0.0.1:5173,http://localhost:5173,"
        "https://pnuai-a-03-team-u.vercel.app"
    )
    CORS_ORIGIN_REGEX: str | None = (
        r"^http://(localhost|127\.0\.0\.1):\d+$|"
        r"^https://pnuai-a-03-team-u(?:-[a-z0-9-]+)?\.vercel\.app$"
    )

    # --- Langfuse (LLM 관측/평가) ---
    # 셋 다 값이 있어야 실제 trace 전송된다. 하나라도 비면 콜백은 no-op.
    # 개인 Cloud 프로젝트 `planu-backend` API 키를 팀 채널에서 공유.
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_BASE_URL: str = "https://cloud.langfuse.com"
    # user_id 해시용 salt. .env에 각자 로컬로 두고, 유출 시 재발급.
    # 없으면 hash가 salt="" 로 만들어져 rainbow 공격에 취약해지므로 반드시 설정.
    LANGFUSE_USER_ID_SALT: str | None = None


settings = Settings()
