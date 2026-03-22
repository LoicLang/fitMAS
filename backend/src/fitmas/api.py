from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from fitmas.api_activities import router as activities_router
from fitmas.api_debug import router as debug_router
from fitmas.api_messages import router as messages_router
from fitmas.api_onboarding import router as onboarding_router
from fitmas.api_plan import router as plan_router
from fitmas.api_read import router as read_router
from fitmas.api_static import router as static_router
from fitmas.db import SessionLocal, init_db
from fitmas.seed import seed_if_empty

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    init_db()
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
    logger.info("FitMAS API ready")
    yield


app = FastAPI(title="FitMAS V0 API", version="0.1.0", lifespan=lifespan)
app.include_router(static_router)
app.include_router(read_router)
app.include_router(debug_router)
app.include_router(activities_router)
app.include_router(onboarding_router)
app.include_router(plan_router)
app.include_router(messages_router)
