"""
RAG Service — FastAPI application.

Port: 8005
Lifespan:
  startup  → ensure Qdrant collection, build BM25 index from DB, preload reranker
  shutdown → nothing special (connections are pooled)
"""

import logging
import os

import redis.asyncio as aioredis
from contextlib import asynccontextmanager
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import bm25_index as bm25_mod
import vector_store
from config import settings
from reranker import preload_model
from routes import router

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB engine
    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    app.state.db_factory = factory

    # Redis
    redis = aioredis.from_url(settings.redis_url, decode_responses=False)
    app.state.redis = redis

    # Qdrant collection
    await vector_store.ensure_collection()

    # BM25 index
    async with factory() as session:
        await bm25_mod.init_index(session)

    # Reranker model (blocking load, done once)
    await preload_model()

    log.info("rag-service ready")
    yield

    await redis.aclose()
    await engine.dispose()


_is_dev = os.environ.get("ENV", "production").lower() == "development"

app = FastAPI(
    title="RAG Service",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _is_dev else None,
    redoc_url=None,
)

app.include_router(router)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "rag-service"}
