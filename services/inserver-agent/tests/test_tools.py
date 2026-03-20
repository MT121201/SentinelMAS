"""
Unit tests for tools.py — mock vault HTTP and DB calls.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tools import (
    restart_service,
    unblock_own_ip,
    dispatch_tool,
    _ALLOWED_RESTART_SERVICES,
)


class TestRestartService:
    @pytest.mark.asyncio
    async def test_allowed_service_calls_ssh(self):
        with patch("tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = {"exit_code": 0, "stdout": "", "stderr": ""}
            result = await restart_service("server-1", "token-abc", "docker")
            assert result["ok"] is True
            assert result["service"] == "docker"
            mock_ssh.assert_called_once()

    @pytest.mark.asyncio
    async def test_disallowed_service_rejected(self):
        result = await restart_service("server-1", "token-abc", "nginx")
        assert result["ok"] is False
        assert "allowed" in result["error"]

    @pytest.mark.asyncio
    async def test_all_allowed_services(self):
        for svc in _ALLOWED_RESTART_SERVICES:
            with patch("tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
                mock_ssh.return_value = {"exit_code": 0, "stdout": "", "stderr": ""}
                result = await restart_service("s1", "tok", svc)
                assert result["ok"] is True, f"Expected {svc} to be allowed"

    @pytest.mark.asyncio
    async def test_failed_restart_returns_exit_code(self):
        with patch("tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = {"exit_code": 1, "stdout": "", "stderr": "failed"}
            result = await restart_service("server-1", "token-abc", "docker")
            assert result["ok"] is False
            assert result["exit_code"] == 1


class TestUnblockOwnIp:
    @pytest.mark.asyncio
    async def test_runs_two_steps(self):
        with patch("tools.ssh_execute", new_callable=AsyncMock) as mock_ssh, \
             patch("tools._get_own_ip", return_value="10.0.0.5"):
            mock_ssh.return_value = {"exit_code": 0, "stdout": "", "stderr": ""}
            result = await unblock_own_ip("server-1", "token-abc")
            assert result["unblocked_ip"] == "10.0.0.5"
            assert len(result["steps"]) == 2
            assert mock_ssh.call_count == 2

    @pytest.mark.asyncio
    async def test_ip_used_in_commands(self):
        with patch("tools.ssh_execute", new_callable=AsyncMock) as mock_ssh, \
             patch("tools._get_own_ip", return_value="192.168.1.1"):
            mock_ssh.return_value = {"exit_code": 0}
            await unblock_own_ip("server-1", "tok")
            calls = [str(c) for c in mock_ssh.call_args_list]
            assert any("192.168.1.1" in c for c in calls)


class TestDispatchTool:
    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        db = AsyncMock()
        result = await dispatch_tool("nonexistent_tool", {}, db)
        assert "error" in result
        assert "Unknown tool" in result["error"]

    @pytest.mark.asyncio
    async def test_get_server_list_dispatched(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        db.execute = AsyncMock(return_value=mock_result)
        result = await dispatch_tool("get_server_list", {}, db)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_restart_service_dispatched(self):
        db = AsyncMock()
        with patch("tools.ssh_execute", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = {"exit_code": 0}
            result = await dispatch_tool(
                "restart_service",
                {"server_id": "1", "session_token": "tok", "service_name": "docker"},
                db,
            )
        assert "ok" in result
