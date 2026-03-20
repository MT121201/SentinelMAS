"""
InServer Agent — FastAPI application.

Port: 8002
Consumes from: mas:inserver_queue (Redis BLPOP)
Runs: maintenance tasks via executor.py → inserver_graph

Single Uvicorn worker — consumer loop shares the event loop.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import settings
from executor import run_maintenance_task

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)

_QUEUE_KEY = f"mas:{settings.queue_name}_queue" if hasattr(settings, "queue_name") else "mas:inserver_queue"
_BLPOP_TIMEOUT = 5


async def _consumer_loop(
    redis: aioredis.Redis,
    db_factory: async_sessionmaker,
    stop: asyncio.Event,
) -> None:
    log.info("inserver-agent consumer started, listening on %s", _QUEUE_KEY)
    while not stop.is_set():
        try:
            result = await redis.blpop(_QUEUE_KEY, timeout=_BLPOP_TIMEOUT)
        except Exception as exc:
            log.error("consumer redis error: %s — retrying in 5s", exc)
            await asyncio.sleep(5)
            continue

        if result is None:
            continue

        _, raw = result
        try:
            task = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.error("consumer: invalid JSON: %s", exc)
            continue

        async with db_factory() as session:
            await run_maintenance_task(task, session)

    log.info("inserver-agent consumer stopped")


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    db_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    redis = aioredis.from_url(settings.redis_url, decode_responses=False)

    stop = asyncio.Event()
    app.state.stop = stop
    consumer = asyncio.create_task(_consumer_loop(redis, db_factory, stop))

    log.info("inserver-agent ready on port 8002")
    yield

    stop.set()
    try:
        await asyncio.wait_for(consumer, timeout=10)
    except asyncio.TimeoutError:
        consumer.cancel()
    await redis.aclose()
    await engine.dispose()


app = FastAPI(
    title="InServer Agent",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "inserver-agent"}
