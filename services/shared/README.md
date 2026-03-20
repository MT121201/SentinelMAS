# shared — Common Utilities

> Foundation layer that every SentinelMAS service builds on — database sessions, Redis, rate limiting, and the task queue.

**Imported by:** all service containers | **Not a standalone service** — deployed via `COPY services/shared/ ./shared/` in each Dockerfile

---

## For Business Stakeholders

### What is this?

Every service in SentinelMAS needs to talk to the database, use the cache, send tasks to agents, and stay within API cost limits. Rather than each service solving these problems separately — introducing inconsistencies, bugs, and security gaps — this shared library solves them once, correctly, and makes that solution available everywhere.

### Why does this matter operationally?

**Cost control is enforced here, not by hoping each agent behaves.**
Every AI model call in the system passes through a single rate limiter before it can proceed. If the system is approaching its daily spend limit, new calls are queued — not dropped, not ignored — until capacity is available. This means there can never be a runaway agent that blows the monthly AI budget overnight.

**The task queue is why no work is ever lost.**
When a customer submits a ticket, the work sits in a Redis queue until an agent picks it up. If any container crashes or restarts, the task is still in the queue. This is not a "nice to have" — it is the mechanism that makes the system reliable.

### Reliability guarantees

| Scenario | What happens |
|---|---|
| An agent container crashes mid-task | Task stays in Redis queue; next available agent picks it up |
| Database connection drops temporarily | Auto-reconnect with `pool_pre_ping`; request retries transparently |
| Redis connection drops temporarily | Client reconnects on next call; queue state is preserved |
| Daily AI cost limit reached | All agents pause and queue their requests; work resumes when the counter resets at midnight |

---

## For Senior Engineers

### Module overview

This package is copied into every service container at `/app/shared/` and imported as `from shared.X import Y`. No pip install required — it's a flat package with `__init__.py`.

---

### `db.py` — Async SQLAlchemy engine

```python
from shared.db import get_db, AsyncSessionLocal, Base

# FastAPI dependency — auto commit/rollback
async def route(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MyModel))

# Standalone context manager
async with AsyncSessionLocal() as session:
    await session.execute(...)
    await session.commit()
```

**Engine config:**
```
create_async_engine(
    pool_pre_ping=True,    # test connection before use (catches stale connections)
    pool_size=5,           # per-process pool
    max_overflow=10,       # burst capacity
)
```

`get_db()` is a FastAPI dependency generator: yields the session, commits on clean exit, rolls back on any exception, always closes.

**Why `expire_on_commit=False`?**
FastAPI routes are async. Without this, accessing ORM attributes after `commit()` would trigger lazy loads that fail in an async context.

---

### `redis_client.py` — Connection pool singleton

```python
from shared.redis_client import get_redis, close_redis, ping

redis = await get_redis()   # singleton; safe to call from multiple coroutines
ok    = await ping()        # True/False — use for health checks
await close_redis()         # call in FastAPI lifespan shutdown
```

Single `aioredis.Redis` instance per process. All coroutines share one connection pool. `decode_responses=True` — all values are strings unless explicitly encoded.

---

### `rate_limiter.py` — Shared Anthropic token bucket

Shared across **all agent containers** via a single Redis key namespace. Every agent must call `acquire()` before an LLM call.

```mermaid
flowchart TD
    A["acquire(estimated_tokens=2000)"]
    A --> B{"daily_cost_usd\n≥ DAILY_COST_LIMIT?"}
    B -->|yes| BLOCK["return False\nagent backs off + retries"]
    B -->|no| C["Lua atomic script\ncheck RPM + TPM counters"]
    C -->|"RPM or TPM exceeded"| BLOCK
    C -->|ok| D["INCR rpm counter (TTL 60s)\nINCR tpm counter (TTL 60s)"]
    D --> E["return True\nagent proceeds"]
    E --> F["LLM call completes"]
    F --> G["record_usage(prompt_tokens, completion_tokens)"]
    G --> H["INCRBYFLOAT mas:cost:daily_usd\nExpires at midnight UTC"]
```

```python
from shared.rate_limiter import acquire, record_usage, get_utilisation, reset_daily_cost

# Before every LLM call
if not await acquire(estimated_tokens=2000):
    await asyncio.sleep(backoff)   # agent is responsible for retry logic

# After LLM call returns
await record_usage(prompt_tokens=1500, completion_tokens=300)

# Ops dashboard
stats = await get_utilisation()
# → {rpm_used: 27, rpm_limit: 60, rpm_pct: 45.0,
#    tpm_used: 32000, tpm_limit: 100000, tpm_pct: 32.0,
#    daily_cost_usd: 12.40, daily_limit_usd: 50.0}
```

**Why a Lua script for the increment?**
RPM and TPM must be checked and incremented atomically. A non-atomic read-then-write would allow two agents to both read "within limit" and both increment, exceeding the actual limit under concurrent load. The Lua script runs as a single Redis command — no race condition is possible.

**Redis keys:**

| Key | Content | TTL |
|---|---|---|
| `mas:rate_limit:rpm` | Request count this minute | 60 s (auto-reset) |
| `mas:rate_limit:tpm` | Token count this minute | 60 s (auto-reset) |
| `mas:cost:daily_usd` | Cumulative spend today (USD float) | Until midnight UTC |

---

### `task_queue.py` — FIFO Redis task queues

```mermaid
sequenceDiagram
    participant GW as api-gateway (producer)
    participant Redis
    participant CA as client-agent (consumer)

    GW->>Redis: RPUSH mas:client_queue {"task_id": "...", "ticket_id": "...", ...}

    loop consume("client", stop_event)
        CA->>Redis: BLPOP mas:client_queue timeout=5s
        Redis-->>CA: (key, task_bytes)
        CA->>CA: json.loads(task_bytes) → handle(task)
    end
```

```python
from shared.task_queue import enqueue, consume, queue_depth

# Producer (api-gateway, scheduler)
await enqueue("client", {"task_id": "...", "ticket_id": "...", "server_id": "..."})

# Consumer (agent service main loop)
stop = asyncio.Event()
async for task in consume("client", stop):
    await handle(task)           # consumer blocks here up to 5s per BLPOP call

# Ops
depth = await queue_depth("client")   # int: pending items
```

**Queue name → Redis key mapping:** `enqueue("client", ...)` → `RPUSH mas:client_queue ...`

**BLPOP timeout (5 s):** Allows the consumer to check `stop_event` regularly for clean shutdown without holding a blocking connection indefinitely.

**Why no acknowledgement (ack) pattern?**
The current design uses simple BLPOP with no explicit ack. If a consumer crashes after BLPOP but before processing, the task is lost. At this scale, this is an acceptable tradeoff — the orchestrator's watchdog detects stuck tasks. A future hardening step (Phase 10) can add a processing set + requeue-on-timeout pattern if needed.

**Queue names in use:**

| Name | Key | Producer | Consumer |
|---|---|---|---|
| `orchestrator` | `mas:orchestrator_queue` | api-gateway (HTTP), scheduler | orchestrator consumer |
| `client` | `mas:client_queue` | api-gateway (direct), orchestrator | client-agent |
| `inserver` | `mas:inserver_queue` | admin routes, scheduler | inserver-agent |
| `report` | `mas:report_queue` | scheduler, orchestrator | report-agent |

---

### Deployment pattern

Each service Dockerfile:
```dockerfile
COPY services/shared/ ./shared/
ENV PYTHONPATH=/app
```

This places the package at `/app/shared/` and makes `from shared.X import Y` resolvable. No `__init__.py` magic needed — Python finds it as a regular package.

---

### Environment variables

| Variable | Module | Default |
|---|---|---|
| `POSTGRES_DSN` | `db.py` | `postgresql+asyncpg://mas:changeme@localhost/masdb` |
| `REDIS_URL` | `redis_client.py` | `redis://localhost:6379/0` |
| `ANTHROPIC_RPM_LIMIT` | `rate_limiter.py` | `60` |
| `ANTHROPIC_TPM_LIMIT` | `rate_limiter.py` | `100000` |
| `DAILY_COST_LIMIT_USD` | `rate_limiter.py` | `50.0` |

### Design references

- `systemdev_docs/AGENT_DESIGN.md §5` — rate limiter design spec
- `systemdev_docs/SYSTEM_DESIGN.md` — task queue architecture
- `services/shared/dev_note.md` — function-level documentation
