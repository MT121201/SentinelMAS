"""
SSH Vault API routes.

All endpoints require X-Internal-Key header.
This service is on the internal Docker network — never publicly exposed.

Endpoints:
    POST   /vault/credentials              add server credential
    PUT    /vault/credentials/{server_id}  update / rotate credential
    DELETE /vault/credentials/{server_id}  deactivate
    POST   /vault/session                  open SSH session → token
    POST   /vault/session/{token}/execute  run command on session
    DELETE /vault/session/{token}          close session
    GET    /health                         health check
"""

import uuid
from datetime import datetime, timezone

import paramiko
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.db import get_db

from config import settings
from crypto import VaultCrypto
from models import CredentialAccessLog, ServerCredential
from session_registry import get_registry

router = APIRouter()
_crypto = VaultCrypto()


# ── Auth dependency ────────────────────────────────────────────────────────────

def require_internal_key(x_internal_key: str = Header(..., alias="X-Internal-Key")) -> None:
    if x_internal_key != settings.internal_api_key:
        raise HTTPException(status_code=403, detail="Invalid internal API key")


# ── Request / Response models ──────────────────────────────────────────────────

class AddCredentialRequest(BaseModel):
    server_id: str = Field(..., max_length=64)
    display_name: str = Field(..., max_length=128)
    hostname: str
    port: int = 22
    username: str
    ssh_private_key: str          # PEM string
    sudo_password: str | None = None


class UpdateCredentialRequest(BaseModel):
    display_name: str | None = None
    hostname: str | None = None
    port: int | None = None
    username: str | None = None
    ssh_private_key: str | None = None
    sudo_password: str | None = None


class CreateSessionRequest(BaseModel):
    server_id: str
    agent_id: str
    trace_id: str
    ttl_seconds: int = Field(default=300, ge=30, le=3600)


class ExecuteRequest(BaseModel):
    command: str
    timeout: int = Field(default=30, ge=1, le=300)


# ── Credential endpoints ───────────────────────────────────────────────────────

@router.post("/vault/credentials", status_code=201, dependencies=[Depends(require_internal_key)])
async def add_credential(body: AddCredentialRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.scalar(
        select(ServerCredential).where(ServerCredential.server_id == body.server_id)
    )
    if existing:
        raise HTTPException(status_code=409, detail="server_id already exists")

    key_enc, key_nonce = _crypto.encrypt(body.ssh_private_key)
    user_enc, user_nonce = _crypto.encrypt(body.username)
    sudo_enc = sudo_nonce = None
    if body.sudo_password:
        sudo_enc, sudo_nonce = _crypto.encrypt(body.sudo_password)

    cred = ServerCredential(
        server_id=body.server_id,
        display_name=body.display_name,
        hostname=body.hostname,
        port=body.port,
        username_enc=user_enc,
        user_nonce=user_nonce,
        ssh_key_enc=key_enc,
        key_nonce=key_nonce,
        sudo_pass_enc=sudo_enc,
        sudo_nonce=sudo_nonce,
    )
    db.add(cred)
    return {"server_id": body.server_id, "status": "created"}


@router.put("/vault/credentials/{server_id}", dependencies=[Depends(require_internal_key)])
async def update_credential(
    server_id: str, body: UpdateCredentialRequest, db: AsyncSession = Depends(get_db)
):
    cred = await db.scalar(
        select(ServerCredential).where(
            ServerCredential.server_id == server_id, ServerCredential.is_active == True
        )
    )
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")

    if body.hostname:
        cred.hostname = body.hostname
    if body.port:
        cred.port = body.port
    if body.display_name:
        cred.display_name = body.display_name
    if body.username:
        cred.username_enc, cred.user_nonce = _crypto.encrypt(body.username)
    if body.ssh_private_key:
        cred.ssh_key_enc, cred.key_nonce = _crypto.encrypt(body.ssh_private_key)
        cred.rotated_at = datetime.now(timezone.utc)
    if body.sudo_password:
        cred.sudo_pass_enc, cred.sudo_nonce = _crypto.encrypt(body.sudo_password)

    return {"server_id": server_id, "status": "updated"}


@router.delete("/vault/credentials/{server_id}", dependencies=[Depends(require_internal_key)])
async def deactivate_credential(server_id: str, db: AsyncSession = Depends(get_db)):
    cred = await db.scalar(
        select(ServerCredential).where(ServerCredential.server_id == server_id)
    )
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    cred.is_active = False
    return {"server_id": server_id, "status": "deactivated"}


# ── Session endpoints ──────────────────────────────────────────────────────────

@router.post("/vault/session", dependencies=[Depends(require_internal_key)])
async def create_session(body: CreateSessionRequest, db: AsyncSession = Depends(get_db)):
    cred = await db.scalar(
        select(ServerCredential).where(
            ServerCredential.server_id == body.server_id,
            ServerCredential.is_active == True,
        )
    )
    if not cred:
        raise HTTPException(status_code=404, detail="No active credential for server_id")

    # Decrypt key material in-memory — never stored outside this scope
    username = _crypto.decrypt(cred.username_enc, cred.user_nonce)
    ssh_key_pem = _crypto.decrypt(cred.ssh_key_enc, cred.key_nonce)

    # Build paramiko client
    import io
    pkey = paramiko.RSAKey.from_private_key(io.StringIO(ssh_key_pem))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=cred.hostname,
            port=cred.port,
            username=username,
            pkey=pkey,
            timeout=15,
            banner_timeout=15,
        )
    except Exception as exc:
        _audit(db, body.server_id, body.agent_id, body.trace_id, "connect", success=False)
        raise HTTPException(status_code=502, detail=f"SSH connect failed: {exc}")
    finally:
        # Zero the pem string (best-effort)
        ssh_key_pem = "0" * len(ssh_key_pem)
        del ssh_key_pem

    token = get_registry().create(
        server_id=body.server_id,
        agent_id=body.agent_id,
        trace_id=body.trace_id,
        client=client,
        ttl=body.ttl_seconds,
    )
    _audit(db, body.server_id, body.agent_id, body.trace_id, "connect", success=True)
    return {"session_token": token}


@router.post("/vault/session/{token}/execute", dependencies=[Depends(require_internal_key)])
async def execute_command(
    token: str, body: ExecuteRequest, db: AsyncSession = Depends(get_db)
):
    reg = get_registry()
    try:
        session_info = reg._sessions.get(token)
        result = reg.execute(token, body.command, timeout=body.timeout)
        if session_info:
            _audit(db, session_info.server_id, session_info.agent_id, session_info.trace_id, "execute", success=True)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Command execution failed: {exc}")


@router.delete("/vault/session/{token}", dependencies=[Depends(require_internal_key)])
async def close_session(token: str):
    reg = get_registry()
    session_info = reg._sessions.get(token)
    try:
        reg.close(token)
        return {"status": "closed"}
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _audit(
    db: AsyncSession,
    server_id: str,
    agent_id: str,
    trace_id: str,
    operation: str,
    success: bool,
) -> None:
    """Write audit log entry (fire-and-forget within the current session)."""
    entry = CredentialAccessLog(
        server_id=server_id,
        agent_id=agent_id,
        trace_id=trace_id,
        operation=operation,
        success=success,
    )
    db.add(entry)
