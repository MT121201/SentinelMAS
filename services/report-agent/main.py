"""
Report Agent — main entry point.

Polls Redis queue mas:report_queue for report tasks dispatched by the
orchestrator scheduler (weekly_report, daily_inserver_check may also
request reports on demand).

Port: 8004
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from executor import run_report_task

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)

QUEUE_KEY = "mas:report_queue"
BLPOP_TIMEOUT = 5  # seconds

_shutdown = asyncio.Event()
_engine = None
_SessionFactory: async_sessionmaker | None = None
_redis: aioredis.Redis | None = None


# ── Lifespan ───────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine, _SessionFactory, _redis

    _engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    _SessionFactory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    _redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    await _redis.ping()
    log.info("report-agent: Redis OK")

    consumer_task = asyncio.create_task(run_consumer(), name="report-consumer")
    log.info("report-agent: started on port 8004")

    yield

    log.info("report-agent: shutting down…")
    _shutdown.set()
    await asyncio.wait_for(consumer_task, timeout=30)
    await _redis.aclose()
    await _engine.dispose()


# ── Consumer loop ──────────────────────────────────────────────────────────────


async def run_consumer() -> None:
    """BLPOP loop — blocks until a task arrives, then processes it."""
    log.info("run_consumer: listening on %s", QUEUE_KEY)
    while not _shutdown.is_set():
        try:
            result = await _redis.blpop(QUEUE_KEY, timeout=BLPOP_TIMEOUT)
            if result is None:
                continue
            _, raw = result
            task = json.loads(raw)
            log.info("run_consumer: received task_id=%s", task.get("task_id"))

            async with _SessionFactory() as db:
                await run_report_task(task, db, _redis)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("run_consumer: unhandled error: %s", exc)
            await asyncio.sleep(2)

    log.info("run_consumer: stopped")


# ── FastAPI app ────────────────────────────────────────────────────────────────


app = FastAPI(title="SentinelMAS Report Agent", lifespan=lifespan)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "report-agent"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8004,
        workers=1,
        log_level=settings.log_level.lower(),
    )
