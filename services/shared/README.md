# shared — Common Utilities

Python package imported by every GPU-MAS service.
Provides async DB sessions, Redis client, rate limiter, and task queue.

Each service container gets this via `COPY services/shared/ ./shared/` in its Dockerfile, with `PYTHONPATH=/app`.

---

## Modules

### `db.py` — Async Database Sessions

```python
from shared.db import get_db, Base

# FastAPI dependency
async def route(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MyModel))

# Standalone
async with AsyncSessionLocal() as session:
    ...
```

`get_db()` auto-commits on success and rolls back on any exception.

---

### `redis_client.py` — Redis Connection Pool

```python
from shared.redis_client import get_redis, ping

redis = await get_redis()       # singleton, safe to call repeatedly
ok    = await ping()            # health check → bool
```

Singleton client — one connection pool shared across the entire container process.

---

### `rate_limiter.py` — Anthropic API Token Bucket

Shared across **all agent containers** via a single Redis key. Every agent checks in here before making an LLM call.

```mermaid
flowchart TD
    A[Agent wants to call LLM] --> B{Daily cost\nceiling hit?}
    B -- Yes --> BLOCK[Return False\nAgent backs off]
    B -- No --> C{Lua script:\nRPM + TPM check}
    C -- Limit exceeded --> BLOCK
    C -- OK --> D[Increment counters in Redis\nRPM key: 60s TTL\nTPM key: 60s TTL]
    D --> E[Return True\nAgent proceeds]
    E --> F[LLM call completes]
    F --> G[record_usage\nprompt_tokens + completion_tokens]
    G --> H[Increment mas:cost:daily_usd\nExpires at midnight UTC]
```

```python
from shared.rate_limiter import acquire, record_usage, get_utilisation

# Before LLM call
if not await acquire(estimated_tokens=2000):
    await asyncio.sleep(backoff)
    # retry

# After LLM call
await record_usage(prompt_tokens=1500, completion_tokens=300)

# Ops dashboard
stats = await get_utilisation()
# → {rpm_pct: 45.0, tpm_pct: 32.1, daily_cost_usd: 12.40, ...}
```

**Redis keys:**
| Key | Content | TTL |
|---|---|---|
| `mas:rate_limit:rpm` | request count this minute | 60s |
| `mas:rate_limit:tpm` | token count this minute | 60s |
| `mas:cost:daily_usd` | cumulative USD today | until midnight UTC |

---

### `task_queue.py` — Redis Task Queue

FIFO queue per agent type. Producers push; consumers BLPOP.

```mermaid
sequenceDiagram
    participant GW as api-gateway
    participant Redis
    participant CA as client-agent

    GW->>Redis: RPUSH mas:client_queue {task_id, ticket_id, ...}
    Note over CA: consume("client") loop
    CA->>Redis: BLPOP mas:client_queue (blocks up to 5s)
    Redis-->>CA: task dict
    CA->>CA: handle(task)
```

```python
from shared.task_queue import enqueue, consume, queue_depth

# Producer (api-gateway)
await enqueue("client", {"task_id": "...", "ticket_id": "...", "server_id": "..."})

# Consumer (client-agent)
stop = asyncio.Event()
async for task in consume("client", stop):
    await handle(task)

# Ops
depth = await queue_depth("client")  # pending task count
```

**Queue names in use:**
| Name | Producer | Consumer |
|---|---|---|
| `client` | api-gateway | client-agent |
| `inserver` | scheduler | inserver-agent |
| `report` | scheduler | report-agent |

---

## Environment Variables

All modules read from environment — no config files needed.

| Variable | Used By | Default |
|---|---|---|
| `POSTGRES_DSN` | `db.py` | `postgresql+asyncpg://mas:changeme@localhost/masdb` |
| `REDIS_URL` | `redis_client.py` | `redis://localhost:6379/0` |
| `ANTHROPIC_RPM_LIMIT` | `rate_limiter.py` | `60` |
| `ANTHROPIC_TPM_LIMIT` | `rate_limiter.py` | `100000` |
| `DAILY_COST_LIMIT_USD` | `rate_limiter.py` | `50.0` |
