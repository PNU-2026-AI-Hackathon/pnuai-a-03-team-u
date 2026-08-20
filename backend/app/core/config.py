from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    PROJECT_NAME: str = "Plan U Backend"

    # 보안 가드의 기준값이다 — 개발 편의 기능(비밀번호 재설정 링크 로그 출력,
    # 크롤러의 .env 개인계정 폴백)은 이 값이 local/dev일 때만 열린다.
    # **기본값이 "production"인 건 의도적이다.** 예전 기본값은 "local"이었는데,
    # 배포 설정 어디에서도 ENV를 지정하지 않아 운영에서도 local로 평가됐다 —
    # 가드가 전부 열린 채였다(fail-open). 안전한 쪽을 기본으로 두면, 설정을
    # 빠뜨렸을 때 로컬에서 눈에 띄게 실패하지 조용히 운영이 노출되지 않는다.
    # 로컬 개발자는 `.env`에 ENV=local을 넣는다 (`.env.example` 참고).
    ENV: str = "production"

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

    # Resend 한 줄 설정. 이것만 채우면 SMTP_HOST/USER/PASSWORD를 따로 안 써도 된다
    # (`mailer.resolve_smtp()`가 Resend 기본값으로 채운다).
    # SMTP_*를 직접 쓰면 그쪽이 우선이라, 다른 메일 서버를 쓰는 경우도 그대로 살아 있다.
    #
    # 키 하나만 두는 이유: SMTP_HOST만 켜고 SMTP_PASSWORD를 비워두면 메일도 안 가고
    # 로그에 링크도 안 남는 반쪽 상태가 된다(2026-08-20 실측). 그 조합 자체를
    # 만들 수 없게 하는 편이 낫다.
    RESEND_API: str | None = None

    # 메일에 담을 재설정 화면 주소. 프론트 배포 주소로 덮어쓴다.
    PASSWORD_RESET_URL_BASE: str = "http://localhost:5173/reset-password"
    PASSWORD_RESET_TOKEN_TTL_MINUTES: int = 30

    # 쉼표로 구분한 프론트엔드 origin 목록. 로컬과 배포 주소를 환경별로 덮어쓴다.
    CORS_ORIGINS: str = (
        "http://127.0.0.1:5173,http://localhost:5173,"
        "https://pnuai-a-03-team-u.vercel.app,"
        "https://planu-pnu.netlify.app"
    )
    CORS_ORIGIN_REGEX: str | None = (
        r"^http://(localhost|127\.0\.0\.1):\d+$|"
        r"^https://pnuai-a-03-team-u(?:-[a-z0-9-]+)?\.vercel\.app$|"
        r"^https://[a-z0-9-]+--planu-pnu\.netlify\.app$"
    )

    # --- 레이트 리밋 (docs/backend/security-privacy-plan.md P0-1) ---
    #
    # 형식은 slowapi/limits 문법: "5/minute", 여러 개면 세미콜론으로 "10/minute;100/day".
    # 로컬에서 반복 테스트할 때만 RATE_LIMIT_ENABLED=false로 끈다 — 배포에서 끄면
    # 로그인 brute force와 챗 LLM 비용 폭탄에 그대로 노출된다.
    RATE_LIMIT_ENABLED: bool = True
    # 비면 in-memory. 워커가 여러 개면 프로세스별로 따로 세므로 스케일아웃 시 redis:// 지정.
    RATE_LIMIT_STORAGE_URI: str | None = None

    RATE_LIMIT_LOGIN: str = "5/minute;30/hour"
    RATE_LIMIT_SIGNUP: str = "5/hour"
    RATE_LIMIT_PASSWORD_RESET: str = "3/hour;10/day"
    # 챗이 가장 빡빡하다 — 요청당 LLM 비용이 나가고 정상 사용자는 이 이상 쓸 이유가 없다.
    RATE_LIMIT_CHAT: str = "10/minute;100/day"
    # Playwright 크롤이라 서버 자원도 많이 쓴다.
    RATE_LIMIT_PORTAL_SYNC: str = "5/hour"
    # RAG 인제스트는 전체 청크 재구축 + OpenAI 임베딩 호출이다. 정상 사용자가 부를 일이
    # 없는 운영 작업인데 인증만 통과하면 누구나 부를 수 있어, 비용 남용 경로였다.
    RATE_LIMIT_RAG_INGEST: str = "2/hour;5/day"

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


# 개발 편의 기능을 열어도 되는 환경인지 판단하는 **단일 기준**.
#
# 이 판단이 두 군데에 각자 구현돼 서로 달랐다: 크롤러 폴백 가드(P1-4)는
# `ENV.strip().lower() in {local, dev, development}`였고, 재설정 링크 로그 가드(P0-4)는
# `ENV == "local"` 정확 일치였다. 그래서 `.env`에 `ENV=dev`를 쓴 개발자는 크롤러
# 폴백은 열리는데 재설정 링크는 안 찍히고, 로그에는 "배포 환경에서 시도됐다"는
# error가 남았다. `ENV=Local`이나 뒤에 공백이 붙은 경우도 마찬가지로 갈렸다.
#
# 두 가드는 "여기는 개발자 로컬인가"라는 **같은 질문**을 하므로 기준도 하나여야 한다.
# 새로 개발 전용 우회를 추가할 때도 반드시 이 함수를 쓴다 — 직접 `settings.ENV`를
# 비교하지 말 것.
_DEV_ENVS = frozenset({"local", "dev", "development"})


def is_dev_environment() -> bool:
    """`ENV`가 개발 환경(local/dev/development)인가. 대소문자·앞뒤 공백 무시."""
    return (settings.ENV or "").strip().lower() in _DEV_ENVS
