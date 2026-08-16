from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from slowapi.errors import RateLimitExceeded

from app.api.auth import router as auth_router
from app.api.courses import router as courses_router
from app.api.curriculum import router as curriculum_router
from app.api.departments import router as departments_router
from app.api.graduation import router as graduation_router
from app.api.portal_sync import router as portal_sync_router
from app.api.profile import router as profile_router
from app.api.rag import router as rag_router
from app.api.roadmap_agent import router as roadmap_agent_router
from app.api.roadmaps import router as roadmaps_router
from app.api.timetables import router as timetables_router
from app.api.timetable import router as timetable_router
from app.api.timetable_agent import router as timetable_agent_router
from app.api.tracks import router as tracks_router
from app.ai.llm.langfuse_callback import flush as langfuse_flush, startup_log as langfuse_startup_log
from app.core.config import settings
from app.core.ratelimit import limiter
from app.core.scheduler import scheduler


def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 응답에서 입력값 원문(`input`)을 제거한다.

    FastAPI 기본 핸들러는 `exc.errors()`를 그대로 내보내는데, pydantic v2의 에러 항목에는
    검증에 실패한 **입력값이 그대로** 담긴다. portal-sync처럼 본문에 One-Stop 비밀번호가
    있는 요청에서 타입이 어긋나면 그 값이 응답으로 되돌아온다
    (security-privacy-plan.md P0-3). 어디가 왜 틀렸는지는 남기고 값만 뺀다.
    """
    safe = [
        {k: v for k, v in err.items() if k not in ("input", "ctx")}
        for err in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": safe})


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """429를 프론트가 그대로 노출할 수 있는 한국어 메시지로 돌려준다.

    slowapi 기본 응답은 "Rate limit exceeded: 5 per 1 minute" 영문이라 사용자에게 그대로
    보여줄 수 없다. Retry-After 헤더는 남겨서 프론트가 재시도 시점을 계산할 수 있게 한다.
    """
    return JSONResponse(
        status_code=429,
        content={"detail": "요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요."},
        headers={"Retry-After": str(getattr(exc, "retry_after", 60) or 60)},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    langfuse_startup_log()
    yield
    scheduler.shutdown()
    # 아직 안 보낸 trace를 배출한다. Langfuse가 꺼져 있으면 no-op.
    langfuse_flush()


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

# 레이트 리밋 (docs/backend/security-privacy-plan.md P0-1).
# SlowAPIMiddleware를 안 쓰고 데코레이터 방식만 쓴다 — 전역 한도를 걸면 조회 API까지
# 묶여서, 정작 비싼 챗과 값싼 조회에 같은 한도가 적용된다.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.add_exception_handler(RequestValidationError, _validation_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()],
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    # 인증은 Authorization: Bearer 헤더로만 한다 — 백엔드 어디에서도 쿠키를 굽거나
    # 읽지 않고(2026-08-14 확인), 프론트 axios 클라이언트도 withCredentials를 쓰지
    # 않는다. 따라서 credentials 허용은 동작에 필요 없고 공격면만 넓힌다
    # (security-privacy-plan.md P1-5). 쿠키 세션을 도입하게 되면 CSRF 대책과 함께
    # 다시 켜야 한다.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(portal_sync_router)
app.include_router(profile_router)
app.include_router(courses_router)
app.include_router(curriculum_router)
app.include_router(departments_router)
app.include_router(roadmaps_router)
app.include_router(roadmap_agent_router)
app.include_router(graduation_router)
app.include_router(rag_router)
app.include_router(timetable_router)
app.include_router(timetable_agent_router)
app.include_router(timetables_router)
app.include_router(tracks_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
