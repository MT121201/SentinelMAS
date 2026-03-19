"""
Async Redis client with connection pool.

Usage:
    from shared.redis_client import get_redis, close_redis

    redis = await get_redis()
    await redis.set("key", "value")
"""

import os
from typing import Optional

import redis.asyncio as aioredis

_client: Optional[aioredis.Redis] = None

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


async def get_redis() -> aioredis.Redis:
    """Return singleton Redis client, creating it on first call."""
    global _client
    if _client is None:
        _client = aioredis.from_url(
            _REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
        )
    return _client


async def close_redis() -> None:
    """Close the Redis connection pool (call on app shutdown)."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def ping() -> bool:
    """Health check — returns True if Redis is reachable."""
    try:
        redis = await get_redis()
        return await redis.ping()
    except Exception:
        return False
