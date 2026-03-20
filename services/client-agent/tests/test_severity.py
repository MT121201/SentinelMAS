"""Tests for severity classifier."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestClassifySeverity:
    @pytest.mark.asyncio
    async def test_returns_valid_level(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"severity": "HIGH", "reason": "Server unreachable"}')]
        with patch("severity._get_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_fn.return_value = mock_client
            from severity import classify_severity
            level, reason = await classify_severity("SSH connection refused on GPU server")
        assert level == "HIGH"
        assert "unreachable" in reason.lower()

    @pytest.mark.asyncio
    async def test_falls_back_on_invalid_json(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="not json at all")]
        with patch("severity._get_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_fn.return_value = mock_client
            from severity import classify_severity
            level, reason = await classify_severity("some ticket text")
        assert level == "MEDIUM"

    @pytest.mark.asyncio
    async def test_falls_back_on_api_error(self):
        with patch("severity._get_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(side_effect=Exception("API error"))
            mock_client_fn.return_value = mock_client
            from severity import classify_severity
            level, reason = await classify_severity("ticket text")
        assert level == "MEDIUM"

    @pytest.mark.asyncio
    async def test_all_valid_levels_accepted(self):
        for expected_level in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text=f'{{"severity": "{expected_level}", "reason": "test"}}')]
            with patch("severity._get_client") as mock_client_fn:
                mock_client = MagicMock()
                mock_client.messages.create = AsyncMock(return_value=mock_response)
                mock_client_fn.return_value = mock_client
                from severity import classify_severity
                level, _ = await classify_severity("test ticket")
            assert level == expected_level

    @pytest.mark.asyncio
    async def test_invalid_level_defaults_to_medium(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"severity": "EXTREME", "reason": "made up level"}')]
        with patch("severity._get_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_client_fn.return_value = mock_client
            from severity import classify_severity
            level, _ = await classify_severity("test")
        assert level == "MEDIUM"
