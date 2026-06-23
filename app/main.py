import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.routers import (
    admin,
    admin_recorded,
    auth,
    classes,
    cohorts,
    cron,
    enrollments,
    health,
    me,
    recorded,
    stream_webhook,
)

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async def warm_database() -> None:
            async with engine.connect() as conn:
                await conn.execute(text("select 1"))

        await asyncio.wait_for(warm_database(), timeout=10)
    except Exception as exc:
        logger.warning("database warmup failed: %s", exc)
    yield


app = FastAPI(title="IM Live Class API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(me.router)
app.include_router(classes.router)
app.include_router(cohorts.router)
app.include_router(recorded.router)
app.include_router(admin.router)
app.include_router(admin_recorded.router)
app.include_router(cron.router)
app.include_router(enrollments.router)
app.include_router(enrollments.webhook_router)
app.include_router(stream_webhook.webhook_router)
