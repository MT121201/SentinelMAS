# dev_note — inserver-agent

> Last updated: 2026-03-20

## Purpose
Daily maintenance agent for the company's own GPU server fleet. Runs health checks via SSH, auto-fixes allowed issues, and emits daily snapshots to Postgres.

---

## config.py

| Setting | Default | Purpose |
|---|---|---|
| `anthropic_api_key` | `""` | Claude API key |
| `anthropic_model` | `claude-sonnet-4-20250514` | Model for agent reasoning |
| `vault_url` | `http://ssh-vault:8100` | SSH vault base URL |
| `internal_api_key` | `""` | X-Internal-Key for vault + orchestrator |
| `orchestrator_url` | `http://orchestrator:8001` | Status reporting target |
| `vault_session_ttl` | `300` | Session TTL requested from vault (seconds) |
| `ssh_command_timeout` | `30` | SSH command timeout |
| `disk_alert_threshold_pct` | `85.0` | Disk usage alert threshold |
| `gpu_memory_alert_threshold_pct` | `90.0` | GPU memory alert threshold |

---

## prompts.py

| Symbol | Purpose |
|---|---|
| `INSERVER_SYSTEM_PROMPT` | System prompt passed to Claude; matches AGENT_DESIGN.md §1.2 exactly |

Allowed autonomous fixes: unblock own IP, restart allowed services, clear large logs.
Forbidden: kernel changes, reboots, network config, user account changes.

---

## health_checks.py

Pure parsing functions — no I/O. All inputs are raw SSH stdout strings.

| Function | Input | Returns |
|---|---|---|
| `parse_gpu_status(nvidia_smi_output)` | `nvidia-smi --query-gpu=... --format=csv` stdout | `{ok, gpus:[{index,name,temp_c,util_pct,mem_used_mb,mem_total_mb,mem_pct,power_w,ecc_errors}], alerts, raw}` |
| `parse_disk_space(df_output)` | `df -h --output=source,size,used,avail,pcent,target` stdout | `{ok, filesystems:[{source,size,used,avail,use_pct,mount}], alerts}` |
| `parse_memory(free_output)` | `free -m` stdout | `{ok, total_mb, used_mb, free_mb, available_mb, use_pct, swap_total_mb, swap_used_mb, alerts}` |
| `parse_process_health(systemctl_output, service_name)` | `systemctl status <svc>` stdout | `{service, active, running, status_line, alerts}` |
| `parse_ssh_blacklist(fail2ban_output, iptables_output, own_ip)` | Both command outputs + IP | `{blocked, found_in_fail2ban, found_in_iptables, own_ip, alerts}` |

**Alert thresholds:**
- GPU temp > 85°C → alert
- GPU mem > 90% → alert
- ECC errors > 0 → alert
- Disk use ≥ 85% → warning; ≥ 95% → CRITICAL
- Memory use > 90% → alert

---

## tools.py

### Tool functions (all async)

| Function | Signature | Purpose |
|---|---|---|
| `ssh_execute` | `(server_id, command, session_token) -> dict` | Execute command via vault; returns {stdout, stderr, exit_code, duration_ms} |
| `get_server_list` | `(db: AsyncSession) -> list[dict]` | SELECT all active servers from server_credentials |
| `check_gpu_status` | `(server_id, session_token) -> dict` | nvidia-smi → parse_gpu_status |
| `check_disk_space` | `(server_id, session_token) -> dict` | df -h → parse_disk_space |
| `check_memory` | `(server_id, session_token) -> dict` | free -m → parse_memory |
| `check_process_health` | `(server_id, session_token, service_name) -> dict` | systemctl status → parse_process_health |
| `check_ssh_blacklist` | `(server_id, session_token) -> dict` | fail2ban + iptables → parse_ssh_blacklist |
| `unblock_own_ip` | `(server_id, session_token) -> dict` | fail2ban-client unban + iptables -D DROP |
| `restart_service` | `(server_id, session_token, service_name) -> dict` | systemctl restart; allowed list enforced |
| `emit_health_snapshot` | `(server_id, metrics, status, db) -> dict` | UPSERT daily_health_snapshots |
| `log_action` | `(action, server_id, result, trace_id, db) -> None` | Structured log entry |
| `dispatch_tool` | `(tool_name, tool_input, db) -> Any` | Route Claude tool_use call to correct function |
| `open_vault_session` | `(server_id, agent_id, trace_id) -> str` | POST /vault/session → session_token |
| `close_vault_session` | `(token) -> None` | DELETE /vault/session/{token} |
| `_get_own_ip` | `() -> str` | Outbound IP via UDP socket trick |

**Allowed restart services:** `nvidia-persistenced`, `docker`, `ssh`, `cron`

### TOOL_DEFINITIONS
Anthropic tool schema list passed to `client.messages.create(tools=...)`.
10 tools defined, matching the function list above.

---

## graph.py

### LangGraph nodes

| Node | Purpose |
|---|---|
| `check_all_servers_node` | Fetches server list from DB; stores in state["server_list"] |
| `per_server_health_node` | Opens vault session per server; runs Claude tool-calling loop (max 20 turns); closes session |
| `emit_snapshot_node` | Upserts daily_health_snapshots for all servers; builds resolution_summary |

### Graph topology
```
check_all_servers → per_server_health → emit_snapshot → END
```

### State extras (beyond AgentState)
| Field | Type | Purpose |
|---|---|---|
| `server_list` | list[dict] | [{server_id, hostname}] from DB |
| `server_results` | dict[server_id → result] | Health check results per server |

`_MAX_AGENT_TURNS = 20` — prevents infinite tool-calling loops.

---

## executor.py

### Functions

| Function | Signature | Purpose |
|---|---|---|
| `run_maintenance_task` | `(task: dict, db: AsyncSession) -> None` | Entry point: build state, invoke graph, report status |
| `_report_status` | `(task_id, status, summary?, error?) -> None` | PUT /internal/tasks/{id}/status on orchestrator |
| `_parse_dt` | `(value?) -> datetime \| None` | ISO string → datetime |

---

## main.py

Port: **8002** | Single Uvicorn worker (consumer loop shares event loop)
Consumes: `mas:inserver_queue` via BLPOP, timeout=5s

---

## Cross-Service Contracts

| Calls | Endpoint | Purpose |
|---|---|---|
| ssh-vault | `POST /vault/session` | Open SSH session per server |
| ssh-vault | `POST /vault/session/{token}/execute` | Run commands |
| ssh-vault | `DELETE /vault/session/{token}` | Close session |
| orchestrator | `PUT /internal/tasks/{id}/status` | Report task progress/completion |
| Postgres | `server_credentials` | Read active server list |
| Postgres | `daily_health_snapshots` | Upsert health metrics |
| Redis | `mas:inserver_queue` | Task intake via BLPOP |

## Known Gaps / Deferred
- `log_action` writes to application log only; DB audit table deferred to Phase 8
- Single-server mode (task.server_id set) — graph currently always fetches all servers; targeted single-server maintenance deferred
