"""
Test configuration for api-gateway.

Uses FastAPI TestClient with mocked DB and Redis dependencies so tests
run without a running Postgres or Redis instance.
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from passlib.context import CryptContext

# Path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Env vars must be set before importing app modules
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-min-32-chars-long!!")
os.environ.setdefault("INTERNAL_API_KEY", "test-internal-key")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD_HASH", _pwd.hash("test-password"))
os.environ.setdefault("VAULT_URL", "http://ssh-vault:8100")
os.environ.setdefault("ORCHESTRATOR_URL", "http://orchestrator:8001")
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://mas:test@localhost/masdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ENV", "development")


@pytest.fixture
def mock_db():
    """Mock AsyncSession so routes don't need a real DB."""
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.execute = AsyncMock(return_value=MagicMock(mappings=lambda: MagicMock(all=lambda: [])))
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.llen = AsyncMock(return_value=0)
    redis.ping = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def client(mock_db, mock_redis):
    """TestClient with DB and Redis mocked out."""
    from main import app
    from shared.db import get_db

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db

    with patch("shared.redis_client._client", mock_redis), \
         patch("shared.task_queue.get_redis", AsyncMock(return_value=mock_redis)), \
         patch("shared.rate_limiter.get_redis", AsyncMock(return_value=mock_redis)):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

    app.dependency_overrides.clear()


@pytest.fixture
def valid_token(client):
    """Get a valid JWT by calling /auth/token."""
    resp = client.post("/auth/token", json={"username": "admin", "password": "test-password"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
def auth_headers(valid_token):
    return {"Authorization": f"Bearer {valid_token}"}


@pytest.fixture
def api_key_headers():
    return {"X-API-Key": "test-internal-key"}
