"""POST /auth/token — issue JWT for valid admin credentials."""

from fastapi import APIRouter, HTTPException, Request

from auth import create_access_token, verify_password
from config import settings
from limiter import limiter
from models import TokenRequest, TokenResponse

router = APIRouter(tags=["auth"])


@router.post("/auth/token", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, body: TokenRequest):
    """
    Exchange username + password for a Bearer JWT.
    Token is valid for jwt_expiry_hours (default 24h).
    """
    username_match = body.username == settings.admin_username
    password_match = verify_password(body.password, settings.admin_password_hash)

    if not username_match or not password_match:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(subject=body.username)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expiry_hours * 3600,
    )
