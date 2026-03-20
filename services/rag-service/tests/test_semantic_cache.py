"""
Unit tests for semantic cache (cosine lookup + Redis write).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import math
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from semantic_cache import _cosine, cache_lookup, cache_write, cache_stats


class TestCosine:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert abs(_cosine(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(_cosine(a, b)) < 1e-6

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(_cosine(a, b) - (-1.0)) < 1e-6

    def test_zero_vector(self):
        a = [0.0, 0.0]
        b = [1.0, 2.0]
        assert _cosine(a, b) == 0.0

    def test_close_vectors(self):
        a = [1.0, 0.1]
        b = [0.99, 0.11]
        sim = _cosine(a, b)
        assert sim > 0.99


def _make_redis(scan_keys: list, get_values: dict):
    """Mock aioredis client with scan_iter and get."""

    async def mock_scan_iter(pattern):
        for k in scan_keys:
            yield k

    async def mock_get(key):
        return get_values.get(key)

    async def mock_setex(key, ttl, value):
        pass

    redis = MagicMock()
    redis.scan_iter = mock_scan_iter
    redis.get = AsyncMock(side_effect=mock_get)
    redis.setex = AsyncMock(side_effect=mock_setex)
    return redis


class TestCacheLookup:
    @pytest.mark.asyncio
    async def test_hit_above_threshold(self):
        embedding = [1.0, 0.0, 0.0]
        cached_embedding = [1.0, 0.0, 0.0]  # cosine = 1.0

        entry = json.dumps({
            "embedding": cached_embedding,
            "results": [{"kb_entry_id": 1, "error_pattern": "test", "fix_steps": "fix"}],
            "kind": "active",
        }).encode()

        redis = _make_redis(["mas:rag_cache:abc123"], {"mas:rag_cache:abc123": entry})

        result = await cache_lookup(embedding, redis)
        assert result is not None
        assert result[0]["kb_entry_id"] == 1

    @pytest.mark.asyncio
    async def test_miss_below_threshold(self):
        query = [1.0, 0.0]
        cached = [0.0, 1.0]  # orthogonal → cosine = 0.0

        entry = json.dumps({
            "embedding": cached,
            "results": [{"kb_entry_id": 99}],
            "kind": "active",
        }).encode()

        redis = _make_redis(["mas:rag_cache:xyz"], {"mas:rag_cache:xyz": entry})

        result = await cache_lookup(query, redis)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_cache_returns_none(self):
        redis = _make_redis([], {})
        result = await cache_lookup([1.0, 0.0], redis)
        assert result is None

    @pytest.mark.asyncio
    async def test_malformed_entry_skipped(self):
        redis = _make_redis(
            ["mas:rag_cache:bad"],
            {"mas:rag_cache:bad": b"not-json"},
        )
        result = await cache_lookup([1.0, 0.0], redis)
        assert result is None


class TestCacheWrite:
    @pytest.mark.asyncio
    async def test_write_calls_setex(self):
        redis = MagicMock()
        redis.setex = AsyncMock()

        embedding = [0.5, 0.5]
        results = [{"kb_entry_id": 1}]

        await cache_write(embedding, results, redis, kind="active")

        assert redis.setex.called
        call_args = redis.setex.call_args
        key = call_args[0][0]
        ttl = call_args[0][1]
        assert key.startswith("mas:rag_cache:")
        assert ttl == 3600  # active TTL

    @pytest.mark.asyncio
    async def test_static_ttl(self):
        redis = MagicMock()
        redis.setex = AsyncMock()

        await cache_write([1.0], [{"kb_entry_id": 2}], redis, kind="static")

        ttl = redis.setex.call_args[0][1]
        assert ttl == 86400


class TestCacheStats:
    @pytest.mark.asyncio
    async def test_counts_correctly(self):
        entries = {
            "mas:rag_cache:a1": json.dumps({"embedding": [1], "results": [], "kind": "active"}).encode(),
            "mas:rag_cache:a2": json.dumps({"embedding": [2], "results": [], "kind": "active"}).encode(),
            "mas:rag_cache:s1": json.dumps({"embedding": [3], "results": [], "kind": "static"}).encode(),
        }

        redis = _make_redis(list(entries.keys()), entries)

        stats = await cache_stats(redis)
        assert stats["active"] == 2
        assert stats["static"] == 1
        assert stats["total"] == 3
