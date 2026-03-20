# dev_note — api-gateway

## Purpose
Public FastAPI entrypoint: JWT auth, rate limiting, request routing to orchestrator and internal services.

## Files

### config.py
- `Settings` — pydantic-settings; reads JWT_SECRET_KEY, INTERNAL_API_KEY, ADMIN_USERNAME, ADMIN_PASSWORD_HASH, VAULT_URL, ORCHESTRATOR_URL, ENV

### auth.py
- `verify_password(plain, hashed) -> bool` — bcrypt check
- `hash_password(plain) -> str` — bcrypt hash (use for generating ADMIN_PASSWORD_HASH)
- `create_access_token(subject) -> str` — signs JWT with HS256, 24h expiry
- `_decode_token(token) -> dict` — verifies JWT; raises 401 on failure
- `get_current_user(credentials) -> dict` — FastAPI dep; validates Bearer JWT
- `require_api_key(key) -> str` — FastAPI dep; validates X-API-Key header
- `require_internal_key(key) -> str` — FastAPI dep; same key, used for /internal routes

### models.py
- `TokenRequest / TokenResponse` — auth
- `TicketCreate / TicketResponse / TicketLogEntry` — ticket lifecycle
- `ServerCreate / ServerInfo` — server fleet
- `AgentStateInfo / QueueStats / CostSummary` — ops dashboard
- `ErrorDetail / ErrorResponse` — standard error envelope

### sanitiser.py
- `sanitise_ticket_input(text) -> str` — strips HTML, prompt-injection markers, truncates to 4000 chars
- `sanitise_log(text) -> str` — redacts IPv4, passwords, PEM keys, home paths before returning to users

### limiter.py
- `limiter` — slowapi Limiter singleton; key_func=get_remote_address; applied via @limiter.limit() decorator

### middleware.py
- `RequestContextMiddleware` — injects X-Request-ID (UUID), structured request/response logging

### routes/auth.py
- `POST /auth/token` — 5/min rate limit; validates admin credentials; returns JWT

### routes/tickets.py
- `POST /tickets` — 20/min; sanitises input; inserts to DB; enqueues to `mas:client_queue`; returns 202
- `GET /tickets/{ticket_id}` — 60/min; polls DB; sanitises resolution_summary before return
- `GET /tickets/{ticket_id}/log` — 30/min; returns sanitised log entries (Loki integration deferred to Phase 8)
- `_Ticket` — inline SQLAlchemy model (mirrors tickets table; canonical in alembic/versions/003)

### routes/reports.py
- `GET /reports/daily` — latest snapshot per server (DISTINCT ON)
- `GET /reports/daily/{date}` — snapshots for specific date
- `GET /reports/weekly` — last 7 days snapshots + ticket status counts

### routes/ops.py
- `GET /ops/agents` — reads `mas:agent:states` Redis key (set by orchestrator in Phase 4); empty until then
- `GET /ops/queue` — Redis queue depths + ticket status counts from DB
- `GET /ops/cost` — calls `rate_limiter.get_utilisation()` → CostSummary
- `POST /ops/cost/reset` — calls `rate_limiter.reset_daily_cost()`
- `GET /ops/servers` — LATERAL JOIN: server_credentials + latest daily_health_snapshots

### routes/admin.py
- `GET /admin/servers` — list all servers with health status
- `POST /admin/servers` — forwards to vault POST /vault/credentials via httpx
- `PUT /admin/servers/{id}/credential` — forwards to vault PUT /vault/credentials/{id}
- `DELETE /admin/servers/{id}` — forwards to vault DELETE /vault/credentials/{id}
- `POST /admin/maintenance/trigger` — enqueues maintenance task to `mas:inserver_queue`

### routes/system.py
- `GET /health` — checks Postgres + Redis; returns queue depths + rate limit stats; 503 if degraded

### main.py
- FastAPI app; port 8000; 4 Gunicorn workers (prod)
- Registers: SlowAPIMiddleware, RequestContextMiddleware, all routers
- `global_exception_handler` — returns structured error with request_id on unhandled exceptions
- `shutdown()` — calls `close_redis()`

## Cross-Service Contracts
- Enqueues to: `mas:client_queue`, `mas:inserver_queue` (Redis)
- Reads: `tickets`, `server_credentials`, `daily_health_snapshots` (Postgres)
- Calls: `ssh-vault` for admin credential CRUD (httpx, X-Internal-Key)
- Reads: `mas:agent:states` Redis key (written by orchestrator, Phase 4)
- Runs migrations: `alembic upgrade head` on startup (Alembic included in image)
- Listens on: port 8000; public + internal Docker networks
- Build context: root (needs `services/shared/` + `alembic/`)

## Known Gaps / Deferred
- `/tickets/{id}/log` — full structured log from Loki deferred to Phase 8 (P8-xx); currently returns synthesised entry from DB
- `GET /ops/agents` — returns empty list until orchestrator (Phase 4) writes `mas:agent:states`
- Admin auth uses single shared API key — per-user RBAC deferred to v2
