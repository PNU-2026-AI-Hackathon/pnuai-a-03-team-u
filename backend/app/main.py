from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
from app.core.scheduler import scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    langfuse_startup_log()
    yield
    scheduler.shutdown()
    # 아직 안 보낸 trace를 배출한다. Langfuse가 꺼져 있으면 no-op.
    langfuse_flush()


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
