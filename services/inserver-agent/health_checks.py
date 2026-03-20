"""
SSH-based health check parsers for GPU server maintenance.

Each function receives raw stdout from an SSH command and returns a structured dict.
Parsers are pure functions — no I/O, fully unit-testable with mock output.

Callers (tools.py) are responsible for the SSH execution step.
"""

import re
from typing import Any


# ── GPU ───────────────────────────────────────────────────────────────────────


def parse_gpu_status(nvidia_smi_output: str) -> dict[str, Any]:
    """
    Parse `nvidia-smi --query-gpu=index,name,temperature.gpu,utilization.gpu,
    memory.used,memory.total,power.draw,ecc.errors.corrected.volatile.total
    --format=csv,noheader,nounits` output.

    Returns:
        {
          "ok": bool,
          "gpus": [{"index", "name", "temp_c", "util_pct", "mem_used_mb",
                    "mem_total_mb", "mem_pct", "power_w", "ecc_errors"}],
          "alerts": [str],
          "raw": str
        }
    """
    gpus = []
    alerts = []

    for line in nvidia_smi_output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 8:
            continue
        try:
            idx = int(parts[0])
            name = parts[1]
            temp = float(parts[2])
            util = float(parts[3])
            mem_used = float(parts[4])
            mem_total = float(parts[5])
            power = float(parts[6]) if parts[6] not in ("N/A", "[N/A]") else 0.0
            ecc = int(parts[7]) if parts[7].isdigit() else 0

            mem_pct = (mem_used / mem_total * 100) if mem_total > 0 else 0.0

            gpu = {
                "index": idx,
                "name": name,
                "temp_c": temp,
                "util_pct": util,
                "mem_used_mb": mem_used,
                "mem_total_mb": mem_total,
                "mem_pct": round(mem_pct, 1),
                "power_w": power,
                "ecc_errors": ecc,
            }
            gpus.append(gpu)

            if temp > 85:
                alerts.append(f"GPU {idx} temperature critical: {temp}°C")
            if mem_pct > 90:
                alerts.append(f"GPU {idx} memory high: {mem_pct:.1f}%")
            if ecc > 0:
                alerts.append(f"GPU {idx} ECC errors: {ecc}")
        except (ValueError, IndexError):
            continue

    return {
        "ok": len(gpus) > 0 and len(alerts) == 0,
        "gpus": gpus,
        "alerts": alerts,
        "raw": nvidia_smi_output,
    }


# ── Disk ──────────────────────────────────────────────────────────────────────


def parse_disk_space(df_output: str) -> dict[str, Any]:
    """
    Parse `df -h --output=source,size,used,avail,pcent,target` output.

    Returns:
        {
          "ok": bool,
          "filesystems": [{"source", "size", "used", "avail", "use_pct", "mount"}],
          "alerts": [str]
        }
    """
    filesystems = []
    alerts = []

    lines = df_output.strip().splitlines()
    # Skip header line
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        source, size, used, avail, pcent_str, mount = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
        try:
            pct = float(pcent_str.rstrip("%"))
        except ValueError:
            continue

        fs = {
            "source": source,
            "size": size,
            "used": used,
            "avail": avail,
            "use_pct": pct,
            "mount": mount,
        }
        filesystems.append(fs)

        if pct >= 85:
            alerts.append(f"Disk {mount} usage high: {pct:.0f}%")
        if pct >= 95:
            alerts.append(f"Disk {mount} CRITICAL: {pct:.0f}% — immediate action required")

    return {
        "ok": len(filesystems) > 0 and len(alerts) == 0,
        "filesystems": filesystems,
        "alerts": alerts,
    }


# ── Memory ────────────────────────────────────────────────────────────────────


def parse_memory(free_output: str) -> dict[str, Any]:
    """
    Parse `free -m` output.

    Returns:
        {
          "ok": bool,
          "total_mb": int,
          "used_mb": int,
          "free_mb": int,
          "available_mb": int,
          "use_pct": float,
          "swap_total_mb": int,
          "swap_used_mb": int,
          "alerts": [str]
        }
    """
    alerts = []
    result: dict[str, Any] = {
        "ok": False,
        "total_mb": 0,
        "used_mb": 0,
        "free_mb": 0,
        "available_mb": 0,
        "use_pct": 0.0,
        "swap_total_mb": 0,
        "swap_used_mb": 0,
        "alerts": [],
    }

    for line in free_output.strip().splitlines():
        parts = line.split()
        if parts[0].lower().startswith("mem"):
            try:
                total = int(parts[1])
                used = int(parts[2])
                free = int(parts[3])
                available = int(parts[6]) if len(parts) > 6 else free
                use_pct = (used / total * 100) if total > 0 else 0.0
                result.update({
                    "total_mb": total,
                    "used_mb": used,
                    "free_mb": free,
                    "available_mb": available,
                    "use_pct": round(use_pct, 1),
                })
                if use_pct > 90:
                    alerts.append(f"Memory usage critical: {use_pct:.1f}%")
            except (ValueError, IndexError):
                pass
        elif parts[0].lower().startswith("swap"):
            try:
                result["swap_total_mb"] = int(parts[1])
                result["swap_used_mb"] = int(parts[2])
            except (ValueError, IndexError):
                pass

    result["alerts"] = alerts
    result["ok"] = result["total_mb"] > 0 and len(alerts) == 0
    return result


# ── Process / Service ─────────────────────────────────────────────────────────


def parse_process_health(systemctl_output: str, service_name: str) -> dict[str, Any]:
    """
    Parse `systemctl status <service>` output.

    Returns:
        {
          "service": str,
          "active": bool,
          "running": bool,
          "status_line": str,
          "alerts": [str]
        }
    """
    text = systemctl_output.lower()
    active = "active (running)" in text
    failed = "failed" in text or "inactive" in text

    # Extract the status line
    status_line = ""
    for line in systemctl_output.splitlines():
        if "active:" in line.lower():
            status_line = line.strip()
            break

    alerts = []
    if not active:
        alerts.append(f"Service {service_name} is not running: {status_line}")

    return {
        "service": service_name,
        "active": active,
        "running": active,
        "status_line": status_line,
        "alerts": alerts,
    }


# ── SSH Blacklist ─────────────────────────────────────────────────────────────


def parse_ssh_blacklist(fail2ban_output: str, iptables_output: str, own_ip: str) -> dict[str, Any]:
    """
    Check if own_ip appears in fail2ban-client status sshd or iptables -L INPUT output.

    Returns:
        {
          "blocked": bool,
          "found_in_fail2ban": bool,
          "found_in_iptables": bool,
          "own_ip": str,
          "alerts": [str]
        }
    """
    found_fail2ban = own_ip in fail2ban_output
    found_iptables = own_ip in iptables_output
    blocked = found_fail2ban or found_iptables

    alerts = []
    if found_fail2ban:
        alerts.append(f"Own IP {own_ip} is blocked in fail2ban sshd jail")
    if found_iptables:
        alerts.append(f"Own IP {own_ip} is blocked in iptables INPUT chain")

    return {
        "blocked": blocked,
        "found_in_fail2ban": found_fail2ban,
        "found_in_iptables": found_iptables,
        "own_ip": own_ip,
        "alerts": alerts,
    }
