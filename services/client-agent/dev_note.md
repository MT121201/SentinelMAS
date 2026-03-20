# dev_note — client-agent

> Last updated: 2026-03-20

## Purpose
Ticket resolution agent. SSHes into client-rented GPU servers, resolves user issues via RAG KB → web search fallback, and stores confirmed fix patterns back into the knowledge base.

---

## config.py

| Setting | Default | Purpose |
|---|---|---|
| `anthropic_model` | `claude-sonnet-4-20250514` | Agent reasoning model |
| `vault_url` | `http://ssh-vault:8100` | SSH session source |
| `rag_url` | `http://rag-service:8005` | Knowledge base |
| `orchestrator_url` | `http://orchestrator:8001` | Status reporting |
| `tavily_api_key` | `""` | Primary web search |
| `serpapi_key` | `""` | Web search fallback |
| `ssh_command_timeout` | `60` | Longer than inserver (client commands may take longer) |
| `max_agent_turns` | `30` | Claude tool-calling loop limit |
| `max_retry_attempts` | `2` | Retries before escalating |

---

## prompts.py

| Symbol | Purpose |
|---|---|
| `CLIENT_SYSTEM_PROMPT` | System prompt for ticket resolution — matches AGENT_DESIGN.md §1.3 |
| `SEVERITY_SYSTEM_PROMPT` | Prompt for severity classifier — returns JSON {severity, reason} |

---

## severity.py

### Functions

| Function | Signature | Returns |
|---|---|---|
| `classify_severity` | `(ticket_text: str) -> tuple[SeverityLevel, str]` | (LOW\|MEDIUM\|HIGH\|CRITICAL, reason). Falls back to MEDIUM on any error. |

**SeverityLevel:** `Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]`

---

## web_search.py

### Functions

| Function | Signature | Purpose |
|---|---|---|
| `web_search` | `(query, max_results=5) -> list[dict]` | Tavily → SerpAPI fallback → []. Returns [{title, snippet, url}] |
| `web_fetch` | `(url) -> str` | Fetch URL text, truncate to 8000 chars |
| `_tavily_search` | `(query, max_results) -> list[dict]` | Tavily API call |
| `_serpapi_search` | `(query, max_results) -> list[dict]` | SerpAPI fallback |

---

## hard_restart.py

### Functions

| Function | Signature | Purpose |
|---|---|---|
| `hard_restart` | `(server_id, session_token, reason, agent_id, trace_id) -> dict` | BMC/IPMI → SSH `reboot -f` fallback. Emits second confirmation log. |
| `_try_bmc_restart` | `(server_id) -> dict` | ⚠️ STUB — always returns {success: False}. Configure BMC per deployment. |
| `_try_ssh_reboot` | `(server_id, session_token) -> dict` | Issues `reboot -f` via vault; ReadTimeout treated as success. |

**Double-log contract:**
1. Caller must call `log_action(action="hard_restart_intent", ...)` BEFORE calling `hard_restart()`
2. `hard_restart()` itself logs `HARD_RESTART CONFIRMED` at WARNING level

---

## tools.py

### Tool functions

| Function | Signature | Purpose |
|---|---|---|
| `rag_search` | `(query, top_k=5) -> dict` | POST /rag/search → {results, cache_hit, total} |
| `web_search` | `(query, max_results=5) -> dict` | Web search wrapper → {results, count} |
| `web_fetch` | `(url) -> dict` | Fetch URL → {url, content} |
| `ssh_execute` | `(server_id, command, session_token) -> dict` | vault POST /execute |
| `log_action` | `(action, server_id, reason, command?) -> dict` | Structured log |
| `update_ticket_status` | `(ticket_id, status, message?, db) -> dict` | UPDATE tickets |
| `store_fix_pattern` | `(error_pattern, fix_steps, tags?, confidence=0.8) -> dict` | POST /rag/ingest |
| `hard_restart_tool` | `(server_id, session_token, reason, agent_id, trace_id) -> dict` | Calls hard_restart() |
| `open_vault_session` | `(server_id, agent_id, trace_id) -> str` | POST /vault/session |
| `close_vault_session` | `(token) -> None` | DELETE /vault/session/{token} |
| `dispatch_tool` | `(tool_name, tool_input, db, agent_id, trace_id) -> Any` | Route Claude tool_use |

### TOOL_DEFINITIONS
8 Anthropic tool schemas passed to `client.messages.create(tools=...)`.

---

## graph.py

### LangGraph nodes

| Node | Purpose |
|---|---|
| `receive_ticket_node` | Validate fields, initialise state |
| `classify_severity_node` | Claude severity classification |
| `rag_lookup_node` | RAG KB search |
| `web_search_node` | Web fallback if RAG empty |
| `resolve_loop_node` | Main Claude tool-calling loop (max 30 turns); opens/closes vault session |
| `verify_node` | Route: done → close_ticket, retry → rag_lookup, exceeded → escalated |
| `close_ticket_node` | Update DB to done, store fix pattern in RAG KB |

### Graph topology
```
receive_ticket → classify_severity → rag_lookup
                                          ↓ (has hits)    ↓ (no hits)
                                     resolve_loop ← web_search_node
                                          ↓
                                       verify
                                       ↙    ↘       ↘
                                close_ticket  rag_lookup  END(escalated)
                                     ↓
                                    END
```

### State extras (beyond AgentState)
| Field | Type | Purpose |
|---|---|---|
| `resolved` | bool | Did the agent confirm the fix worked? |
| `retry_count` | int | Number of resolve attempts made |

---

## executor.py

| Function | Signature | Purpose |
|---|---|---|
| `run_ticket_task` | `(task: dict, db: AsyncSession) -> None` | Build state, invoke graph, report status |
| `_report_status` | `(task_id, status, summary?, error?) -> None` | PUT /internal/tasks/{id}/status |

---

## main.py

Port: **8003** | Single Uvicorn worker | Consumes `mas:client_queue` via BLPOP timeout=5s

---

## Cross-Service Contracts

| Calls | Endpoint | Purpose |
|---|---|---|
| ssh-vault | `POST /vault/session` | Open SSH session |
| ssh-vault | `POST /vault/session/{token}/execute` | Run commands |
| ssh-vault | `DELETE /vault/session/{token}` | Close session |
| rag-service | `POST /rag/search` | KB lookup |
| rag-service | `POST /rag/ingest` | Store confirmed fix |
| orchestrator | `PUT /internal/tasks/{id}/status` | Report status |
| Postgres | `tickets` table | Update status + resolution_summary |
| Redis | `mas:client_queue` | Task intake via BLPOP |
| Tavily/SerpAPI | external | Web search for unknown errors |

## Known Gaps / Deferred
- `hard_restart._try_bmc_restart` — ⚠️ STUB. Requires BMC hostname/credentials per server in `server_credentials` or a separate table. BMC integration is infrastructure-specific.
- Web search TTL caching to Redis — deferred (currently no caching of web results)
