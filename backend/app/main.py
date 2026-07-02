from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.activities import router as activities_router
from app.core.config import settings
from app.core.scheduler import scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)
app.include_router(activities_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
