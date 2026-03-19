# SYSTEM DESIGN — GPU-MAS

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL WORLD                               │
│  GPU Rental Users (ticket via HTTP)   Manager (report via HTTP)     │
└────────────────────────┬────────────────────────┬───────────────────┘
                         │                        │
                    ┌────▼────────────────────────▼────┐
                    │         API GATEWAY               │
                    │  FastAPI  │  Auth  │  Rate Limiter │
                    │  (Bearer JWT + API Key)            │
                    └────────────────┬─────────────────┘
                                     │
                    ┌────────────────▼─────────────────┐
                    │       AGENT ORCHESTRATOR          │
                    │   LangGraph Supervisor Graph      │
                    │  ┌──────────┐  ┌──────────────┐  │
                    │  │ Ticket   │  │  Scheduler   │  │
                    │  │ Router   │  │  (cron jobs) │  │
                    │  └────┬─────┘  └──────┬───────┘  │
                    └───────┼───────────────┼──────────┘
             ┌─────────────┼───────────────┼──────────────┐
             │             │               │              │
    ┌────────▼──────┐ ┌────▼─────────┐ ┌──▼──────────┐  │
    │ CLIENT AGENT  │ │ INSERVER     │ │  REPORT     │  │
    │ (ticket work) │ │ AGENT        │ │  AGENT      │  │
    │               │ │ (daily maint)│ │  (summary)  │  │
    └───────┬───────┘ └─────┬────────┘ └──────┬──────┘  │
            │               │                 │          │
    ┌───────▼───────────────▼─────────────────▼──────┐  │
    │              SHARED TOOL LAYER                   │  │
    │  ┌──────────┐ ┌──────────┐ ┌─────────────────┐  │  │
    │  │ SSH Exec │ │ RAG/Cache│ │  Web Search     │  │  │
    │  │ (vault)  │ │ Service  │ │  (Tavily/SerpAPI│  │  │
    │  └────┬─────┘ └────┬─────┘ └────────┬────────┘  │  │
    └───────┼────────────┼────────────────┼────────────┘  │
            │            │                │               │
    ┌───────▼────┐ ┌──────▼──────┐ ┌──────▼───────┐      │
    │ SSH VAULT  │ │  VECTOR DB  │ │  REDIS       │      │
    │ (Postgres  │ │ (Qdrant)    │ │  Cache +     │      │
    │  AES-256)  │ │ + BM25 idx  │ │  Task Queue  │      │
    └────────────┘ └─────────────┘ └──────────────┘      │
                                                          │
    ┌───────────────────────────────────────────────────┐ │
    │                   LLMOPS / OBSERVABILITY          │◄┘
    │   Langfuse (traces) │ Prometheus │ Grafana        │
    │   Structured JSON logs → Loki                     │
    └───────────────────────────────────────────────────┘
```

---

## 2. Component Descriptions

### 2.1 API Gateway (`services/api-gateway`)

- **Framework**: FastAPI with Uvicorn + Gunicorn workers
- **Auth**: Bearer JWT (user-facing) + static API Key (manager/internal)
- **Rate Limiting**: `slowapi` per-IP + per-user token bucket; hard cap protects Anthropic API quota
- **Responsibilities**:
  - Validate + decode tokens
  - Route `/ticket` → Orchestrator task queue
  - Route `/report` → Report Agent
  - Route `/admin/*` → InServer Agent
  - Serve `/health` and `/metrics` endpoints

### 2.2 Agent Orchestrator (`services/agent-orchestrator`)

- **Framework**: LangGraph `StateGraph` with a Supervisor node
- **Pattern**: Supervisor selects which specialist agent handles each task; agents report back; supervisor decides if resolved or escalates
- **State**: Full agent state stored in Redis (TTL-bound) for resumability
- **Worker Pool**: `asyncio` semaphore limits concurrent agent invocations to prevent API rate-limit bursts
- **Cron Integration**: APScheduler fires daily InServer tasks and weekly report generation

### 2.3 InServer Agent (`services/inserver-agent`)

Handles **our own infrastructure**. Runs on schedule or alert trigger.

**Daily tasks**:
1. SSH health probe all registered servers
2. Disk / memory / GPU utilization check
3. SSH blacklist self-recovery (detect + unblock own IP)
4. Service restart if process down
5. Log rotation check
6. Generate daily status snapshot → Redis

**Capabilities**: Read-only by default; write-ops require a confirmed action plan logged before execution.

### 2.4 Client Agent (`services/client-agent`)

Handles **user tickets** — SSH into client-side servers (still our hardware, client's environment).

**Workflow**:
1. Receive ticket (text, optional screenshot/log attachment)
2. Classify severity: `LOW | MEDIUM | HIGH | CRITICAL`
3. RAG lookup → check known error patterns + fix playbooks
4. If no hit → web search fallback
5. Build action plan, log plan before executing
6. SSH into target server, execute fix steps
7. Verify fix, capture output
8. Respond to user with resolution summary + log trace ID

**Hard Restart**: `CRITICAL` severity can trigger server hard restart via IPMI/BMC API call (separate privileged tool, requires double-confirmation in log).

### 2.5 RAG Service (`services/rag-service`)

- **Retrieval**: Hybrid — dense vector (Qdrant, `text-embedding-3-small`) + sparse BM25 (`rank_bm25`)
- **Reranking**: Cross-encoder rerank top-20 → top-5
- **Cache**: Redis semantic cache — before retrieval, check if query embedding is within cosine threshold of a cached query result (TTL: 1 hour for error fixes, 24 hours for static docs)
- **Knowledge Base**: Starts empty ("fake-it" mode). Populated incrementally as error+fix pairs are confirmed.
- **Privacy**: Client server content (logs, configs) is **never** stored in the KB. Only sanitised error patterns are stored.

### 2.6 SSH Vault (`services/ssh-vault`)

- **Storage**: PostgreSQL table `server_credentials`, encrypted columns (AES-256-GCM) using `cryptography` library
- **Master Key**: Injected via environment variable at container startup, never written to disk
- **Access Pattern**: Agents do not receive raw SSH keys. They call `vault.get_session(server_id, agent_id, ttl=300)` which returns a short-lived `paramiko` session object (in-process) or a signed temp-key written to a tmpfs mount (never persisted)
- **Audit Log**: Every credential access logged: `{timestamp, agent_id, server_id, operation, trace_id}`

### 2.7 LLMOps / Observability (`services/llmops`)

- **Trace**: Langfuse OSS (self-hosted) — captures every LLM call: prompt, response, token count, latency, cost
- **Metrics**: Prometheus scrapes all services; Grafana dashboards for: agent queue depth, API error rate, token spend/hour, server health scores
- **Logs**: All services emit structured JSON logs → Loki. Every agent reasoning step tagged with `trace_id`, `agent_id`, `task_id`
- **Supervisor View**: A lightweight dashboard (`/ops`) shows live agent thought chains for human oversight

### 2.8 Scheduler (`services/scheduler`)

- APScheduler with persistent job store in PostgreSQL
- Jobs: `daily_inserver_check` (00:00 UTC), `weekly_report` (Monday 08:00), `cache_cleanup` (hourly)

---

## 3. Data Flow — User Ticket

```
User POST /ticket
  → API Gateway validates JWT
  → Enqueue task to Redis queue (Celery or asyncio queue)
  → Return {ticket_id, status: "queued"} immediately (202)

Orchestrator picks up task:
  → Supervisor: classify ticket
  → Client Agent activated
    → RAG lookup (hybrid search)
    → Cache hit? → use cached fix plan
    → Cache miss → web search
    → Build action plan
    → Log plan (LLMOps trace)
    → Request SSH session from vault
    → Execute steps on server
    → Verify + capture output
    → Store error+fix pattern in RAG KB (sanitised)
    → Update ticket status → "resolved"
    → Notify user (webhook / polling endpoint)
```

---

## 4. Data Flow — Daily Maintenance

```
Scheduler fires daily_inserver_check:
  → Orchestrator creates InServer Agent task
  → Agent iterates all registered servers (parallel, bounded semaphore)
  → Per server:
    - SSH probe
    - Run check scripts
    - Detect anomalies
    - Auto-fix if within allowed ops
    - Flag if escalation needed
  → Aggregate results → daily snapshot in Postgres
  → Report Agent formats summary (markdown + metrics)
  → POST to manager webhook / email
```

---

## 5. Scaling Design

**Principle**: Pool first, scale second. Scale in, not out of hand.

| Layer | Strategy |
|---|---|
| API Gateway | Gunicorn multi-worker; scale replica count (2→8) |
| Agent Workers | `asyncio` semaphore pool within container; add containers via compose `--scale` |
| LLM Calls | Token-bucket rate limiter (singleton in Redis); all agents share one bucket |
| DB Connections | PgBouncer connection pool in front of Postgres |
| Redis | Single Redis instance with cluster mode ready config; pipeline batch ops |
| Qdrant | Single node; collection sharding ready when >1M vectors |

**Scale trigger**: Prometheus alert → Grafana webhook → ops team decision (no auto-scale to avoid cost runaway).

---

## 6. Privacy & Trust Boundaries

```
┌──────────────────────────────────────────────────────┐
│  TRUST ZONE: OUR AGENTS                              │
│                                                      │
│  Can see: server IDs, IP addresses, error codes,     │
│           sanitised log snippets (no user data)      │
│                                                      │
│  Cannot see: raw client files, user documents,       │
│              SSH private key bytes                   │
│                                                      │
│  SSH vault is a black box — agents get sessions,     │
│  not keys.                                           │
└──────────────────────────────────────────────────────┘
```

No client document ingestion in this version. RAG KB is built only from **confirmed error+fix pairs** that agents discover during operations.
