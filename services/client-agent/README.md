# Client Agent

Ticket resolution agent. Receives user support tickets, finds fixes via RAG + web search, SSHes into the client's rented server, executes the fix, and closes the ticket.

**Port:** `8003` | **Built in:** Phase 6 | **Status:** scaffold

---

## Ticket Resolution Flow

```mermaid
flowchart TD
    TICKET["Receive ticket\n{server_id, description}"] --> SEV["classify_severity\nLOW | MEDIUM | HIGH | CRITICAL"]
    SEV --> RAG["rag_search\nquery knowledge base"]

    RAG -->|hit ≥ 0.92 confidence| PLAN_RAG["build_action_plan\nfrom RAG fix_steps"]
    RAG -->|miss| WEB["web_search\nTavily API → SerpAPI fallback"]
    WEB --> PLAN_WEB["parse_web_fix\nbuild_action_plan"]

    PLAN_RAG & PLAN_WEB --> LOG["log_action_plan\nBEFORE any execution"]
    LOG --> SSH_SESSION["request SSH session\nPOST /vault/session"]
    SSH_SESSION --> EXEC["execute steps\nPOST /vault/session/token/execute"]
    EXEC --> VERIFY["verify fix\ncheck output + re-run check command"]

    VERIFY -->|resolved| STORE["store_fix_pattern\nsanitised → RAG KB"]
    STORE --> CLOSE["update_ticket_status → done\nresolution_summary to user"]

    VERIFY -->|still failing| RETRY["retry or escalate"]
    SEV -->|CRITICAL + unresponsive| HARD["hard_restart\nBMC/IPMI reboot\ndouble-log required"]
```

## Key Rules
- **RAG first, web second** — never skip the knowledge base
- **Log before execute** — action plan must be in the trace before any SSH call
- **Never store client data** — only sanitised error+fix patterns go into RAG KB
- **Hard restart** — CRITICAL severity only; requires double confirmation in logs

## Design References
- `systemdev_docs/AGENT_DESIGN.md §1.3` — full workflow, tools, system prompt
- `systemdev_docs/SECURITY.md §5` — sanitisation rules
- `services/client-agent/dev_note.md`
