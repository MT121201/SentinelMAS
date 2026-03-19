# REQUIREMENTS — GPU-MAS

## 1. Functional Requirements

### FR-01 — InServer Daily Maintenance
- [ ] Agent runs daily health check on all registered servers via SSH
- [ ] Check items: CPU, RAM, GPU utilization, disk space, process health, SSH daemon
- [ ] Detect and recover from SSH IP blacklist (own IP blocked by server firewall)
- [ ] Restart failed services within allowed service list
- [ ] Generate structured daily report (JSON + human-readable markdown)
- [ ] Deliver report to manager via webhook or polling endpoint

### FR-02 — User Ticket Handling
- [ ] Accept ticket via REST API (`POST /ticket`) with text description + optional file attachment (log, screenshot)
- [ ] Return ticket ID immediately (async, 202 Accepted)
- [ ] Classify ticket severity: `LOW | MEDIUM | HIGH | CRITICAL`
- [ ] Resolve ticket using RAG knowledge base
- [ ] Fall back to web search if KB has no relevant answer
- [ ] SSH into target server and execute fix steps
- [ ] Verify fix success before closing ticket
- [ ] Update ticket status (queued → in_progress → resolved | escalated)
- [ ] Provide user-facing summary of what was done (no raw server output)

### FR-03 — Hard Restart Capability
- [ ] `CRITICAL` severity tickets may trigger server hard restart
- [ ] Hard restart requires: (a) automatic confirmation check, (b) logged intent before action, (c) BMC/IPMI API call or SSH reboot command
- [ ] Restart event must be reported to manager immediately

### FR-04 — RAG Knowledge Base
- [ ] Hybrid retrieval: dense vector + BM25
- [ ] Redis semantic cache on top of retrieval
- [ ] KB populated from confirmed error+fix pairs (not client documents)
- [ ] Cache invalidation: 1h for operational fixes, 24h for static knowledge
- [ ] KB starts empty; system operates in web-search-fallback mode

### FR-05 — SSH Credential Vault
- [ ] Store per-server: hostname/IP, port, username, SSH private key, sudo password (optional)
- [ ] All credentials encrypted at rest (AES-256-GCM)
- [ ] Agents access credentials via session API (never receive raw key bytes in application memory beyond paramiko context)
- [ ] Credential access audit log
- [ ] Admin API to add/update/rotate credentials

### FR-06 — LLMOps & Observability
- [ ] Every LLM call traced (prompt, response, tokens, latency, cost) via Langfuse
- [ ] Structured JSON logs from all services with `trace_id`, `agent_id`, `task_id`
- [ ] Prometheus metrics exposed per service
- [ ] Grafana dashboards: queue depth, agent state, token spend, error rate, server health
- [ ] Supervisor "thought chain" view for human oversight

### FR-07 — Authentication
- [ ] JWT Bearer token auth for user-facing endpoints (issue via `/auth/token`)
- [ ] API Key auth for manager/admin/internal service-to-service calls
- [ ] All sensitive endpoints require auth
- [ ] Token expiry: 24h for user JWT, no expiry for static API keys (rotatable)

### FR-08 — Agent Onboarding Log
- [ ] When agent picks up a task, emit onboarding event: `{ticket_id, agent_id, assigned_at, estimated_start}`
- [ ] User can poll `GET /ticket/{id}/status` to see live agent state
- [ ] Agent state machine: `queued → assigned → thinking → executing → verifying → done | failed`

---

## 2. Non-Functional Requirements

### NFR-01 — Performance & Throughput
- [ ] API Gateway: handle 500 concurrent HTTP connections without degradation
- [ ] Ticket ingestion: accept up to 1000 tickets/minute (enqueue async, respond in <100ms)
- [ ] Agent resolution: median time-to-resolution < 3 minutes for LOW/MEDIUM, < 10 min for HIGH
- [ ] RAG retrieval (cache miss): < 500ms end-to-end
- [ ] RAG retrieval (cache hit): < 20ms

### NFR-02 — Reliability
- [ ] Daily maintenance job must not be skippable; missed jobs are retried within 1 hour
- [ ] SSH operations are idempotent where possible; retried up to 3 times with exponential backoff
- [ ] Vault service must have 99.9% availability (Postgres with WAL-based backup)

### NFR-03 — Rate Limiting & Cost Control
- [ ] Global Anthropic API token-bucket: configurable TPM (tokens-per-minute) and RPM (requests-per-minute) limits
- [ ] Limits stored and checked in Redis (single source of truth across all agent containers)
- [ ] When limit approached (>80% utilised), agents queue requests rather than fail
- [ ] Alert to ops team when sustained >90% of rate limit for >5 minutes
- [ ] Daily cost ceiling: configurable hard stop (e.g. $50/day); exceed → queue + alert, no new LLM calls until manual reset

### NFR-04 — Security
- [ ] SSH private keys never logged, never in environment variables, never in application stdout
- [ ] All inter-service communication over internal Docker network (no external exposure except API gateway)
- [ ] Secrets injected via Docker secrets or environment (not baked into images)
- [ ] Vault DB column encryption independent of Postgres disk encryption
- [ ] Agent SSH sessions use ephemeral keys where supported (paramiko in-memory)

### NFR-05 — Scalability
- [ ] Each service is stateless (state in Redis/Postgres) and can be scaled horizontally via `docker compose --scale`
- [ ] Agent worker pool scales via semaphore within container; new containers share the same Redis queue
- [ ] No component requires shared disk (no NFS, no volume mounts for state)

### NFR-06 — Observability
- [ ] 100% of LLM calls traced
- [ ] 100% of SSH operations audit-logged
- [ ] P95 latency dashboards per agent type
- [ ] Alert: agent stuck in `executing` state >15 minutes → escalate to ops

### NFR-07 — Privacy
- [ ] Client server file content is never stored in any database, log, or knowledge base
- [ ] Log sanitisation: strip IP addresses from user-facing responses; keep internally
- [ ] RAG KB entries store only: error_pattern (sanitised), fix_steps (sanitised), confidence score

### NFR-08 — Portability
- [ ] Full stack runs via `docker compose up` with zero host dependencies except Docker
- [ ] Container images pinned to specific versions in production
- [ ] Stack can be duplicated per deployment zone by changing `.env` values only

---

## 3. Out of Scope (v1)

- Heavy authentication (OAuth2 flows, MFA, SSO) — lightweight JWT only
- Client document ingestion into RAG — deferred until trust established
- Auto-scaling infrastructure (K8s, ECS) — manual scale via compose `--scale`
- Billing integration
- Multi-tenant isolation beyond API key scoping
