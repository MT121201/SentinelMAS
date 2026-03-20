"""
Semantic cache backed by Redis.

On lookup: embed query → scan cached entries → return hit if cosine ≥ 0.92.
On write: store embedding + serialised results in Redis with TTL.

Keys:
  mas:rag_cache:{sha256_of_embedding} → JSON {embedding: [...], results: [...], kind: "active"|"static"}

Kind determines TTL:
  active — recent error fixes — 1h (cache_ttl_active)
  static — general GPU/Linux knowledge — 24h (cache_ttl_static)

O(n) scan is acceptable at this scale (<10k cached entries).
"""

import hashlib
import json
import logging
import math

import redis.asyncio as aioredis

from config import settings

log = logging.getLogger(__name__)

_CACHE_PREFIX = "mas:rag_cache:"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _embedding_key(embedding: list[float]) -> str:
    """Deterministic Redis key derived from the embedding vector."""
    raw = json.dumps(embedding, separators=(",", ":")).encode()
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return f"{_CACHE_PREFIX}{digest}"


async def cache_lookup(
    query_embedding: list[float],
    redis: aioredis.Redis,
) -> list[dict] | None:
    """
    Scan all cached embeddings. Return deserialized results if cosine ≥ threshold.
    Returns None on miss.
    """
    threshold = settings.cache_cosine_threshold

    # Scan all cache keys
    async for key in redis.scan_iter(f"{_CACHE_PREFIX}*"):
        raw = await redis.get(key)
        if raw is None:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        cached_embedding = entry.get("embedding")
        if not cached_embedding:
            continue
        sim = _cosine(query_embedding, cached_embedding)
        if sim >= threshold:
            log.debug("cache hit (cosine=%.4f)", sim)
            return entry.get("results", [])

    return None


async def cache_write(
    query_embedding: list[float],
    results: list[dict],
    redis: aioredis.Redis,
    kind: str = "active",
) -> None:
    """
    Store query embedding + results in Redis.

    kind: "active" (1h TTL) or "static" (24h TTL).
    """
    ttl = (
        settings.cache_ttl_active if kind == "active" else settings.cache_ttl_static
    )
    key = _embedding_key(query_embedding)
    payload = json.dumps(
        {"embedding": query_embedding, "results": results, "kind": kind},
        separators=(",", ":"),
    )
    await redis.setex(key, ttl, payload)
    log.debug("cache write key=%s ttl=%d", key, ttl)


async def cache_stats(redis: aioredis.Redis) -> dict:
    """Return count of active and static cached entries."""
    active = 0
    static = 0
    async for key in redis.scan_iter(f"{_CACHE_PREFIX}*"):
        raw = await redis.get(key)
        if raw is None:
            continue
        try:
            entry = json.loads(raw)
            if entry.get("kind") == "static":
                static += 1
            else:
                active += 1
        except json.JSONDecodeError:
            pass
    return {"active": active, "static": static, "total": active + static}
