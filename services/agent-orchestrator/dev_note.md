# dev_note — agent-orchestrator

> Last updated: 2026-03-20

## Purpose
LangGraph supervisor that consumes the Redis task queue, classifies/routes tasks to specialist agents via a worker pool, and runs APScheduler cron jobs.

---

## state.py

### AgentState TypedDict — canonical definition; all agent services use compatible copies

| Field | Type | Purpose | Status |
|---|---|---|---|
| `task_id` | str | Unique UUID per task | active |
| `trace_id` | str | Langfuse trace correlation ID | active |
| `task_type` | Literal | ticket / maintenance / report / unknown | active |
| `assigned_agent` | Optional[str] | client-agent / inserver-agent / report-agent | active |
| `severity` | Optional[Literal] | LOW/MEDIUM/HIGH/CRITICAL | active |
| `ticket_id` | Optional[str] | rag_kb_entries.id (stringified) | active |
| `user_message` | Optional[str] | Raw ticket description | active |
| `server_id` | Optional[str] | Target server for SSH | active |
| `rag_hits` | list[dict] | RAG search results | active |
| `web_search_results` | list[dict] | Tavily results | active |
| `action_plan` | list[str] | Steps agent will execute | active |
| `execution_log` | list[dict] | {command, output, success, timestamp} | active |
| `status` | Literal | queued→assigned→thinking→executing→verifying→done/failed/escalated | active |
| `resolution_summary` | Optional[str] | Final plain-language answer | active |
| `error` | Optional[str] | Error message if failed | active |
| `created_at` | datetime | Task creation time | active |
| `updated_at` | datetime | Last state change | active |

---

## config.py

| Setting | Default | Purpose |
|---|---|---|
| `anthropic_api_key` | `""` | For Claude supervisor classification |
| `anthropic_model` | `claude-sonnet-4-20250514` | Model used for unknown task classification |
| `postgres_dsn` | `...` | Async SQLAlchemy DSN |
| `postgres_dsn_sync` | `...` | Sync DSN for APScheduler SQLAlchemyJobStore |
| `redis_url` | `...` | Redis connection |
| `internal_api_key` | `""` | X-Internal-Key header check |
| `queue_orchestrator` | `orchestrator` | Main intake queue |
| `queue_client` | `client` | Client-agent queue |
| `queue_inserver` | `inserver` | InServer-agent queue |
| `queue_report` | `report` | Report-agent queue |
| `max_concurrent_tasks` | `10` | Worker pool semaphore size |
| `stuck_task_threshold_seconds` | `900` | 15-min watchdog trigger |
| `langfuse_*` | `""` | Langfuse keys — tracing degrades gracefully if not set |

---

## supervisor.py

### LangGraph nodes

| Node | Purpose |
|---|---|
| `classify_node` | If task_type == "unknown", calls Claude to classify. Otherwise pass-through. |
| `route_node` | RPUSH to specialist Redis queue; update ticket status=assigned in Postgres |

### Functions

| Function | Signature | Purpose |
|---|---|---|
| `build_supervisor_graph` | `() -> StateGraph` | Compiles classify→route graph |
| `supervisor_graph` | module-level compiled graph | Reused per invocation |

**Config keys expected in LangGraph config:** `redis` (aioredis.Redis), `db` (AsyncSession)

**Queue routing:**
```
ticket       → mas:client_queue
maintenance  → mas:inserver_queue
report       → mas:report_queue
```

---

## worker_pool.py

### WorkerPool dataclass fields

| Field | Type | Purpose |
|---|---|---|
| `_sem` | asyncio.Semaphore | Limits concurrent supervisor invocations |
| `_active` | dict[task_id → datetime] | Tracks running tasks for watchdog |
| `_watchdog_task` | asyncio.Task | Background watchdog loop handle |
| `_stop` | asyncio.Event | Shutdown signal |

### Functions

| Function | Signature | Purpose |
|---|---|---|
| `WorkerPool.start` | `() -> None` | Start watchdog; called from lifespan |
| `WorkerPool.stop` | `() -> None` | Signal shutdown + await watchdog |
| `WorkerPool.dispatch` | `(task_id, coro) -> None` | Acquire semaphore + create_task |
| `WorkerPool.active_count` | property → int | Number of in-flight tasks |
| `WorkerPool.active_tasks` | property → list[dict] | task_id, started_at, elapsed_seconds |
| `init_pool` | `(max_concurrent?) -> WorkerPool` | Create + set module-level singleton |
| `get_pool` | `() -> WorkerPool` | Get singleton; raises if not initialised |

---

## consumer.py

### Functions

| Function | Signature | Purpose |
|---|---|---|
| `run_consumer` | `(redis, db_factory, stop_event) -> None` | BLPOP loop on all 4 queues |
| `_process_task` | `(raw, redis, db_factory) -> None` | Deserialise + build AgentState + dispatch to pool |
| `_parse_dt` | `(value?) -> datetime \| None` | ISO string → datetime |

**Queue poll order (BLPOP priority):**
1. `mas:orchestrator_queue` — primary intake
2. `mas:client_queue` — api-gateway direct push
3. `mas:inserver_queue` — admin maintenance trigger
4. `mas:report_queue` — scheduler push

---

## scheduler_jobs.py

### Functions

| Function | Signature | Purpose |
|---|---|---|
| `daily_inserver_check` | `(redis, db_factory) -> None` | Enqueue maintenance task per active server at 00:05 UTC |
| `weekly_report` | `(redis) -> None` | Enqueue weekly report task at 06:00 UTC Monday |
| `hourly_cache_cleanup` | `(redis) -> None` | Log Redis cache key counts; TTL auto-expires |
| `register_jobs` | `(scheduler, redis, db_factory) -> None` | Register all 3 cron triggers |

---

## langfuse_tracer.py

### Functions

| Function | Signature | Purpose |
|---|---|---|
| `init_tracer` | `() -> None` | Init Langfuse client; no-op if keys not set |
| `get_langfuse` | `() -> Langfuse \| None` | Return client or None |
| `create_trace` | `(name, task_id, trace_id, metadata?) -> trace` | Create trace or return _NoOpTrace |
| `record_llm_call` | `(trace, model, prompt_tokens, completion_tokens, name) -> None` | Record token usage |
| `flush` | `() -> None` | Flush pending events on shutdown |

**`_NoOpTrace`** — stub returned when Langfuse disabled; all methods are no-ops.

---

## routes.py

### Pydantic Models

| Model | Purpose |
|---|---|
| `EnqueueTaskRequest` | task_type, ticket_id, server_id, user_message, severity, trace_id |
| `EnqueueTaskResponse` | task_id, queued |
| `StatusUpdateRequest` | status, resolution_summary, error |

### Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/internal/tasks` | X-Internal-Key | Push task to orchestrator queue |
| `PUT` | `/internal/tasks/{id}/status` | X-Internal-Key | Agent reports progress/completion |
| `GET` | `/ops/agents` | none | Live active tasks from worker pool |
| `GET` | `/ops/queue` | none | Queue depths from Redis |

---

## main.py

### Startup sequence

1. Async DB engine + `async_sessionmaker`
2. Redis connection
3. `init_pool()` + `pool.start()` (watchdog)
4. `langfuse_tracer.init_tracer()`
5. APScheduler start + `register_jobs()` (MemoryJobStore — see Known Gaps)
6. `run_consumer()` as `asyncio.create_task`

Port: **8001** (single Uvicorn worker — consumer loop must be in same event loop)

---

## Cross-Service Contracts

| Consumer/Producer | Field/Queue | Notes |
|---|---|---|
| api-gateway | `POST /internal/tasks` | Alternative to direct Redis push |
| api-gateway (tickets.py) | `mas:client_queue` | Direct Redis push — consumer listens here |
| api-gateway (admin.py) | `mas:inserver_queue` | Direct Redis push — consumer listens here |
| supervisor → client-agent | `mas:client_queue` | RPUSH routed here for ticket tasks |
| supervisor → inserver-agent | `mas:inserver_queue` | RPUSH routed here for maintenance tasks |
| supervisor → report-agent | `mas:report_queue` | RPUSH routed here for report tasks |
| Postgres | `tickets` table | Status updated on route + agent callback |
| Postgres | `apscheduler_jobs` | Table exists (migration 006) but not used as job store — MemoryJobStore active |

## Known Gaps / Deferred
- Langfuse self-hosted instance configured in Phase 8
- APScheduler uses `MemoryJobStore` (not `SQLAlchemyJobStore`). Async Redis clients cannot be pickled by APScheduler's PostgreSQL job store. Jobs re-register on every startup via `register_jobs()` with `replace_existing=True` — behaviour is identical to persistent store for our 3 fixed cron jobs. Migrate to PostgreSQL job store if jobs need to survive rolling restarts without re-registration.
- specialist agents (inserver, client, report) send status callbacks via `PUT /internal/tasks/{id}/status`
