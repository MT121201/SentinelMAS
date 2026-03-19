"""
Anthropic API rate limiter — token bucket backed by Redis.

Shared singleton across ALL agent containers (single Redis key).
Agents call acquire() before every LLM call; they queue+retry on False.
record_usage() is called after every LLM call to track actual token spend.

Redis keys:
    mas:rate_limit:rpm   — request count in current 60s window (INCR + EXPIRE)
    mas:rate_limit:tpm   — token count in current 60s window  (INCRBY + EXPIRE)
    mas:cost:daily_usd   — cumulative USD spend today (float stored as string)
"""

import os
import time
from typing import Optional

from shared.redis_client import get_redis

# ── Config (overridable via env) ───────────────────────────────────────────────
RPM_LIMIT = int(os.environ.get("ANTHROPIC_RPM_LIMIT", "60"))
TPM_LIMIT = int(os.environ.get("ANTHROPIC_TPM_LIMIT", "100000"))
DAILY_COST_LIMIT_USD = float(os.environ.get("DAILY_COST_LIMIT_USD", "50.0"))

# claude-sonnet-4 pricing (USD per 1k tokens — approximate)
_COST_PER_1K_INPUT = 0.003
_COST_PER_1K_OUTPUT = 0.015

# ── Lua script — atomic RPM + TPM check-and-acquire ───────────────────────────
_LUA_ACQUIRE = """
local rpm_key   = KEYS[1]
local tpm_key   = KEYS[2]
local rpm_limit = tonumber(ARGV[1])
local tpm_limit = tonumber(ARGV[2])
local est_tok   = tonumber(ARGV[3])
local window    = 60

local cur_rpm = tonumber(redis.call('GET', rpm_key) or 0)
local cur_tpm = tonumber(redis.call('GET', tpm_key) or 0)

if cur_rpm >= rpm_limit then return 0 end
if cur_tpm + est_tok > tpm_limit then return 0 end

redis.call('INCR', rpm_key)
redis.call('EXPIRE', rpm_key, window)
redis.call('INCRBY', tpm_key, est_tok)
redis.call('EXPIRE', tpm_key, window)
return 1
"""

_acquire_script: Optional[object] = None


async def _get_script():
    global _acquire_script
    if _acquire_script is None:
        redis = await get_redis()
        _acquire_script = redis.register_script(_LUA_ACQUIRE)
    return _acquire_script


async def acquire(estimated_tokens: int = 1000) -> bool:
    """
    Attempt to reserve capacity for an LLM call.

    Returns True if within limits (call may proceed).
    Returns False if RPM or TPM limit would be exceeded (agent should back off).

    Also returns False if daily USD cost ceiling has been reached.
    """
    redis = await get_redis()

    # Check daily cost ceiling first (cheap READ before expensive Lua)
    daily_cost = float(await redis.get("mas:cost:daily_usd") or 0)
    if daily_cost >= DAILY_COST_LIMIT_USD:
        return False

    script = await _get_script()
    result = await script(
        keys=["mas:rate_limit:rpm", "mas:rate_limit:tpm"],
        args=[RPM_LIMIT, TPM_LIMIT, estimated_tokens],
    )
    return bool(result)


async def record_usage(prompt_tokens: int, completion_tokens: int) -> float:
    """
    Record actual token usage after an LLM call completes.
    Updates daily cost counter. Returns the new daily total.
    """
    cost = (prompt_tokens / 1000 * _COST_PER_1K_INPUT) + \
           (completion_tokens / 1000 * _COST_PER_1K_OUTPUT)

    redis = await get_redis()
    new_total = await redis.incrbyfloat("mas:cost:daily_usd", cost)

    # Key expires at next midnight UTC (rough TTL)
    now = time.time()
    seconds_until_midnight = 86400 - (now % 86400)
    await redis.expire("mas:cost:daily_usd", int(seconds_until_midnight) + 60)

    return float(new_total)


async def get_utilisation() -> dict:
    """Return current rate limit utilisation (used by /health and ops dashboard)."""
    redis = await get_redis()
    cur_rpm = int(await redis.get("mas:rate_limit:rpm") or 0)
    cur_tpm = int(await redis.get("mas:rate_limit:tpm") or 0)
    daily_cost = float(await redis.get("mas:cost:daily_usd") or 0)
    return {
        "rpm_used": cur_rpm,
        "rpm_limit": RPM_LIMIT,
        "rpm_pct": round(cur_rpm / RPM_LIMIT * 100, 1),
        "tpm_used": cur_tpm,
        "tpm_limit": TPM_LIMIT,
        "tpm_pct": round(cur_tpm / TPM_LIMIT * 100, 1),
        "daily_cost_usd": round(daily_cost, 4),
        "daily_cost_limit_usd": DAILY_COST_LIMIT_USD,
        "daily_cost_pct": round(daily_cost / DAILY_COST_LIMIT_USD * 100, 1),
    }


async def reset_daily_cost() -> None:
    """Manual reset of the daily cost counter (ops endpoint)."""
    redis = await get_redis()
    await redis.delete("mas:cost:daily_usd")
