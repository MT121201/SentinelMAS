"""
In-process SSH session registry.

Stores active paramiko.SSHClient instances keyed by opaque session tokens.
Sessions are auto-evicted after TTL seconds by a background asyncio task.

IMPORTANT: SSH key material lives here only transiently — it is decrypted
from the vault DB to open the paramiko connection, then the plaintext key
is zeroed from memory (best-effort). The SSHClient itself holds the
connection; no key bytes are stored in this registry.
"""

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional

import paramiko

from safety import is_safe_command

logger = logging.getLogger(__name__)


@dataclass
class _Session:
    token: str
    server_id: str
    agent_id: str
    trace_id: str
    client: paramiko.SSHClient
    expires_at: float  # unix timestamp
    created_at: float = field(default_factory=time.time)


class SessionRegistry:
    """Thread-safe (within asyncio event loop) session store with TTL eviction."""

    def __init__(self, default_ttl: int = 300) -> None:
        self._sessions: dict[str, _Session] = {}
        self._default_ttl = default_ttl
        self._eviction_task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Start the background TTL eviction loop. Call once on app startup."""
        self._eviction_task = asyncio.create_task(self._eviction_loop())

    async def stop(self) -> None:
        """Cancel eviction loop and close all open sessions. Call on shutdown."""
        if self._eviction_task:
            self._eviction_task.cancel()
        for token in list(self._sessions.keys()):
            self._close(token)

    def create(
        self,
        server_id: str,
        agent_id: str,
        trace_id: str,
        client: paramiko.SSHClient,
        ttl: Optional[int] = None,
    ) -> str:
        """Register a new SSHClient and return an opaque session token."""
        token = secrets.token_urlsafe(32)
        ttl = ttl or self._default_ttl
        self._sessions[token] = _Session(
            token=token,
            server_id=server_id,
            agent_id=agent_id,
            trace_id=trace_id,
            client=client,
            expires_at=time.time() + ttl,
        )
        logger.info("session created token=*** server=%s agent=%s ttl=%ds", server_id, agent_id, ttl)
        return token

    def execute(self, token: str, command: str, timeout: int = 30) -> dict:
        """
        Run a command on the session's SSH connection.

        Returns: {stdout, stderr, exit_code, duration_ms}
        Raises: KeyError if token not found or expired.
                ValueError if command fails safety check.
        """
        session = self._get_or_raise(token)

        safety = is_safe_command(command)
        if not safety.safe:
            logger.warning(
                "SAFETY BLOCK server=%s agent=%s trace=%s reason=%s",
                session.server_id, session.agent_id, session.trace_id, safety.reason,
            )
            raise ValueError(f"Command blocked by safety filter: {safety.reason}")

        logger.info(
            "ssh_execute server=%s agent=%s trace=%s cmd_hash=%s",
            session.server_id, session.agent_id, session.trace_id, hash(command),
        )

        start = time.monotonic()
        stdin, stdout, stderr = session.client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        duration_ms = int((time.monotonic() - start) * 1000)

        return {
            "stdout": stdout.read().decode("utf-8", errors="replace"),
            "stderr": stderr.read().decode("utf-8", errors="replace"),
            "exit_code": exit_code,
            "duration_ms": duration_ms,
        }

    def close(self, token: str) -> None:
        """Explicitly close a session."""
        self._close(token)

    def _get_or_raise(self, token: str) -> _Session:
        session = self._sessions.get(token)
        if session is None:
            raise KeyError(f"Session token not found or already expired")
        if time.time() > session.expires_at:
            self._close(token)
            raise KeyError(f"Session token expired")
        return session

    def _close(self, token: str) -> None:
        session = self._sessions.pop(token, None)
        if session:
            try:
                session.client.close()
            except Exception:
                pass
            logger.info("session closed server=%s agent=%s", session.server_id, session.agent_id)

    async def _eviction_loop(self) -> None:
        """Background task: check for expired sessions every 30 seconds."""
        while True:
            await asyncio.sleep(30)
            now = time.time()
            expired = [t for t, s in self._sessions.items() if now > s.expires_at]
            for token in expired:
                logger.info("evicting expired session token=*** server=%s", self._sessions[token].server_id)
                self._close(token)


# Module-level singleton — created in main.py on startup
registry: Optional[SessionRegistry] = None


def get_registry() -> SessionRegistry:
    if registry is None:
        raise RuntimeError("SessionRegistry not initialised — call startup first")
    return registry
