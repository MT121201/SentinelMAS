"""
Structured JSON logger factory — shared across all GPU-MAS services.

Usage:
    from shared.logger import get_logger
    log = get_logger("my-service", service="my-service")

    # With bound context (preferred inside agent/task loops):
    log = log.bind(trace_id="abc123", agent_id="client-1", ticket_id="t-xyz")
    log.info("processing_ticket", server_id="srv-01")

Output (JSON to stdout):
    {"level": "info", "event": "processing_ticket", "service": "client-agent",
     "trace_id": "abc123", "agent_id": "client-1", "ticket_id": "t-xyz",
     "server_id": "srv-01", "timestamp": "2026-03-20T08:01:23.456Z"}
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(log_level: str = "INFO") -> None:
    """
    Call once at application startup (main.py / lifespan).
    Sets up structlog with JSON renderer + stdlib integration.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Stdlib logging → structlog bridge (catches library logs too)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str, **initial_context: Any) -> structlog.BoundLogger:
    """
    Return a structlog BoundLogger pre-bound with the given context fields.

    Recommended fields:
        service    — service name (e.g. "client-agent")
        agent_id   — agent instance identifier
        trace_id   — Langfuse trace ID (bind per task, not globally)
    """
    return structlog.get_logger(name).bind(**initial_context)


def bind_trace_context(
    trace_id: str = "",
    agent_id: str = "",
    task_id: str = "",
    ticket_id: str = "",
) -> None:
    """
    Bind trace context into structlog's contextvars store.
    Context is automatically cleared at the end of each asyncio task
    if you call `structlog.contextvars.clear_contextvars()`.

    Typically called at the start of each task/request:
        bind_trace_context(trace_id=state["trace_id"], agent_id="client-1")
    """
    ctx: dict[str, str] = {}
    if trace_id:
        ctx["trace_id"] = trace_id
    if agent_id:
        ctx["agent_id"] = agent_id
    if task_id:
        ctx["task_id"] = task_id
    if ticket_id:
        ctx["ticket_id"] = ticket_id
    structlog.contextvars.bind_contextvars(**ctx)


def clear_trace_context() -> None:
    """Clear all bound context vars. Call at end of each task."""
    structlog.contextvars.clear_contextvars()
