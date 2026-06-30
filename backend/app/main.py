from fastapi import FastAPI

from app.core.config import settings

app = FastAPI(title=settings.PROJECT_NAME)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
