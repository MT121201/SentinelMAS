"""
Tool wrappers for the Client Agent.

Each tool is async and maps 1-to-1 to an Anthropic tool_use name.
dispatch_tool() routes Claude tool calls to the correct function.

Tools (matching AGENT_DESIGN.md §1.3):
  rag_search            — search RAG knowledge base
  web_search            — Tavily / SerpAPI search
  web_fetch             — fetch a URL content
  ssh_execute           — run command via vault session
  classify_severity     — LLM ticket severity classification
  hard_restart          — CRITICAL-only BMC/IPMI + SSH fallback reboot
  update_ticket_status  — update tickets table status + summary
  store_fix_pattern     — POST sanitised fix to rag-service /rag/ingest
  log_action            — structured log before every SSH or destructive call
"""

import logging
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from hard_restart import hard_restart as _hard_restart
from severity import classify_severity as _classify_severity
from web_search import web_fetch as _web_fetch
from web_search import web_search as _web_search

log = logging.getLogger(__name__)

# Anthropic tool schema
TOOL_DEFINITIONS = [
    {
        "name": "rag_search",
        "description": "Search the internal knowledge base for known GPU error patterns and fixes. Always call this FIRST before web_search.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Error description or symptom to search for"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_search",
        "description": "Search the web for GPU error fixes when the knowledge base has no answer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query including error message and GPU model if known"},
                "max_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_fetch",
        "description": "Fetch the full content of a URL found via web_search (e.g. documentation page, forum thread).",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"}
            },
            "required": ["url"],
        },
    },
    {
        "name": "ssh_execute",
        "description": "Execute a shell command on the client's server via SSH vault. Always call log_action first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "command": {"type": "string"},
                "session_token": {"type": "string"},
            },
            "required": ["server_id", "command", "session_token"],
        },
    },
    {
        "name": "log_action",
        "description": "Log your planned action BEFORE executing it. Required before any ssh_execute or hard_restart call.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "server_id": {"type": "string"},
                "reason": {"type": "string"},
                "command": {"type": "string"},
            },
            "required": ["action", "server_id", "reason"],
        },
    },
    {
        "name": "update_ticket_status",
        "description": "Update the ticket status and resolution summary in the database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["thinking", "executing", "verifying", "done", "failed", "escalated"],
                },
                "message": {"type": "string", "description": "Human-readable status message"},
            },
            "required": ["ticket_id", "status"],
        },
    },
    {
        "name": "store_fix_pattern",
        "description": "Store a confirmed error+fix pair in the knowledge base after successful ticket resolution. Do NOT store if fix failed or is uncertain.",
        "input_schema": {
            "type": "object",
            "properties": {
                "error_pattern": {"type": "string", "description": "Description of the error (will be sanitised)"},
                "fix_steps": {"type": "string", "description": "Step-by-step fix that worked (will be sanitised)"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number", "description": "0.0-1.0, how confident the fix is correct"},
            },
            "required": ["error_pattern", "fix_steps"],
        },
    },
    {
        "name": "hard_restart",
        "description": "CRITICAL ONLY. Perform a hard server restart via BMC/IPMI or SSH reboot -f. Requires prior log_action call with action='hard_restart_intent'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "session_token": {"type": "string"},
                "reason": {"type": "string", "description": "Explicit justification for hard restart"},
            },
            "required": ["server_id", "session_token", "reason"],
        },
    },
]


# ── Vault helper ──────────────────────────────────────────────────────────────


async def open_vault_session(server_id: str, agent_id: str, trace_id: str) -> str:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{settings.vault_url}/vault/session",
            json={"server_id": server_id, "agent_id": agent_id, "trace_id": trace_id, "ttl": settings.vault_session_ttl},
            headers={"X-Internal-Key": settings.internal_api_key},
        )
        resp.raise_for_status()
        return resp.json()["session_token"]


async def close_vault_session(token: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.delete(
                f"{settings.vault_url}/vault/session/{token}",
                headers={"X-Internal-Key": settings.internal_api_key},
            )
    except Exception as exc:
        log.warning("close_vault_session failed: %s", exc)


# ── Tool implementations ──────────────────────────────────────────────────────


async def rag_search(query: str, top_k: int = 5) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.rag_url}/rag/search",
                json={"query": query, "top_k": top_k, "use_cache": True},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        log.warning("rag_search failed: %s", exc)
        return {"results": [], "cache_hit": False, "total": 0, "error": str(exc)}


async def web_search(query: str, max_results: int = 5) -> dict:
    results = await _web_search(query, max_results)
    return {"results": results, "count": len(results)}


async def web_fetch(url: str) -> dict:
    content = await _web_fetch(url)
    return {"url": url, "content": content}


async def ssh_execute(server_id: str, command: str, session_token: str) -> dict:
    async with httpx.AsyncClient(timeout=settings.ssh_command_timeout + 5) as client:
        resp = await client.post(
            f"{settings.vault_url}/vault/session/{session_token}/execute",
            json={"command": command, "timeout": settings.ssh_command_timeout},
            headers={"X-Internal-Key": settings.internal_api_key},
        )
        resp.raise_for_status()
        return resp.json()


async def log_action(action: str, server_id: str, reason: str, command: str | None = None) -> dict:
    log.info(
        "client_agent_action action=%s server_id=%s reason=%s command=%s",
        action, server_id, reason, command or "",
    )
    return {"logged": True, "action": action, "server_id": server_id}


async def update_ticket_status(
    ticket_id: str, status: str, message: str | None, db: AsyncSession
) -> dict:
    try:
        await db.execute(
            text(
                "UPDATE tickets SET status=:status, resolution_summary=COALESCE(:msg, resolution_summary), "
                "updated_at=now() WHERE id=:id"
            ),
            {"status": status, "msg": message, "id": int(ticket_id)},
        )
        await db.commit()
        return {"updated": True, "ticket_id": ticket_id, "status": status}
    except Exception as exc:
        log.error("update_ticket_status failed: %s", exc)
        return {"updated": False, "error": str(exc)}


async def store_fix_pattern(
    error_pattern: str,
    fix_steps: str,
    tags: list[str] | None = None,
    confidence: float = 0.8,
) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.rag_url}/rag/ingest",
                json={
                    "error_pattern": error_pattern,
                    "fix_steps": fix_steps,
                    "tags": tags or [],
                    "confidence": confidence,
                    "source": "ticket-resolution",
                },
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        log.warning("store_fix_pattern failed: %s", exc)
        return {"stored": False, "error": str(exc)}


async def hard_restart_tool(
    server_id: str,
    session_token: str,
    reason: str,
    agent_id: str,
    trace_id: str,
) -> dict:
    return await _hard_restart(
        server_id=server_id,
        session_token=session_token,
        reason=reason,
        agent_id=agent_id,
        trace_id=trace_id,
    )


# ── Dispatcher ────────────────────────────────────────────────────────────────


async def dispatch_tool(
    tool_name: str,
    tool_input: dict,
    db: AsyncSession,
    agent_id: str = "",
    trace_id: str = "",
) -> Any:
    match tool_name:
        case "rag_search":
            return await rag_search(**tool_input)
        case "web_search":
            return await web_search(**tool_input)
        case "web_fetch":
            return await web_fetch(**tool_input)
        case "ssh_execute":
            return await ssh_execute(**tool_input)
        case "log_action":
            return await log_action(**tool_input)
        case "update_ticket_status":
            return await update_ticket_status(**tool_input, db=db)
        case "store_fix_pattern":
            return await store_fix_pattern(**tool_input)
        case "hard_restart":
            return await hard_restart_tool(**tool_input, agent_id=agent_id, trace_id=trace_id)
        case _:
            return {"error": f"Unknown tool: {tool_name}"}
