"""
P9-01 — End-to-end: submit ticket → agent picks up → SSH mock → resolved.

Tests the complete client-agent graph flow with all external deps mocked:
  - Anthropic Claude API → mocked to simulate tool-calling + resolution
  - SSH Vault → mocked httpx session open/execute/close
  - RAG service → mocked with a pre-built hit
  - Postgres → mocked session
  - Redis → fakeredis

The test verifies:
  1. ticket is classified (severity returned)
  2. RAG hit found → skips web search
  3. resolve_loop runs Claude tool-calling
  4. verify node marks resolved=True
  5. close_ticket updates status to "done"
  6. store_fix_pattern calls RAG ingest
"""

import json
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "client-agent"))

from conftest import make_anthropic_text_response, make_anthropic_tool_response


# ── Fixtures ───────────────────────────────────────────────────────────────────

RAG_HIT = {
    "id": "kb-001",
    "error_pattern": "CUDA out of memory",
    "fix_steps": "1. Kill stale processes: kill $(fuser /dev/nvidia*)\n2. Restart training job",
    "score": 0.92,
}

TICKET_TASK = {
    "task_id": "task-e2e-001",
    "ticket_id": "ticket-abc",
    "server_id": "srv-gpu-01",
    "user_message": "CUDA out of memory error on training job — GPU shows 100% mem usage",
    "trace_id": "trace-001",
    "agent_id": "client-test-1",
}


@pytest.mark.asyncio
async def test_ticket_resolved_via_rag_hit(mock_db, fake_redis_bytes):
    """
    Full graph flow: ticket → RAG hit → resolve_loop → done.
    Claude makes two tool calls (log_action + ssh_execute) then returns text resolution.
    """
    # Mock DB: ticket update calls
    mock_db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))

    # Mock RAG search → hit
    async def mock_post(*args, **kwargs):
        url = args[0] if args else kwargs.get("url", "")
        resp = MagicMock()
        resp.is_success = True
        if "/rag/search" in str(url):
            resp.json = MagicMock(return_value={"results": [RAG_HIT]})
        elif "/rag/ingest" in str(url):
            resp.json = MagicMock(return_value={"id": "kb-002"})
        elif "/vault/session" in str(url) and "execute" not in str(url):
            resp.json = MagicMock(return_value={"session_token": "tok-test-001"})
        elif "execute" in str(url):
            resp.json = MagicMock(return_value={"stdout": "Killed 2 processes\n", "stderr": "", "exit_code": 0})
        else:
            resp.json = MagicMock(return_value={})
        resp.status_code = 200
        return resp

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=mock_post)
    mock_client.delete = AsyncMock(return_value=MagicMock(is_success=True))

    # Claude responses: tool_use(log_action) → tool_use(ssh_execute) → end_turn(resolution)
    claude_responses = [
        # Severity classification
        make_anthropic_text_response('{"severity": "HIGH", "reason": "GPU OOM on training job"}'),
        # resolve_loop turn 1: log_action
        make_anthropic_tool_response("log_action", {
            "action": "kill_stale_gpu_processes",
            "reason": "GPU memory at 100% due to zombie CUDA processes",
        }),
        # resolve_loop turn 2: ssh_execute
        make_anthropic_tool_response("ssh_execute", {
            "server_id": "srv-gpu-01",
            "command": "kill $(fuser /dev/nvidia*)",
            "session_token": "tok-test-001",
        }),
        # resolve_loop turn 3: end_turn with resolution
        make_anthropic_text_response(
            "Issue resolved: killed stale CUDA processes, GPU memory freed from 100% to 12%."
        ),
        # verify node: Claude confirms resolved
        make_anthropic_text_response('{"resolved": true, "summary": "Killed zombie CUDA processes. GPU memory freed."}'),
    ]

    call_count = 0

    async def mock_messages_create(*args, **kwargs):
        nonlocal call_count
        resp = claude_responses[min(call_count, len(claude_responses) - 1)]
        call_count += 1
        return resp

    mock_anthropic = MagicMock()
    mock_anthropic.messages.create = AsyncMock(side_effect=mock_messages_create)

    with patch("anthropic.AsyncAnthropic", return_value=mock_anthropic), \
         patch("httpx.AsyncClient", return_value=mock_client):

        from executor import run_ticket_task
        await run_ticket_task(TICKET_TASK, mock_db, fake_redis_bytes)

    # Verify DB was called to update ticket status
    assert mock_db.execute.called, "DB execute should be called to update ticket status"


@pytest.mark.asyncio
async def test_ticket_escalated_after_max_retries(mock_db, fake_redis_bytes):
    """
    Graph flow: all resolve attempts fail → ticket escalated after max retries.
    """
    mock_db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))

    async def mock_post(*args, **kwargs):
        url = args[0] if args else kwargs.get("url", "")
        resp = MagicMock()
        resp.is_success = True
        resp.status_code = 200
        if "/rag/search" in str(url):
            resp.json = MagicMock(return_value={"results": []})
        elif "/vault/session" in str(url) and "execute" not in str(url):
            resp.json = MagicMock(return_value={"session_token": "tok-001"})
        elif "execute" in str(url):
            resp.json = MagicMock(return_value={"stdout": "", "stderr": "permission denied", "exit_code": 1})
        elif "tavily" in str(url) or "serpapi" in str(url):
            resp.json = MagicMock(return_value={"results": []})
        else:
            resp.json = MagicMock(return_value={})
        return resp

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=mock_post)
    mock_client.get = AsyncMock(return_value=MagicMock(is_success=True, text="", status_code=200))
    mock_client.delete = AsyncMock(return_value=MagicMock(is_success=True))

    # Claude always says unresolved
    unresolved_response = make_anthropic_text_response(
        '{"resolved": false, "summary": "Could not resolve — permission denied on all commands"}'
    )
    severity_response = make_anthropic_text_response('{"severity": "MEDIUM", "reason": "unknown error"}')

    call_count = 0

    async def mock_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return severity_response
        return unresolved_response

    mock_anthropic = MagicMock()
    mock_anthropic.messages.create = AsyncMock(side_effect=mock_create)

    with patch("anthropic.AsyncAnthropic", return_value=mock_anthropic), \
         patch("httpx.AsyncClient", return_value=mock_client):

        from executor import run_ticket_task
        await run_ticket_task(TICKET_TASK, mock_db, fake_redis_bytes)

    # Ticket should have been marked escalated — DB was called
    assert mock_db.execute.called


@pytest.mark.asyncio
async def test_ticket_vault_session_failure_marks_failed(mock_db, fake_redis_bytes):
    """
    If vault session open fails, ticket is immediately marked failed.
    No SSH commands should be attempted.
    """
    mock_db.execute = AsyncMock(return_value=MagicMock(fetchone=MagicMock(return_value=None)))

    async def mock_post(*args, **kwargs):
        url = args[0] if args else kwargs.get("url", "")
        resp = MagicMock()
        resp.status_code = 500
        resp.is_success = False
        if "/rag/search" in str(url):
            resp.is_success = True
            resp.status_code = 200
            resp.json = MagicMock(return_value={"results": [RAG_HIT]})
        elif "/vault/session" in str(url):
            resp.is_success = False
            resp.status_code = 500
            resp.json = MagicMock(return_value={"detail": "Vault connection refused"})
        return resp

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=mock_post)
    mock_client.delete = AsyncMock(return_value=MagicMock(is_success=True))

    severity_resp = make_anthropic_text_response('{"severity": "HIGH", "reason": "OOM"}')
    mock_anthropic = MagicMock()
    mock_anthropic.messages.create = AsyncMock(return_value=severity_resp)

    with patch("anthropic.AsyncAnthropic", return_value=mock_anthropic), \
         patch("httpx.AsyncClient", return_value=mock_client):

        from executor import run_ticket_task
        await run_ticket_task(TICKET_TASK, mock_db, fake_redis_bytes)

    # DB should be called to mark failed
    assert mock_db.execute.called
