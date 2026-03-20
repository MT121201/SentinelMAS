"""
Shared pytest fixtures for integration tests.

Uses fakeredis for Redis — no running Redis instance required.
DB calls are mocked at the SQLAlchemy session level.
"""

import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ── Sys path helpers ───────────────────────────────────────────────────────────
# Each service adds its own src dir; integration tests patch at import level.

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))


def service_path(name: str) -> str:
    return os.path.join(REPO_ROOT, "services", name)


# ── Event loop ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop so fixtures can share state."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Fake Redis ─────────────────────────────────────────────────────────────────

@pytest.fixture
async def fake_redis():
    """
    In-memory async Redis using fakeredis.
    Automatically flushed between tests.
    """
    import fakeredis.aioredis as faioredis
    redis = faioredis.FakeRedis(decode_responses=True)
    yield redis
    await redis.flushall()
    await redis.aclose()


@pytest.fixture
async def fake_redis_bytes():
    """fakeredis without decode_responses — for consumers that expect bytes."""
    import fakeredis.aioredis as faioredis
    redis = faioredis.FakeRedis(decode_responses=False)
    yield redis
    await redis.flushall()
    await redis.aclose()


# ── Mock DB session ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db():
    """
    AsyncMock that satisfies the SQLAlchemy AsyncSession interface.
    Tests configure return values per-query.
    """
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


# ── Mock Anthropic client ──────────────────────────────────────────────────────

def make_anthropic_text_response(text: str) -> MagicMock:
    """Build a minimal mock Anthropic message with stop_reason=end_turn."""
    content_block = MagicMock()
    content_block.type = "text"
    content_block.text = text

    usage = MagicMock()
    usage.input_tokens = 500
    usage.output_tokens = 200

    msg = MagicMock()
    msg.content = [content_block]
    msg.stop_reason = "end_turn"
    msg.usage = usage
    return msg


def make_anthropic_tool_response(tool_name: str, tool_input: dict) -> MagicMock:
    """Build a mock Anthropic message with a single tool_use block."""
    content_block = MagicMock()
    content_block.type = "tool_use"
    content_block.name = tool_name
    content_block.id = "toolu_test_001"
    content_block.input = tool_input

    usage = MagicMock()
    usage.input_tokens = 400
    usage.output_tokens = 100

    msg = MagicMock()
    msg.content = [content_block]
    msg.stop_reason = "tool_use"
    msg.usage = usage
    return msg
