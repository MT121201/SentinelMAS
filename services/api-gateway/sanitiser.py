"""
Input sanitisation for user-supplied text.

sanitise_ticket_input() — cleans ticket descriptions before storage + agent use.
sanitise_log()          — strips sensitive data from agent logs before returning to users.

Based on SECURITY.md §5.1 and §5.3.
"""

import re


# ── Ticket input ──────────────────────────────────────────────────────────────

_PROMPT_INJECTION_PATTERNS = [
    re.compile(r"<\|.*?\|>", re.DOTALL),                                      # <|system|> style tokens
    re.compile(r"###\s*(System|Assistant|Human|User)\s*:", re.IGNORECASE),    # role markers
    re.compile(r"\[INST\]|\[/INST\]"),                                        # Llama-style tags
    re.compile(r"<s>|</s>"),                                                  # BOS/EOS tokens
]

_HTML_TAG = re.compile(r"<[^>]+>")
_MAX_TICKET_LEN = 4000


def sanitise_ticket_input(text: str) -> str:
    """
    Sanitise user-supplied ticket description:
    1. Strip HTML tags
    2. Remove prompt-injection markers
    3. Truncate to max length
    4. Strip surrounding whitespace
    """
    # Strip HTML
    text = _HTML_TAG.sub("", text)

    # Remove prompt injection markers
    for pattern in _PROMPT_INJECTION_PATTERNS:
        text = pattern.sub("", text)

    # Truncate
    text = text[:_MAX_TICKET_LEN]

    return text.strip()


# ── Log output ────────────────────────────────────────────────────────────────

_LOG_SANITISE_RULES: list[tuple[re.Pattern, str]] = [
    # IPv4 addresses
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP_REDACTED]"),
    # Passwords / secrets in key=value form
    (re.compile(r"(?i)(password|passwd|secret|token|key|apikey)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    # PEM key blocks
    (re.compile(r"-----BEGIN [A-Z ]+-----[\s\S]+?-----END [A-Z ]+-----"), "[KEY_REDACTED]"),
    # Home directories
    (re.compile(r"/home/\w+"), "/home/[USER]"),
    (re.compile(r"/root"), "/[ROOT]"),
    # Internal hostnames (e.g. gpu-node-01.internal)
    (re.compile(r"\b[\w-]+\.internal\b"), "[HOST_REDACTED]"),
]


def sanitise_log(text: str) -> str:
    """
    Strip sensitive data from agent execution logs before returning to users.
    Applied to resolution_summary and any log entries shown via /tickets/{id}/log.
    """
    for pattern, replacement in _LOG_SANITISE_RULES:
        text = pattern.sub(replacement, text)
    return text
