# SentinelMAS

**Autonomous GPU Infrastructure Management — Multi-Agent System**

SentinelMAS is a production-grade, containerised multi-agent system that manages fleets of GPU servers without human intervention. It monitors company infrastructure on a daily schedule, resolves user-submitted support tickets via SSH, generates operational intelligence reports, and keeps a running knowledge base that improves with every fix it applies.

Built on **LangGraph + Anthropic Claude**, deployed as **9 Docker services** with full LLMOps observability, AES-256-GCM credential encryption, hybrid RAG, and a Redis token-bucket rate limiter shared across all agents.

---

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║                                                                                  ║
║    ███████╗███████╗███╗   ██╗████████╗██╗███╗   ██╗███████╗██╗                 ║
║    ██╔════╝██╔════╝████╗  ██║╚══██╔══╝██║████╗  ██║██╔════╝██║                 ║
║    ███████╗█████╗  ██╔██╗ ██║   ██║   ██║██╔██╗ ██║█████╗  ██║                 ║
║    ╚════██║██╔══╝  ██║╚██╗██║   ██║   ██║██║╚██╗██║██╔══╝  ██║                 ║
║    ███████║███████╗██║ ╚████║   ██║   ██║██║ ╚████║███████╗███████╗            ║
║    ╚══════╝╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚═╝╚═╝  ╚═══╝╚══════╝╚══════╝            ║
║                                                                                  ║
║         M U L T I - A G E N T   G P U   I N F R A S T R U C T U R E           ║
║                    Autonomous · Secure · Self-Healing · 24/7/365                ║
╚══════════════════════════════════════════════════════════════════════════════════╝
```

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ◈  SCENE I  ·  14 : 32  UTC  ·  A CUSTOMER IS STUCK, DEADLINE TOMORROW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  💬  user  »  "gpu mem keeps throwing ECC ERR!! i cant do anything on this box"
  💬  user  »  "why is this code not running, it was fine yesterday wtf"
  💬  user  »  "how do i even install the right cuda version, no idea where to start"

                              POST /tickets
                                   │
          ┌────────────────────────▼────────────────────────┐
          │              api-gateway  :8000                  │
          │                                                   │
          │  ✦ sanitise_ticket_input()                        │
          │    └─ HTML stripped · prompt-injection purged     │
          │    └─ PII redacted  · 4 000 char cap enforced     │
          └────────────────────────┬────────────────────────┘
                                   │  RPUSH  →  mas:client_queue
                                   │
          ┌────────────────────────▼────────────────────────┐
          │          agent-orchestrator  :8001               │
          │                                                   │
          │  BLPOP  →  classify  →  Severity : HIGH          │
          │                         Type     : GPU_MEMORY     │
          │  Route  →  client-agent worker pool               │
          └──────┬──────────────────────────┬───────────────┘
                 │                          │
     ┌───────────▼──────────┐   ┌───────────▼───────────────────────┐
     │    rag-service :8005  │   │        ssh-vault :8100             │
     │                       │   │                                    │
     │  Cache miss           │   │  GET /vault/session/srv-gpu-07    │
     │  ├─ Dense  (Qdrant)   │   │  AES-256-GCM decrypt              │
     │  │   "ECC mem remap"  │   │  paramiko session  TTL 300s       │
     │  │   score: 0.93 ✓    │   │                                    │
     │  ├─ Sparse (BM25)     │   │  ⚠  RAW KEY : NEVER LEAVES VAULT  │
     │  │   "nvidia-smi err" │   │      agent sees session token only │
     │  └─ Rerank top-3      │   └─────────────────┬─────────────────┘
     │    ✓ known fix found  │                      │
     └───────────┬───────────┘                      │
                 │  fix recipe                      │  session token
                 └──────────────────┬───────────────┘
                                    │
          ┌─────────────────────────▼───────────────────────┐
          │             client-agent  :8003                  │
          │         LangGraph 5-node StateGraph              │
          │                                                   │
          │  classify → rag_search → execute → verify → close│
          │                                                   │
          │  is_safe_command("nvidia-smi --gpu-reset")  ✓    │
          │  is_safe_command("nvidia-smi -r -i 0")      ✓    │
          │  Executing on srv-gpu-07 via vault session...    │
          │                                                   │
          │  GPU memory reset  ████████████████  OK          │
          │  ECC rows cleared  ████████████████  OK          │
          │  CUDA re-init      ████████████████  OK          │
          │  Verify: nvidia-smi → Temp 94°C  →  57°C  ✓     │
          │  Verify: job re-submitted         → RUNNING ✓    │
          └─────────────────────────┬───────────────────────┘
                                    │
                     ┌──────────────▼─────────────┐
                     │  rag-service  /rag/ingest   │
                     │  Fix confirmed → KB entry   │
                     │  Learns for next ticket ✓   │
                     └────────────────────────────┘

  [ticket#4821]  Status: DONE  ·  Auto-resolved: YES  ·  Duration: 43 s

  💬  user  »  "wait it just fixed itself?? ok that was actually insane"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ◈  SCENE II  ·  00 : 05  UTC  ·  THE NIGHTWATCHER BEGINS ITS ROUNDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

         〔  Everyone is asleep.  SentinelMAS is not.  〕

  [APScheduler]  00:05:00  →  daily_inserver_check  fired
                               24 servers in fleet
                               Dispatching to mas:inserver_queue ...

  ┌───────────────────────────────────────────────────────────────────────┐
  │ server         │ GPU     │ disk     │ mem      │ action taken         │
  ├───────────────────────────────────────────────────────────────────────┤
  │ srv-gpu-01     │  54°C ✓ │  41%  ✓ │  62%  ✓ │ —  all clear         │
  │ srv-gpu-02     │  67°C ✓ │  88%  ⚠ │  59%  ✓ │ log rotation → 61% ✓│
  │ srv-gpu-03     │  59°C ✓ │  44%  ✓ │  93%  ⚠ │ drop_caches  → 70% ✓│
  │ srv-gpu-04     │  —      │  —      │  —      │ SSH timeout × 3      │
  │                │         │         │         │ → snapshot: UNREACHABLE
  │                │         │         │         │ → on-call paged  🔔   │
  │ srv-gpu-05     │  61°C ✓ │  46%  ✓ │  68%  ✓ │ fail2ban: 847 IPs   │
  │                │         │         │         │   blocked → reload ✓ │
  │ srv-gpu-09     │  72°C ✓ │  39%  ✓ │  74%  ✓ │ clock drift reset ✓ │
  │ srv-gpu-14     │  55°C ✓ │  91%  ⚠ │  60%  ✓ │ core dump purge      │
  │                │         │         │         │   → 55% ✓            │
  │ srv-gpu-18     │  63°C ✓ │  48%  ✓ │  66%  ✓ │ SSH blacklisted →   │
  │                │         │         │         │   unban + key rotate ✓
  │ srv-gpu-21     │  58°C ✓ │  52%  ✓ │  96%  ⚠ │ OOM near-miss →     │
  │                │         │         │         │   priority rebalance ✓
  │ srv-gpu-22..24 │   ✓     │   ✓     │   ✓     │ —  all clear         │
  └───────────────────────────────────────────────────────────────────────┘

  [inserver-agent]  00:23:14  ·  Probed: 24  ·  Fixed: 7  ·  Unreachable: 1
                               ·  Snapshots saved to daily_health_snapshots
                               ·  Human pages sent: 1  (srv-gpu-04 only)

         〔  7 servers self-healed overnight.  Zero human effort.  〕

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ◈  SCENE III  ·  08 : 01  UTC  ·  MANAGER ARRIVES WITH COFFEE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  💬  manager  »  "had a good sleep, did anything happen last night?"

  ┌──────────────────────────────────────────────────────────────────────────┐
  │  DAILY OPERATIONS SUMMARY  ·  2026-03-21  ·  Auto-generated  00:24 UTC  │
  ├──────────────────────────────────────────────────────────────────────────┤
  │  Fleet Health                                                            │
  │  ● 24 servers probed   ● 23 healthy   ● 1 unreachable  (srv-gpu-04)     │
  │                                                                          │
  │  Auto-Remediation   (while you slept)                                   │
  │  ✓  srv-gpu-02  Disk  88% → 61%    log rotation                        │
  │  ✓  srv-gpu-03  Mem   93% → 70%    kernel cache flush                  │
  │  ✓  srv-gpu-05  847 IPs blocked    fail2ban reload                      │
  │  ✓  srv-gpu-09  Clock drift        nvidia-smi reset                     │
  │  ✓  srv-gpu-14  Disk  91% → 55%    core dump cleanup                   │
  │  ✓  srv-gpu-18  SSH blacklisted    unban + root key rotated             │
  │  ✓  srv-gpu-21  OOM near-miss      process priority rebalanced          │
  │                                                                          │
  │  Customer Tickets  (last 24 h)                                          │
  │  Received: 11   Auto-resolved: 10   Escalated: 1   Open: 0             │
  │  Avg resolution time: 58 s                                              │
  │                                                                          │
  │  ⚠  ACTION NEEDED: srv-gpu-04 unreachable — please verify power / BMC  │
  └──────────────────────────────────────────────────────────────────────────┘

  💬  manager  »  "only 1 thing to check, everything else just handled itself"
  💬  manager  »  "ok this is genuinely what i bought this system for"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ◈  SCENE IV  ·  REAL-TIME  ·  OPS TEAM WATCHES THE SYSTEM RUN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌──────────────────────────────────────────────────────────────────────────┐
  │  LIVE OPS DASHBOARD  ·  GET /ops/dashboard                              │
  ├──────────────────────────────────────────────────────────────────────────┤
  │                                                                          │
  │  AGENTS                              QUEUES                             │
  │  ● client-agent-1    executing       client_queue    ▓▓░░░░  2 pending  │
  │  ● client-agent-2    executing       inserver_queue  ░░░░░░  0 pending  │
  │  ○ client-agent-3    idle            report_queue    ░░░░░░  0 pending  │
  │  ○ inserver-agent    idle                                                │
  │                                                                          │
  │  COST GUARD  (today)                           [shared/rate_limiter.py] │
  │  RPM   ████████████░░░░░░░░  43 / 60    (72%)                          │
  │  TPM   ███████░░░░░░░░░░░░░  73k / 100k (73%)                          │
  │  USD   ████░░░░░░░░░░░░░░░░  $19.20 / $50.00        ← well within cap  │
  │                                                                          │
  │  LANGFUSE TRACES          STRUCTLOG  (Loki)                             │
  │  ticket#4821  43s  ✓      {"event":"rag_search","cache":false,         │
  │  ticket#4822  31s  ●       "dense_score":0.93,"bm25_hits":4}           │
  │  ticket#4823   8s  ●      {"event":"ssh_execute","exit_code":0,        │
  │  maint#0318   18m  ✓       "command_hash":"sha256:a3f…","safe":true}   │
  │                                                                          │
  │  Grafana :3001  ·  Agent Overview  /  Token Spend  /  Server Fleet     │
  └──────────────────────────────────────────────────────────────────────────┘

  💬  ops-eng  »  "all agents green, cost under half limit, nothing to do here"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ◈  THE FIVE SAFETY LAYERS  ·  No command reaches a server unchecked.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Internet  (ticket text / admin call)
      │
      │   ╔══ LAYER 1 — Network perimeter ══════════════════════════════════╗
      │   ║  nginx  +  slowapi                                              ║
      │   ║  DDoS rate-limit · /internal/* unreachable from public net     ║
      │   ║  Request-ID injected on every hop for full trace correlation   ║
      │   ╚═════════════════════════════════════════════════════════════════╝
      │
      │   ╔══ LAYER 2 — Input sanitisation ═════════════════════════════════╗
      │   ║  api-gateway  sanitiser.py                                      ║
      │   ║  HTML tags stripped · <|...|> prompt-injection markers purged  ║
      │   ║  ###System: / [INST] injections neutralised · 4 000 char cap   ║
      │   ╚═════════════════════════════════════════════════════════════════╝
      │
      │   ╔══ LAYER 3 — Zero-trust credential vault ════════════════════════╗
      │   ║  ssh-vault  vault.py  +  session_manager.py                     ║
      │   ║  SSH keys encrypted at rest with AES-256-GCM                   ║
      │   ║  Agents receive short-lived session tokens (TTL 300s) only     ║
      │   ║  Every session: agent_id · server_id · command_hash logged     ║
      │   ╚═════════════════════════════════════════════════════════════════╝
      │
      │   ╔══ LAYER 4 — Command safety filter ══════════════════════════════╗
      │   ║  ssh-vault  safety_filter.py  (24 test cases)                   ║
      │   ║  BLOCKED:  rm -rf  ·  mkfs  ·  dd  ·  iptables --flush        ║
      │   ║  BLOCKED:  wget|bash  ·  curl|sh  ·  fork-bomb  ·  /etc/shadow║
      │   ║  BLOCKED:  reboot (unapproved)  ·  >  /dev/sda  ·  poweroff   ║
      │   ╚═════════════════════════════════════════════════════════════════╝
      │
      │   ╔══ LAYER 5 — LLM cost circuit-breaker ══════════════════════════╗
      │   ║  shared  rate_limiter.py  (atomic Redis Lua token-bucket)      ║
      │   ║  3-gate check:  RPM  ≤ limit  ·  TPM  ≤ limit  ·  USD ≤ cap  ║
      │   ║  Returns False → agent queues retry, ticket never dropped      ║
      │   ╚═════════════════════════════════════════════════════════════════╝
      │
   GPU Server  ← command arrives only after all five gates pass

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Tickets auto-resolved while engineers focus on what actually matters.
  Servers self-healed while managers sleep.
  Every LLM call traced. Every SSH command logged. Every dollar counted.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [System Architecture](#system-architecture)
3. [The Two Operational Planes](#the-two-operational-planes)
4. [Agent Design — LangGraph Supervisor Pattern](#agent-design--langgraph-supervisor-pattern)
5. [SSH Vault — Zero-Trust Credential Model](#ssh-vault--zero-trust-credential-model)
6. [RAG Knowledge Pipeline](#rag-knowledge-pipeline)
7. [LLMOps — Full Observability Stack](#llmops--full-observability-stack)
8. [Security Architecture](#security-architecture)
9. [Resilience & Stress Handling](#resilience--stress-handling)
10. [Tech Stack](#tech-stack)
11. [Getting Started](#getting-started)
12. [Where to Find What](#where-to-find-what)
13. [API Reference](#api-reference)

---

## What It Does

A GPU rental company operates two classes of servers:

| Class | Owner | Problem |
|---|---|---|
| **Company servers** | GPU rental company | Need daily health checks: disk, GPU temp, memory, SSH blacklist recovery |
| **Client servers** | Paying customers | Users submit tickets when their rented GPU server has issues |

SentinelMAS handles both autonomously:

- **00:05 UTC daily** — SSH into every company server, run diagnostics, apply fixes, emit health snapshots
- **Ticket arrives** — Classify severity, search the knowledge base for known fixes, attempt SSH remediation, escalate only if all automated paths fail
- **Monday 06:00 UTC** — Generate a weekly operations report and deliver it via webhook or email
- **Every fix that works** — Gets written back to the knowledge base for future tickets

No on-call engineer needed for the majority of routine infrastructure events.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PUBLIC NETWORK                                      │
│                                                                              │
│   ┌────────────────────────────────────────────────────────────────────┐   │
│   │  nginx :80  (rate limiting, request ID injection, /internal block) │   │
│   └───────────────────────────┬────────────────────────────────────────┘   │
└───────────────────────────────│─────────────────────────────────────────────┘
                                │
┌───────────────────────────────│─────────────────────────────────────────────┐
│                       INTERNAL NETWORK                                       │
│                                                                              │
│   ┌───────────────────────┐   │                                             │
│   │   api-gateway :8000   │◄──┘   JWT auth · slowapi · sanitiser           │
│   │  FastAPI + Gunicorn   │       Ticket CRUD · Admin · Ops UI             │
│   └──────────┬────────────┘                                                 │
│              │ RPUSH                                                         │
│   ┌──────────▼────────────────────────────────────┐                        │
│   │              Redis  :6379                      │                        │
│   │  mas:client_queue   mas:inserver_queue         │  Token-bucket          │
│   │  mas:report_queue   mas:orchestrator_queue     │  rate limiter          │
│   └──────────┬────────────────────────────────────┘                        │
│              │ BLPOP                                                         │
│   ┌──────────▼────────────────────────────────────┐                        │
│   │         agent-orchestrator :8001              │                        │
│   │  LangGraph Supervisor · Worker pool           │  APScheduler           │
│   │  Consumer loop · Task watchdog (900s)         │  cron jobs             │
│   └──┬──────────┬────────────────┬───────────────┘                        │
│      │          │                │                                           │
│  ┌───▼──┐  ┌────▼─────┐  ┌──────▼──────┐                                  │
│  │client│  │inserver  │  │   report    │   All agents:                    │
│  │agent │  │agent     │  │   agent     │   · LangGraph StateGraph         │
│  │:8003 │  │:8002     │  │   :8004     │   · Claude claude-sonnet-4-*     │
│  └──┬───┘  └──┬───────┘  └──────┬──────┘   · Structured JSON logging     │
│     │         │                  │           · Langfuse trace per task     │
│     │    ┌────▼──────────────────▼────┐                                   │
│     │    │      ssh-vault :8100       │  AES-256-GCM encrypted keys       │
│     │    │  paramiko sessions (TTL    │  Agents never see raw keys         │
│     │    │  300s) · Safety filter     │  is_safe_command() pre-exec        │
│     │    └───────────────────────────┘                                    │
│     │                                                                       │
│     └──► rag-service :8005                                                 │
│          Qdrant + BM25 + CrossEncoder + Redis semantic cache               │
│                                                                              │
│   ┌──────────────────────────────────────────────────────────────┐        │
│   │  Postgres :5432  (via PgBouncer :5432)                       │        │
│   │  tickets · server_credentials · daily_health_snapshots       │        │
│   │  rag_kb_entries · credential_access_log · apscheduler_jobs   │        │
│   └──────────────────────────────────────────────────────────────┘        │
│                                                                              │
│   ┌─ Observability ──────────────────────────────────────────────┐        │
│   │  Prometheus :9090  ·  Grafana :3001  ·  Loki  ·  Promtail   │        │
│   │  Langfuse :3000 (self-hosted LLMOps)                         │        │
│   └──────────────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## The Two Operational Planes

### InServer Plane — Company Infrastructure

Triggered by APScheduler at **00:05 UTC daily** (and on-demand via `POST /admin/servers/{id}/check`).

```
Scheduler ──► orchestrator_queue ──► inserver-agent
                                           │
                              LangGraph 4-node graph:
                              classify → probe → fix → report
                                           │
                                    ssh-vault session
                                           │
                              ┌────────────▼───────────────┐
                              │   Company GPU Server       │
                              │  nvidia-smi, df, free,     │
                              │  journalctl, fail2ban       │
                              └────────────────────────────┘
                                           │
                              daily_health_snapshots table
                              (GPU temp · disk · mem · uptime)
```

**Tools available to inserver-agent:**
`ssh_execute` · `hard_restart` (BMC/IPMI stub → SSH reboot fallback) · `log_action` · `get_server_info`

> **Deep dive →** [`services/inserver-agent/README.md`](services/inserver-agent/README.md) — graph nodes, tool signatures, health snapshot schema, failure modes.

### Client Plane — Ticket Resolution

```
User POST /tickets ──► client_queue ──► client-agent
                                              │
                                   LangGraph 5-node graph:
                                   classify → rag_search → execute → verify → close
                                              │
                              ┌───────────────┴──────────────────┐
                              │                                   │
                         rag-service                        ssh-vault
                         (known fix?)              (execute fix on client server)
                              │                                   │
                         hit: apply fix                    safety_filter
                         miss: web search                  (11 forbidden patterns)
                         (Tavily API)                            │
                              │                                   │
                              └───────────────┬──────────────────┘
                                              │
                                   Fix confirmed → write to KB
                                   All retries failed → ESCALATED
```

**Severity routing:** `CRITICAL` tickets skip RAG and go direct to SSH. `LOW` tickets try RAG-only first.

> **Deep dive →** [`services/client-agent/README.md`](services/client-agent/README.md) — 5-node graph, tool list, severity routing table, RAG integration, escalation logic.

### Report Agent — Operational Intelligence

Every **Monday at 06:00 UTC** (and on-demand) the report agent aggregates the week's health snapshots and ticket outcomes into a structured report delivered via webhook or email.

> **Deep dive →** [`services/report-agent/README.md`](services/report-agent/README.md) — formatter, sender, Jinja2 templates, delivery channels.

---

## Agent Design — LangGraph Supervisor Pattern

Every specialist agent is a compiled `StateGraph` with typed state (`TypedDict`), deterministic edges, and a tool-calling loop backed by Claude.

```python
# All agents follow this pattern
graph = StateGraph(AgentState)
graph.add_node("classify",  classify_node)   # determine intent + severity
graph.add_node("execute",   tool_loop_node)  # Claude + tools loop
graph.add_node("finalise",  finalise_node)   # write result, update ticket
graph.set_entry_point("classify")
graph.add_conditional_edges("execute", should_continue)  # loop or exit
compiled = graph.compile()
```

The **Supervisor** in `agent-orchestrator/supervisor.py` routes tasks from Redis to the correct agent based on `task_type`:

| `task_type` | Agent | Queue |
|---|---|---|
| `ticket` | `client-agent` | `mas:client_queue` |
| `maintenance` | `inserver-agent` | `mas:inserver_queue` |
| `report` | `report-agent` | `mas:report_queue` |

**Worker pool** (`worker_pool.py`) enforces `MAX_CONCURRENT_AGENTS` (default 10) and runs a watchdog that logs `STUCK TASK` for any task exceeding 900 seconds.

> **Deep dive →** [`services/agent-orchestrator/README.md`](services/agent-orchestrator/README.md) — supervisor routing logic, worker pool internals, APScheduler cron jobs, Redis consumer pattern.

---

## SSH Vault — Zero-Trust Credential Model

The most security-sensitive component. **Agents never receive raw SSH private keys.**

```
Agent calls:  GET /vault/session/{server_id}
                          │
                    ssh-vault verifies X-Internal-Key
                          │
                    Decrypts key from Postgres
                    (AES-256-GCM, VAULT_MASTER_KEY)
                          │
                    Opens paramiko SSH connection
                          │
                    Returns: session_token (UUID, TTL 300s)
                          │
Agent calls:  POST /vault/execute
              { session_token, command }
                          │
                    is_safe_command(command)
                    ── 11 forbidden pattern classes ──
                    rm -rf · mkfs · dd · iptables flush
                    wget/curl pipe to shell · fork bomb
                    /etc/shadow · reboot (unless approved)
                    ...
                          │
                    Execute via paramiko
                    Log to credential_access_log (audit trail)
                          │
                    Return stdout/stderr
```

Every SSH command is logged with `agent_id`, `trace_id`, `server_id`, `command_hash`, `success` before execution. The vault container runs as `appuser` uid 1000 with no host volume mounts.

**Key files:**
- [`services/ssh-vault/vault.py`](services/ssh-vault/vault.py) — encryption/decryption, credential CRUD
- [`services/ssh-vault/safety_filter.py`](services/ssh-vault/safety_filter.py) — `is_safe_command()` with 24 test cases
- [`services/ssh-vault/session_manager.py`](services/ssh-vault/session_manager.py) — paramiko lifecycle, TTL management

> **Deep dive →** [`services/ssh-vault/README.md`](services/ssh-vault/README.md) — AES-256-GCM encryption design, all 11 forbidden command patterns, session token lifecycle, audit log schema.

---

## RAG Knowledge Pipeline

SentinelMAS gets smarter with every resolved ticket. Confirmed fix pairs (error pattern → fix steps) are ingested into a hybrid retrieval system.

```
Query: "nvidia-smi shows GPU memory leak on A100"
              │
              ▼
    ┌─────────────────────────────────────────┐
    │          Semantic Cache (Redis)          │
    │  cosine similarity ≥ 0.92 → cache hit  │
    │  TTL: active errors 1h / static 24h    │
    └──────────────────┬──────────────────────┘
                       │ cache miss
              ┌────────▼────────┐
              │                 │
    ┌─────────▼──────┐  ┌───────▼──────────┐
    │  Dense Search  │  │  Sparse Search   │
    │  Qdrant        │  │  BM25 (rank-bm25)│
    │  text-embed-   │  │  TF-IDF keyword  │
    │  3-small 1536d │  │  exact matching  │
    └─────────┬──────┘  └───────┬──────────┘
              └────────┬────────┘
                       │ Reciprocal Rank Fusion
                       │ score(d) = Σ 1/(60 + rank)
              ┌────────▼────────────────────────┐
              │  Cross-Encoder Reranker          │
              │  ms-marco-MiniLM-L-6-v2          │
              │  scores all candidate pairs      │
              └────────┬────────────────────────┘
                       │ top-k results
              ┌────────▼────────────────────────┐
              │  Agent receives ranked fixes     │
              │  with confidence scores          │
              └─────────────────────────────────┘
```

**Why hybrid?** Dense search finds semantically similar errors (different wording, same root cause). BM25 finds exact error codes and command names. The cross-encoder reranker applies expensive pairwise scoring only to the top candidates — not the full corpus. The semantic cache prevents redundant embeddings for repeated patterns.

**Key files:**
- [`services/rag-service/hybrid_search.py`](services/rag-service/hybrid_search.py) — RRF merge logic
- [`services/rag-service/reranker.py`](services/rag-service/reranker.py) — cross-encoder with lru_cache(1)
- [`services/rag-service/semantic_cache.py`](services/rag-service/semantic_cache.py) — cosine similarity cache layer
- [`services/rag-service/embedder.py`](services/rag-service/embedder.py) — OpenAI async embedding client

> **Deep dive →** [`services/rag-service/README.md`](services/rag-service/README.md) — full pipeline config, BM25 index design, RRF formula, cache TTL strategy, ingest/search API contract.

---

## LLMOps — Full Observability Stack

Every LLM call is traceable end-to-end from ticket intake to resolution.

### Langfuse — Distributed Tracing

```
Ticket created  →  trace_id generated (UUID)
      │
      ├── span: classify_ticket       (model, tokens, latency)
      ├── span: rag_search            (query, results count)
      ├── span: ssh_execute_attempt1  (command hash, result)
      ├── span: ssh_execute_attempt2
      └── span: write_to_kb          (new entry ID)

All spans share the same trace_id — full causal chain visible in Langfuse UI.
```

`langfuse_tracer.py` wraps every `create_trace()` call. If `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` are not set, a `_NoOpTrace` stub is returned — **the system degrades gracefully and never crashes due to missing tracing config**.

Langfuse is self-hosted at `http://localhost:3000`. Create an account on first visit.

### Prometheus + Grafana — Real-Time Metrics

Three pre-built dashboards provisioned automatically at startup:

| Dashboard | What it shows |
|---|---|
| **Agent Overview** | Queue depths · active tasks · HTTP request rate · p95 latency · error rate |
| **Token Spend** | Daily USD cost · RPM/TPM utilisation burn rate · cost ceiling proximity |
| **Server Fleet** | Per-server GPU temperature · disk % · memory % · uptime trend |

Access Grafana at `http://localhost:3001` (admin / see `.env` `GRAFANA_PASSWORD`).

Every FastAPI service exposes `/metrics` in Prometheus format via `prometheus-fastapi-instrumentator`. Promtail ships all structured JSON logs to Loki; Grafana queries both.

> **Deep dive →** [`services/agent-orchestrator/README.md`](services/agent-orchestrator/README.md) — Langfuse tracer implementation, `_NoOpTrace` graceful degradation, span naming conventions.

### Structured Logging — `structlog` → Loki

All services emit JSON logs with `trace_id`, `agent_id`, `task_id`, `ticket_id` injected via contextvars. No string formatting — every log line is a structured event queryable in Grafana Explore.

```json
{"timestamp": "2026-03-20T12:34:56Z", "level": "info", "event": "ssh_execute",
 "trace_id": "abc-123", "agent_id": "client-agent-1",
 "server_id": "srv-gpu-07", "command_hash": "sha256:...", "exit_code": 0}
```

> **Deep dive →** [`services/shared/README.md`](services/shared/README.md) — logger contextvars design, rate_limiter Lua script, DB session factory, Redis client singleton.

---

## Security Architecture

### Threat Model & Mitigations

| Threat | Mitigation | Where |
|---|---|---|
| SSH key exfiltration | AES-256-GCM at rest; agents receive session tokens only | `ssh-vault/vault.py` |
| Prompt injection via ticket text | `sanitise_ticket_input()` strips HTML + `<\|...\|>` + `###System:` markers | `api-gateway/sanitiser.py` |
| Destructive command execution | `is_safe_command()` — 11 forbidden pattern classes, case-insensitive, DOTALL | `ssh-vault/safety_filter.py` |
| Container escape → host pivot | Non-root `appuser` uid 1000; no `--privileged`; no host volume mounts on vault | All Dockerfiles |
| Redis cache poisoning | Internal Docker network only; `requirepass` enforced; no public port in prod | `docker-compose.yml` |
| Log data leaking server info | `sanitise_log()` strips IPv4, credentials, PEM keys, home paths | `api-gateway/sanitiser.py` |
| LLM cost runaway | Daily USD ceiling in Redis; `acquire()` returns `False` when hit; circuit-break immediate | `shared/rate_limiter.py` |
| API key leakage | Docker secrets in prod; `.gitignore` covers `secrets/*.txt` | `docker-compose.prod.yml` |

Full threat model and audit checklist: [`docs/SECURITY_REVIEW.md`](docs/SECURITY_REVIEW.md)

### Network Isolation

```
PUBLIC network:   nginx (only service with public port)
INTERNAL network: everything else — cannot receive connections from outside Docker
                  (internal: true in docker-compose.yml)

Prod overlay (docker-compose.prod.yml):
  - All internal services: ports: []  (no host binding at all)
  - Grafana: 127.0.0.1:3001:3000      (loopback only)
  - Swagger (/docs): disabled         (docs_url=None when ENV=production)
```

### Authentication Layers

| Layer | Mechanism | Scope |
|---|---|---|
| User → API | JWT HS256, 24h expiry | All `/tickets`, `/reports` endpoints |
| Service → Service | `X-Internal-Key` header (constant-time compare) | `/internal/*` endpoints |
| User → Admin | Same JWT + admin role check | `/admin/*` endpoints |
| Vault → Postgres | Direct asyncpg connection (no pgbouncer) | Credential read/write |

> **Deep dive →** [`services/api-gateway/README.md`](services/api-gateway/README.md) — all routes, JWT auth flow, slowapi rate limiting, prompt injection sanitiser, request middleware.

---

## Resilience & Stress Handling

### Token Bucket Rate Limiter (Redis Lua script)

All LLM calls go through a single shared rate limiter in `shared/rate_limiter.py`. Implemented as an atomic Lua script — no race conditions across replicas.

```
acquire(model, prompt_tokens) checks three gates atomically:
  1. RPM  ≤ ANTHROPIC_RPM_LIMIT  (default 60/min)
  2. TPM  ≤ ANTHROPIC_TPM_LIMIT  (default 100k/min)
  3. Daily cost ≤ DAILY_COST_LIMIT_USD (default $50)

Returns: True (proceed) | False (circuit-break this call)
```

Agents that receive `False` do NOT drop the ticket — they queue the task and retry after the window resets. The Redis key TTLs naturally reset the buckets.

### Horizontal Scaling

```bash
# High ticket volume
docker compose up --scale client-agent=6 -d

# Large server fleet
docker compose up --scale inserver-agent=4 -d

# High RAG search latency
docker compose up --scale rag-service=3 -d
```

The consumer loop in the orchestrator uses `BLPOP` with a shared queue — multiple agent replicas consume from the same queue without coordination overhead. No leader election needed.

**Rule of thumb:** 1 client-agent handles ~5 concurrent tickets. 1 inserver-agent handles ~3 servers concurrently.

### Stuck Task Watchdog

`worker_pool.py` logs `STUCK TASK` at WARNING level every 60 seconds for any task running longer than 900 seconds. The runbook describes manual cancellation: [`docs/RUNBOOK.md §4`](docs/RUNBOOK.md).

### Graceful Degradation

| Component fails | Behaviour |
|---|---|
| Langfuse unavailable | `_NoOpTrace` stub — zero impact on agent execution |
| RAG service unavailable | Client agent falls back to Tavily web search |
| Tavily unavailable | Agent attempts direct SSH with general diagnostic commands |
| SSH vault credential decrypt fails | Ticket immediately escalated (no silent failure) |
| Daily cost limit hit | All new LLM calls circuit-break; existing tasks complete; ops dashboard shows alert |

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **Agent framework** | LangGraph `StateGraph` | Deterministic execution graph; typed state; easy to test nodes in isolation |
| **LLM** | Anthropic Claude (`claude-sonnet-4-20250514`) | Function calling reliability; long context for SSH output parsing |
| **API** | FastAPI + Gunicorn/Uvicorn | Async; automatic OpenAPI; pydantic validation at boundary |
| **Queue** | Redis `BLPOP` | Zero-dependency async task dispatch; sub-millisecond push |
| **Database** | PostgreSQL 16 + Alembic + PgBouncer | ACID guarantees for credential and ticket state; connection pooling |
| **Vector store** | Qdrant v1.9 | Cosine similarity on 1536-dim embeddings; persistent storage |
| **Embeddings** | OpenAI `text-embedding-3-small` | Best cost/quality ratio for semantic similarity |
| **Reranker** | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Pairwise relevance scoring; pre-downloaded into image |
| **SSH** | `paramiko` (inside vault container) | Pure-Python; session lifecycle management; no agent forwarding |
| **Encryption** | `cryptography` AES-256-GCM | Authenticated encryption; detects tampering on decrypt |
| **Auth** | `python-jose` JWT + `bcrypt` | Industry standard; bcrypt for admin credential storage |
| **Rate limiting** | Redis Lua token-bucket + `slowapi` | Atomic across replicas; no distributed lock needed |
| **Web search** | Tavily API (SerpAPI fallback) | Structured search results; no HTML parsing |
| **LLMOps** | Langfuse OSS (self-hosted) | Full prompt/response/token trace; no data leaves your infra |
| **Metrics** | Prometheus + Grafana + `prometheus-fastapi-instrumentator` | Auto-instrumented HTTP metrics; 3 pre-built dashboards |
| **Logs** | `structlog` → Promtail → Loki | JSON structured logs; queryable in Grafana Explore |
| **Scheduler** | APScheduler `AsyncIOScheduler` | Embedded in orchestrator; cron triggers; no separate service |
| **Container** | Docker Compose + prod overlay | Dev/prod parity; Docker secrets for credentials in prod |

---

## Getting Started

Full step-by-step setup: **[`docs/ONBOARDING.md`](docs/ONBOARDING.md)**

```bash
# 1. Clone
git clone https://github.com/MT121201/SentinelMAS.git && cd SentinelMAS

# 2. Configure
cp .env.example .env
make generate-vault-key   # → VAULT_MASTER_KEY=...
make rotate-jwt-secret    # → JWT_SECRET_KEY=...
# Fill in: ANTHROPIC_API_KEY, OPENAI_API_KEY, passwords

# 3. Start
docker compose up --build -d

# 4. Migrate
make migrate

# 5. Verify
curl http://localhost:80/health   # {"status":"ok"}

# 6. Get a token
TOKEN=$(curl -s -X POST http://localhost:80/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"YOUR_ADMIN_PASS"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 7. Submit a ticket
curl -X POST http://localhost:80/tickets \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"server_id":"srv-gpu-01","description":"GPU temp high","user_id":"ops"}'
```

**Admin credentials** are set via `ADMIN_PASSWORD_HASH` in `.env` (bcrypt hash). Generate:
```bash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())"
```

### Dashboards

| Dashboard | URL | Credentials |
|---|---|---|
| Grafana metrics | `http://localhost:3001` | admin / `$GRAFANA_PASSWORD` |
| Langfuse traces | `http://localhost:3000` | Create account on first visit |
| Ops live view | `http://localhost:80/ops/ui/ops.html` | None |
| Prometheus raw | `http://localhost:9090` | None (internal only) |

---

## Where to Find What

| Topic | File |
|---|---|
| **Build plan / task checklist** | [`systemdev_docs/TODO.md`](systemdev_docs/TODO.md) |
| **Full system design** | [`systemdev_docs/SYSTEM_DESIGN.md`](systemdev_docs/SYSTEM_DESIGN.md) |
| **Agent roles + prompts** | [`systemdev_docs/AGENT_DESIGN.md`](systemdev_docs/AGENT_DESIGN.md) |
| **All API routes + Pydantic models** | [`systemdev_docs/API_DESIGN.md`](systemdev_docs/API_DESIGN.md) |
| **SSH vault + safety filter design** | [`systemdev_docs/SECURITY.md`](systemdev_docs/SECURITY.md) |
| **Docker topology + resource limits** | [`systemdev_docs/INFRA.md`](systemdev_docs/INFRA.md) |
| **Security audit checklist** | [`docs/SECURITY_REVIEW.md`](docs/SECURITY_REVIEW.md) |
| **On-call runbook** | [`docs/RUNBOOK.md`](docs/RUNBOOK.md) |
| **First-time setup guide** | [`docs/ONBOARDING.md`](docs/ONBOARDING.md) |
| **LangGraph agent graphs** | `services/{client,inserver,report}-agent/graph.py` |
| **SSH safety filter (24 test cases)** | [`services/ssh-vault/safety_filter.py`](services/ssh-vault/safety_filter.py) |
| **Rate limiter (Lua token bucket)** | [`services/shared/rate_limiter.py`](services/shared/rate_limiter.py) |
| **Hybrid RAG search** | [`services/rag-service/hybrid_search.py`](services/rag-service/hybrid_search.py) |
| **Semantic cache** | [`services/rag-service/semantic_cache.py`](services/rag-service/semantic_cache.py) |
| **Langfuse tracer** | [`services/agent-orchestrator/langfuse_tracer.py`](services/agent-orchestrator/langfuse_tracer.py) |
| **Structured logger** | [`services/shared/logger.py`](services/shared/logger.py) |
| **Database schema migrations** | [`alembic/versions/`](alembic/versions/) |
| **Integration tests** | [`tests/integration/`](tests/integration/) |
| **Load test (Locust)** | [`tests/load/locustfile.py`](tests/load/locustfile.py) |
| **Production compose overlay** | [`docker-compose.prod.yml`](docker-compose.prod.yml) |

---

## API Reference

### Authentication

```http
POST /auth/token
Content-Type: application/json

{"username": "admin", "password": "..."}

→ {"access_token": "eyJ...", "token_type": "bearer"}
```

Rate limited: **5 requests/minute**.

### Tickets

```http
POST   /tickets                     # Submit a new ticket (returns 202)
GET    /tickets/{id}                # Poll status
GET    /tickets/{id}/log            # Sanitised execution log

Ticket status flow:
queued → assigned → executing → done
                              ↘ escalated  (all automated paths failed)
                              ↘ failed     (vault unreachable, SSH error)
```

### Admin

```http
GET    /admin/servers               # List fleet + latest health
POST   /admin/servers               # Register new server (forwards to vault)
POST   /admin/servers/{id}/check    # Trigger immediate health check
DELETE /admin/servers/{id}          # Remove server + credentials
```

### Ops

```http
GET    /ops/dashboard               # Live: agents + queues + tickets + cost
GET    /ops/agents                  # Active task list from worker pool
GET    /ops/cost                    # Rate limit utilisation
POST   /ops/cost/reset              # Reset daily cost counter (emergency)
GET    /ops/servers                 # Fleet with latest snapshots
```

---

## Running Tests

```bash
# Unit + integration (no running stack needed)
pip install -r tests/requirements-test.txt
pytest -q

# Single service
make test-service SERVICE=client-agent

# Smoke tests (stack must be running)
pytest tests/smoke/ -v

# Load test — 50 users, 60s
locust -f tests/load/locustfile.py \
  --host=http://localhost \
  --users=50 --spawn-rate=10 --run-time=60s --headless
```

Test suite coverage: safety filter (24 cases), rate limiter (7 cases), vault security (8 cases), ticket E2E (3 cases), maintenance E2E (3 cases), formatter (22 cases), sender (11 cases).

---

## Production Deployment

```bash
mkdir -p secrets && chmod 700 secrets
printf '%s' "$VAULT_MASTER_KEY" > secrets/vault_master_key.txt
# ... (see docs/ONBOARDING.md §10 for all secret files)
chmod 600 secrets/*.txt

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

The prod overlay disables all internal ports, enables Docker secrets, disables Swagger on all services, and binds Grafana to loopback only. See [`docker-compose.prod.yml`](docker-compose.prod.yml).

---

*Built with LangGraph · Anthropic Claude · FastAPI · Redis · PostgreSQL · Qdrant · Langfuse*
