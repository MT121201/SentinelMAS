import base64
import os
import sys

import pytest

# Ensure vault service and shared are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Set required env vars before importing vault modules
os.environ.setdefault(
    "VAULT_MASTER_KEY",
    base64.b64encode(b"test_key_32bytes_exactly_padded!").decode(),
)
os.environ.setdefault("INTERNAL_API_KEY", "test-internal-key")
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://mas:test@localhost:5432/masdb")
