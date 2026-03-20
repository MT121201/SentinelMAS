# dev_note — report-agent

## Purpose
Aggregates daily/weekly operational data from Postgres and Redis, renders a markdown report, and delivers it via webhook or SMTP.

## Files

### config.py
- `Settings` — pydantic-settings; includes DB, Redis, Anthropic, webhook, SMTP, Langfuse keys

### prompts.py
- `REPORT_SYSTEM_PROMPT` — system prompt for Report Agent (matches AGENT_DESIGN.md §1.4)

### aggregator.py
- `get_fleet_health(db, report_date?)` → `list[dict]` — daily_health_snapshots JOIN server_credentials for one date
- `get_fleet_health_range(db, days=7)` → `dict[str, list]` — 7-day snapshots grouped by server_id
- `get_ticket_stats(db, since?)` → `dict` — total, resolved, failed, escalated, in_progress, resolution_rate_pct, avg_resolution_min
- `get_recent_escalations(db, since?, limit=10)` → `list[dict]` — escalated tickets with description[:120]
- `get_cost_summary(redis)` → `dict` — daily_cost_usd, rpm_used, tpm_used from Redis keys
- `get_weekly_cost(db)` → `dict` — ⚠️ STUB: returns placeholder until Langfuse wired (Phase 8)
- `aggregate_daily(db, redis, report_date?)` → `dict` — full daily bundle: fleet, tickets, escalations, cost
- `aggregate_weekly(db, redis)` → `dict` — weekly bundle with server_uptime_pct computed from health range

### formatter.py
- `format_daily_report(data)` → `str` — renders daily markdown with 5 sections (fleet table, ticket stats, cost, escalations, actions)
- `format_weekly_report(data)` → `str` — renders weekly markdown with 7-day uptime bars
- `wrap_html(markdown_body, subject)` → `str` — minimal HTML wrapper for SMTP delivery
- `_pct_bar(pct, width)` → `str` — ASCII progress bar (internal helper)
- `_status_icon(status)` → `str` — emoji icon for server status (internal)
- `_severity_icon(severity)` → `str` — emoji icon for ticket severity (internal)

### sender.py
- `send_webhook(report_text, subject)` → `bool` — POST to MANAGER_WEBHOOK_URL; returns False if not configured or failed
- `send_email(report_text, subject)` → `bool` — SMTP delivery (sync); returns False if not configured or failed
- `deliver_report(report_text, subject)` → `dict[str, bool]` — runs both channels; warns if neither succeeds
- `_build_email(subject, plain_text, html_text)` → `MIMEMultipart` — internal email builder

### graph.py
- `ReportState` — TypedDict: task_id, period, report_date, aggregated_data, report_text, status, delivery_result, error
- `aggregate_node(state, config)` — calls aggregate_daily or aggregate_weekly; sets aggregated_data
- `format_node(state, config)` — calls format_daily_report or format_weekly_report; sets report_text
- `send_node(state, config)` — calls deliver_report; sets status=done/failed
- `build_report_graph()` → compiled LangGraph — aggregate → format → send → END
- `report_graph` — module-level compiled graph singleton

### executor.py
- `run_report_task(task, db, redis)` — deserialise task dict, invoke report_graph, call _update_status
- `_update_status(task_id, status, summary)` — PUT /internal/tasks/{id}/status to orchestrator; fire-and-forget on error

### main.py
- FastAPI app port 8004
- `run_consumer()` — BLPOP on `mas:report_queue`, dispatches to run_report_task
- `GET /health` — liveness probe

## State Fields

| Field | Type | Purpose | Status |
|---|---|---|---|
| `task_id` | str | Unique task identifier | active |
| `period` | str | "daily" \| "weekly" | active |
| `report_date` | str | ISO date for daily reports (optional) | active |
| `aggregated_data` | dict | Raw data bundle from aggregator | active |
| `report_text` | str | Rendered markdown report | active |
| `status` | str | "done" \| "failed" | active |
| `delivery_result` | dict | {webhook: bool, email: bool} | active |
| `error` | str | Error message on failure | active |

## Cross-Service Contracts
- Reads: `daily_health_snapshots`, `tickets`, `server_credentials` from Postgres
- Reads: `mas:cost:daily_usd`, `mas:rate_limit:rpm/tpm` from Redis
- Reads task from: Redis queue `mas:report_queue`
- Calls: `orchestrator /internal/tasks/{id}/status` to report completion
- Sends: HTTP POST to `MANAGER_WEBHOOK_URL` (Slack/Teams/custom)
- Sends: SMTP email to `SMTP_TO` (optional)
- Listens on: port 8004

## Known Gaps / Deferred
- `get_weekly_cost()` — ⚠️ STUB: full breakdown requires Langfuse API integration (Phase 8)
- BMC/IPMI cost data — not tracked at report level; Langfuse will provide per-call token costs
- LLM narrative summary — `REPORT_SYSTEM_PROMPT` defined but Claude not wired into the graph; formatter is purely deterministic for now
