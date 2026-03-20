"""
APScheduler cron jobs.

Jobs registered at startup:
  daily_inserver_check  — 00:05 UTC daily — enqueue maintenance task for every active server
  weekly_report         — 06:00 UTC Monday — enqueue weekly report generation task
  hourly_cache_cleanup  — :00 every hour  — log Redis cache stats (TTL auto-expires keys)

All jobs push tasks onto Redis queues consumed by the orchestrator consumer loop.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

log = logging.getLogger(__name__)


async def daily_inserver_check(
    redis: aioredis.Redis,
    db_factory: async_sessionmaker,
) -> None:
    """
    Fetch all active servers from DB and enqueue a maintenance task for each.
    Pushed to mas:orchestrator_queue → routed to inserver-agent.
    """
    log.info("scheduler: daily_inserver_check starting")
    try:
        async with db_factory() as session:
            result = await session.execute(
                text("SELECT id FROM server_credentials WHERE is_active = true")
            )
            server_ids = [str(row.id) for row in result.fetchall()]

        if not server_ids:
            log.info("scheduler: no active servers found — skipping maintenance tasks")
            return

        for server_id in server_ids:
            task_id = str(uuid.uuid4())
            payload = json.dumps({
                "task_id": task_id,
                "trace_id": task_id,
                "task_type": "maintenance",
                "server_id": server_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            await redis.rpush("mas:orchestrator_queue", payload)
            log.info("scheduler: enqueued maintenance task %s for server %s", task_id, server_id)

        log.info("scheduler: daily_inserver_check enqueued %d tasks", len(server_ids))
    except Exception as exc:
        log.error("scheduler: daily_inserver_check failed: %s", exc)


async def weekly_report(redis: aioredis.Redis) -> None:
    """
    Enqueue a weekly report generation task.
    Pushed to mas:orchestrator_queue → routed to report-agent.
    """
    log.info("scheduler: weekly_report starting")
    try:
        task_id = str(uuid.uuid4())
        payload = json.dumps({
            "task_id": task_id,
            "trace_id": task_id,
            "task_type": "report",
            "report_period": "weekly",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await redis.rpush("mas:orchestrator_queue", payload)
        log.info("scheduler: enqueued weekly report task %s", task_id)
    except Exception as exc:
        log.error("scheduler: weekly_report failed: %s", exc)


async def hourly_cache_cleanup(redis: aioredis.Redis) -> None:
    """
    Log Redis key counts per category. TTL auto-expires keys — no manual cleanup needed.
    This job is a health-check / observability hook, not a hard cleaner.
    """
    try:
        rag_keys = len([k async for k in redis.scan_iter("mas:rag_cache:*")])
        rate_keys = len([k async for k in redis.scan_iter("mas:rate_limit:*")])
        agent_state_key = await redis.exists("mas:agent:states")
        log.info(
            "scheduler: cache snapshot — rag_cache=%d rate_limit=%d agent_states=%d",
            rag_keys,
            rate_keys,
            agent_state_key,
        )
    except Exception as exc:
        log.warning("scheduler: hourly_cache_cleanup failed: %s", exc)


def register_jobs(scheduler, redis: aioredis.Redis, db_factory: async_sessionmaker) -> None:
    """
    Register all cron jobs with the APScheduler instance.
    Uses async-compatible trigger types.
    """
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(
        daily_inserver_check,
        trigger=CronTrigger(hour=0, minute=5, timezone="UTC"),
        id="daily_inserver_check",
        replace_existing=True,
        kwargs={"redis": redis, "db_factory": db_factory},
        name="Daily InServer Health Check",
    )

    scheduler.add_job(
        weekly_report,
        trigger=CronTrigger(day_of_week="mon", hour=6, minute=0, timezone="UTC"),
        id="weekly_report",
        replace_existing=True,
        kwargs={"redis": redis},
        name="Weekly Report Generation",
    )

    scheduler.add_job(
        hourly_cache_cleanup,
        trigger=CronTrigger(minute=0, timezone="UTC"),
        id="hourly_cache_cleanup",
        replace_existing=True,
        kwargs={"redis": redis},
        name="Hourly Cache Cleanup",
    )

    log.info("scheduler: registered 3 cron jobs")
