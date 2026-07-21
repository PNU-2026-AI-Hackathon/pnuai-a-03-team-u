from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.courses import router as courses_router
from app.api.graduation import router as graduation_router
from app.api.portal_sync import router as portal_sync_router
from app.api.profile import router as profile_router
from app.api.rag import router as rag_router
from app.api.roadmap_agent import router as roadmap_agent_router
from app.api.roadmaps import router as roadmaps_router
from app.core.config import settings
from app.core.scheduler import scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()],
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(portal_sync_router)
app.include_router(profile_router)
app.include_router(courses_router)
app.include_router(roadmaps_router)
app.include_router(roadmap_agent_router)
app.include_router(graduation_router)
app.include_router(rag_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
