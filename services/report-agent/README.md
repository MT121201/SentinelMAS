# Report Agent

Aggregates daily health snapshots and ticket statistics, formats a structured markdown report, and delivers it to the manager via webhook or email.

**Port:** `8004` | **Built in:** Phase 7 | **Status:** scaffold

---

## Report Generation Flow

```mermaid
flowchart TD
    TRIGGER["Scheduler\nMonday 08:00 UTC"] --> TASK["Orchestrator enqueues\nreport task"]
    TASK --> AGG["aggregator.py\nfetch data"]

    AGG --> SNAP["daily_health_snapshots\nlast 7 days per server"]
    AGG --> TICKETS["tickets table\nresolved / failed / escalated counts"]
    AGG --> COST["Langfuse API\ntoken spend + LLM cost"]

    SNAP & TICKETS & COST --> FORMAT["formatter.py\nrender markdown report"]

    FORMAT --> REPORT["Report sections:\n1. Fleet Health Summary\n2. Ticket Summary\n3. Cost Summary\n4. Alerts & Anomalies\n5. Recommended Actions"]

    REPORT --> SEND["sender.py"]
    SEND -->|configured| WEBHOOK["POST manager webhook"]
    SEND -->|configured| SMTP["SMTP email"]
```

## Report Content Rules
- No raw server IPs in user-facing output
- No client file content or user PII
- Critical events highlighted in bold
- Uses tables and bullet points for scannability

## Design References
- `systemdev_docs/AGENT_DESIGN.md §1.4` — tools, system prompt, report sections
- `alembic/dev_note.md` — `daily_health_snapshots`, `tickets` table schemas
- `services/report-agent/dev_note.md`
