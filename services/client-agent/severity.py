"""
LLM-based ticket severity classifier.

Returns: LOW | MEDIUM | HIGH | CRITICAL
Falls back to MEDIUM on parse error.
"""

import json
import logging
from typing import Literal

import anthropic

from config import settings
from prompts import SEVERITY_SYSTEM_PROMPT

log = logging.getLogger(__name__)

SeverityLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def classify_severity(ticket_text: str) -> tuple[SeverityLevel, str]:
    """
    Classify ticket severity using Claude.

    Returns (severity_level, reason).
    Falls back to ("MEDIUM", "classification failed") on any error.
    """
    client = _get_client()
    try:
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=128,
            system=SEVERITY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": ticket_text}],
        )
        raw = response.content[0].text.strip()
        data = json.loads(raw)
        level = data.get("severity", "MEDIUM").upper()
        if level not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            level = "MEDIUM"
        reason = data.get("reason", "")
        return level, reason  # type: ignore[return-value]
    except Exception as exc:
        log.warning("severity classification failed: %s — defaulting to MEDIUM", exc)
        return "MEDIUM", "classification failed"
