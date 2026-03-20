"""
Report endpoints (API key required):
  GET /reports/daily           latest daily snapshot summary
  GET /reports/daily/{date}    specific date (YYYY-MM-DD)
  GET /reports/weekly          last 7 days aggregated
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shared.db import get_db

from auth import require_api_key
from limiter import limiter

router = APIRouter(tags=["reports"])


@router.get("/reports/daily")
@limiter.limit("30/minute")
async def get_latest_daily_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(require_api_key),
):
    """Return the most recent daily health snapshot for all servers."""
    result = await db.execute(text("""
        SELECT DISTINCT ON (server_id)
            server_id, date, status, metrics_json, created_at
        FROM daily_health_snapshots
        ORDER BY server_id, date DESC
    """))
    rows = result.mappings().all()
    return {
        "report_type": "daily",
        "generated_for": str(date.today()),
        "servers": [dict(r) for r in rows],
        "total_servers": len(rows),
        "healthy": sum(1 for r in rows if r["status"] == "ok"),
        "degraded": sum(1 for r in rows if r["status"] == "warn"),
        "critical": sum(1 for r in rows if r["status"] == "critical"),
    }


@router.get("/reports/daily/{report_date}")
@limiter.limit("30/minute")
async def get_daily_report(
    request: Request,
    report_date: date,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(require_api_key),
):
    """Return daily health snapshots for a specific date."""
    result = await db.execute(text("""
        SELECT server_id, date, status, metrics_json, created_at
        FROM daily_health_snapshots
        WHERE date = :d
        ORDER BY server_id
    """), {"d": report_date})
    rows = result.mappings().all()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No snapshot data for {report_date}")
    return {
        "report_type": "daily",
        "date": str(report_date),
        "servers": [dict(r) for r in rows],
    }


@router.get("/reports/weekly")
@limiter.limit("30/minute")
async def get_weekly_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(require_api_key),
):
    """Return last 7 days of health + ticket stats."""
    since = date.today() - timedelta(days=7)

    snapshots = await db.execute(text("""
        SELECT server_id, date, status
        FROM daily_health_snapshots
        WHERE date >= :since
        ORDER BY date DESC
    """), {"since": since})

    tickets = await db.execute(text("""
        SELECT
            status,
            COUNT(*) as count
        FROM tickets
        WHERE created_at >= :since
        GROUP BY status
    """), {"since": since})

    ticket_rows = tickets.mappings().all()
    ticket_summary = {r["status"]: r["count"] for r in ticket_rows}

    return {
        "report_type": "weekly",
        "period_start": str(since),
        "period_end": str(date.today()),
        "snapshots": [dict(r) for r in snapshots.mappings().all()],
        "ticket_summary": ticket_summary,
        "total_tickets": sum(ticket_summary.values()),
    }
