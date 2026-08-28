from fastapi import FastAPI

from .database import get_session
from .mode2 import router as mode2_router

app = FastAPI(title="AI Prescription Tool")


app.include_router(mode2_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
