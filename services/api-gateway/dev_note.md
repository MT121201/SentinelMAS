# dev_note — api-gateway

## Purpose
Public FastAPI entrypoint: JWT auth, rate limiting, request routing to orchestrator and internal services.

## Files
> Phase 0 scaffold — no code files yet. Built in Phase 2.

Planned files (from TODO.md P2-xx):
- `main.py` — FastAPI app, all routers mounted
- `auth.py` — JWT issue + verify, API key check
- `models.py` — all Pydantic request/response models
- `middleware.py` — request ID injection, structured logging, rate limiter
- `sanitiser.py` — `sanitise_ticket_input()`, `sanitise_log()`
- `routes/auth.py` — `POST /auth/token`
- `routes/tickets.py` — `POST /tickets`, `GET /tickets/{id}`, `GET /tickets/{id}/log`
- `routes/reports.py` — `GET /reports/daily`, `GET /reports/weekly`
- `routes/ops.py` — agent/queue/cost/server ops endpoints
- `routes/admin.py` — server fleet CRUD, manual maintenance trigger
- `routes/system.py` — `/health`, `/metrics`

## Cross-Service Contracts
- Enqueues tasks to Redis queue (key: `mas:task_queue`) consumed by orchestrator
- Reads ticket status from Postgres `tickets` table
- Internal services call each other using `INTERNAL_API_KEY` header

## State Fields
N/A — stateless service; all state in Postgres + Redis.

## Known Gaps / Deferred
- Phase 0: directory scaffold only, no implementation
