"""
Unit tests: SessionRegistry — create/execute/close lifecycle.
Mocks paramiko.SSHClient so no real SSH connection is needed.
"""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest
from session_registry import SessionRegistry


@pytest.fixture
def registry():
    return SessionRegistry(default_ttl=300)


def make_mock_client(stdout_data="ok\n", stderr_data="", exit_code=0):
    """Build a mock paramiko.SSHClient with a controllable exec_command."""
    channel = MagicMock()
    channel.recv_exit_status.return_value = exit_code

    stdout = MagicMock()
    stdout.channel = channel
    stdout.read.return_value = stdout_data.encode()

    stderr = MagicMock()
    stderr.read.return_value = stderr_data.encode()

    client = MagicMock()
    client.exec_command.return_value = (MagicMock(), stdout, stderr)
    return client


# ── Create ────────────────────────────────────────────────────────────────────

def test_create_returns_token(registry):
    client = make_mock_client()
    token = registry.create("srv-1", "agent-1", "trace-1", client)
    assert isinstance(token, str)
    assert len(token) > 20


def test_create_stores_session(registry):
    client = make_mock_client()
    token = registry.create("srv-1", "agent-1", "trace-1", client)
    assert token in registry._sessions
    assert registry._sessions[token].server_id == "srv-1"


# ── Execute ───────────────────────────────────────────────────────────────────

def test_execute_returns_result(registry):
    client = make_mock_client(stdout_data="GPU OK\n")
    token = registry.create("srv-1", "agent-1", "trace-1", client)
    result = registry.execute(token, "nvidia-smi")
    assert result["stdout"] == "GPU OK\n"
    assert result["exit_code"] == 0
    assert "duration_ms" in result


def test_execute_nonzero_exit_code(registry):
    client = make_mock_client(stdout_data="", stderr_data="not found", exit_code=127)
    token = registry.create("srv-1", "agent-1", "trace-1", client)
    result = registry.execute(token, "nonexistent-cmd")
    assert result["exit_code"] == 127
    assert "not found" in result["stderr"]


def test_execute_blocked_by_safety_filter(registry):
    client = make_mock_client()
    token = registry.create("srv-1", "agent-1", "trace-1", client)
    with pytest.raises(ValueError, match="safety filter"):
        registry.execute(token, "rm -rf /")
    client.exec_command.assert_not_called()


def test_execute_invalid_token_raises(registry):
    with pytest.raises(KeyError):
        registry.execute("nonexistent-token", "ls")


# ── Close ─────────────────────────────────────────────────────────────────────

def test_close_removes_session(registry):
    client = make_mock_client()
    token = registry.create("srv-1", "agent-1", "trace-1", client)
    registry.close(token)
    assert token not in registry._sessions
    client.close.assert_called_once()


def test_execute_after_close_raises(registry):
    client = make_mock_client()
    token = registry.create("srv-1", "agent-1", "trace-1", client)
    registry.close(token)
    with pytest.raises(KeyError):
        registry.execute(token, "ls")


# ── TTL ───────────────────────────────────────────────────────────────────────

def test_expired_session_raises(registry):
    client = make_mock_client()
    token = registry.create("srv-1", "agent-1", "trace-1", client, ttl=1)
    # Manually expire the session
    registry._sessions[token].expires_at = time.time() - 1
    with pytest.raises(KeyError, match="expired"):
        registry.execute(token, "ls")
