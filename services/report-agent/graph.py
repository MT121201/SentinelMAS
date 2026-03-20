"""
LangGraph for the Report Agent.

Three-node pipeline:
    aggregate_node → format_node → send_node

State carries the aggregated data dict and the final rendered markdown.
The graph is intentionally simple — no LLM call required; Claude is used
only if the orchestrator explicitly requests a narrative summary (future).
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from aggregator import aggregate_daily, aggregate_weekly
from formatter import format_daily_report, format_weekly_report
from sender import deliver_report

log = logging.getLogger(__name__)


# ── State ──────────────────────────────────────────────────────────────────────


class ReportState(TypedDict, total=False):
    # Inputs (set before invoking)
    task_id: str
    period: str          # "daily" | "weekly"
    report_date: str     # ISO date string (daily only), optional

    # Intermediate
    aggregated_data: dict[str, Any]
    report_text: str

    # Output
    status: str          # "done" | "failed"
    delivery_result: dict[str, bool]
    error: str


# ── Nodes ──────────────────────────────────────────────────────────────────────


async def aggregate_node(state: ReportState, config: dict) -> ReportState:
    """Fetch all data from Postgres + Redis."""
    db = config["configurable"]["db"]
    redis = config["configurable"]["redis"]
    period = state.get("period", "daily")

    try:
        if period == "weekly":
            data = await aggregate_weekly(db, redis)
        else:
            from datetime import date as _date
            raw_date = state.get("report_date")
            report_date = _date.fromisoformat(raw_date) if raw_date else None
            data = await aggregate_daily(db, redis, report_date)

        log.info(
            "aggregate_node: period=%s task_id=%s fleet_count=%s",
            period,
            state.get("task_id"),
            len(data.get("fleet", data.get("fleet_range", {}))),
        )
        return {**state, "aggregated_data": data}
    except Exception as exc:
        log.error("aggregate_node: failed: %s", exc)
        return {**state, "status": "failed", "error": str(exc)}


async def format_node(state: ReportState, config: dict) -> ReportState:
    """Render aggregated data to markdown."""
    if state.get("status") == "failed":
        return state

    data = state.get("aggregated_data", {})
    period = state.get("period", "daily")

    try:
        if period == "weekly":
            text = format_weekly_report(data)
        else:
            text = format_daily_report(data)

        log.info(
            "format_node: rendered %d chars for period=%s task_id=%s",
            len(text),
            period,
            state.get("task_id"),
        )
        return {**state, "report_text": text}
    except Exception as exc:
        log.error("format_node: failed: %s", exc)
        return {**state, "status": "failed", "error": str(exc)}


async def send_node(state: ReportState, config: dict) -> ReportState:
    """Deliver the report via configured channels."""
    if state.get("status") == "failed":
        return state

    period = state.get("period", "daily").capitalize()
    report_date = state.get("report_date") or state.get("aggregated_data", {}).get("date", "")
    date_range = state.get("aggregated_data", {}).get("date_range", "")

    subject = (
        f"SentinelMAS Weekly Report — {date_range}"
        if period == "Weekly"
        else f"SentinelMAS Daily Report — {report_date}"
    )

    report_text = state.get("report_text", "")
    try:
        result = await deliver_report(report_text, subject=subject)
        log.info(
            "send_node: task_id=%s delivery=%s",
            state.get("task_id"),
            result,
        )
        return {**state, "status": "done", "delivery_result": result}
    except Exception as exc:
        log.error("send_node: failed: %s", exc)
        return {**state, "status": "failed", "error": str(exc)}


# ── Graph ──────────────────────────────────────────────────────────────────────


def _should_continue(state: ReportState) -> str:
    return "failed" if state.get("status") == "failed" else "ok"


def build_report_graph() -> Any:
    g = StateGraph(ReportState)

    g.add_node("aggregate", aggregate_node)
    g.add_node("format", format_node)
    g.add_node("send", send_node)

    g.set_entry_point("aggregate")
    g.add_edge("aggregate", "format")
    g.add_edge("format", "send")
    g.add_edge("send", END)

    return g.compile()


report_graph = build_report_graph()
