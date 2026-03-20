"""
Ops dashboard endpoint — live agent/queue state for the ops.html page.

GET /ops/dashboard  — returns JSON snapshot consumed by ops.html auto-refresh.
                      No auth required (internal network only, behind nginx).
                      Data is read-only and contains no PII.
"""

import json
from datetime import date

from fastapi import APIRouter
from sqlalchemy import text

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.db import get_db
from shared.rate_limiter import get_utilisation
from shared.redis_client import get_redis
from shared.task_queue import queue_depth

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["ops"])

_QUEUE_NAMES = ["client", "inserver", "report", "orchestrator"]


@router.get("/ops/dashboard")
async def ops_dashboard(
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregate snapshot for the ops HTML page.
    Combines: agent states, queue depths, ticket counts, cost utilisation.
    Refreshed every 10s by ops.html.
    """
    redis = await get_redis()

    # Agent states (written by orchestrator)
    raw_agents = await redis.get("mas:agent:states")
    agents = json.loads(raw_agents) if raw_agents else []

    # Queue depths
    queues = []
    total_pending = 0
    for name in _QUEUE_NAMES:
        depth = await queue_depth(name)
        total_pending += depth
        queues.append({"queue": name, "pending": depth})

    # Ticket counts for today
    result = await db.execute(text("""
        SELECT status, COUNT(*) AS count
        FROM tickets
        WHERE DATE(created_at) = CURRENT_DATE
        GROUP BY status
    """))
    ticket_counts = {r["status"]: int(r["count"]) for r in result.mappings().all()}
    total_today = sum(ticket_counts.values())
    done_today = ticket_counts.get("done", 0)
    resolution_rate = round(done_today / total_today * 100, 1) if total_today > 0 else 0.0

    # Cost / rate limit utilisation
    util = await get_utilisation()

    return {
        "timestamp": date.today().isoformat(),
        "agents": {
            "active": agents,
            "count": len(agents),
        },
        "queues": queues,
        "total_pending": total_pending,
        "tickets_today": {
            "total": total_today,
            "done": done_today,
            "failed": ticket_counts.get("failed", 0),
            "escalated": ticket_counts.get("escalated", 0),
            "in_progress": ticket_counts.get("queued", 0) + ticket_counts.get("executing", 0),
            "resolution_rate_pct": resolution_rate,
        },
        "cost": {
            "daily_usd": util.get("daily_cost_usd", 0.0),
            "daily_limit_usd": util.get("daily_cost_limit_usd", 50.0),
            "daily_pct": util.get("daily_cost_pct", 0.0),
            "rpm_used": util.get("rpm_used", 0),
            "rpm_limit": util.get("rpm_limit", 60),
            "tpm_used": util.get("tpm_used", 0),
            "tpm_limit": util.get("tpm_limit", 100000),
        },
    }
