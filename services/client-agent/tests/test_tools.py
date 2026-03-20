"""Tests for tools.py — mock HTTP calls to vault, RAG, and web."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestRagSearch:
    @pytest.mark.asyncio
    async def test_returns_results_on_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": [{"kb_entry_id": 1}], "cache_hit": False, "total": 1}
        mock_resp.raise_for_status = MagicMock()
        with patch("tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client
            from tools import rag_search
            result = await rag_search("CUDA memory error")
        assert result["total"] == 1
        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_on_failure(self):
        with patch("tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
            mock_cls.return_value = mock_client
            from tools import rag_search
            result = await rag_search("something")
        assert result["results"] == []
        assert "error" in result


class TestSshExecute:
    @pytest.mark.asyncio
    async def test_passes_command_to_vault(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"stdout": "ok", "stderr": "", "exit_code": 0}
        mock_resp.raise_for_status = MagicMock()
        with patch("tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client
            from tools import ssh_execute
            result = await ssh_execute("server-1", "nvidia-smi", "tok-abc")
        assert result["exit_code"] == 0
        assert result["stdout"] == "ok"


class TestStoreFixPattern:
    @pytest.mark.asyncio
    async def test_posts_to_rag_ingest(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"kb_entry_id": 10, "embedding_id": "uuid"}
        mock_resp.raise_for_status = MagicMock()
        with patch("tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client
            from tools import store_fix_pattern
            result = await store_fix_pattern(
                error_pattern="CUDA out of memory during training",
                fix_steps="Reduce batch size and call torch.cuda.empty_cache()",
                tags=["cuda", "memory"],
                confidence=0.9,
            )
        assert result["kb_entry_id"] == 10

    @pytest.mark.asyncio
    async def test_returns_error_on_failure(self):
        with patch("tools.httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=Exception("rag down"))
            mock_cls.return_value = mock_client
            from tools import store_fix_pattern
            result = await store_fix_pattern("pattern", "fix")
        assert result["stored"] is False


class TestDispatchTool:
    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        db = AsyncMock()
        from tools import dispatch_tool
        result = await dispatch_tool("does_not_exist", {}, db)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_log_action_dispatched(self):
        db = AsyncMock()
        from tools import dispatch_tool
        result = await dispatch_tool(
            "log_action",
            {"action": "planned_fix", "server_id": "s1", "reason": "disk full"},
            db,
        )
        assert result["logged"] is True

    @pytest.mark.asyncio
    async def test_web_search_dispatched(self):
        with patch("tools._web_search", new_callable=AsyncMock) as mock_ws:
            mock_ws.return_value = [{"title": "fix", "snippet": "do this", "url": "http://x"}]
            db = AsyncMock()
            from tools import dispatch_tool
            result = await dispatch_tool("web_search", {"query": "CUDA error"}, db)
        assert result["count"] == 1


class TestUpdateTicketStatus:
    @pytest.mark.asyncio
    async def test_executes_update(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        from tools import update_ticket_status
        result = await update_ticket_status("42", "done", "Issue resolved", db)
        assert result["updated"] is True
        db.execute.assert_called_once()
        db.commit.assert_called_once()
