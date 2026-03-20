"""
Executor — receives a ticket task and runs the client agent graph.
"""

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from graph import client_graph

log = logging.getLogger(__name__)


async def run_ticket_task(task: dict, db: AsyncSession) -> None:
    task_id = task.get("task_id", "unknown")
    ticket_id = task.get("ticket_id") or task_id
    trace_id = task.get("trace_id", task_id)

    log.info("executor: starting ticket task_id=%s ticket_id=%s", task_id, ticket_id)

    initial_state = {
        "task_id": task_id,
        "trace_id": trace_id,
        "task_type": "ticket",
        "assigned_agent": "client-agent",
        "severity": task.get("severity"),
        "ticket_id": str(ticket_id),
        "user_message": task.get("user_message", ""),
        "server_id": task.get("server_id"),
        "rag_hits": [],
        "web_search_results": [],
        "action_plan": [],
        "execution_log": [],
        "status": "thinking",
        "resolution_summary": None,
        "error": None,
        "resolved": False,
        "retry_count": 0,
        "created_at": _parse_dt(task.get("created_at")) or datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    try:
        await _report_status(task_id, "thinking")
        final_state = await client_graph.ainvoke(
            initial_state,
            config={"configurable": {"db": db}},
        )
        status = final_state.get("status", "done")
        summary = final_state.get("resolution_summary")
        await _report_status(task_id, status, resolution_summary=summary)
        log.info("executor: ticket %s completed → %s", ticket_id, status)
    except Exception as exc:
        log.error("executor: ticket %s failed: %s", ticket_id, exc)
        await _report_status(task_id, "failed", error=str(exc))


async def _report_status(
    task_id: str,
    status: str,
    resolution_summary: str | None = None,
    error: str | None = None,
) -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.put(
                f"{settings.orchestrator_url}/internal/tasks/{task_id}/status",
                json={"status": status, "resolution_summary": resolution_summary, "error": error},
                headers={"X-Internal-Key": settings.internal_api_key},
            )
    except Exception as exc:
        log.warning("executor: status report failed for %s: %s", task_id, exc)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
