"""
JWT and API Key authentication for the API Gateway.

Two auth schemes:
  - Bearer JWT  → user-facing endpoints (/tickets)
  - X-API-Key   → manager/admin/internal endpoints (/reports, /ops, /admin)
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from config import settings

bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# ── Password helpers ───────────────────────────────────────────────────────────

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(subject: str) -> str:
    """Issue a signed JWT valid for jwt_expiry_hours."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=settings.jwt_expiry_hours)
    payload = {"sub": subject, "iat": now, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {exc}")


# ── FastAPI dependencies ───────────────────────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """Dependency: validates Bearer JWT, returns decoded payload."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Bearer token required")
    return _decode_token(credentials.credentials)


async def require_api_key(
    key: Optional[str] = Depends(api_key_header),
) -> str:
    """Dependency: validates X-API-Key for manager/ops endpoints."""
    if not key or key != settings.internal_api_key:
        raise HTTPException(status_code=403, detail="Valid API key required")
    return key


async def require_internal_key(
    key: Optional[str] = Depends(api_key_header),
) -> str:
    """Dependency: same key, used for /internal endpoints (services call each other)."""
    if not key or key != settings.internal_api_key:
        raise HTTPException(status_code=403, detail="Internal API key required")
    return key
