"""
Agent Orchestrator — FastAPI application.

Port: 8001
Responsibilities:
  - Serve internal HTTP API (routes.py)
  - Start Redis consumer loop (consumer.py)
  - Start APScheduler cron jobs (scheduler_jobs.py)
  - Manage worker pool (worker_pool.py)
  - Initialise Langfuse tracer (langfuse_tracer.py)

Startup order:
  1. DB engine + session factory
  2. Redis connection
  3. Worker pool (start watchdog)
  4. Langfuse tracer init
  5. APScheduler start + register cron jobs
  6. Consumer loop (asyncio.Task)
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import langfuse_tracer
import worker_pool as pool_mod
from config import settings
from consumer import run_consumer
from routes import router
from scheduler_jobs import register_jobs

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. DB
    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    db_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    app.state.db_factory = db_factory

    # 2. Redis
    redis = aioredis.from_url(settings.redis_url, decode_responses=False)
    app.state.redis = redis

    # 3. Worker pool
    pool = pool_mod.init_pool()
    pool.start()

    # 4. Langfuse
    langfuse_tracer.init_tracer()

    # 5. APScheduler (AsyncIO scheduler with PostgreSQL job store)
    jobstores = {
        "default": SQLAlchemyJobStore(url=settings.postgres_dsn_sync, tablename="apscheduler_jobs")
    }
    executors = {"default": AsyncIOExecutor()}
    scheduler = AsyncIOScheduler(jobstores=jobstores, executors=executors)
    register_jobs(scheduler, redis, db_factory)
    scheduler.start()
    app.state.scheduler = scheduler

    # 6. Consumer loop
    stop_event = asyncio.Event()
    app.state.consumer_stop = stop_event
    consumer_task = asyncio.create_task(run_consumer(redis, db_factory, stop_event))
    app.state.consumer_task = consumer_task

    log.info("agent-orchestrator ready on port 8001")
    yield

    # Shutdown
    stop_event.set()
    try:
        await asyncio.wait_for(consumer_task, timeout=10)
    except asyncio.TimeoutError:
        consumer_task.cancel()

    scheduler.shutdown(wait=False)
    await pool.stop()
    langfuse_tracer.flush()
    await redis.aclose()
    await engine.dispose()
    log.info("agent-orchestrator shutdown complete")


app = FastAPI(
    title="Agent Orchestrator",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.include_router(router)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "agent-orchestrator"}
