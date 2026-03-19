# dev_note — agent-orchestrator

## Purpose
LangGraph supervisor that consumes the Redis task queue, routes tasks to specialist agents via a worker pool, and runs APScheduler cron jobs.

## Files
> Phase 0 scaffold — no code files yet. Built in Phase 4.

Planned files (from TODO.md P4-xx):
- `main.py` — starts Redis consumer loop + APScheduler
- `supervisor.py` — LangGraph `StateGraph`, conditional routing by task_type
- `state.py` — `AgentState` TypedDict (canonical definition, imported by all agents)
- `worker_pool.py` — `asyncio.Semaphore` pool, task dispatch, stuck-task watchdog (>15 min alert)
- `consumer.py` — `BLPOP mas:task_queue` loop → dispatches to worker_pool
- `scheduler_jobs.py` — `daily_inserver_check`, `weekly_report`, `hourly_cache_cleanup`
- `langfuse_tracer.py` — wraps LLM calls with Langfuse trace decorator, token recording
- `routes.py` — internal API: task enqueue, status update, ops view

## Cross-Service Contracts
- Consumes: Redis list `mas:task_queue` (pushed by api-gateway)
- Dispatches to: `inserver-agent`, `client-agent`, `report-agent` (via their own Redis queues)
- Publishes status back: updates `tickets` table in Postgres
- Listens on: port 8001

## State Fields (AgentState — defined in state.py, used by ALL agents)
| Field | Type | Purpose | Status |
|---|---|---|---|
| `task_id` | str | Unique task identifier | planned |
| `trace_id` | str | Langfuse trace correlation ID | planned |
| `task_type` | Literal | ticket / maintenance / report | planned |
| `assigned_agent` | Optional[str] | Which specialist agent handles this | planned |
| `severity` | Optional[Literal] | LOW/MEDIUM/HIGH/CRITICAL | planned |
| `ticket_id` | Optional[str] | Linked ticket in DB | planned |
| `server_id` | Optional[str] | Target server | planned |
| `user_message` | Optional[str] | Raw ticket text | planned |
| `rag_hits` | List[dict] | RAG search results | planned |
| `web_search_results` | List[dict] | Tavily results | planned |
| `action_plan` | List[str] | Steps agent will execute | planned |
| `execution_log` | List[dict] | {command, output, success, timestamp} | planned |
| `status` | Literal | queued→assigned→thinking→executing→verifying→done/failed/escalated | planned |
| `resolution_summary` | Optional[str] | Final answer to user | planned |
| `error` | Optional[str] | Error message if failed | planned |
| `created_at` | datetime | Task creation time | planned |
| `updated_at` | datetime | Last state change | planned |

## Known Gaps / Deferred
- Phase 0: directory scaffold only, no implementation
- Task queue thread/process flow diagram — not yet written in systemdev_docs (gap identified)
