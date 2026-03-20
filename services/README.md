# services/ — Service Directory

Each subdirectory is an independently deployable microservice (or shared library). Every directory contains a `README.md` (architecture + API reference) and a `dev_note.md` (implementation inventory — read this before adding new functions).

## Service Map

| Directory | Port | Role | Key Files |
|---|---|---|---|
| [`api-gateway/`](api-gateway/README.md) | 8000 | Public entrypoint — JWT auth, rate limiting, ticket intake, ops UI | `routes/`, `auth.py`, `sanitiser.py` |
| [`agent-orchestrator/`](agent-orchestrator/README.md) | 8001 | Redis queue consumer, LangGraph supervisor, APScheduler cron, worker pool | `supervisor.py`, `consumer.py`, `worker_pool.py`, `scheduler_jobs.py` |
| [`inserver-agent/`](inserver-agent/README.md) | 8002 | Daily health checks on company's own GPU servers | `graph.py`, `tools.py` |
| [`client-agent/`](client-agent/README.md) | 8003 | Ticket resolution agent — SSH into client-rented servers | `graph.py`, `tools.py` |
| [`report-agent/`](report-agent/README.md) | 8004 | Weekly/daily report generation and delivery | `graph.py`, `formatter.py`, `sender.py` |
| [`rag-service/`](rag-service/README.md) | 8005 | Hybrid RAG: Qdrant dense + BM25 sparse + cross-encoder rerank + semantic cache | `embedder.py`, `hybrid_search.py`, `reranker.py`, `semantic_cache.py` |
| [`ssh-vault/`](ssh-vault/README.md) | 8100 | AES-256-GCM encrypted SSH credential store; issues paramiko sessions | `vault.py`, `session_manager.py`, `safety_filter.py` |
| [`shared/`](shared/README.md) | — | Cross-service utilities (DB, Redis, rate limiter, logger, task queue) | `db.py`, `rate_limiter.py`, `logger.py`, `task_queue.py` |
| [`scheduler/`](scheduler/README.md) | — | **REMOVED** — cron jobs embedded in `agent-orchestrator/scheduler_jobs.py` | See `scheduler/dev_note.md` |

## Communication Pattern

```
External client
      │
      ▼ HTTP (port 80)
   nginx
      │
      ▼ HTTP (port 8000)
  api-gateway ──── writes ────► mas:client_queue (Redis)
      │                          mas:inserver_queue
      │                          mas:report_queue
      │
      ◄──── agent callbacks (PUT /internal/tasks/{id}/status)
      │
      ▼ BLPOP
  orchestrator ──► routes task type ──► specialist agent (HTTP or same process)
      │
      ├──► client-agent   ──► ssh-vault (GET /vault/session/{id})
      ├──► inserver-agent ──► ssh-vault
      ├──► report-agent   ──► api-gateway (reads DB via direct conn)
      └──► rag-service    ◄── client-agent (GET /rag/search?q=...)
```

## Dev Rules

1. **Read `dev_note.md` before writing any new function** — prevents duplicates across sessions.
2. **Update `dev_note.md` before ending a session** — mark new functions, removed functions (`❌ REMOVED`), and stubs (`⚠️ STUB`).
3. **Shared utilities live in `shared/`** — don't re-implement DB sessions, Redis clients, or rate limiters in individual services.
4. **Agents never receive raw SSH keys** — they call `ssh-vault` for a session token. This is enforced by design.
