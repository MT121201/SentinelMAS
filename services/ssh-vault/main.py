"""
SSH Vault Service — FastAPI application entry point.

Internal network only — never exposed publicly.
Port: 8100
"""

import logging
import os
import sys

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import settings
from routes import router
import session_registry as sr

# ── Structured logging setup ───────────────────────────────────────────────────
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.log_level.upper(), logging.INFO)
    )
)
log = structlog.get_logger()

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="SSH Vault",
    version="0.1.0",
    docs_url=None if os.environ.get("ENV") == "production" else "/docs",
    redoc_url=None,
)

app.include_router(router)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.on_event("startup")
async def startup() -> None:
    sr.registry = sr.SessionRegistry(default_ttl=settings.session_ttl_seconds)
    sr.registry.start()
    log.info("ssh_vault_started", ttl=settings.session_ttl_seconds)


@app.on_event("shutdown")
async def shutdown() -> None:
    if sr.registry:
        await sr.registry.stop()
    log.info("ssh_vault_stopped")


@app.get("/health")
async def health():
    from shared.db import engine
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:
        db_status = f"error: {exc}"

    active_sessions = len(sr.registry._sessions) if sr.registry else 0
    return JSONResponse({
        "status": "ok" if db_status == "ok" else "degraded",
        "service": "ssh-vault",
        "version": "0.1.0",
        "dependencies": {"postgres": db_status},
        "metrics": {"active_sessions": active_sessions},
    })
