# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Where to Find Plans, Design Docs & Progress

All design and planning documents live in `systemdev_docs/`:

| File | Purpose |
|---|---|
| `systemdev_docs/TODO.md` | **Phased task list** — the build plan. Work top-to-bottom per phase. Mark `[x]` when done. |
| `systemdev_docs/SYSTEM_DESIGN.md` | Architecture overview, component descriptions, data-flow diagrams |
| `systemdev_docs/AGENT_DESIGN.md` | Agent roles, tool lists, system prompts, RAG design |
| `systemdev_docs/REQUIREMENTS.md` | Functional + non-functional requirements |
| `systemdev_docs/API_DESIGN.md` | FastAPI routes, Pydantic models, auth, rate-limiting spec |
| `systemdev_docs/SECURITY.md` | SSH vault design, key rotation, command safety filter |
| `systemdev_docs/INFRA.md` | Docker topology, service ports, scaling rules, resource limits |

**Always read `TODO.md` first** to know the current phase and the next unchecked task. Mark tasks `[x]` as they are completed.

## Project: GPU-MAS (SentinelMAS)

A containerised **Multi-Agent System** that autonomously manages GPU server infrastructure for a GPU rental company. Two operational planes:

- **InServer plane** — cron-triggered daily health checks, disk/GPU/memory probes, SSH blacklist self-recovery on the company's own servers
- **Client plane** — SSH into client-rented servers to resolve user-submitted support tickets

## Planned Monorepo Structure

```
services/
  api-gateway/          # FastAPI, JWT auth, rate limiting, public entrypoint
  agent-orchestrator/   # LangGraph supervisor, Redis queue consumer, APScheduler
  inserver-agent/       # Daily maintenance agent (own infra)
  client-agent/         # Ticket resolution agent (client servers)
  report-agent/         # Weekly/daily summary aggregator + sender
  rag-service/          # Hybrid retrieval (Qdrant + BM25) + semantic cache
  ssh-vault/            # AES-256-GCM encrypted credential store, paramiko sessions
  shared/               # db.py, redis_client.py, rate_limiter.py, logger.py
infra/
  docker-compose.yml
  docker-compose.prod.yml
  postgres/             # init.sh (creates masdb + langfuse DBs)
  nginx/
  prometheus/
  grafana/dashboards/
  loki/
```

## Architecture Key Points

- **Agent framework**: LangGraph `StateGraph` with a Supervisor node routing tasks to specialist agents.
- **LLM**: Anthropic Claude (`claude-sonnet-4-20250514`) for all agent reasoning.
- **Task flow**: API Gateway → Redis queue → Orchestrator → specialist agent → SSH Vault → target server.
- **SSH access pattern**: Agents never receive raw SSH keys. They call `vault.get_session(server_id)` which returns a short-lived `paramiko` session (TTL 300 s). Raw keys stay inside the vault service.
- **RAG**: Hybrid dense (Qdrant `text-embedding-3-small`) + sparse (BM25), cross-encoder reranked, with a Redis semantic cache layer in front. KB starts empty and is populated from confirmed fix pairs.
- **Rate limiting**: Single token-bucket in Redis shared by all agents; wraps every Anthropic API call. Agents queue, never drop.
- **Observability**: Every LLM call traced in Langfuse (self-hosted). Structured JSON logs → Loki. Prometheus metrics → Grafana.

## Directory Dev Notes — Mandatory Rule

Every service/package directory (`services/*`, `infra/*`, `services/shared/`) **must** contain a `dev_note.md` file. This is the single source of truth for what exists in that directory and prevents duplicate functions, orphaned state fields, and re-invented utilities across sessions.

### When to create it
Create `dev_note.md` the moment you write the **first file** in a new directory.

### When to update it
Update `dev_note.md` **every time** you add, rename, remove, or significantly change a function, class, or state field in that directory — before ending the session.

### What goes inside

```markdown
# dev_note — <service-name>

## Purpose
One sentence: what this service/module does.

## Files
### <filename>.py
- `ClassName` — what it is
  - `method_name(args)` — what it does, return type
  - `method_name(args)` — ⚠️ STUB: defined but not implemented yet
  - `method_name(args)` — ❌ REMOVED: was X, replaced by Y in <other_file>.py

## State Fields (for LangGraph state files)
| Field | Type | Purpose | Status |
|---|---|---|---|
| `task_id` | str | Unique task identifier | active |
| `waiting_for` | str | Blocks execution until this resolves | active |
| `final_response` | str | Output returned to caller | active |
| `severity` | Literal | Ticket severity level | active |

## Cross-Service Contracts
- Calls: `ssh-vault /vault/session` — to get SSH session token
- Called by: `agent-orchestrator` — via Redis queue task dispatch
- Shares: `AgentState` TypedDict from `services/shared/state.py`

## Known Gaps / Deferred
- `hard_restart()` — wired in tools.py but BMC/IPMI call not implemented (Phase 6)
- Rate limit backoff — placeholder sleep, real backoff in shared rate_limiter.py
```

### Rules
- **Before writing any function**: check `dev_note.md` to confirm it does not already exist in this dir or a shared module.
- **State fields**: every field in a `TypedDict` or `AgentState` must appear in the State Fields table with its purpose. No field without a row.
- **Stubs**: mark unimplemented functions `⚠️ STUB` so the next session knows not to treat them as working.
- **Removed code**: when you delete or replace a function, log it as `❌ REMOVED` with what replaced it — prevents re-creation.
- **Cross-service**: if this module calls another service or is called by one, document the contract so refactors stay consistent.

---

## Development Commands

> The Makefile is defined in `TODO.md P0-06` and will be created during Phase 0.

```bash
# Start all services (dev)
make dev
# or
docker compose up --build

# Run all tests
make test

# Lint
make lint

# Run a single test file
pytest services/<service>/tests/test_<module>.py -v

# Generate vault master key
make generate-vault-key

# Apply DB migrations
alembic upgrade head

# Run a single service in isolation
docker compose up api-gateway redis postgres
```

## Tech Stack

| Layer | Technology |
|---|---|
| Agents | LangGraph + Anthropic Claude |
| API | FastAPI + Uvicorn + Gunicorn |
| Queue | Redis (asyncio `BLPOP` consumer) |
| Database | PostgreSQL 16 + Alembic + PgBouncer |
| Vector Store | Qdrant |
| Embedding | OpenAI `text-embedding-3-small` |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| SSH | paramiko (via vault service) |
| Encryption | `cryptography` AES-256-GCM |
| Auth | `python-jose` JWT |
| Web Search | Tavily API (SerpAPI fallback) |
| LLMOps | Langfuse OSS (self-hosted) |
| Metrics | Prometheus + Grafana |
| Logs | structlog → Loki |
| Scheduler | APScheduler (PostgreSQL job store) |
