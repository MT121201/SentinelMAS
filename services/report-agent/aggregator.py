"""
Data aggregator — fetches all metrics needed for reports from Postgres and Redis.

Provides two aggregation windows:
  daily  — last 24h (or specific date)
  weekly — last 7 days

All queries return plain dicts — no ORM models — so formatter.py has no DB dependency.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings

log = logging.getLogger(__name__)


# ── Fleet health ──────────────────────────────────────────────────────────────


async def get_fleet_health(
    db: AsyncSession,
    report_date: date | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch daily_health_snapshots for report_date (defaults to today).
    Returns list of {server_id, date, status, metrics_json}.
    """
    target = report_date or date.today()
    result = await db.execute(
        text(
            """
            SELECT s.id AS server_id,
                   s.hostname,
                   h.date,
                   h.status,
                   h.metrics_json
            FROM daily_health_snapshots h
            JOIN server_credentials s ON s.id = h.server_id
            WHERE h.date = :date
            ORDER BY s.id
            """
        ),
        {"date": target.isoformat()},
    )
    rows = result.fetchall()
    return [
        {
            "server_id": r.server_id,
            "hostname": r.hostname,
            "date": str(r.date),
            "status": r.status,
            "metrics": r.metrics_json or {},
        }
        for r in rows
    ]


async def get_fleet_health_range(
    db: AsyncSession,
    days: int = 7,
) -> dict[str, list[dict]]:
    """
    Fetch health snapshots for last `days` days, grouped by server_id.
    Used for weekly trend analysis.
    """
    since = (date.today() - timedelta(days=days)).isoformat()
    result = await db.execute(
        text(
            """
            SELECT s.id AS server_id, s.hostname, h.date, h.status
            FROM daily_health_snapshots h
            JOIN server_credentials s ON s.id = h.server_id
            WHERE h.date >= :since
            ORDER BY s.id, h.date
            """
        ),
        {"since": since},
    )
    grouped: dict[str, list] = {}
    for r in result.fetchall():
        key = str(r.server_id)
        grouped.setdefault(key, []).append(
            {"date": str(r.date), "status": r.status, "hostname": r.hostname}
        )
    return grouped


# ── Ticket stats ──────────────────────────────────────────────────────────────


async def get_ticket_stats(
    db: AsyncSession,
    since: datetime | None = None,
) -> dict[str, Any]:
    """
    Aggregate ticket counts, resolution rate, avg resolution time, escalations.
    since defaults to 24h ago for daily, or 7 days for weekly (caller sets this).
    """
    since = since or (datetime.now(timezone.utc) - timedelta(hours=24))

    result = await db.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE created_at >= :since)                          AS total,
                COUNT(*) FILTER (WHERE status = 'done' AND updated_at >= :since)      AS resolved,
                COUNT(*) FILTER (WHERE status = 'failed' AND updated_at >= :since)    AS failed,
                COUNT(*) FILTER (WHERE status = 'escalated' AND updated_at >= :since) AS escalated,
                COUNT(*) FILTER (WHERE status IN ('queued','assigned','thinking',
                                 'executing','verifying'))                             AS in_progress,
                ROUND(AVG(
                    EXTRACT(EPOCH FROM (updated_at - created_at)) / 60.0
                ) FILTER (WHERE status = 'done' AND updated_at >= :since), 1)         AS avg_resolution_min
            FROM tickets
            WHERE created_at >= :since
            """
        ),
        {"since": since},
    )
    row = result.fetchone()
    total = row.total or 0
    resolved = row.resolved or 0
    return {
        "total": total,
        "resolved": resolved,
        "failed": row.failed or 0,
        "escalated": row.escalated or 0,
        "in_progress": row.in_progress or 0,
        "resolution_rate_pct": round(resolved / total * 100, 1) if total > 0 else 0.0,
        "avg_resolution_min": float(row.avg_resolution_min or 0),
    }


async def get_recent_escalations(
    db: AsyncSession,
    since: datetime | None = None,
    limit: int = 10,
) -> list[dict]:
    """Fetch recent escalated tickets for the Alerts section."""
    since = since or (datetime.now(timezone.utc) - timedelta(days=7))
    result = await db.execute(
        text(
            """
            SELECT id, server_id, severity, description, resolution_summary, created_at
            FROM tickets
            WHERE status = 'escalated' AND created_at >= :since
            ORDER BY created_at DESC
            LIMIT :limit
            """
        ),
        {"since": since, "limit": limit},
    )
    return [
        {
            "ticket_id": r.id,
            "server_id": r.server_id,
            "severity": r.severity,
            "description": (r.description or "")[:120],
            "summary": r.resolution_summary,
            "created_at": str(r.created_at),
        }
        for r in result.fetchall()
    ]


# ── Cost data ─────────────────────────────────────────────────────────────────


async def get_cost_summary(redis) -> dict[str, Any]:
    """
    Fetch cost + rate limit utilisation from Redis (populated by rate_limiter.py).
    Falls back to zeros if keys are absent.
    """
    try:
        daily_cost = await redis.get("mas:cost:daily_usd")
        rpm_used = await redis.get("mas:rate_limit:rpm")
        tpm_used = await redis.get("mas:rate_limit:tpm")

        return {
            "daily_cost_usd": float(daily_cost or 0),
            "rpm_used": int(rpm_used or 0),
            "tpm_used": int(tpm_used or 0),
        }
    except Exception as exc:
        log.warning("get_cost_summary: redis error: %s", exc)
        return {"daily_cost_usd": 0.0, "rpm_used": 0, "tpm_used": 0}


async def get_weekly_cost(db: AsyncSession) -> dict[str, Any]:
    """
    Estimate weekly cost from ticket volume (proxy until Langfuse is wired in Phase 8).
    Reads rate_limiter Redis keys — only the current day's live counter is available.
    Weekly total is a best-effort estimate.
    """
    # For now, return what we have from Redis — Langfuse integration in Phase 8
    return {
        "note": "Full weekly cost breakdown available after Langfuse integration (Phase 8)",
        "current_day_usd": 0.0,
    }


# ── Full aggregation entry points ─────────────────────────────────────────────


async def aggregate_daily(
    db: AsyncSession,
    redis,
    report_date: date | None = None,
) -> dict[str, Any]:
    """Gather all data needed for a daily report."""
    target = report_date or date.today()
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    fleet = await get_fleet_health(db, target)
    tickets = await get_ticket_stats(db, since_24h)
    escalations = await get_recent_escalations(db, since_24h)
    cost = await get_cost_summary(redis)

    return {
        "period": "daily",
        "date": target.isoformat(),
        "fleet": fleet,
        "tickets": tickets,
        "escalations": escalations,
        "cost": cost,
    }


async def aggregate_weekly(
    db: AsyncSession,
    redis,
) -> dict[str, Any]:
    """Gather all data needed for a weekly report."""
    since_7d = datetime.now(timezone.utc) - timedelta(days=7)

    fleet_range = await get_fleet_health_range(db, days=7)
    tickets = await get_ticket_stats(db, since_7d)
    escalations = await get_recent_escalations(db, since_7d, limit=20)
    cost = await get_cost_summary(redis)
    weekly_cost = await get_weekly_cost(db)

    # Compute per-server uptime pct from health snapshots
    server_uptime: dict[str, float] = {}
    for server_id, days_data in fleet_range.items():
        healthy_days = sum(1 for d in days_data if d["status"] == "healthy")
        server_uptime[server_id] = round(healthy_days / max(len(days_data), 1) * 100, 1)

    return {
        "period": "weekly",
        "date_range": f"{(date.today() - timedelta(days=7)).isoformat()} to {date.today().isoformat()}",
        "fleet_range": fleet_range,
        "server_uptime_pct": server_uptime,
        "tickets": tickets,
        "escalations": escalations,
        "cost": cost,
        "weekly_cost": weekly_cost,
    }
