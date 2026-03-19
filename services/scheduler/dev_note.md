# dev_note — scheduler

## Purpose
Lightweight APScheduler container that fires cron tasks (daily maintenance, weekly reports, hourly cache cleanup) to the orchestrator via HTTP POST.

## Files
> Not yet built — part of Phase 4 (P4-05, P4-06).

Planned files:
- `main.py` — configures APScheduler with PostgreSQL job store, starts scheduler
- `jobs.py` — `daily_inserver_check`, `weekly_report`, `hourly_cache_cleanup`

## Cross-Service Contracts
- Calls: `orchestrator POST /internal/tasks` to enqueue scheduled tasks
- Uses: Postgres `apscheduler_jobs` table as job store (migration P1-06)
- Auth: `INTERNAL_API_KEY` header

## Known Gaps / Deferred
- Phase 0/1: scaffold only — no implementation until Phase 4
