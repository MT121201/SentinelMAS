"""
Client Agent LangGraph graph — full ticket resolution pipeline.

Graph topology (matches AGENT_DESIGN.md §1.3):

  [receive_ticket]
        ↓
  [classify_severity]
        ↓
  [rag_lookup] ──hit──→ [execute_and_verify]
        ↓ miss                   ↓
  [web_search_node]       resolved? → [close_ticket] → [store_fix_pattern]
        ↓                            ↓ no
  [execute_and_verify]      [retry_or_escalate]

Implemented as a linear graph with conditional edges:
  receive_ticket → classify_severity → rag_lookup →(hit/miss)→ resolve_loop → close_or_escalate
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

import anthropic
from langgraph.graph import END, StateGraph

from config import settings
from prompts import CLIENT_SYSTEM_PROMPT
from severity import classify_severity
from tools import (
    TOOL_DEFINITIONS,
    close_vault_session,
    dispatch_tool,
    open_vault_session,
    rag_search,
    store_fix_pattern,
    update_ticket_status,
)

log = logging.getLogger(__name__)
_MAX_TURNS = settings.max_agent_turns
_MAX_RETRIES = settings.max_retry_attempts


# ── Nodes ──────────────────────────────────────────────────────────────────────


async def receive_ticket_node(state: dict, config: dict) -> dict:
    """Validate ticket fields are present. Sets status → thinking."""
    ticket_id = state.get("ticket_id")
    user_message = state.get("user_message", "")
    server_id = state.get("server_id")

    if not ticket_id or not user_message:
        return {
            "status": "failed",
            "error": "Missing ticket_id or user_message",
            "updated_at": datetime.now(timezone.utc),
        }

    log.info("client graph: receiving ticket_id=%s server_id=%s", ticket_id, server_id)
    return {
        "status": "thinking",
        "action_plan": [],
        "execution_log": [],
        "rag_hits": [],
        "web_search_results": [],
        "retry_count": 0,
        "updated_at": datetime.now(timezone.utc),
    }


async def classify_severity_node(state: dict, config: dict) -> dict:
    """Classify ticket severity using Claude."""
    db = config["configurable"]["db"]
    ticket_id = state["ticket_id"]
    user_message = state.get("user_message", "")

    severity, reason = await classify_severity(user_message)
    log.info("client graph: ticket %s severity=%s reason=%s", ticket_id, severity, reason)

    await update_ticket_status(ticket_id, "thinking", f"Severity: {severity} — {reason}", db)
    return {"severity": severity, "updated_at": datetime.now(timezone.utc)}


async def rag_lookup_node(state: dict, config: dict) -> dict:
    """Search RAG knowledge base. Sets rag_hits."""
    user_message = state.get("user_message", "")
    result = await rag_search(user_message, top_k=5)
    hits = result.get("results", [])
    log.info("client graph: RAG returned %d hits", len(hits))
    return {
        "rag_hits": hits,
        "updated_at": datetime.now(timezone.utc),
    }


def _should_use_rag(state: dict) -> str:
    """Conditional: if RAG has hits, skip web search."""
    if state.get("rag_hits"):
        return "resolve_loop"
    return "web_search_node"


async def web_search_node(state: dict, config: dict) -> dict:
    """Web search fallback when RAG has no results."""
    from tools import web_search
    user_message = state.get("user_message", "")
    result = await web_search(user_message, max_results=5)
    web_results = result.get("results", [])
    log.info("client graph: web search returned %d results", len(web_results))
    return {
        "web_search_results": web_results,
        "updated_at": datetime.now(timezone.utc),
    }


async def resolve_loop_node(state: dict, config: dict) -> dict:
    """
    Main Claude agent loop — plan → execute → verify.
    Opens a vault SSH session if server_id is set.
    Runs up to _MAX_TURNS tool-calling turns.
    """
    db = config["configurable"]["db"]
    ticket_id = state["ticket_id"]
    server_id = state.get("server_id")
    task_id = state.get("task_id", ticket_id)
    trace_id = state.get("trace_id", task_id)
    severity = state.get("severity", "MEDIUM")

    await update_ticket_status(ticket_id, "executing", "Agent is working on the fix", db)

    # Build context message from RAG hits or web results
    context_parts = []
    if state.get("rag_hits"):
        context_parts.append("Knowledge base found these relevant fixes:")
        for h in state["rag_hits"][:3]:
            context_parts.append(f"- Pattern: {h.get('error_pattern','')}\n  Fix: {h.get('fix_steps','')}")
    elif state.get("web_search_results"):
        context_parts.append("Web search results:")
        for r in state["web_search_results"][:3]:
            context_parts.append(f"- {r.get('title','')} ({r.get('url','')})\n  {r.get('snippet','')}")

    user_msg = (
        f"Ticket #{ticket_id} | Server: {server_id} | Severity: {severity}\n\n"
        f"User problem: {state.get('user_message','')}\n\n"
        + ("\n".join(context_parts) if context_parts else "No prior knowledge found — investigate from scratch.")
        + "\n\nPlease diagnose and fix the problem. Log your plan before executing commands."
    )

    messages = [{"role": "user", "content": user_msg}]
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    execution_log = list(state.get("execution_log", []))
    session_token: str | None = None
    resolution_summary = ""
    resolved = False

    # Open SSH session if we have a server
    if server_id:
        try:
            session_token = await open_vault_session(server_id, task_id, trace_id)
        except Exception as exc:
            log.error("client graph: cannot open vault session: %s", exc)
            return {
                "status": "failed",
                "error": f"Cannot SSH to server: {exc}",
                "updated_at": datetime.now(timezone.utc),
            }

    try:
        for _turn in range(_MAX_TURNS):
            response = await client.messages.create(
                model=settings.anthropic_model,
                max_tokens=4096,
                system=CLIENT_SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )

            tool_calls = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b.text for b in response.content if b.type == "text"]
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                resolution_summary = " ".join(text_blocks).strip()
                resolved = True
                break

            if response.stop_reason == "tool_use":
                tool_results = []
                for tc in tool_calls:
                    inp = dict(tc.input)
                    # Inject session_token for SSH tools
                    if tc.name == "ssh_execute" and session_token:
                        inp.setdefault("session_token", session_token)
                    if tc.name == "hard_restart" and session_token:
                        inp.setdefault("session_token", session_token)

                    log.info("client graph: tool=%s ticket=%s", tc.name, ticket_id)
                    try:
                        output = await dispatch_tool(tc.name, inp, db, task_id, trace_id)
                    except Exception as exc:
                        output = {"error": str(exc)}

                    execution_log.append({
                        "tool": tc.name,
                        "input": inp,
                        "output": output,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": json.dumps(output),
                    })
                messages.append({"role": "user", "content": tool_results})
            else:
                break
    finally:
        if session_token:
            await close_vault_session(session_token)

    status = "verifying" if resolved else "failed"
    return {
        "status": status,
        "resolution_summary": resolution_summary,
        "execution_log": execution_log,
        "resolved": resolved,
        "updated_at": datetime.now(timezone.utc),
    }


async def verify_node(state: dict, config: dict) -> dict:
    """Determine final outcome: done, retry, or escalate."""
    db = config["configurable"]["db"]
    ticket_id = state["ticket_id"]
    resolved = state.get("resolved", False)
    retry_count = state.get("retry_count", 0)

    if resolved:
        return {"status": "done", "updated_at": datetime.now(timezone.utc)}

    if retry_count < _MAX_RETRIES:
        log.info("client graph: ticket %s — retrying (attempt %d)", ticket_id, retry_count + 1)
        return {
            "status": "thinking",
            "retry_count": retry_count + 1,
            "rag_hits": [],
            "web_search_results": [],
            "updated_at": datetime.now(timezone.utc),
        }

    log.warning("client graph: ticket %s escalated after %d retries", ticket_id, retry_count)
    await update_ticket_status(ticket_id, "escalated", "Agent could not resolve — escalated for human review", db)
    return {"status": "escalated", "updated_at": datetime.now(timezone.utc)}


async def close_ticket_node(state: dict, config: dict) -> dict:
    """Mark ticket done and store fix pattern in RAG KB."""
    db = config["configurable"]["db"]
    ticket_id = state["ticket_id"]
    summary = state.get("resolution_summary", "Issue resolved.")
    severity = state.get("severity", "MEDIUM")

    await update_ticket_status(ticket_id, "done", summary, db)

    # Store fix if we have enough context
    user_message = state.get("user_message", "")
    if user_message and summary and len(summary) > 20:
        await store_fix_pattern(
            error_pattern=user_message[:500],
            fix_steps=summary[:1000],
            tags=[severity.lower(), "ticket-resolved"],
            confidence=0.85,
        )
        log.info("client graph: stored fix pattern for ticket %s", ticket_id)

    return {"status": "done", "updated_at": datetime.now(timezone.utc)}


# ── Routing helpers ───────────────────────────────────────────────────────────


def _route_after_verify(state: dict) -> str:
    status = state.get("status")
    if status == "done":
        return "close_ticket"
    if status == "thinking":
        return "rag_lookup"   # retry path
    return END  # escalated or failed


# ── Graph construction ─────────────────────────────────────────────────────────


def build_client_graph():
    graph = StateGraph(dict)

    graph.add_node("receive_ticket", receive_ticket_node)
    graph.add_node("classify_severity", classify_severity_node)
    graph.add_node("rag_lookup", rag_lookup_node)
    graph.add_node("web_search_node", web_search_node)
    graph.add_node("resolve_loop", resolve_loop_node)
    graph.add_node("verify", verify_node)
    graph.add_node("close_ticket", close_ticket_node)

    graph.set_entry_point("receive_ticket")
    graph.add_edge("receive_ticket", "classify_severity")
    graph.add_edge("classify_severity", "rag_lookup")
    graph.add_conditional_edges("rag_lookup", _should_use_rag, {
        "resolve_loop": "resolve_loop",
        "web_search_node": "web_search_node",
    })
    graph.add_edge("web_search_node", "resolve_loop")
    graph.add_edge("resolve_loop", "verify")
    graph.add_conditional_edges("verify", _route_after_verify, {
        "close_ticket": "close_ticket",
        "rag_lookup": "rag_lookup",
        END: END,
    })
    graph.add_edge("close_ticket", END)

    return graph.compile()


client_graph = build_client_graph()
