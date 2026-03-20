"""Integration tests: auth flow."""

import pytest


def test_login_success(client):
    resp = client.post("/auth/token", json={"username": "admin", "password": "test-password"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 86400


def test_login_wrong_password(client):
    resp = client.post("/auth/token", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


def test_login_wrong_username(client):
    resp = client.post("/auth/token", json={"username": "hacker", "password": "test-password"})
    assert resp.status_code == 401


def test_protected_route_without_token(client):
    resp = client.post("/tickets", json={"server_id": "gpu-01", "description": "test issue here"})
    assert resp.status_code == 401


def test_protected_route_with_invalid_token(client):
    resp = client.post(
        "/tickets",
        json={"server_id": "gpu-01", "description": "test issue here"},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


def test_protected_route_with_valid_token(client, auth_headers, mock_redis):
    """Ticket submission with valid JWT should reach the handler (202)."""
    mock_redis.rpush = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock()
    resp = client.post(
        "/tickets",
        json={"server_id": "gpu-01", "description": "GPU is not responding to nvidia-smi command"},
        headers=auth_headers,
    )
    assert resp.status_code == 202


def test_api_key_required_for_ops(client):
    resp = client.get("/ops/queue")
    assert resp.status_code == 403


def test_api_key_accepted_for_ops(client, api_key_headers, mock_redis):
    mock_redis.llen = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(return_value=0)
    mock_redis.get = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(return_value=None)
    resp = client.get("/ops/queue", headers=api_key_headers)
    assert resp.status_code == 200


def test_request_id_in_response_headers(client):
    resp = client.get("/health")
    assert "x-request-id" in resp.headers
