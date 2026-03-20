"""
InServer Agent LangGraph graph.

Graph topology:
  [start] → check_all_servers → per_server_health → fix_if_allowed → emit_snapshot → [end]

State carries the full AgentState TypedDict.
The graph runs one full server health cycle per invocation.
Server iteration is handled by the executor — the graph processes one server at a time.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

import anthropic
from langgraph.graph import END, StateGraph

from config import settings
from prompts import INSERVER_SYSTEM_PROMPT
from tools import TOOL_DEFINITIONS, dispatch_tool

log = logging.getLogger(__name__)

_MAX_AGENT_TURNS = 20  # prevent infinite tool-calling loops


# ── Node implementations ──────────────────────────────────────────────────────


async def check_all_servers_node(state: dict, config: dict) -> dict:
    """
    Fetch server list from DB and store in state for downstream nodes.
    Sets state["server_list"] = [{"server_id", "hostname"}, ...]
    """
    from tools import get_server_list
    db = config["configurable"]["db"]
    servers = await get_server_list(db)
    log.info("inserver graph: found %d active servers", len(servers))
    return {
        "server_list": servers,
        "status": "thinking",
        "updated_at": datetime.now(timezone.utc),
    }


async def per_server_health_node(state: dict, config: dict) -> dict:
    """
    Run the Claude agent loop for each server in server_list.
    Collects health results into state["server_results"].
    Opens/closes vault sessions per server.
    """
    from tools import open_vault_session, close_vault_session

    db = config["configurable"]["db"]
    trace_id = state.get("trace_id", "unknown")
    task_id = state.get("task_id", "unknown")
    servers = state.get("server_list", [])

    server_results = {}
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    for server in servers:
        server_id = server["server_id"]
        hostname = server.get("hostname", server_id)
        log.info("inserver: checking server %s (%s)", server_id, hostname)

        session_token = None
        try:
            session_token = await open_vault_session(server_id, task_id, trace_id)
        except Exception as exc:
            log.error("inserver: cannot open vault session for %s: %s", server_id, exc)
            server_results[server_id] = {
                "status": "unreachable",
                "error": str(exc),
                "alerts": [f"Cannot open SSH session: {exc}"],
            }
            continue

        # Initial prompt for this server
        messages = [
            {
                "role": "user",
                "content": (
                    f"Please run a complete health check on server_id={server_id} (hostname={hostname}).\n"
                    f"Session token for vault: {session_token}\n"
                    "Check: GPU status, disk space, memory, nvidia-persistenced service, docker service, "
                    "SSH blacklist. Report all findings and fix any issues within your allowed operations."
                ),
            }
        ]

        result = {"server_id": server_id, "alerts": [], "fixes_applied": [], "status": "healthy"}

        try:
            for _turn in range(_MAX_AGENT_TURNS):
                response = await client.messages.create(
                    model=settings.anthropic_model,
                    max_tokens=4096,
                    system=INSERVER_SYSTEM_PROMPT,
                    tools=TOOL_DEFINITIONS,
                    messages=messages,
                )

                # Collect text and tool_use blocks
                tool_calls = []
                text_parts = []
                for block in response.content:
                    if block.type == "tool_use":
                        tool_calls.append(block)
                    elif block.type == "text":
                        text_parts.append(block.text)

                # Append assistant message
                messages.append({"role": "assistant", "content": response.content})

                if response.stop_reason == "end_turn":
                    # Agent finished — extract final summary from text
                    result["summary"] = " ".join(text_parts).strip()
                    break

                if response.stop_reason == "tool_use":
                    # Execute all tool calls and return results
                    tool_results = []
                    for tc in tool_calls:
                        log.info(
                            "inserver: server=%s tool=%s", server_id, tc.name
                        )
                        try:
                            output = await dispatch_tool(tc.name, tc.input, db)
                        except Exception as exc:
                            output = {"error": str(exc)}
                            log.error("inserver: tool %s failed: %s", tc.name, exc)

                        # Accumulate alerts from health check tools
                        if isinstance(output, dict) and "alerts" in output:
                            result["alerts"].extend(output["alerts"])

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "content": json.dumps(output),
                        })

                    messages.append({"role": "user", "content": tool_results})
                else:
                    break  # unexpected stop reason

        except Exception as exc:
            log.error("inserver: agent loop failed for server %s: %s", server_id, exc)
            result["status"] = "error"
            result["error"] = str(exc)
        finally:
            try:
                await close_vault_session(session_token)
            except Exception:
                pass

        # Determine overall status from alerts
        if result["alerts"]:
            result["status"] = "warning" if not any("CRITICAL" in a for a in result["alerts"]) else "critical"

        server_results[server_id] = result
        log.info("inserver: server %s → %s (%d alerts)", server_id, result["status"], len(result["alerts"]))

    return {
        "server_results": server_results,
        "execution_log": state.get("execution_log", []) + [
            {"step": "per_server_health", "servers_checked": len(servers), "timestamp": datetime.now(timezone.utc).isoformat()}
        ],
        "updated_at": datetime.now(timezone.utc),
    }


async def emit_snapshot_node(state: dict, config: dict) -> dict:
    """
    Write one daily_health_snapshot row per server to Postgres.
    Builds resolution_summary from all server results.
    """
    from tools import emit_health_snapshot

    db = config["configurable"]["db"]
    server_results: dict = state.get("server_results", {})

    summary_parts = []
    for server_id, result in server_results.items():
        status = result.get("status", "unknown")
        alerts = result.get("alerts", [])
        await emit_health_snapshot(server_id, result, status, db)
        summary_parts.append(
            f"Server {server_id}: {status}" + (f" — {'; '.join(alerts[:3])}" if alerts else "")
        )

    all_healthy = all(r.get("status") == "healthy" for r in server_results.values())

    return {
        "status": "done",
        "resolution_summary": "\n".join(summary_parts) or "No servers checked.",
        "updated_at": datetime.now(timezone.utc),
    }


# ── Graph construction ─────────────────────────────────────────────────────────


def build_inserver_graph() -> Any:
    graph = StateGraph(dict)

    graph.add_node("check_all_servers", check_all_servers_node)
    graph.add_node("per_server_health", per_server_health_node)
    graph.add_node("emit_snapshot", emit_snapshot_node)

    graph.set_entry_point("check_all_servers")
    graph.add_edge("check_all_servers", "per_server_health")
    graph.add_edge("per_server_health", "emit_snapshot")
    graph.add_edge("emit_snapshot", END)

    return graph.compile()


inserver_graph = build_inserver_graph()
