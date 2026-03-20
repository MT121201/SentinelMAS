"""
Tool wrappers for the InServer Maintenance Agent.

Each tool is an async function. Tools call the SSH vault service for remote
execution and write results to Postgres. The LangGraph graph node calls these
tools via the Anthropic tool_use API.

Tools defined here (matching AGENT_DESIGN.md §1.2):
  ssh_execute            — run arbitrary command via vault session
  ssh_check_connectivity — ping + SSH handshake test
  get_server_list        — fetch all registered servers from DB
  check_gpu_status       — nvidia-smi → parsed GPU metrics
  check_disk_space       — df -h → parsed filesystem usage
  check_memory           — free -m → parsed memory stats
  check_process_health   — systemctl status → running/failed
  check_ssh_blacklist    — fail2ban + iptables → own IP blocked?
  unblock_own_ip         — run fail2ban-client unban + iptables -D
  restart_service        — systemctl restart <name> (allowed list only)
  log_action             — structured log entry to Postgres (tickets table unused here — uses snapshot log)
  emit_health_snapshot   — write to daily_health_snapshots table
"""

import hashlib
import logging
import socket
from datetime import date, datetime, timezone
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from health_checks import (
    parse_disk_space,
    parse_gpu_status,
    parse_memory,
    parse_process_health,
    parse_ssh_blacklist,
)

log = logging.getLogger(__name__)

_ALLOWED_RESTART_SERVICES = {"nvidia-persistenced", "docker", "ssh", "cron"}

# Anthropic tool definitions for use in the LangGraph graph
TOOL_DEFINITIONS = [
    {
        "name": "ssh_execute",
        "description": "Execute a shell command on a GPU server via the SSH vault. Always log your intent before calling this.",
        "input_schema": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string", "description": "Target server ID"},
                "command": {"type": "string", "description": "Shell command to execute"},
                "session_token": {"type": "string", "description": "Active vault session token"},
            },
            "required": ["server_id", "command", "session_token"],
        },
    },
    {
        "name": "get_server_list",
        "description": "Fetch all active GPU servers registered in the fleet database.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "check_gpu_status",
        "description": "Run nvidia-smi on a server and return parsed GPU metrics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "session_token": {"type": "string"},
            },
            "required": ["server_id", "session_token"],
        },
    },
    {
        "name": "check_disk_space",
        "description": "Run df -h on a server and return parsed filesystem usage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "session_token": {"type": "string"},
            },
            "required": ["server_id", "session_token"],
        },
    },
    {
        "name": "check_memory",
        "description": "Run free -m on a server and return parsed memory statistics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "session_token": {"type": "string"},
            },
            "required": ["server_id", "session_token"],
        },
    },
    {
        "name": "check_process_health",
        "description": "Check if a systemd service is running on a server.",
        "input_schema": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "session_token": {"type": "string"},
                "service_name": {"type": "string", "description": "e.g. nvidia-persistenced, docker"},
            },
            "required": ["server_id", "session_token", "service_name"],
        },
    },
    {
        "name": "check_ssh_blacklist",
        "description": "Detect if the management IP is blocked in fail2ban or iptables on a server.",
        "input_schema": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "session_token": {"type": "string"},
            },
            "required": ["server_id", "session_token"],
        },
    },
    {
        "name": "unblock_own_ip",
        "description": "Remove the management IP from fail2ban and iptables on a server. Use only if check_ssh_blacklist confirmed our IP is blocked.",
        "input_schema": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "session_token": {"type": "string"},
            },
            "required": ["server_id", "session_token"],
        },
    },
    {
        "name": "restart_service",
        "description": f"Restart an allowed systemd service. Allowed: {sorted(_ALLOWED_RESTART_SERVICES)}",
        "input_schema": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "session_token": {"type": "string"},
                "service_name": {"type": "string"},
            },
            "required": ["server_id", "session_token", "service_name"],
        },
    },
    {
        "name": "emit_health_snapshot",
        "description": "Write the completed health metrics for a server to the daily_health_snapshots table.",
        "input_schema": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "metrics": {"type": "object", "description": "Full health metrics dict"},
                "status": {
                    "type": "string",
                    "enum": ["healthy", "warning", "critical"],
                },
            },
            "required": ["server_id", "metrics", "status"],
        },
    },
]


# ── Vault HTTP helpers ────────────────────────────────────────────────────────


async def _vault_post(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{settings.vault_url}{path}",
            json=body,
            headers={"X-Internal-Key": settings.internal_api_key},
        )
        resp.raise_for_status()
        return resp.json()


async def open_vault_session(server_id: str, agent_id: str, trace_id: str) -> str:
    """Open a vault session for server_id. Returns session token."""
    data = await _vault_post(
        "/vault/session",
        {"server_id": server_id, "agent_id": agent_id, "trace_id": trace_id, "ttl": settings.vault_session_ttl},
    )
    return data["session_token"]


async def close_vault_session(token: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.delete(
            f"{settings.vault_url}/vault/session/{token}",
            headers={"X-Internal-Key": settings.internal_api_key},
        )


# ── Tool implementations ──────────────────────────────────────────────────────


async def ssh_execute(server_id: str, command: str, session_token: str) -> dict:
    """Execute command on server via vault session. Returns {stdout, stderr, exit_code, duration_ms}."""
    data = await _vault_post(
        f"/vault/session/{session_token}/execute",
        {"command": command, "timeout": settings.ssh_command_timeout},
    )
    return data


async def get_server_list(db: AsyncSession) -> list[dict]:
    """Fetch all active servers from server_credentials table."""
    result = await db.execute(
        text("SELECT id, hostname FROM server_credentials WHERE is_active = true ORDER BY id")
    )
    return [{"server_id": str(r.id), "hostname": r.hostname} for r in result.fetchall()]


async def check_gpu_status(server_id: str, session_token: str) -> dict:
    cmd = (
        "nvidia-smi --query-gpu=index,name,temperature.gpu,utilization.gpu,"
        "memory.used,memory.total,power.draw,ecc.errors.corrected.volatile.total "
        "--format=csv,noheader,nounits"
    )
    result = await ssh_execute(server_id, cmd, session_token)
    return parse_gpu_status(result.get("stdout", ""))


async def check_disk_space(server_id: str, session_token: str) -> dict:
    result = await ssh_execute(
        server_id,
        "df -h --output=source,size,used,avail,pcent,target -x tmpfs -x devtmpfs",
        session_token,
    )
    return parse_disk_space(result.get("stdout", ""))


async def check_memory(server_id: str, session_token: str) -> dict:
    result = await ssh_execute(server_id, "free -m", session_token)
    return parse_memory(result.get("stdout", ""))


async def check_process_health(server_id: str, session_token: str, service_name: str) -> dict:
    result = await ssh_execute(server_id, f"systemctl status {service_name}", session_token)
    return parse_process_health(result.get("stdout", ""), service_name)


async def check_ssh_blacklist(server_id: str, session_token: str) -> dict:
    own_ip = _get_own_ip()
    fail2ban_out = await ssh_execute(
        server_id, "fail2ban-client status sshd 2>/dev/null || echo 'fail2ban not running'", session_token
    )
    iptables_out = await ssh_execute(
        server_id, "iptables -L INPUT -n 2>/dev/null || echo 'no iptables'", session_token
    )
    return parse_ssh_blacklist(
        fail2ban_out.get("stdout", ""),
        iptables_out.get("stdout", ""),
        own_ip,
    )


async def unblock_own_ip(server_id: str, session_token: str) -> dict:
    own_ip = _get_own_ip()
    log.info("unblocking own IP %s on server %s", own_ip, server_id)
    results = []

    # fail2ban unban
    r1 = await ssh_execute(
        server_id,
        f"fail2ban-client set sshd unbanip {own_ip} 2>/dev/null || true",
        session_token,
    )
    results.append({"action": "fail2ban_unban", "exit_code": r1.get("exit_code")})

    # iptables delete DROP rule if present
    r2 = await ssh_execute(
        server_id,
        f"iptables -D INPUT -s {own_ip} -j DROP 2>/dev/null || true",
        session_token,
    )
    results.append({"action": "iptables_delete", "exit_code": r2.get("exit_code")})

    return {"unblocked_ip": own_ip, "steps": results}


async def restart_service(server_id: str, session_token: str, service_name: str) -> dict:
    if service_name not in _ALLOWED_RESTART_SERVICES:
        return {
            "ok": False,
            "error": f"Service '{service_name}' not in allowed restart list: {sorted(_ALLOWED_RESTART_SERVICES)}",
        }
    log.info("restarting service %s on server %s", service_name, server_id)
    result = await ssh_execute(server_id, f"systemctl restart {service_name}", session_token)
    return {"ok": result.get("exit_code") == 0, "service": service_name, "exit_code": result.get("exit_code")}


async def emit_health_snapshot(
    server_id: str,
    metrics: dict,
    status: str,
    db: AsyncSession,
) -> dict:
    """Upsert daily health snapshot for server_id."""
    today = date.today().isoformat()
    await db.execute(
        text(
            """
            INSERT INTO daily_health_snapshots (server_id, date, metrics_json, status, created_at)
            VALUES (:sid, :date, :metrics::jsonb, :status, now())
            ON CONFLICT (server_id, date) DO UPDATE
              SET metrics_json = EXCLUDED.metrics_json,
                  status = EXCLUDED.status
            """
        ),
        {
            "sid": int(server_id),
            "date": today,
            "metrics": __import__("json").dumps(metrics),
            "status": status,
        },
    )
    await db.commit()
    return {"server_id": server_id, "date": today, "status": status}


async def log_action(
    action: str,
    server_id: str,
    result: Any,
    trace_id: str,
    db: AsyncSession,
) -> None:
    """Structured action log — writes to application log and can be extended to a DB table."""
    log.info(
        "agent_action action=%s server_id=%s trace_id=%s result=%s",
        action,
        server_id,
        trace_id,
        result,
    )


def _get_own_ip() -> str:
    """Resolve outbound IP of this container (used for blacklist checks)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


# ── Tool dispatcher ───────────────────────────────────────────────────────────


async def dispatch_tool(
    tool_name: str,
    tool_input: dict,
    db: AsyncSession,
) -> Any:
    """
    Route a tool_use call from Claude to the correct async function.
    Called by executor.py inside the agent loop.
    """
    match tool_name:
        case "ssh_execute":
            return await ssh_execute(**tool_input)
        case "get_server_list":
            return await get_server_list(db)
        case "check_gpu_status":
            return await check_gpu_status(**tool_input)
        case "check_disk_space":
            return await check_disk_space(**tool_input)
        case "check_memory":
            return await check_memory(**tool_input)
        case "check_process_health":
            return await check_process_health(**tool_input)
        case "check_ssh_blacklist":
            return await check_ssh_blacklist(**tool_input)
        case "unblock_own_ip":
            return await unblock_own_ip(**tool_input)
        case "restart_service":
            return await restart_service(**tool_input)
        case "emit_health_snapshot":
            return await emit_health_snapshot(**tool_input, db=db)
        case _:
            return {"error": f"Unknown tool: {tool_name}"}
