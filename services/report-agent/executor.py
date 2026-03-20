"""
Executor for report tasks received from the orchestrator queue.

Deserialises the task dict, invokes the report graph, and reports
status back to the orchestrator via its internal API.
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from graph import report_graph

log = logging.getLogger(__name__)


async def run_report_task(task: dict, db: AsyncSession, redis) -> None:
    """
    Entry point called by the consumer loop for each report task.

    Expected task fields:
        task_id   — unique task ID
        period    — "daily" | "weekly"
        date      — ISO date string (optional, daily only)
        trace_id  — Langfuse trace ID (optional)
    """
    task_id = task.get("task_id", "unknown")
    period = task.get("period", "daily")
    report_date = task.get("date")
    trace_id = task.get("trace_id", "")

    log.info(
        "run_report_task: starting task_id=%s period=%s date=%s",
        task_id,
        period,
        report_date,
    )

    await _update_status(task_id, "executing")

    initial_state = {
        "task_id": task_id,
        "period": period,
        "report_date": report_date,
    }

    try:
        final_state = await report_graph.ainvoke(
            initial_state,
            config={"configurable": {"db": db, "redis": redis}},
        )
        outcome = final_state.get("status", "failed")
        delivery = final_state.get("delivery_result", {})
        error = final_state.get("error", "")

        if outcome == "done":
            log.info(
                "run_report_task: done task_id=%s delivery=%s",
                task_id,
                delivery,
            )
            await _update_status(task_id, "done", summary=f"Report delivered: {delivery}")
        else:
            log.error(
                "run_report_task: failed task_id=%s error=%s",
                task_id,
                error,
            )
            await _update_status(task_id, "failed", summary=error)

    except Exception as exc:
        log.exception("run_report_task: unhandled exception task_id=%s: %s", task_id, exc)
        await _update_status(task_id, "failed", summary=str(exc))


async def _update_status(task_id: str, status: str, summary: str = "") -> None:
    """
    Notify the orchestrator of the new task status.
    Fires-and-forgets on error — report delivery is not blocked by this.
    """
    url = f"{settings.orchestrator_url}/internal/tasks/{task_id}/status"
    payload: dict = {"status": status}
    if summary:
        payload["resolution_summary"] = summary[:500]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.put(
                url,
                json=payload,
                headers={"X-Internal-Key": settings.internal_api_key},
            )
            if not resp.is_success:
                log.warning(
                    "_update_status: orchestrator returned %s for task_id=%s",
                    resp.status_code,
                    task_id,
                )
    except Exception as exc:
        log.warning("_update_status: could not reach orchestrator: %s", exc)
