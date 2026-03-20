"""
AgentState — canonical TypedDict shared across all agents.

This is the single source of truth for the LangGraph state schema.
Every agent service imports this (or a compatible copy) to ensure field alignment.

Matches AGENT_DESIGN.md §2 exactly.
"""

from datetime import datetime
from typing import Literal, Optional, TypedDict


class AgentState(TypedDict):
    # ── Task identity ──────────────────────────────────────────────────────
    task_id: str                       # Unique UUID for this task
    trace_id: str                      # Langfuse trace correlation ID
    task_type: Literal["ticket", "maintenance", "report", "unknown"]

    # ── Routing ────────────────────────────────────────────────────────────
    assigned_agent: Optional[str]      # "client-agent" | "inserver-agent" | "report-agent"
    severity: Optional[Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]]

    # ── Ticket fields ──────────────────────────────────────────────────────
    ticket_id: Optional[str]           # rag_kb_entries.id (stringified)
    user_message: Optional[str]        # Raw ticket description from user
    server_id: Optional[str]           # Target server for SSH operations

    # ── Agent working memory ───────────────────────────────────────────────
    rag_hits: list[dict]               # [{pattern, fix_steps, confidence, rerank_score}]
    web_search_results: list[dict]     # [{title, snippet, url}]
    action_plan: list[str]             # Ordered steps agent will execute
    execution_log: list[dict]          # [{command, output, success, timestamp}]

    # ── Resolution ─────────────────────────────────────────────────────────
    status: Literal[
        "queued",
        "assigned",
        "thinking",
        "executing",
        "verifying",
        "done",
        "failed",
        "escalated",
    ]
    resolution_summary: Optional[str]  # Final plain-language answer to user
    error: Optional[str]               # Error message if status == "failed"

    # ── Timestamps ─────────────────────────────────────────────────────────
    created_at: datetime
    updated_at: datetime
