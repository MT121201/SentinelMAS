# dev_note — inserver-agent

## Purpose
Daily maintenance agent for the company's own GPU server fleet. Runs health checks, auto-fixes allowed issues, emits daily snapshots.

## Files
> Phase 0 scaffold — no code files yet. Built in Phase 5.

Planned files (from TODO.md P5-xx):
- `main.py` — polls orchestrator for maintenance tasks
- `executor.py` — receives task, runs LangGraph graph, reports results
- `graph.py` — LangGraph: check_all_servers → per_server_health → fix_if_allowed → emit_snapshot
- `prompts.py` — system prompt (see AGENT_DESIGN.md §1.2)
- `tools.py` — all SSH/DB tool wrappers callable by the agent
- `health_checks.py` — `check_gpu()`, `check_disk()`, `check_memory()`, `check_process()`, `check_ssh_blacklist()`

## Cross-Service Contracts
- Calls: `ssh-vault POST /vault/session` — to get SSH session
- Calls: `ssh-vault POST /vault/session/{token}/execute` — to run commands
- Writes: `daily_health_snapshots` table in Postgres
- Reads task from: Redis queue `mas:inserver_queue` (dispatched by orchestrator)
- Listens on: port 8002

## State Fields
Inherits `AgentState` from `services/agent-orchestrator/state.py`. No additional fields.

## Known Gaps / Deferred
- Phase 0: directory scaffold only
- BMC/IPMI hard restart not in scope for this agent (client-agent only)
