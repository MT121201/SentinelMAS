"""Tests for hard_restart — double-log confirmation and fallback logic."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestHardRestart:
    @pytest.mark.asyncio
    async def test_bmc_stub_falls_back_to_ssh(self):
        """BMC is always a stub — must fall back to SSH reboot."""
        with patch("hard_restart._try_ssh_reboot", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = {"exit_code": 0, "stdout": "", "stderr": "read timeout (server rebooted)"}
            from hard_restart import hard_restart
            result = await hard_restart(
                server_id="server-42",
                session_token="tok-abc",
                reason="Server completely unresponsive",
                agent_id="client-agent",
                trace_id="trace-123",
            )
        assert result["method"] == "ssh_reboot_f"
        assert result["success"] is True
        assert result["server_id"] == "server-42"
        mock_ssh.assert_called_once_with("server-42", "tok-abc")

    @pytest.mark.asyncio
    async def test_result_includes_reason(self):
        with patch("hard_restart._try_ssh_reboot", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = {"exit_code": 0}
            from hard_restart import hard_restart
            result = await hard_restart("s1", "tok", "all GPUs dead", "agent", "trace")
        assert result["reason"] == "all GPUs dead"

    @pytest.mark.asyncio
    async def test_result_includes_timestamp(self):
        with patch("hard_restart._try_ssh_reboot", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = {"exit_code": 0}
            from hard_restart import hard_restart
            result = await hard_restart("s1", "tok", "reason", "agent", "trace")
        assert "timestamp" in result
        assert "T" in result["timestamp"]  # ISO format check

    @pytest.mark.asyncio
    async def test_ssh_read_timeout_treated_as_success(self):
        """ReadTimeout means the server rebooted — this is the expected happy path."""
        import httpx
        with patch("hard_restart.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
            mock_client_cls.return_value = mock_client

            from hard_restart import _try_ssh_reboot
            result = await _try_ssh_reboot("server-1", "tok")
        assert result["exit_code"] == 0
        assert "rebooted" in result["stderr"]

    @pytest.mark.asyncio
    async def test_bmc_always_returns_not_configured(self):
        from hard_restart import _try_bmc_restart
        result = await _try_bmc_restart("any-server")
        assert result["success"] is False
        assert "not configured" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_second_confirmation_log_emitted(self, caplog):
        """Verify the second confirmation log is emitted with HARD_RESTART CONFIRMED."""
        import logging
        with patch("hard_restart._try_ssh_reboot", new_callable=AsyncMock) as mock_ssh:
            mock_ssh.return_value = {"exit_code": 0}
            with caplog.at_level(logging.WARNING, logger="hard_restart"):
                from hard_restart import hard_restart
                await hard_restart("srv-1", "tok", "test reason", "agent-1", "trace-1")
        assert any("HARD_RESTART CONFIRMED" in r.message for r in caplog.records)
