"""
Hard restart — BMC/IPMI power cycle with SSH `reboot -f` fallback.

CRITICAL severity only. Requires double-log confirmation before execution:
  1. First log: intent statement with reason
  2. Second log: confirmed execution with timestamp

BMC/IPMI call is a ⚠️ STUB — real BMC hostname/credentials schema is
infrastructure-specific and must be configured per deployment.
The SSH fallback (`reboot -f`) is fully implemented.
"""

import logging
from datetime import datetime, timezone

import httpx

from config import settings

log = logging.getLogger(__name__)


async def hard_restart(
    server_id: str,
    session_token: str,
    reason: str,
    agent_id: str,
    trace_id: str,
) -> dict:
    """
    Perform a hard restart on server_id.

    Safety contract (double-log):
      - Caller MUST have already called log_action with action="hard_restart_intent"
        before calling this function.
      - This function logs action="hard_restart_confirmed" before executing.

    Execution order:
      1. Try BMC/IPMI power cycle (stub — logs warning if not configured)
      2. Fall back to SSH `reboot -f` via vault session

    Returns dict with {method, success, timestamp, reason}.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Second confirmation log (first must be done by caller via log_action)
    log.warning(
        "HARD_RESTART CONFIRMED server_id=%s agent=%s trace=%s reason=%s timestamp=%s",
        server_id,
        agent_id,
        trace_id,
        reason,
        now,
    )

    # 1. Attempt BMC/IPMI (stub)
    bmc_result = await _try_bmc_restart(server_id)
    if bmc_result["success"]:
        return {
            "method": "bmc_ipmi",
            "success": True,
            "timestamp": now,
            "reason": reason,
            "server_id": server_id,
        }

    # 2. SSH fallback: reboot -f
    log.warning(
        "BMC unavailable for server %s — falling back to SSH reboot -f", server_id
    )
    ssh_result = await _try_ssh_reboot(server_id, session_token)
    return {
        "method": "ssh_reboot_f",
        "success": ssh_result.get("exit_code") in (0, None),
        "timestamp": now,
        "reason": reason,
        "server_id": server_id,
        "ssh_output": ssh_result,
    }


async def _try_bmc_restart(server_id: str) -> dict:
    """
    ⚠️ STUB — BMC/IPMI power cycle.

    Real implementation requires:
    - BMC hostname per server (stored in server_credentials or separate table)
    - IPMI credentials
    - ipmitool or Redfish API call

    Until configured, always returns success=False so SSH fallback is used.
    """
    log.warning(
        "BMC/IPMI restart is a stub — configure BMC credentials per server to enable"
    )
    return {"success": False, "reason": "BMC not configured"}


async def _try_ssh_reboot(server_id: str, session_token: str) -> dict:
    """Issue `reboot -f` via vault SSH session. Connection will drop immediately."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.vault_url}/vault/session/{session_token}/execute",
                json={"command": "reboot -f", "timeout": 10},
                headers={"X-Internal-Key": settings.internal_api_key},
            )
            # The connection will likely drop before a response comes back
            if resp.status_code in (200, 500):
                return resp.json()
            return {"exit_code": 0, "stdout": "", "stderr": "connection dropped (expected)"}
    except httpx.ReadTimeout:
        # Expected — server rebooted before response
        return {"exit_code": 0, "stdout": "", "stderr": "read timeout (server rebooted)"}
    except Exception as exc:
        log.error("SSH reboot fallback failed: %s", exc)
        return {"exit_code": 1, "stdout": "", "stderr": str(exc)}
