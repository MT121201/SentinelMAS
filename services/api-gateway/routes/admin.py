"""
Admin endpoints (API key required):
  GET    /admin/servers                  list all registered servers
  POST   /admin/servers                  register new server (forwards to vault)
  PUT    /admin/servers/{id}/credential  rotate SSH credential (forwards to vault)
  DELETE /admin/servers/{id}             decommission server
  POST   /admin/maintenance/trigger      manual maintenance trigger
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shared.db import get_db
from shared.task_queue import enqueue

from auth import require_api_key
from config import settings
from limiter import limiter
from models import ServerCreate, ServerInfo

router = APIRouter(tags=["admin"])

_VAULT_HEADERS = {"X-Internal-Key": settings.internal_api_key}


@router.get("/admin/servers", response_model=list[ServerInfo])
@limiter.limit("30/minute")
async def list_servers(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _key: str = Depends(require_api_key),
):
    result = await db.execute(text("""
        SELECT s.server_id, s.display_name, s.hostname, s.port, s.is_active,
               d.date::text AS last_snapshot_date, d.status AS health_status
        FROM server_credentials s
        LEFT JOIN LATERAL (
            SELECT date, status FROM daily_health_snapshots
            WHERE server_id = s.server_id
            ORDER BY date DESC LIMIT 1
        ) d ON true
        ORDER BY s.server_id
    """))
    return [ServerInfo(**dict(r)) for r in result.mappings().all()]


@router.post("/admin/servers", status_code=201)
@limiter.limit("10/minute")
async def register_server(
    request: Request,
    body: ServerCreate,
    _key: str = Depends(require_api_key),
):
    """Forward credential registration to the vault service."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{settings.vault_url}/vault/credentials",
            json=body.model_dump(),
            headers=_VAULT_HEADERS,
        )
    if resp.status_code == 409:
        raise HTTPException(status_code=409, detail="server_id already registered")
    if resp.status_code != 201:
        raise HTTPException(status_code=502, detail=f"Vault error: {resp.text}")
    return resp.json()


@router.put("/admin/servers/{server_id}/credential")
@limiter.limit("10/minute")
async def rotate_credential(
    request: Request,
    server_id: str,
    body: dict,
    _key: str = Depends(require_api_key),
):
    """Forward credential rotation to the vault service."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.put(
            f"{settings.vault_url}/vault/credentials/{server_id}",
            json=body,
            headers=_VAULT_HEADERS,
        )
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Server not found")
    if not resp.is_success:
        raise HTTPException(status_code=502, detail=f"Vault error: {resp.text}")
    return resp.json()


@router.delete("/admin/servers/{server_id}", status_code=200)
@limiter.limit("10/minute")
async def decommission_server(
    request: Request,
    server_id: str,
    _key: str = Depends(require_api_key),
):
    """Deactivate a server credential in the vault."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.delete(
            f"{settings.vault_url}/vault/credentials/{server_id}",
            headers=_VAULT_HEADERS,
        )
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Server not found")
    if not resp.is_success:
        raise HTTPException(status_code=502, detail=f"Vault error: {resp.text}")
    return {"server_id": server_id, "status": "decommissioned"}


@router.post("/admin/maintenance/trigger", status_code=202)
@limiter.limit("5/minute")
async def trigger_maintenance(
    request: Request,
    body: dict = {},
    _key: str = Depends(require_api_key),
):
    """Manually enqueue a maintenance task for a specific server or all servers."""
    server_id = body.get("server_id")  # None = all servers
    task = {
        "task_type": "maintenance",
        "server_id": server_id,
        "trigger": "manual",
    }
    await enqueue("inserver", task)
    return {"status": "queued", "server_id": server_id or "all"}
