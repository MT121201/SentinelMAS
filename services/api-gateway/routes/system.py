"""
System endpoints (no auth required):
  GET /health   liveness + dependency check
  GET /metrics  Prometheus metrics (via instrumentator)
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shared.db import engine
from shared.redis_client import ping as redis_ping
from shared.rate_limiter import get_utilisation
from shared.task_queue import queue_depth

import sqlalchemy

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    # Postgres
    try:
        async with engine.connect() as conn:
            await conn.execute(sqlalchemy.text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:
        db_status = f"error: {exc}"

    # Redis
    redis_ok = await redis_ping()
    redis_status = "ok" if redis_ok else "error"

    # Queue depth
    client_depth = await queue_depth("client")
    inserver_depth = await queue_depth("inserver")

    # Rate limit utilisation
    util = await get_utilisation()

    overall = "ok" if db_status == "ok" and redis_status == "ok" else "degraded"

    return JSONResponse(
        status_code=200 if overall == "ok" else 503,
        content={
            "status": overall,
            "service": "api-gateway",
            "version": "0.1.0",
            "dependencies": {
                "postgres": db_status,
                "redis": redis_status,
            },
            "metrics": {
                "queue_client_pending": client_depth,
                "queue_inserver_pending": inserver_depth,
                "rate_limit_rpm_pct": util["rpm_pct"],
                "rate_limit_tpm_pct": util["tpm_pct"],
                "daily_cost_usd": util["daily_cost_usd"],
            },
        },
    )
