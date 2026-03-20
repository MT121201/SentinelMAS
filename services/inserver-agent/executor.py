"""
Executor — receives a maintenance task from the queue and runs the inserver graph.

Responsibilities:
  1. Deserialise task dict → initial state
  2. Run inserver_graph.ainvoke()
  3. Report final status back to orchestrator via PUT /internal/tasks/{id}/status
"""

import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from graph import inserver_graph

log = logging.getLogger(__name__)


async def run_maintenance_task(task: dict, db: AsyncSession) -> None:
    """
    Entry point called by the consumer loop for each maintenance task.

    task keys: task_id, trace_id, task_type, server_id, created_at
    """
    task_id = task.get("task_id", "unknown")
    trace_id = task.get("trace_id", task_id)

    log.info("executor: starting maintenance task_id=%s", task_id)

    initial_state = {
        "task_id": task_id,
        "trace_id": trace_id,
        "task_type": "maintenance",
        "assigned_agent": "inserver-agent",
        "severity": None,
        "ticket_id": None,
        "user_message": None,
        "server_id": task.get("server_id"),   # if set, only check this server; else check all
        "rag_hits": [],
        "web_search_results": [],
        "action_plan": [],
        "execution_log": [],
        "status": "thinking",
        "resolution_summary": None,
        "error": None,
        "created_at": _parse_dt(task.get("created_at")) or datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "server_list": [],
        "server_results": {},
    }

    try:
        await _report_status(task_id, "thinking")

        final_state = await inserver_graph.ainvoke(
            initial_state,
            config={"configurable": {"db": db}},
        )

        status = final_state.get("status", "done")
        summary = final_state.get("resolution_summary", "")
        await _report_status(task_id, status, resolution_summary=summary)
        log.info("executor: maintenance task_id=%s completed → %s", task_id, status)

    except Exception as exc:
        log.error("executor: maintenance task_id=%s failed: %s", task_id, exc)
        await _report_status(task_id, "failed", error=str(exc))


async def _report_status(
    task_id: str,
    status: str,
    resolution_summary: str | None = None,
    error: str | None = None,
) -> None:
    """Notify orchestrator of task status change."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.put(
                f"{settings.orchestrator_url}/internal/tasks/{task_id}/status",
                json={"status": status, "resolution_summary": resolution_summary, "error": error},
                headers={"X-Internal-Key": settings.internal_api_key},
            )
    except Exception as exc:
        log.warning("executor: failed to report status for task %s: %s", task_id, exc)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
