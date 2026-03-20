"""
RAG-specific sanitiser — strips PII from error patterns and fix steps
before they are stored in the knowledge base.

More aggressive than the api-gateway log sanitiser:
KB entries must contain zero identifiable infrastructure data.
"""

import re

_RULES: list[tuple[re.Pattern, str]] = [
    # IPv4 and IPv6
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP]"),
    (re.compile(r"\b([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"), "[IPv6]"),
    # Hostnames / server names (e.g. gpu-node-03.company.com)
    (re.compile(r"\b[\w-]+\.(internal|local|company\.com|corp)\b", re.IGNORECASE), "[HOST]"),
    # Usernames in paths
    (re.compile(r"/home/\w+"), "/home/[USER]"),
    (re.compile(r"/root"), "/[ROOT]"),
    (re.compile(r"/users/\w+", re.IGNORECASE), "/users/[USER]"),
    # Credentials patterns
    (re.compile(r"(?i)(password|passwd|secret|token|apikey|api_key)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    # PEM / SSH key blocks
    (re.compile(r"-----BEGIN [A-Z ]+-----[\s\S]+?-----END [A-Z ]+-----"), "[KEY_REDACTED]"),
    # UUIDs that might identify specific resources
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE), "[UUID]"),
    # Specific numeric IDs that look like resource IDs (> 6 digits)
    (re.compile(r"\b\d{7,}\b"), "[ID]"),
]

_MAX_LEN = 2000


def sanitise_pattern(text: str) -> str:
    """Strip PII from an error pattern before KB storage. Truncate to 2000 chars."""
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text[:_MAX_LEN].strip()


def sanitise_fix_steps(text: str) -> str:
    """Strip PII from fix steps. Same rules — fix steps may contain server-specific paths."""
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text[:_MAX_LEN].strip()
