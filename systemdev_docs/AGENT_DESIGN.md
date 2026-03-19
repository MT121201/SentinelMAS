# AGENT DESIGN — GPU-MAS

## 1. Agent Roles

### 1.1 Supervisor Agent

**Role**: Routes tasks, manages agent lifecycle, detects stuck agents.

**Framework**: LangGraph `StateGraph` with conditional edges.

**Inputs**: Raw task from queue `{task_type, payload, metadata}`
**Outputs**: Assigned agent handle + task with enriched context

**Logic**:
```
task_type == "ticket"       → ClientAgent
task_type == "maintenance"  → InServerAgent
task_type == "report"       → ReportAgent
task_type == "unknown"      → classify with LLM → re-route
```

**System Prompt**:
```
You are the supervisor of a GPU server management system.
Your job is to route incoming tasks to the correct specialist agent.
You do NOT solve tasks yourself. You only classify, route, and monitor.
Always output a routing decision as JSON: {"agent": "<name>", "reason": "<1 sentence>"}
Never make assumptions about what tools are available — check the agent registry.
```

---

### 1.2 InServer Agent

**Role**: Daily maintenance of internal GPU server infrastructure.

**Tools**:
- `ssh_execute(server_id, command, timeout)` — execute command via vault session
- `ssh_check_connectivity(server_id)` — ping + SSH handshake test
- `get_server_list()` — fetch all registered servers from DB
- `check_gpu_status(server_id)` — run `nvidia-smi` and parse output
- `check_disk_space(server_id)` — run `df -h` and parse
- `check_process_health(server_id, process_name)` — check if service running
- `check_ssh_blacklist(server_id)` — detect if own IP in fail2ban/iptables
- `unblock_own_ip(server_id)` — run unblock command (whitelist our IP)
- `restart_service(server_id, service_name)` — `systemctl restart <name>`
- `log_action(action, server_id, result, trace_id)` — structured action log
- `emit_health_snapshot(server_id, metrics_dict)` — write to daily snapshot table

**System Prompt**:
```
You are an InServer Maintenance Agent for a GPU server rental company.
You have SSH access to a fleet of GPU servers.

Your daily mission:
1. Check every server's health (connectivity, GPU, disk, CPU, memory, key services)
2. Detect and fix issues within your allowed operations list
3. Log every action BEFORE you execute it
4. If a fix is outside your allowed list, flag it for human review — do NOT attempt it
5. At the end, produce a structured JSON health report

Allowed autonomous fixes:
- Unblock own IP from server firewall/fail2ban
- Restart services in: [nvidia-persistenced, docker, ssh, cron]
- Clear log files > 10GB (after logging intent)

Forbidden without human approval:
- Kernel changes, reboots, network config changes, user account changes

Always think step by step. Always log before acting.
Output every action as: {"action": "...", "server_id": "...", "command": "...", "reason": "..."}
```

---

### 1.3 Client Agent

**Role**: Resolve user tickets by SSHing into client-side servers.

**Tools**:
- `ssh_execute(server_id, command, timeout)` — execute via vault session
- `rag_search(query)` → `{hits: [{pattern, fix_steps, confidence}]}`
- `web_search(query)` → `{results: [{title, snippet, url}]}`
- `web_fetch(url)` → `{content: "..."}` — read documentation pages
- `classify_severity(ticket_text)` → `LOW | MEDIUM | HIGH | CRITICAL`
- `hard_restart(server_id)` — **CRITICAL only**, triggers BMC/IPMI reboot
- `update_ticket_status(ticket_id, status, message)` — update user-facing state
- `store_fix_pattern(error_pattern, fix_steps, tags)` — add to RAG KB (sanitised)
- `log_action(...)` — required before every SSH command

**Ticket Resolution Workflow** (LangGraph nodes):

```
[receive_ticket]
      ↓
[classify_severity]
      ↓
[rag_lookup] ──hit──→ [build_action_plan_from_rag]
      ↓ miss                    ↓
[web_search]          [confirm_plan_in_log]
      ↓                         ↓
[parse_web_fix]       [execute_via_ssh]
      ↓                         ↓
[build_action_plan]   [verify_fix]
                                ↓
                    resolved? ──yes──→ [close_ticket] → [store_fix_pattern]
                                ↓ no
                    [retry_or_escalate]
```

**System Prompt**:
```
You are a Client Support Agent for a GPU server management company.
You help users fix problems on their rented GPU servers via SSH.

Guidelines:
- ALWAYS search the knowledge base first before attempting a fix
- If KB has no answer, search the web for the specific error
- ALWAYS log your action plan BEFORE executing any commands
- Commands must be minimal and targeted — do not run destructive commands
- Never read, copy, or store client files or configurations
- Sanitise all log output before storing any fix patterns
- If severity is CRITICAL and server is unresponsive, consider hard restart — but log clearly why

When solving a ticket:
1. Understand the error
2. Find the fix (RAG → web)
3. Plan the commands
4. Log the plan
5. Execute step by step
6. Verify
7. Report back in plain language (not raw terminal output)

Output your reasoning as chain-of-thought before each tool call.
```

---

### 1.4 Report Agent

**Role**: Aggregate daily snapshots and generate manager reports.

**Tools**:
- `get_daily_snapshots(date_range)` — fetch from Postgres
- `get_ticket_summary(date_range)` — resolved/open/escalated counts
- `get_cost_summary()` — token spend from Langfuse
- `format_report(data)` → markdown string
- `send_report(channel, content)` — webhook POST or email via SMTP

**System Prompt**:
```
You are the Reporting Agent. Your job is to produce clear, accurate daily/weekly
operations reports for the manager.

Report sections:
1. Fleet Health Summary (per-server status, any critical events)
2. Ticket Summary (volume, resolution rate, avg resolution time, escalations)
3. System Cost Summary (token spend, API calls)
4. Alerts & Anomalies (anything unusual)
5. Recommended Actions (if any)

Be concise. Use tables and bullet points. Highlight critical items in bold.
Do not include raw server data, IP addresses of client servers, or user PII.
```

---

## 2. LangGraph State Schema

```python
from typing import TypedDict, Literal, Optional, List
from datetime import datetime

class AgentState(TypedDict):
    # Task identity
    task_id: str
    trace_id: str
    task_type: Literal["ticket", "maintenance", "report"]

    # Routing
    assigned_agent: Optional[str]
    severity: Optional[Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]]

    # Ticket fields
    ticket_id: Optional[str]
    user_message: Optional[str]
    server_id: Optional[str]

    # Agent working memory
    rag_hits: List[dict]
    web_search_results: List[dict]
    action_plan: List[str]
    execution_log: List[dict]  # {command, output, success, timestamp}

    # Resolution
    status: Literal["queued","assigned","thinking","executing","verifying","done","failed","escalated"]
    resolution_summary: Optional[str]
    error: Optional[str]

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

---

## 3. RAG Architecture

### 3.1 Indexing Pipeline

```
Error+Fix Pair (from confirmed agent resolution)
        ↓
[Sanitiser]  ← strip IPs, hostnames, usernames, file paths
        ↓
[Chunker]    ← split into: error_description + fix_steps (separate chunks)
        ↓
[Embedder]   ← text-embedding-3-small (1536-dim)
        ↓
[Qdrant]     ← upsert with payload: {pattern, tags, fix_steps, confidence, source}
        ↓
[BM25 Index] ← update in-memory BM25 index (persisted to Postgres on change)
```

### 3.2 Query Pipeline

```
User query / agent search query
        ↓
[Redis Semantic Cache Check]
  embedding → cosine similarity vs cached query embeddings
  threshold: 0.92 cosine similarity
        ↓ cache miss
[Parallel Retrieval]
  Dense:  Qdrant top-20 by cosine similarity
  Sparse: BM25 top-20 by BM25 score
        ↓
[Reciprocal Rank Fusion]  ← merge dense + sparse results
        ↓
[Cross-encoder Rerank]    ← top-20 → top-5
        ↓
[Result]  → agent receives top-5 {pattern, fix_steps, confidence}
        ↓
[Cache Write]  ← store query embedding + results in Redis (TTL per type)
```

### 3.3 Cache TTL Policy

| Content Type | TTL |
|---|---|
| Active error fix (seen in last 7 days) | 1 hour |
| Static knowledge (general Linux/GPU fixes) | 24 hours |
| Web search results | 30 minutes |

---

## 4. SSH Tool Design

```python
# agents never call this directly — they call tool wrappers
class VaultSession:
    """Short-lived SSH session, in-process only"""

    def __init__(self, server_id: str, agent_id: str, trace_id: str):
        ...  # fetches encrypted key from vault, decrypts in-memory only

    def execute(self, command: str, timeout: int = 30) -> dict:
        """
        Returns: {stdout, stderr, exit_code, duration_ms}
        Logs: {timestamp, agent_id, server_id, command_hash, exit_code, trace_id}
        NEVER logs: command plaintext if it contains password/key patterns
        """
        ...

    def close(self):
        """Explicitly zero out key material from memory"""
        ...
```

**Command safety filter** (before execution):
```python
FORBIDDEN_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"mkfs\.",
    r"dd\s+if=",
    r"> /dev/sd",
    r"chmod\s+777\s+/",
]
# If pattern matches → reject, log attempt, alert ops
```

---

## 5. Rate Limit Shield

```python
# Singleton in Redis, shared across all agent containers
class AnthropicRateLimiter:
    RPM_LIMIT = int(os.env("ANTHROPIC_RPM_LIMIT", 60))
    TPM_LIMIT = int(os.env("ANTHROPIC_TPM_LIMIT", 100_000))
    DAILY_COST_LIMIT_USD = float(os.env("DAILY_COST_LIMIT_USD", 50.0))

    async def acquire(self, estimated_tokens: int) -> bool:
        """
        Token bucket check in Redis (atomic Lua script).
        If limit exceeded: queue request, return False.
        Agent waits and retries with exponential backoff.
        """
        ...

    async def record_usage(self, prompt_tokens: int, completion_tokens: int):
        """Called after every LLM call. Updates daily cost counter."""
        ...
```
