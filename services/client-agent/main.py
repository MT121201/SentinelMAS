"""
Client Agent — FastAPI application.

Port: 8003
Consumes: mas:client_queue (Redis BLPOP)
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import settings
from executor import run_ticket_task

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)

_QUEUE_KEY = "mas:client_queue"
_BLPOP_TIMEOUT = 5


async def _consumer_loop(
    redis: aioredis.Redis,
    db_factory: async_sessionmaker,
    stop: asyncio.Event,
) -> None:
    log.info("client-agent consumer started, listening on %s", _QUEUE_KEY)
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
            await run_ticket_task(task, session)

    log.info("client-agent consumer stopped")


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    db_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    redis = aioredis.from_url(settings.redis_url, decode_responses=False)

    stop = asyncio.Event()
    consumer = asyncio.create_task(_consumer_loop(redis, db_factory, stop))

    log.info("client-agent ready on port 8003")
    yield

    stop.set()
    try:
        await asyncio.wait_for(consumer, timeout=10)
    except asyncio.TimeoutError:
        consumer.cancel()
    await redis.aclose()
    await engine.dispose()


app = FastAPI(
    title="Client Agent",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "client-agent"}
