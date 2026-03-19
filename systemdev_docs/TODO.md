# TODO — GPU-MAS Build Plan

> Phased task list for Claude Code. Each task is atomic and testable.
> Work top-to-bottom within each phase. Mark `[x]` when done.

---

## PHASE 0 — Project Scaffold

- [x] `P0-01` Create monorepo directory structure (all `services/`, `infra/`, `docs/`)
- [x] `P0-02` Create root `docker-compose.yml` with all service stubs (image: placeholder, networks defined)
- [x] `P0-03` Create `.env.example` with all required variables documented
- [x] `P0-04` Create `.gitignore` (secrets, `.env`, `__pycache__`, `*.pem`, etc.)
- [x] `P0-05` Create shared `requirements-base.txt` (fastapi, uvicorn, pydantic, langchain, langgraph, anthropic, redis, asyncpg, sqlalchemy, cryptography, paramiko, prometheus-client, structlog)
- [x] `P0-06` Create shared `pyproject.toml` / `Makefile` with: `make dev`, `make build`, `make test`, `make lint`
- [x] `P0-07` Create `infra/postgres/init.sh` for multi-database init (masdb + langfuse)

---

## PHASE 1 — Core Infrastructure

### 1A — Database

- [ ] `P1-01` Write Alembic migration: `server_credentials` table (SECURITY.md §2.1)
- [ ] `P1-02` Write Alembic migration: `credential_access_log` table
- [ ] `P1-03` Write Alembic migration: `tickets` table `{id, server_id, description, severity, status, agent_id, trace_id, resolution_summary, created_at, updated_at}`
- [ ] `P1-04` Write Alembic migration: `daily_health_snapshots` table `{id, server_id, date, metrics_json, status, created_at}`
- [ ] `P1-05` Write Alembic migration: `rag_kb_entries` table `{id, error_pattern, fix_steps, tags, confidence, embedding_id, source, created_at}`
- [ ] `P1-06` Write Alembic migration: `task_queue` table (APScheduler job store)
- [ ] `P1-07` Create `services/shared/db.py` — async SQLAlchemy engine + session factory

### 1B — Redis Utilities

- [ ] `P1-08` Create `services/shared/redis_client.py` — async Redis client, connection pool, ping test
- [ ] `P1-09` Create `services/shared/rate_limiter.py` — token bucket (AGENT_DESIGN.md §5), Lua script, `acquire()` + `record_usage()`
- [ ] `P1-10` Create `services/shared/task_queue.py` — enqueue/dequeue task dicts via Redis list; `BLPOP` consumer loop

### 1C — SSH Vault Service

- [ ] `P1-11` Create `services/ssh-vault/main.py` — FastAPI app, internal network only
- [ ] `P1-12` Create `services/ssh-vault/crypto.py` — `VaultCrypto` class (SECURITY.md §2.2)
- [ ] `P1-13` Create `services/ssh-vault/models.py` — SQLAlchemy ORM models for credential tables
- [ ] `P1-14` Create `services/ssh-vault/routes.py`:
  - `POST /vault/credentials` — add server credential (encrypts all fields)
  - `PUT /vault/credentials/{server_id}` — update / rotate
  - `DELETE /vault/credentials/{server_id}` — deactivate
  - `POST /vault/session` — create short-lived SSH session, return session token
  - `POST /vault/session/{token}/execute` — run command via active session
  - `DELETE /vault/session/{token}` — close session
- [ ] `P1-15` Create `services/ssh-vault/session_registry.py` — in-process dict of `{token: paramiko.SSHClient}`, TTL-eviction via asyncio task
- [ ] `P1-16` Create `services/ssh-vault/safety.py` — `is_safe_command()` filter (SECURITY.md §5.2)
- [ ] `P1-17` Write Dockerfile for `ssh-vault`
- [ ] `P1-18` Write unit tests: encrypt/decrypt round-trip, session create/execute/close, safety filter

---

## PHASE 2 — API Gateway

- [ ] `P2-01` Create `services/api-gateway/main.py` — FastAPI app with all routers mounted
- [ ] `P2-02` Create `services/api-gateway/auth.py` — JWT issue + verify, API key check (API_DESIGN.md §6)
- [ ] `P2-03` Create `services/api-gateway/models.py` — all Pydantic models (API_DESIGN.md §2)
- [ ] `P2-04` Create `services/api-gateway/routes/auth.py` — `POST /auth/token`
- [ ] `P2-05` Create `services/api-gateway/routes/tickets.py`:
  - `POST /tickets` — validate, sanitise input, enqueue, return 202
  - `GET /tickets/{id}` — poll status from Postgres
  - `GET /tickets/{id}/log` — return sanitised agent log for ticket
- [ ] `P2-06` Create `services/api-gateway/routes/reports.py`:
  - `GET /reports/daily` and `GET /reports/daily/{date}`
  - `GET /reports/weekly`
- [ ] `P2-07` Create `services/api-gateway/routes/ops.py`:
  - `GET /ops/agents`, `GET /ops/queue`, `GET /ops/cost`, `POST /ops/cost/reset`
  - `GET /ops/servers`
- [ ] `P2-08` Create `services/api-gateway/routes/admin.py`:
  - CRUD for server fleet, manual maintenance trigger
- [ ] `P2-09` Create `services/api-gateway/routes/system.py` — `/health`, `/metrics`
- [ ] `P2-10` Create `services/api-gateway/middleware.py` — request ID injection, structured logging, rate limiter integration
- [ ] `P2-11` Create `services/api-gateway/sanitiser.py` — `sanitise_ticket_input()`, `sanitise_log()` (SECURITY.md §5.1, §5.3)
- [ ] `P2-12` Write Dockerfile for `api-gateway`
- [ ] `P2-13` Write integration tests: auth flow, ticket submit+poll, rate limit enforcement
- [ ] `P2-14` Create `infra/nginx/nginx.conf` — proxy to api-gateway, timeout config

---

## PHASE 3 — RAG Service

- [ ] `P3-01` Create `services/rag-service/main.py` — FastAPI app
- [ ] `P3-02` Create `services/rag-service/embedder.py` — OpenAI `text-embedding-3-small` calls, batch support
- [ ] `P3-03` Create `services/rag-service/vector_store.py` — Qdrant client, collection setup, upsert, search
- [ ] `P3-04` Create `services/rag-service/bm25_index.py` — `rank_bm25` index, persist index to Postgres (serialised), load on startup
- [ ] `P3-05` Create `services/rag-service/hybrid_search.py` — dense + sparse parallel search, Reciprocal Rank Fusion merge
- [ ] `P3-06` Create `services/rag-service/reranker.py` — cross-encoder rerank (sentence-transformers model loaded once at startup)
- [ ] `P3-07` Create `services/rag-service/semantic_cache.py` — query embedding → Redis cosine check → read/write cache
- [ ] `P3-08` Create `services/rag-service/routes.py`:
  - `POST /rag/search` — full pipeline: cache → hybrid → rerank
  - `POST /rag/ingest` — add error+fix pair to KB (sanitise → embed → upsert)
  - `DELETE /rag/entry/{id}` — remove entry
  - `GET /rag/stats` — KB size, cache hit rate
- [ ] `P3-09` Create `services/rag-service/sanitiser.py` — strip PII from patterns before storage
- [ ] `P3-10` Write Dockerfile for `rag-service`
- [ ] `P3-11` Write tests: ingest → search round-trip, cache hit behaviour, BM25 index persistence

---

## PHASE 4 — Agent Orchestrator

- [ ] `P4-01` Create `services/agent-orchestrator/state.py` — `AgentState` TypedDict (AGENT_DESIGN.md §2)
- [ ] `P4-02` Create `services/agent-orchestrator/supervisor.py` — LangGraph `StateGraph` with conditional routing
- [ ] `P4-03` Create `services/agent-orchestrator/worker_pool.py` — `asyncio.Semaphore` pool, task dispatch, stuck-task watchdog
- [ ] `P4-04` Create `services/agent-orchestrator/consumer.py` — Redis queue consumer loop, dispatches to worker pool
- [ ] `P4-05` Create `services/agent-orchestrator/main.py` — starts consumer + APScheduler
- [ ] `P4-06` Create `services/agent-orchestrator/scheduler_jobs.py`:
  - `daily_inserver_check` — enqueue maintenance task for all active servers
  - `weekly_report` — enqueue report generation task
  - `hourly_cache_cleanup` — clear expired Redis entries
- [ ] `P4-07` Create `services/agent-orchestrator/langfuse_tracer.py` — wrap LLM calls with Langfuse trace decorator, token recording
- [ ] `P4-08` Create `services/agent-orchestrator/routes.py` — internal API:
  - `POST /internal/tasks` — accept task enqueue from gateway
  - `PUT /internal/tasks/{id}/status` — agents report status
  - `GET /ops/agents` — live state view
  - `GET /ops/queue` — queue metrics
- [ ] `P4-09` Write Dockerfile for `agent-orchestrator`

---

## PHASE 5 — InServer Agent

- [ ] `P5-01` Create `services/inserver-agent/tools.py` — all tools listed in AGENT_DESIGN.md §1.2 (each as an async function calling vault service or Postgres)
- [ ] `P5-02` Create `services/inserver-agent/graph.py` — LangGraph graph: check_all_servers → per_server_health → fix_if_allowed → emit_snapshot
- [ ] `P5-03` Create `services/inserver-agent/prompts.py` — system prompt (AGENT_DESIGN.md §1.2)
- [ ] `P5-04` Create `services/inserver-agent/executor.py` — agent runner: receive task from orchestrator, run graph, report results
- [ ] `P5-05` Create `services/inserver-agent/health_checks.py`:
  - `check_gpu()` — nvidia-smi parser
  - `check_disk()` — df -h parser
  - `check_memory()` — free -m parser  
  - `check_process()` — systemctl status parser
  - `check_ssh_blacklist()` — fail2ban-client + iptables check
- [ ] `P5-06` Create `services/inserver-agent/main.py` — poll orchestrator for maintenance tasks
- [ ] `P5-07` Write Dockerfile for `inserver-agent`
- [ ] `P5-08` Write tests: mock SSH responses, verify health check parsers, verify blacklist detection + recovery

---

## PHASE 6 — Client Agent

- [ ] `P6-01` Create `services/client-agent/tools.py` — all tools: rag_search, web_search, web_fetch, ssh_execute, hard_restart, update_ticket_status, store_fix_pattern
- [ ] `P6-02` Create `services/client-agent/web_search.py` — Tavily API client with fallback to SerpAPI
- [ ] `P6-03` Create `services/client-agent/severity.py` — LLM classifier returning `LOW|MEDIUM|HIGH|CRITICAL`
- [ ] `P6-04` Create `services/client-agent/graph.py` — full ticket resolution LangGraph (AGENT_DESIGN.md §1.3 workflow)
- [ ] `P6-05` Create `services/client-agent/prompts.py` — system prompt (AGENT_DESIGN.md §1.3)
- [ ] `P6-06` Create `services/client-agent/hard_restart.py` — BMC/IPMI reboot call + SSH fallback `reboot -f`; requires double-log confirmation
- [ ] `P6-07` Create `services/client-agent/executor.py` — receive ticket task, run graph, update ticket status
- [ ] `P6-08` Create `services/client-agent/main.py` — poll orchestrator for ticket tasks
- [ ] `P6-09` Write Dockerfile for `client-agent`
- [ ] `P6-10` Write tests: mock RAG responses, mock SSH, verify plan→execute→verify flow, verify hard restart double-confirmation

---

## PHASE 7 — Report Agent

- [ ] `P7-01` Create `services/report-agent/aggregator.py` — fetch daily snapshots, ticket stats, cost data
- [ ] `P7-02` Create `services/report-agent/formatter.py` — render markdown report with tables
- [ ] `P7-03` Create `services/report-agent/sender.py` — webhook POST + optional SMTP
- [ ] `P7-04` Create `services/report-agent/graph.py` — LangGraph: aggregate → format → send
- [ ] `P7-05` Create `services/report-agent/prompts.py` — report agent system prompt
- [ ] `P7-06` Create `services/report-agent/main.py` — poll orchestrator for report tasks
- [ ] `P7-07` Write Dockerfile for `report-agent`

---

## PHASE 8 — LLMOps & Observability

- [ ] `P8-01` Configure Langfuse self-hosted in docker-compose (already in INFRA.md — verify working)
- [ ] `P8-02` Create `services/shared/logger.py` — structlog JSON logger factory, auto-injects `trace_id`, `agent_id`, `service`
- [ ] `P8-03` Add Prometheus `/metrics` to each service (use `prometheus-fastapi-instrumentator`)
- [ ] `P8-04` Create `infra/prometheus/prometheus.yml` — scrape all services
- [ ] `P8-05` Create `infra/grafana/dashboards/agent_overview.json` — queue depth, active agents, success rate
- [ ] `P8-06` Create `infra/grafana/dashboards/token_spend.json` — daily cost, RPM/TPM utilisation
- [ ] `P8-07` Create `infra/grafana/dashboards/server_fleet.json` — per-server health scores
- [ ] `P8-08` Create `infra/loki/loki-config.yaml` — local storage, 30d retention
- [ ] `P8-09` Add Loki log shipper (Promtail) sidecar or Docker logging driver to compose
- [ ] `P8-10` Create `services/api-gateway/routes/ops_dashboard.py` — `GET /ops/agents` live view endpoint (used by simple ops HTML page)
- [ ] `P8-11` Create simple ops HTML page at `services/api-gateway/static/ops.html` — auto-refreshing agent state table

---

## PHASE 9 — Integration & Testing

- [ ] `P9-01` Write end-to-end test: submit ticket → agent picks up → SSH mock → resolved
- [ ] `P9-02` Write end-to-end test: daily maintenance trigger → all servers checked → report generated
- [ ] `P9-03` Write load test (locust): 1000 ticket submissions → verify queue handles without dropping
- [ ] `P9-04` Write rate limit test: exceed `ANTHROPIC_RPM_LIMIT` → verify queuing, not dropping
- [ ] `P9-05` Write vault security test: attempt to access credentials without internal key → verify 403
- [ ] `P9-06` Write safety filter test: attempt forbidden SSH commands → verify rejection + alert log
- [ ] `P9-07` Docker compose smoke test: `docker compose up` → all `/health` endpoints return 200

---

## PHASE 10 — Hardening & Delivery

- [ ] `P10-01` Pin all Docker image versions in compose files
- [ ] `P10-02` Create `docker-compose.prod.yml` with Docker secrets, no port exposure for internal services
- [ ] `P10-03` Add `HEALTHCHECK` to every Dockerfile
- [ ] `P10-04` Create `Makefile` targets: `generate-vault-key`, `rotate-jwt-secret`, `backup-db`
- [ ] `P10-05` Write `docs/RUNBOOK.md` — how to scale, how to add a server, how to rotate secrets, how to investigate a stuck agent
- [ ] `P10-06` Write `docs/ONBOARDING.md` — first-time setup guide for ops team
- [ ] `P10-07` Disable `/docs` (Swagger) in production env
- [ ] `P10-08` Final security review against SECURITY.md checklist

---

## Tech Stack Reference

| Component | Technology |
|---|---|
| Agent Framework | LangGraph + Anthropic Claude (claude-sonnet-4-20250514) |
| API | FastAPI + Uvicorn + Gunicorn |
| Task Queue | Redis (asyncio consumer) |
| Database | PostgreSQL 16 + Alembic |
| Connection Pool | PgBouncer |
| Cache | Redis 7 |
| Vector Store | Qdrant |
| Embedding | OpenAI text-embedding-3-small (via Anthropic API or direct) |
| Reranker | sentence-transformers cross-encoder/ms-marco-MiniLM-L-6-v2 |
| SSH | paramiko |
| Encryption | cryptography (AES-256-GCM) |
| Auth | python-jose (JWT) |
| Rate Limiting | slowapi + Redis token bucket |
| Web Search | Tavily API |
| LLMOps | Langfuse OSS (self-hosted) |
| Metrics | Prometheus + Grafana |
| Logs | structlog → Loki |
| Scheduler | APScheduler |
| Containers | Docker + Docker Compose |
