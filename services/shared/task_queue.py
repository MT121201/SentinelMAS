"""
Redis-backed task queue.

Producers (api-gateway, scheduler):
    await enqueue("client", task_dict)

Consumers (agent containers):
    async for task in consume("client"):
        await handle(task)

Queue key pattern: mas:{queue_name}_queue
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from shared.redis_client import get_redis

logger = logging.getLogger(__name__)

_QUEUE_PREFIX = "mas"
_BLOCK_TIMEOUT = 5  # seconds to block on BLPOP before looping (allows graceful shutdown)


def _key(queue_name: str) -> str:
    return f"{_QUEUE_PREFIX}:{queue_name}_queue"


async def enqueue(queue_name: str, task: dict[str, Any]) -> None:
    """
    Push a task dict onto the right end of the Redis list.
    Consumers BLPOP from the left, so this is FIFO.
    """
    redis = await get_redis()
    payload = json.dumps(task)
    await redis.rpush(_key(queue_name), payload)
    logger.debug("enqueued task to %s: %s", queue_name, task.get("task_id", "?"))


async def queue_depth(queue_name: str) -> int:
    """Return the number of pending tasks in a queue."""
    redis = await get_redis()
    return await redis.llen(_key(queue_name))


async def consume(queue_name: str, stop_event: asyncio.Event | None = None) -> AsyncIterator[dict]:
    """
    Async generator that yields tasks from the queue one at a time.
    Blocks (BLPOP) for up to _BLOCK_TIMEOUT seconds, then loops.
    Exits cleanly when stop_event is set.

    Usage:
        stop = asyncio.Event()
        async for task in consume("client", stop):
            await handle(task)
    """
    redis = await get_redis()
    key = _key(queue_name)
    while True:
        if stop_event and stop_event.is_set():
            break
        result = await redis.blpop(key, timeout=_BLOCK_TIMEOUT)
        if result is None:
            continue  # timeout — loop and check stop_event
        _, raw = result
        try:
            task = json.loads(raw)
            yield task
        except json.JSONDecodeError:
            logger.error("Malformed task payload on queue %s: %r", queue_name, raw)
