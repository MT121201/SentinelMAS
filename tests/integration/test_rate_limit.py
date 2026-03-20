"""
P9-04 — Rate limit tests: exceed ANTHROPIC_RPM_LIMIT → verify queuing, not dropping.

Tests:
  1. acquire() returns False when RPM limit reached
  2. acquire() returns False when TPM limit reached
  3. acquire() returns False when daily cost ceiling reached
  4. record_usage() accumulates daily cost correctly
  5. reset_daily_cost() clears the counter
  6. get_utilisation() reflects real counters
"""

import sys
import os
from unittest.mock import patch, AsyncMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "shared"))


@pytest.mark.asyncio
async def test_acquire_succeeds_under_limit(fake_redis):
    """acquire() returns True when RPM/TPM limits are not reached."""
    with patch("shared.redis_client.get_redis", AsyncMock(return_value=fake_redis)), \
         patch("rate_limiter.get_redis", AsyncMock(return_value=fake_redis)), \
         patch("rate_limiter.RPM_LIMIT", 60), \
         patch("rate_limiter.TPM_LIMIT", 100_000), \
         patch("rate_limiter.DAILY_COST_LIMIT_USD", 50.0), \
         patch("rate_limiter._acquire_script", None):

        import rate_limiter
        rate_limiter._acquire_script = None

        result = await rate_limiter.acquire(estimated_tokens=500)
        assert result is True


@pytest.mark.asyncio
async def test_acquire_blocked_at_rpm_limit(fake_redis):
    """acquire() returns False once RPM limit is saturated."""
    rpm_limit = 3
    with patch("rate_limiter.get_redis", AsyncMock(return_value=fake_redis)), \
         patch("rate_limiter.RPM_LIMIT", rpm_limit), \
         patch("rate_limiter.TPM_LIMIT", 100_000), \
         patch("rate_limiter.DAILY_COST_LIMIT_USD", 50.0), \
         patch("rate_limiter._acquire_script", None):

        import rate_limiter
        rate_limiter._acquire_script = None

        # Consume all RPM slots
        for _ in range(rpm_limit):
            result = await rate_limiter.acquire(estimated_tokens=100)
            assert result is True

        # Next call should be blocked
        blocked = await rate_limiter.acquire(estimated_tokens=100)
        assert blocked is False, "acquire() must return False when RPM limit is reached"


@pytest.mark.asyncio
async def test_acquire_blocked_at_daily_cost_limit(fake_redis):
    """acquire() returns False when daily cost ceiling has been reached."""
    await fake_redis.set("mas:cost:daily_usd", "50.01")

    with patch("rate_limiter.get_redis", AsyncMock(return_value=fake_redis)), \
         patch("rate_limiter.RPM_LIMIT", 60), \
         patch("rate_limiter.TPM_LIMIT", 100_000), \
         patch("rate_limiter.DAILY_COST_LIMIT_USD", 50.0), \
         patch("rate_limiter._acquire_script", None):

        import rate_limiter
        result = await rate_limiter.acquire(estimated_tokens=500)
        assert result is False, "acquire() must return False when daily cost limit is exceeded"


@pytest.mark.asyncio
async def test_record_usage_accumulates_cost(fake_redis):
    """record_usage() increments daily_cost_usd correctly."""
    with patch("rate_limiter.get_redis", AsyncMock(return_value=fake_redis)):
        import rate_limiter

        total1 = await rate_limiter.record_usage(prompt_tokens=1000, completion_tokens=500)
        # cost = (1000/1000 * 0.003) + (500/1000 * 0.015) = 0.003 + 0.0075 = 0.0105
        assert total1 == pytest.approx(0.0105, abs=0.0001)

        total2 = await rate_limiter.record_usage(prompt_tokens=2000, completion_tokens=1000)
        # additional = (2000/1000 * 0.003) + (1000/1000 * 0.015) = 0.006 + 0.015 = 0.021
        assert total2 == pytest.approx(0.0315, abs=0.0001)


@pytest.mark.asyncio
async def test_reset_daily_cost_clears_counter(fake_redis):
    """reset_daily_cost() deletes the daily cost Redis key."""
    await fake_redis.set("mas:cost:daily_usd", "12.50")

    with patch("rate_limiter.get_redis", AsyncMock(return_value=fake_redis)):
        import rate_limiter
        await rate_limiter.reset_daily_cost()

    remaining = await fake_redis.get("mas:cost:daily_usd")
    assert remaining is None, "Daily cost key should be deleted after reset"


@pytest.mark.asyncio
async def test_get_utilisation_reflects_redis_state(fake_redis):
    """get_utilisation() returns correct percentages from Redis counters."""
    await fake_redis.set("mas:rate_limit:rpm", "30")
    await fake_redis.set("mas:rate_limit:tpm", "75000")
    await fake_redis.set("mas:cost:daily_usd", "25.00")

    with patch("rate_limiter.get_redis", AsyncMock(return_value=fake_redis)), \
         patch("rate_limiter.RPM_LIMIT", 60), \
         patch("rate_limiter.TPM_LIMIT", 100_000), \
         patch("rate_limiter.DAILY_COST_LIMIT_USD", 50.0):

        import rate_limiter
        util = await rate_limiter.get_utilisation()

    assert util["rpm_used"] == 30
    assert util["rpm_pct"] == pytest.approx(50.0)
    assert util["tpm_used"] == 75000
    assert util["tpm_pct"] == pytest.approx(75.0)
    assert util["daily_cost_usd"] == pytest.approx(25.0)
    assert util["daily_cost_pct"] == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_acquire_blocked_when_tpm_would_exceed(fake_redis):
    """acquire() returns False when adding estimated_tokens would exceed TPM limit."""
    tpm_limit = 1000
    # Pre-fill so next call would exceed
    await fake_redis.set("mas:rate_limit:tpm", "900")
    await fake_redis.expire("mas:rate_limit:tpm", 60)

    with patch("rate_limiter.get_redis", AsyncMock(return_value=fake_redis)), \
         patch("rate_limiter.RPM_LIMIT", 60), \
         patch("rate_limiter.TPM_LIMIT", tpm_limit), \
         patch("rate_limiter.DAILY_COST_LIMIT_USD", 50.0), \
         patch("rate_limiter._acquire_script", None):

        import rate_limiter
        rate_limiter._acquire_script = None

        # 200 tokens would push 900 → 1100, exceeding 1000 limit
        result = await rate_limiter.acquire(estimated_tokens=200)
        assert result is False, "acquire() must block when TPM would be exceeded"
