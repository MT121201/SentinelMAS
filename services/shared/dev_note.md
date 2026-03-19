# dev_note — shared

## Purpose
Shared utilities imported by all services: DB session factory, Redis client, rate limiter, task queue helpers, structured logger.

## Files
> Phase 0 scaffold — no code files yet. Built in Phase 1A/1B.

Planned files (from TODO.md P1-07 to P1-10):
- `db.py` — async SQLAlchemy engine + session factory (`get_db()` dependency)
- `redis_client.py` — async Redis client, connection pool, `ping()` health check
- `rate_limiter.py` — `AnthropicRateLimiter`: token bucket via Lua script in Redis; `acquire()` + `record_usage()`
- `task_queue.py` — `enqueue(queue, task_dict)` + `consume(queue)` BLPOP loop
- `logger.py` — structlog JSON logger factory; auto-injects `trace_id`, `agent_id`, `service`

## Cross-Service Contracts
- Imported by: all services as a local package
- `rate_limiter.py` uses Redis key `mas:rate_limit:rpm` and `mas:rate_limit:tpm` (singleton across all containers)
- `task_queue.py` Redis key pattern: `mas:{queue_name}_queue`

## Known Gaps / Deferred
- Phase 0: directory scaffold only
- `rate_limiter.py` Lua script for atomic token bucket — implement carefully to avoid race conditions
