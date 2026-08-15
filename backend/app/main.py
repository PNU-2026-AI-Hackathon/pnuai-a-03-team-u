import time
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
from app.api.tracks import public_router as tracks_public_router, router as tracks_router
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


def _retry_after_seconds(request: Request, exc: RateLimitExceeded) -> int:
    """429에 실을 Retry-After(초).

    예전에는 `getattr(exc, "retry_after", 60)`이었는데, slowapi의 `RateLimitExceeded`는
    `limit` 하나만 갖고 `retry_after` 속성이 **없다**(slowapi/errors.py). 그래서 폴백 60이
    항상 이겨서, `5/hour`(포털동기화·가입)·`3/hour;10/day`(재설정)·`100/day`(챗)에 걸린
    사용자에게 "1분 뒤 재시도"라고 안내했다. 그대로 따르면 또 429를 받는다.

    slowapi는 예외를 던지기 직전에 `request.state.view_rate_limit`에
    `(RateLimitItem, [식별자])`를 넣어두므로(extension.py 530행, raise는 533행),
    저장소에 윈도우 리셋 시각을 물어 정확한 값을 낼 수 있다.

    이 함수는 절대 예외를 밖으로 내지 않는다 — 429 응답을 만들다가 500이 나면
    사용자 입장에서 더 나쁘다.
    """
    try:
        item, identifiers = request.state.view_rate_limit
        reset_at, _remaining = limiter.limiter.get_window_stats(item, *identifiers)
        seconds = int(reset_at - time.time()) + 1
        if seconds > 0:
            return seconds
    except Exception:  # noqa: BLE001 - 아래 폴백으로 충분하다
        pass

    # 폴백: 한도 윈도우 길이 전체. 실제 리셋보다 늦을 수는 있어도 이르지는 않으므로
    # "따랐는데 또 429"는 나오지 않는다.
    try:
        return max(1, int(exc.limit.limit.get_expiry()))
    except Exception:  # noqa: BLE001
        return 60


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """429를 프론트가 그대로 노출할 수 있는 한국어 메시지로 돌려준다.

    slowapi 기본 응답은 "Rate limit exceeded: 5 per 1 minute" 영문이라 사용자에게 그대로
    보여줄 수 없다. Retry-After 헤더는 남겨서 프론트가 재시도 시점을 계산할 수 있게 한다.
    """
    return JSONResponse(
        status_code=429,
        content={"detail": "요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요."},
        headers={"Retry-After": str(_retry_after_seconds(request, exc))},
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
app.include_router(tracks_public_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
