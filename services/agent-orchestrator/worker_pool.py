"""
Worker pool — bounded asyncio task dispatcher with stuck-task watchdog.

- Semaphore limits concurrent in-flight supervisor graph runs.
- Active task registry tracks start times for the watchdog.
- Watchdog fires every 60 s and logs/alerts any task running > stuck_threshold.
"""

import asyncio
import logging
from datetime import datetime, timezone

from config import settings

log = logging.getLogger(__name__)


class WorkerPool:
    """
    Manages concurrent LangGraph supervisor invocations.

    State fields:
        _sem           — asyncio.Semaphore(max_concurrent_tasks)
        _active        — dict[task_id → started_at datetime]
        _watchdog_task — asyncio background task handle
        _stop          — asyncio.Event to signal shutdown
    """

    def __init__(self, max_concurrent: int | None = None):
        max_concurrent = max_concurrent or settings.max_concurrent_tasks
        self._sem = asyncio.Semaphore(max_concurrent)
        self._active: dict[str, datetime] = {}
        self._watchdog_task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        """Start the watchdog loop. Call from main.py lifespan startup."""
        self._stop.clear()
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        log.info("worker pool started (max_concurrent=%d)", self._sem._value)

    async def stop(self) -> None:
        """Signal shutdown and wait for watchdog to finish."""
        self._stop.set()
        if self._watchdog_task:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass

    async def dispatch(self, task_id: str, coro) -> None:
        """
        Acquire a semaphore slot and run coro as a background task.
        Registers/deregisters the task in the active registry.
        """
        await self._sem.acquire()
        asyncio.create_task(self._run(task_id, coro))

    async def _run(self, task_id: str, coro) -> None:
        self._active[task_id] = datetime.now(timezone.utc)
        try:
            await coro
        except Exception as exc:
            log.error("task %s raised unhandled exception: %s", task_id, exc)
        finally:
            self._active.pop(task_id, None)
            self._sem.release()

    async def _watchdog_loop(self) -> None:
        """Every 60 s check for tasks stuck longer than stuck_threshold."""
        threshold = settings.stuck_task_threshold_seconds
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._stop.wait()), timeout=60
                )
            except asyncio.TimeoutError:
                pass

            now = datetime.now(timezone.utc)
            for task_id, started_at in list(self._active.items()):
                elapsed = (now - started_at).total_seconds()
                if elapsed > threshold:
                    log.error(
                        "STUCK TASK detected: task_id=%s running for %.0f s (threshold=%d s)",
                        task_id,
                        elapsed,
                        threshold,
                    )

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def active_tasks(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        return [
            {
                "task_id": tid,
                "started_at": started.isoformat(),
                "elapsed_seconds": (now - started).total_seconds(),
            }
            for tid, started in self._active.items()
        ]


# Module-level singleton — initialised in main.py lifespan
_pool: WorkerPool | None = None


def get_pool() -> WorkerPool:
    if _pool is None:
        raise RuntimeError("WorkerPool not initialised — call init_pool() first")
    return _pool


def init_pool(max_concurrent: int | None = None) -> WorkerPool:
    global _pool
    _pool = WorkerPool(max_concurrent)
    return _pool
