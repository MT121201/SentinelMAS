# dev_note — report-agent

## Purpose
Aggregates daily health snapshots and ticket stats, formats markdown report, delivers via webhook or SMTP.

## Files
> Phase 0 scaffold — no code files yet. Built in Phase 7.

Planned files (from TODO.md P7-xx):
- `main.py` — polls orchestrator for report tasks
- `graph.py` — LangGraph: aggregate → format → send
- `aggregator.py` — fetches snapshots, ticket stats, cost data from Postgres/Langfuse
- `formatter.py` — renders markdown report with tables
- `sender.py` — webhook POST + optional SMTP
- `prompts.py` — report agent system prompt

## Cross-Service Contracts
- Reads: `daily_health_snapshots`, `tickets` tables from Postgres
- Reads: cost data from Langfuse API
- Sends: webhook POST to `MANAGER_WEBHOOK_URL`
- Reads task from: Redis queue `mas:report_queue`
- Listens on: port 8004

## State Fields
Inherits `AgentState` from `services/agent-orchestrator/state.py`. No additional fields.

## Known Gaps / Deferred
- Phase 0: directory scaffold only
