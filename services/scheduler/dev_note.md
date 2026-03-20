# dev_note — scheduler

## Status: REMOVED FROM DOCKER-COMPOSE — EMBEDDED IN ORCHESTRATOR

The originally planned separate `scheduler` container was **never built** and was **removed from `docker-compose.yml`** during the Phase 10 deployment fix. All scheduling functionality lives inside `services/agent-orchestrator/`.

## Where the scheduler lives now

| File | What it does |
|---|---|
| `services/agent-orchestrator/scheduler_jobs.py` | All three cron jobs: `daily_inserver_check`, `weekly_report`, `hourly_cache_cleanup` |
| `services/agent-orchestrator/main.py` (step 5) | APScheduler startup + `register_jobs()` call |

## Why it was consolidated

Running APScheduler inside the orchestrator eliminates a network hop (scheduler → orchestrator HTTP call) and removes an extra service to manage. The orchestrator already holds the Redis and DB connections the jobs need.

## APScheduler configuration

- **Job store:** `MemoryJobStore` (jobs re-register on startup with `replace_existing=True`)
- **Executor:** `AsyncIOExecutor` (shares the orchestrator's event loop)
- **Jobs:** 3 fixed cron schedules — see `scheduler_jobs.py` for trigger definitions

## Do not re-create this as a separate service unless

- You need multi-replica orchestrators (each would fire duplicate jobs)
- You need jobs to survive orchestrator restarts without re-registration

In either case, switch the job store to `SQLAlchemyJobStore` AND refactor job kwargs to avoid passing unpicklable async objects (use module-level globals or a factory pattern instead).
