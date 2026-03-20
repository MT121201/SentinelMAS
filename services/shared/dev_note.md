# dev_note — shared

## Purpose
Shared utilities imported by all GPU-MAS services: DB session factory, Redis client, rate limiter, task queue helpers.

## Files

### db.py
- `Base` — SQLAlchemy `DeclarativeBase`; import in every model module
- `engine` — async SQLAlchemy engine; reads POSTGRES_DSN env var
- `AsyncSessionLocal` — `async_sessionmaker`; use directly for non-FastAPI contexts
- `get_db()` — FastAPI dependency; yields transactional `AsyncSession`; auto-commits on success, rolls back on exception

### redis_client.py
- `get_redis() -> aioredis.Redis` — singleton async Redis client; creates on first call
- `close_redis() -> None` — closes connection pool; call on app shutdown
- `ping() -> bool` — health check

### rate_limiter.py
- `acquire(estimated_tokens: int) -> bool` — atomic Lua token-bucket check; returns False if RPM/TPM/daily limit exceeded
- `record_usage(prompt_tokens, completion_tokens) -> float` — increments `mas:cost:daily_usd`; returns new daily total
- `get_utilisation() -> dict` — returns current RPM%, TPM%, daily cost% (used by /health + ops dashboard)
- `reset_daily_cost() -> None` — manual reset of daily cost (ops endpoint)
- Redis keys: `mas:rate_limit:rpm`, `mas:rate_limit:tpm`, `mas:cost:daily_usd`

### task_queue.py
- `enqueue(queue_name: str, task: dict) -> None` — RPUSH to `mas:{queue_name}_queue`
- `consume(queue_name, stop_event) -> AsyncIterator[dict]` — BLPOP loop; yields task dicts; exits when stop_event set
- `queue_depth(queue_name) -> int` — returns pending task count
- Queue key pattern: `mas:{queue_name}_queue`
- Queue names in use: `client`, `inserver`, `report`

## Cross-Service Contracts
- Imported by: all services via `PYTHONPATH=/app` (shared/ copied into each container)
- `rate_limiter.py` uses a Redis singleton shared across ALL containers — do not create per-container rate limiters

### logger.py
- `configure_logging(log_level)` — call once at startup; sets up structlog JSON → stdout, bridges stdlib logging
- `get_logger(name, **initial_context)` → `BoundLogger` — returns structlog logger pre-bound with service-level context
- `bind_trace_context(trace_id, agent_id, task_id, ticket_id)` — binds per-task context into structlog contextvars store
- `clear_trace_context()` — clears all contextvars; call at end of each task

## Known Gaps / Deferred
- None — all planned shared modules are implemented
