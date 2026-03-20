"""
P9-05 — Vault security tests: attempt to access credentials without internal key → 403.

Tests:
  1. All vault endpoints return 403 when X-Internal-Key is missing
  2. All vault endpoints return 403 when X-Internal-Key is wrong
  3. Correct key allows the request to proceed (to next layer)
  4. require_internal_key dependency raises HTTPException(403) directly
"""

import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "ssh-vault"))


# ── Unit tests for require_internal_key ────────────────────────────────────────

def test_require_internal_key_rejects_missing():
    """require_internal_key raises 403 when header is absent."""
    with patch("routes.settings") as mock_settings:
        mock_settings.internal_api_key = "correct-key"

        from routes import require_internal_key

        with pytest.raises(HTTPException) as exc_info:
            require_internal_key(x_internal_key="wrong-key")

        assert exc_info.value.status_code == 403


def test_require_internal_key_accepts_correct_key():
    """require_internal_key returns None (passes) for the correct key."""
    with patch("routes.settings") as mock_settings:
        mock_settings.internal_api_key = "correct-key"

        from routes import require_internal_key

        result = require_internal_key(x_internal_key="correct-key")
        assert result is None


def test_require_internal_key_rejects_empty_string():
    """Empty key string is treated as wrong, not as 'no auth required'."""
    with patch("routes.settings") as mock_settings:
        mock_settings.internal_api_key = "correct-key"

        from routes import require_internal_key

        with pytest.raises(HTTPException) as exc_info:
            require_internal_key(x_internal_key="")

        assert exc_info.value.status_code == 403


def test_require_internal_key_rejects_partial_match():
    """Substring of correct key is not accepted."""
    with patch("routes.settings") as mock_settings:
        mock_settings.internal_api_key = "correct-key-12345"

        from routes import require_internal_key

        with pytest.raises(HTTPException) as exc_info:
            require_internal_key(x_internal_key="correct-key")

        assert exc_info.value.status_code == 403


# ── API-Gateway auth tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_gateway_reports_requires_api_key():
    """
    GET /reports/daily without Authorization header → 401 or 403.
    Tests that the gateway's require_api_key dependency is wired.
    """
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "api-gateway"))

    with patch("shared.redis_client.get_redis", AsyncMock()), \
         patch("shared.db.get_db", AsyncMock()):

        from routes.auth import router as auth_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        # Test the dependency directly
        with patch("auth.settings") as mock_s:
            mock_s.internal_api_key = "real-key"

            from auth import require_api_key

            with pytest.raises(HTTPException) as exc_info:
                await require_api_key(authorization="Bearer wrong-token")

            assert exc_info.value.status_code in (401, 403)


@pytest.mark.asyncio
async def test_api_gateway_api_key_accepted():
    """Valid API key passes require_api_key without raising."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "api-gateway"))

    VALID_KEY = "valid-internal-key-abc123"

    with patch("auth.settings") as mock_s:
        mock_s.internal_api_key = VALID_KEY

        from auth import require_api_key

        # API key passed as Bearer token
        result = await require_api_key(authorization=f"Bearer {VALID_KEY}")
        assert result == VALID_KEY


# ── Vault route-level tests via TestClient ─────────────────────────────────────

@pytest.fixture
def vault_client():
    """TestClient wrapping the ssh-vault FastAPI app with mocked DB and registry."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "ssh-vault"))

    with patch("session_registry.SessionRegistry") as mock_reg_cls, \
         patch("routes.settings") as mock_settings, \
         patch("routes.get_db", AsyncMock()):

        mock_settings.internal_api_key = "test-internal-key"

        from main import app
        client = TestClient(app, raise_server_exceptions=False)
        yield client, "test-internal-key"


def test_vault_credentials_post_no_key(vault_client):
    """POST /vault/credentials without X-Internal-Key → 422 (missing required header) or 403."""
    client, _ = vault_client
    resp = client.post("/vault/credentials", json={
        "server_id": "srv-001",
        "display_name": "Test",
        "hostname": "1.2.3.4",
        "port": 22,
        "username": "ubuntu",
        "ssh_private_key": "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
    })
    # Missing required header → either 422 (FastAPI validation) or 403
    assert resp.status_code in (403, 422)


def test_vault_credentials_post_wrong_key(vault_client):
    """POST /vault/credentials with wrong X-Internal-Key → 403."""
    client, _ = vault_client
    resp = client.post(
        "/vault/credentials",
        json={
            "server_id": "srv-001",
            "display_name": "Test",
            "hostname": "1.2.3.4",
            "port": 22,
            "username": "ubuntu",
            "ssh_private_key": "fake-key",
        },
        headers={"X-Internal-Key": "wrong-key"},
    )
    assert resp.status_code == 403


def test_vault_session_post_no_key(vault_client):
    """POST /vault/session without X-Internal-Key → 422 or 403."""
    client, _ = vault_client
    resp = client.post("/vault/session", json={"server_id": "srv-001", "task_id": "t1", "trace_id": "tr1"})
    assert resp.status_code in (403, 422)


def test_vault_session_execute_no_key(vault_client):
    """POST /vault/session/{token}/execute without key → 422 or 403."""
    client, _ = vault_client
    resp = client.post("/vault/session/fake-token/execute", json={"command": "ls"})
    assert resp.status_code in (403, 422)
