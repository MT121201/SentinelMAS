"""
Ops endpoints (API key required):
  GET  /ops/agents      live agent states (populated by orchestrator in Phase 4)
  GET  /ops/queue       Redis queue depths + ticket stats
  GET  /ops/cost        rate limiter utilisation + daily USD spend
  POST /ops/cost/reset  reset daily cost counter
  GET  /ops/servers     server fleet from credentials table
"""

import json
from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shared.db import get_db
from shared.rate_limiter import get_utilisation, reset_daily_cost
from shared.redis_client import get_redis
from shared.task_queue import queue_depth

from auth import require_api_key
from limiter import limiter
from models import CostSummary, QueueStats

router = APIRouter(tags=["ops"])

_QUEUE_NAMES = ["client", "inserver", "report"]


@router.get("/ops/agents")
@limiter.limit("30/minute")
async def get_agents(
    request: Request,
    _key: str = Depends(require_api_key),
):
    """
    Live agent state overview.
    Orchestrator writes to Redis key mas:agent:states (Phase 4).
    Returns empty list until orchestrator is running.
    """
    redis = await get_redis()
    raw = await redis.get("mas:agent:states")
    agents = json.loads(raw) if raw else []
    return {"agents": agents, "total": len(agents)}


@router.get("/ops/queue")
@limiter.limit("30/minute")
async def get_queue_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(require_api_key),
):
    """Queue depths from Redis + ticket status counts from Postgres."""
    # Redis queue depths
    queues = []
    for name in _QUEUE_NAMES:
        depth = await queue_depth(name)
        queues.append({"queue": name, "pending": depth})

    # Ticket status counts (today)
    result = await db.execute(text("""
        SELECT status, COUNT(*) as count
        FROM tickets
        WHERE DATE(created_at) = CURRENT_DATE
        GROUP BY status
    """))
    status_counts = {r["status"]: r["count"] for r in result.mappings().all()}

    return {
        "queues": queues,
        "tickets_today": status_counts,
        "completed_today": status_counts.get("done", 0),
        "failed_today": status_counts.get("failed", 0),
        "escalated_today": status_counts.get("escalated", 0),
    }


@router.get("/ops/cost", response_model=CostSummary)
@limiter.limit("30/minute")
async def get_cost(
    request: Request,
    _key: str = Depends(require_api_key),
):
    """Current rate limiter utilisation and daily token spend."""
    util = await get_utilisation()
    return CostSummary(
        date=str(date.today()),
        total_cost_usd=util["daily_cost_usd"],
        limit_usd=util["daily_cost_limit_usd"],
        utilisation_pct=util["daily_cost_pct"],
        rpm_used=util["rpm_used"],
        rpm_limit=util["rpm_limit"],
        tpm_used=util["tpm_used"],
        tpm_limit=util["tpm_limit"],
    )


@router.post("/ops/cost/reset", status_code=200)
@limiter.limit("10/minute")
async def reset_cost(
    request: Request,
    _key: str = Depends(require_api_key),
):
    """Manually reset daily cost counter (use after reviewing spend)."""
    await reset_daily_cost()
    return {"status": "reset", "message": "Daily cost counter cleared"}


@router.get("/ops/servers")
@limiter.limit("30/minute")
async def get_servers(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(require_api_key),
):
    """Fleet overview — non-sensitive columns from server_credentials."""
    result = await db.execute(text("""
        SELECT s.server_id, s.display_name, s.hostname, s.port, s.is_active,
               d.date AS last_snapshot_date, d.status AS health_status
        FROM server_credentials s
        LEFT JOIN LATERAL (
            SELECT date, status FROM daily_health_snapshots
            WHERE server_id = s.server_id
            ORDER BY date DESC LIMIT 1
        ) d ON true
        ORDER BY s.server_id
    """))
    rows = result.mappings().all()
    return {"servers": [dict(r) for r in rows], "total": len(rows)}
