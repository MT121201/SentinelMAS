"""
Redis queue consumer loop.

Listens on the orchestrator intake queue (mas:orchestrator_queue) via BLPOP.
For each task, runs the supervisor LangGraph graph via the worker pool.

Also listens on specialist queues when in passthrough mode — tasks pushed
directly by api-gateway (e.g. mas:client_queue) are consumed by this loop
and forwarded through the supervisor for validation + DB status update.

Queue priority (BLPOP polls all in order, returns first available):
  1. mas:orchestrator_queue   ← primary intake (POST /internal/tasks)
  2. mas:client_queue         ← api-gateway direct push (tickets)
  3. mas:inserver_queue       ← admin maintenance trigger
  4. mas:report_queue         ← scheduler jobs
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import settings
from state import AgentState
from supervisor import supervisor_graph
from worker_pool import get_pool

log = logging.getLogger(__name__)

_QUEUES = [
    f"mas:{settings.queue_orchestrator}_queue",
    f"mas:{settings.queue_client}_queue",
    f"mas:{settings.queue_inserver}_queue",
    f"mas:{settings.queue_report}_queue",
]

_BLPOP_TIMEOUT = 5  # seconds — allows graceful shutdown checks


async def _process_task(
    raw: bytes,
    redis: aioredis.Redis,
    db_factory: async_sessionmaker,
) -> None:
    """Deserialise task and run it through the supervisor graph."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("consumer: invalid JSON in queue: %s", exc)
        return

    task_id = data.get("task_id", "unknown")
    log.info("consumer: received task_id=%s type=%s", task_id, data.get("task_type"))

    # Build initial AgentState
    now = datetime.now(timezone.utc)
    state: AgentState = {
        "task_id": task_id,
        "trace_id": data.get("trace_id", task_id),
        "task_type": data.get("task_type", "unknown"),
        "assigned_agent": None,
        "severity": data.get("severity"),
        "ticket_id": data.get("ticket_id"),
        "user_message": data.get("user_message"),
        "server_id": data.get("server_id"),
        "rag_hits": [],
        "web_search_results": [],
        "action_plan": [],
        "execution_log": [],
        "status": "queued",
        "resolution_summary": None,
        "error": None,
        "created_at": _parse_dt(data.get("created_at")) or now,
        "updated_at": now,
    }

    async def _run():
        async with db_factory() as session:
            await supervisor_graph.ainvoke(
                state,
                config={"configurable": {"redis": redis, "db": session}},
            )

    pool = get_pool()
    await pool.dispatch(task_id, _run())


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


async def run_consumer(
    redis: aioredis.Redis,
    db_factory: async_sessionmaker,
    stop_event: asyncio.Event,
) -> None:
    """
    BLPOP consumer loop. Runs until stop_event is set.
    Each received message is dispatched to the worker pool (non-blocking).
    """
    log.info("consumer starting — watching queues: %s", _QUEUES)
    while not stop_event.is_set():
        try:
            result = await redis.blpop(_QUEUES, timeout=_BLPOP_TIMEOUT)
        except Exception as exc:
            log.error("consumer: redis error: %s — retrying in 5s", exc)
            await asyncio.sleep(5)
            continue

        if result is None:
            # Timeout — loop back and check stop_event
            continue

        _queue_key, raw = result
        await _process_task(raw, redis, db_factory)

    log.info("consumer: stop signal received, exiting")
