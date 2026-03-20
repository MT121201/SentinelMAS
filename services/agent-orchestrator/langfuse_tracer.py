"""
Langfuse tracing wrapper.

Wraps Anthropic LLM calls with Langfuse traces for full LLMOps observability.
Degrades gracefully (no-op) when Langfuse keys are not set — agents still work.

Phase 8 will configure the Langfuse self-hosted instance. Until then, tracing
is silently disabled if LANGFUSE_PUBLIC_KEY is empty.
"""

import logging
from functools import wraps
from typing import Any, Callable

from config import settings

log = logging.getLogger(__name__)

_langfuse = None
_enabled = False


def _try_init() -> None:
    global _langfuse, _enabled
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        log.info("langfuse keys not set — tracing disabled")
        return
    try:
        from langfuse import Langfuse
        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        _enabled = True
        log.info("langfuse tracing enabled → %s", settings.langfuse_host)
    except ImportError:
        log.warning("langfuse package not installed — tracing disabled")


def init_tracer() -> None:
    """Call once at startup (from main.py lifespan)."""
    _try_init()


def get_langfuse():
    """Return Langfuse client or None if not enabled."""
    return _langfuse if _enabled else None


def create_trace(name: str, task_id: str, trace_id: str, metadata: dict | None = None):
    """
    Create a Langfuse trace for a task execution.
    Returns trace object or a no-op stub.
    """
    if not _enabled or _langfuse is None:
        return _NoOpTrace()
    try:
        return _langfuse.trace(
            name=name,
            id=trace_id,
            metadata={"task_id": task_id, **(metadata or {})},
        )
    except Exception as exc:
        log.warning("langfuse trace creation failed: %s", exc)
        return _NoOpTrace()


def record_llm_call(
    trace,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    name: str = "llm_call",
) -> None:
    """Record token usage on a trace span."""
    if not _enabled or isinstance(trace, _NoOpTrace):
        return
    try:
        trace.generation(
            name=name,
            model=model,
            usage={
                "input": prompt_tokens,
                "output": completion_tokens,
                "total": prompt_tokens + completion_tokens,
            },
        )
    except Exception as exc:
        log.warning("langfuse generation record failed: %s", exc)


def flush() -> None:
    """Flush pending events to Langfuse. Call on shutdown."""
    if _enabled and _langfuse:
        try:
            _langfuse.flush()
        except Exception:
            pass


class _NoOpTrace:
    """Stub returned when Langfuse is disabled — all methods are no-ops."""

    def generation(self, **kwargs): return self
    def span(self, **kwargs): return self
    def score(self, **kwargs): return self
    def update(self, **kwargs): return self
    def end(self, **kwargs): return self
