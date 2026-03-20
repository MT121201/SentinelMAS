"""
Agent-orchestrator internal HTTP API.

POST /internal/tasks           — enqueue a task from api-gateway
PUT  /internal/tasks/{id}/status — specialist agent reports status update
GET  /ops/agents               — live active task list from worker pool
GET  /ops/queue                — queue depths from Redis
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from worker_pool import get_pool

log = logging.getLogger(__name__)

router = APIRouter()


# ── Auth ───────────────────────────────────────────────────────────────────────


async def _require_internal_key(request: Request) -> None:
    key = request.headers.get("X-Internal-Key", "")
    if key != settings.internal_api_key:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Pydantic models ────────────────────────────────────────────────────────────


class EnqueueTaskRequest(BaseModel):
    task_type: Literal["ticket", "maintenance", "report", "unknown"] = "unknown"
    ticket_id: str | None = None
    server_id: str | None = None
    user_message: str | None = None
    severity: str | None = None
    trace_id: str | None = None


class EnqueueTaskResponse(BaseModel):
    task_id: str
    queued: bool


class StatusUpdateRequest(BaseModel):
    status: Literal[
        "queued", "assigned", "thinking", "executing", "verifying", "done", "failed", "escalated"
    ]
    resolution_summary: str | None = None
    error: str | None = None


# ── Dependencies ───────────────────────────────────────────────────────────────


async def _get_redis(request: Request):
    return request.app.state.redis


async def _get_db(request: Request) -> AsyncSession:
    async with request.app.state.db_factory() as session:
        yield session


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.post(
    "/internal/tasks",
    response_model=EnqueueTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(_require_internal_key)],
)
async def enqueue_task(
    body: EnqueueTaskRequest,
    redis=Depends(_get_redis),
):
    task_id = str(uuid.uuid4())
    trace_id = body.trace_id or task_id

    payload = json.dumps({
        "task_id": task_id,
        "trace_id": trace_id,
        "task_type": body.task_type,
        "ticket_id": body.ticket_id,
        "server_id": body.server_id,
        "user_message": body.user_message,
        "severity": body.severity,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await redis.rpush("mas:orchestrator_queue", payload)
    log.info("enqueued task_id=%s type=%s", task_id, body.task_type)
    return EnqueueTaskResponse(task_id=task_id, queued=True)


@router.put(
    "/internal/tasks/{task_id}/status",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(_require_internal_key)],
)
async def update_task_status(
    task_id: str,
    body: StatusUpdateRequest,
    db: AsyncSession = Depends(_get_db),
):
    """
    Specialist agents call this to report progress/completion.
    Updates the tickets table if ticket_id matches task_id or is derivable.
    """
    try:
        await db.execute(
            text(
                """
                UPDATE tickets
                SET status = :status,
                    resolution_summary = COALESCE(:summary, resolution_summary),
                    updated_at = now()
                WHERE trace_id = :task_id OR id::text = :task_id
                """
            ),
            {
                "status": body.status,
                "summary": body.resolution_summary,
                "task_id": task_id,
            },
        )
        await db.commit()
    except Exception as exc:
        log.warning("status update failed for task %s: %s", task_id, exc)

    log.info("task %s status → %s", task_id, body.status)
    return {"task_id": task_id, "status": body.status}


@router.get("/ops/agents")
async def get_agents():
    """Live view of active tasks in the worker pool."""
    try:
        pool = get_pool()
        return {
            "active_count": pool.active_count,
            "active_tasks": pool.active_tasks,
        }
    except RuntimeError:
        return {"active_count": 0, "active_tasks": []}


@router.get("/ops/queue")
async def get_queue_depths(redis=Depends(_get_redis)):
    """Queue depth for all managed Redis queues."""
    queues = [
        settings.queue_orchestrator,
        settings.queue_client,
        settings.queue_inserver,
        settings.queue_report,
    ]
    depths = {}
    for q in queues:
        key = f"mas:{q}_queue"
        depths[q] = await redis.llen(key)
    return {"queues": depths}
