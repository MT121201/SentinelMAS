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
