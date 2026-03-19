# dev_note — client-agent

## Purpose
Ticket resolution agent. SSHes into client-rented servers, resolves user issues via RAG + web search, stores sanitised fix patterns back into KB.

## Files
> Phase 0 scaffold — no code files yet. Built in Phase 6.

Planned files (from TODO.md P6-xx):
- `main.py` — polls orchestrator for ticket tasks
- `executor.py` — receives ticket task, runs LangGraph graph, updates ticket status
- `graph.py` — full resolution graph (see AGENT_DESIGN.md §1.3 workflow)
- `prompts.py` — system prompt
- `tools.py` — rag_search, web_search, web_fetch, ssh_execute, hard_restart, update_ticket_status, store_fix_pattern, log_action
- `web_search.py` — Tavily client with SerpAPI fallback
- `severity.py` — LLM classifier → LOW|MEDIUM|HIGH|CRITICAL
- `hard_restart.py` — BMC/IPMI reboot + SSH fallback; requires double-log confirmation

## Cross-Service Contracts
- Calls: `ssh-vault` for SSH sessions
- Calls: `rag-service POST /rag/search` for KB lookup
- Calls: `rag-service POST /rag/ingest` to store confirmed fix patterns
- Reads task from: Redis queue `mas:client_queue`
- Updates: `tickets` table status + resolution_summary
- Listens on: port 8003

## State Fields
Inherits `AgentState` from `services/agent-orchestrator/state.py`. No additional fields.

## Known Gaps / Deferred
- Phase 0: directory scaffold only
- `hard_restart.py` — BMC/IPMI call is a ⚠️ STUB until Phase 6 (P6-06)
