"""
SSH command safety filter.

Called before every command execution via the vault.
Any match → command rejected, attempt logged, ops alerted.
"""

import re
from typing import NamedTuple

# Patterns that are NEVER allowed regardless of agent or severity level.
# Ordered roughly by severity of potential damage.
FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"rm\s+-rf\s+[/~]",              "recursive delete from root/home"),
    (r"\bmkfs\b",                      "filesystem format command"),
    (r"\bdd\b.*of=/dev/",             "raw device write via dd"),
    (r">\s*/dev/sd[a-z]",             "direct block device write"),
    (r"chmod\s+[0-7]*7[0-7]*\s+/",   "world-writable permission on root path"),
    (r":\(\)\{.*?\}",                 "fork bomb"),
    (r"curl\s+[^\n]*\|\s*(ba)?sh",    "pipe URL to shell"),
    (r"wget\s+[^\n]*-O\s*-\s*\|",    "pipe wget to shell"),
    (r"\bpoweroff\b",                 "system poweroff"),
    (r"\bshutdown\b",                 "system shutdown"),
    (r"iptables\s+(-F|--flush)",      "iptables flush — would drop all firewall rules"),
]

_COMPILED = [(re.compile(pat, re.IGNORECASE | re.DOTALL), reason) for pat, reason in FORBIDDEN_PATTERNS]


class SafetyResult(NamedTuple):
    safe: bool
    reason: str


def is_safe_command(command: str) -> SafetyResult:
    """
    Check a command string against forbidden patterns.

    Returns SafetyResult(safe=True, reason="ok") if the command is allowed.
    Returns SafetyResult(safe=False, reason=<description>) if forbidden.
    """
    for compiled, reason in _COMPILED:
        if compiled.search(command):
            return SafetyResult(safe=False, reason=f"Forbidden pattern: {reason}")
    return SafetyResult(safe=True, reason="ok")
