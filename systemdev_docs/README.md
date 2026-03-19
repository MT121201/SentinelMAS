# GPU-MAS — Multi-Agent Server Management System

> Outsourced AI Senior System — GPU Rental Company Infrastructure Automation

---

## What This Is

A containerised **Multi-Agent System (MAS)** that autonomously manages GPU server infrastructure for a rental company. Two operational planes:

| Plane | Scope | Trigger |
|---|---|---|
| **InServer** | Daily health checks, blacklist recovery, proactive maintenance on *our* infra | Cron + Alert |
| **External (Client-Side)** | SSH into client-rented servers, resolve user tickets, install packages, fix errors | User ticket |

Agents are fully observable via structured logs and an LLMOps dashboard. The system is self-healing, rate-limit-aware, and ships as a Docker Compose stack that can be duplicated per deployment zone.

---

## Repo Structure

```
gpu-mas/
├── README.md                   ← you are here
├── SYSTEM_DESIGN.md            ← architecture, data-flow, component map
├── REQUIREMENTS.md             ← functional + non-functional requirements
├── AGENT_DESIGN.md             ← agent roles, tools, prompts, RAG design
├── SECURITY.md                 ← SSH vault, key rotation, secret handling
├── INFRA.md                    ← Docker topology, scaling rules, resource limits
├── API_DESIGN.md               ← FastAPI routes, auth, rate limiting
├── TODO.md                     ← phased task list ready for Claude Code
│
├── services/
│   ├── api-gateway/            ← FastAPI entrypoint (auth, rate-limit, routing)
│   ├── agent-orchestrator/     ← LangGraph supervisor + agent pool
│   ├── inserver-agent/         ← daily maintenance agent
│   ├── client-agent/           ← ticket resolution + SSH executor
│   ├── rag-service/            ← hybrid retrieval (vector + BM25) + cache
│   ├── ssh-vault/              ← encrypted SSH credential store
│   ├── llmops/                 ← log collector, trace exporter, dashboard
│   └── scheduler/              ← cron triggers for daily tasks
│
├── infra/
│   ├── docker-compose.yml
│   ├── docker-compose.prod.yml
│   └── nginx/
│
└── docs/
    └── architecture-diagram.md
```

---

## Quick Start (Dev)

```bash
# 1. Copy env template
cp .env.example .env
# Fill: ANTHROPIC_API_KEY, VAULT_MASTER_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD

# 2. Build & launch all services
docker compose up --build

# 3. API is at http://localhost:8000
# 4. LLMOps dashboard at http://localhost:3001
# 5. Flower (task monitor) at http://localhost:5555
```

---

## Core Design Principles

1. **Agent transparency** — every agent thought, tool call, and decision is logged with a trace ID.
2. **Secret isolation** — SSH keys never leave the vault service; agents receive a signed session token per operation.
3. **Rate-limit shield** — a token-bucket middleware wraps all Anthropic API calls; agents queue rather than drop.
4. **Pool before scale** — worker pools, connection pools, and async queues are exhausted before horizontal scaling.
5. **Client server privacy** — the system never stores or logs raw content from client servers beyond operation metadata.
6. **Fake-it-until architecture** — RAG and knowledge base are designed to be populated incrementally; system operates with empty KB and degrades gracefully to web search fallback.
