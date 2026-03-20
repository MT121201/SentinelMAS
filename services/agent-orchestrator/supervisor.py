"""
Supervisor — LangGraph StateGraph that classifies and routes tasks.

Graph:
    [classify] → [route]

classify: If task_type is known (ticket/maintenance/report), pass through.
          If unknown, call Claude to determine task_type.
route:    Enqueue to the appropriate specialist Redis queue.
          Update task status in Postgres.
"""

import json
import logging
from datetime import datetime, timezone

import anthropic
from langgraph.graph import END, StateGraph
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from langfuse_tracer import create_trace, record_llm_call
from state import AgentState

log = logging.getLogger(__name__)

_anthropic_client: anthropic.AsyncAnthropic | None = None

_SUPERVISOR_SYSTEM_PROMPT = """You are the supervisor of a GPU server management system.
Your job is to route incoming tasks to the correct specialist agent.
You do NOT solve tasks yourself. You only classify, route, and monitor.
Always output a routing decision as JSON: {"agent": "<name>", "reason": "<1 sentence>"}
Valid agent names: client-agent, inserver-agent, report-agent
Never make assumptions about what tools are available — check the agent registry."""


def _get_client() -> anthropic.AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


# ── Task type → queue name mapping ────────────────────────────────────────────

_QUEUE_MAP = {
    "ticket": settings.queue_client,
    "maintenance": settings.queue_inserver,
    "report": settings.queue_report,
}

_AGENT_MAP = {
    "ticket": "client-agent",
    "maintenance": "inserver-agent",
    "report": "report-agent",
}


# ── Nodes ──────────────────────────────────────────────────────────────────────


async def classify_node(state: AgentState, config: dict) -> dict:
    """
    Determine task_type if it is 'unknown'. Otherwise pass through unchanged.
    Uses Claude to classify based on user_message or task payload.
    """
    if state["task_type"] != "unknown":
        return {}

    trace = create_trace(
        name="supervisor.classify",
        task_id=state["task_id"],
        trace_id=state["trace_id"],
    )

    user_context = state.get("user_message") or f"task_id={state['task_id']}"
    prompt = (
        f"Classify this task:\n\n{user_context}\n\n"
        "Choose one: ticket, maintenance, report.\n"
        'Output JSON: {"agent": "<name>", "reason": "<reason>"}'
    )

    client = _get_client()
    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=128,
        system=_SUPERVISOR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    usage = response.usage
    record_llm_call(
        trace,
        model=settings.anthropic_model,
        prompt_tokens=usage.input_tokens,
        completion_tokens=usage.output_tokens,
    )

    try:
        raw = response.content[0].text.strip()
        decision = json.loads(raw)
        agent_name = decision.get("agent", "")
        task_type_map = {
            "client-agent": "ticket",
            "inserver-agent": "maintenance",
            "report-agent": "report",
        }
        resolved_type = task_type_map.get(agent_name, "ticket")
        log.info("supervisor classified task %s → %s", state["task_id"], resolved_type)
        return {"task_type": resolved_type, "updated_at": datetime.now(timezone.utc)}
    except (json.JSONDecodeError, KeyError) as exc:
        log.warning("supervisor classification parse error: %s — defaulting to ticket", exc)
        return {"task_type": "ticket", "updated_at": datetime.now(timezone.utc)}


async def route_node(state: AgentState, config: dict) -> dict:
    """
    Enqueue the task to the specialist agent Redis queue.
    Update ticket status to 'assigned' in Postgres if ticket_id is set.

    Config keys expected:
        redis: aioredis.Redis
        db:    AsyncSession
    """
    redis = config["configurable"]["redis"]
    db: AsyncSession = config["configurable"]["db"]

    task_type = state["task_type"]
    queue_name = _QUEUE_MAP.get(task_type, settings.queue_client)
    assigned = _AGENT_MAP.get(task_type, "client-agent")

    # Push to specialist queue
    import json as _json
    payload = _json.dumps({
        "task_id": state["task_id"],
        "trace_id": state["trace_id"],
        "task_type": task_type,
        "ticket_id": state.get("ticket_id"),
        "server_id": state.get("server_id"),
        "user_message": state.get("user_message"),
        "severity": state.get("severity"),
        "created_at": state["created_at"].isoformat(),
    })
    await redis.rpush(f"mas:{queue_name}_queue", payload)

    log.info(
        "supervisor routed task %s → %s (queue: mas:%s_queue)",
        state["task_id"],
        assigned,
        queue_name,
    )

    # Update ticket status → assigned
    if state.get("ticket_id"):
        try:
            await db.execute(
                text(
                    "UPDATE tickets SET status='assigned', agent_id=:agent, updated_at=now() "
                    "WHERE id=:id"
                ),
                {"agent": assigned, "id": int(state["ticket_id"])},
            )
            await db.commit()
        except Exception as exc:
            log.warning("supervisor: failed to update ticket status: %s", exc)

    return {
        "assigned_agent": assigned,
        "status": "assigned",
        "updated_at": datetime.now(timezone.utc),
    }


# ── Graph construction ─────────────────────────────────────────────────────────


def build_supervisor_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("classify", classify_node)
    graph.add_node("route", route_node)

    graph.set_entry_point("classify")
    graph.add_edge("classify", "route")
    graph.add_edge("route", END)

    return graph.compile()


# Module-level compiled graph — built once, reused per invocation
supervisor_graph = build_supervisor_graph()
