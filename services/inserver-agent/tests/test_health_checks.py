"""
Unit tests for health check parsers.
All tests use realistic mock SSH output — no real SSH connections.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from health_checks import (
    parse_gpu_status,
    parse_disk_space,
    parse_memory,
    parse_process_health,
    parse_ssh_blacklist,
)


# ── GPU ───────────────────────────────────────────────────────────────────────


NVIDIA_SMI_NORMAL = """\
0, NVIDIA A100 80GB PCIe, 42, 15, 12288, 81920, 300.00, 0
1, NVIDIA A100 80GB PCIe, 45, 20, 16384, 81920, 320.00, 0
"""

NVIDIA_SMI_HIGH_TEMP = """\
0, NVIDIA A100 80GB PCIe, 88, 95, 70000, 81920, 400.00, 0
"""

NVIDIA_SMI_HIGH_MEM = """\
0, NVIDIA A100 80GB PCIe, 50, 80, 75000, 81920, 350.00, 0
"""

NVIDIA_SMI_ECC_ERRORS = """\
0, NVIDIA A100 80GB PCIe, 50, 10, 8192, 81920, 300.00, 5
"""

NVIDIA_SMI_EMPTY = ""


class TestParseGpuStatus:
    def test_normal_two_gpus(self):
        result = parse_gpu_status(NVIDIA_SMI_NORMAL)
        assert result["ok"] is True
        assert len(result["gpus"]) == 2
        assert result["alerts"] == []

    def test_gpu_fields_present(self):
        result = parse_gpu_status(NVIDIA_SMI_NORMAL)
        gpu = result["gpus"][0]
        assert gpu["index"] == 0
        assert "A100" in gpu["name"]
        assert gpu["temp_c"] == 42.0
        assert gpu["mem_pct"] == round(12288 / 81920 * 100, 1)

    def test_high_temperature_alert(self):
        result = parse_gpu_status(NVIDIA_SMI_HIGH_TEMP)
        assert result["ok"] is False
        assert any("temperature" in a.lower() for a in result["alerts"])

    def test_high_memory_alert(self):
        result = parse_gpu_status(NVIDIA_SMI_HIGH_MEM)
        assert result["ok"] is False
        assert any("memory" in a.lower() for a in result["alerts"])

    def test_ecc_errors_alert(self):
        result = parse_gpu_status(NVIDIA_SMI_ECC_ERRORS)
        assert result["ok"] is False
        assert any("ecc" in a.lower() for a in result["alerts"])

    def test_empty_output_no_gpus(self):
        result = parse_gpu_status(NVIDIA_SMI_EMPTY)
        assert result["ok"] is False
        assert result["gpus"] == []


# ── Disk ──────────────────────────────────────────────────────────────────────


DF_NORMAL = """\
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda1       500G   80G  420G  16% /
/dev/sdb1       2.0T  400G  1.6T  20% /data
"""

DF_HIGH_USAGE = """\
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda1       500G  430G   70G  86% /
/dev/nvme0n1    2.0T  1.9T  100G  95% /data
"""


class TestParseDiskSpace:
    def test_normal_disks(self):
        result = parse_disk_space(DF_NORMAL)
        assert result["ok"] is True
        assert len(result["filesystems"]) == 2
        assert result["alerts"] == []

    def test_high_usage_alerts(self):
        result = parse_disk_space(DF_HIGH_USAGE)
        assert result["ok"] is False
        assert len(result["alerts"]) >= 2  # /data is critical (95%)

    def test_critical_alert_text(self):
        result = parse_disk_space(DF_HIGH_USAGE)
        assert any("CRITICAL" in a for a in result["alerts"])

    def test_filesystem_fields(self):
        result = parse_disk_space(DF_NORMAL)
        fs = result["filesystems"][0]
        assert "source" in fs
        assert "use_pct" in fs
        assert "mount" in fs


# ── Memory ────────────────────────────────────────────────────────────────────


FREE_NORMAL = """\
              total        used        free      shared  buff/cache   available
Mem:         257870       12345      200000        512       45000      240000
Swap:          8191           0        8191
"""

FREE_HIGH_USAGE = """\
              total        used        free      shared  buff/cache   available
Mem:         257870      240000        5000        512       12870       10000
Swap:          8191        4000        4191
"""


class TestParseMemory:
    def test_normal_memory(self):
        result = parse_memory(FREE_NORMAL)
        assert result["ok"] is True
        assert result["total_mb"] == 257870
        assert result["alerts"] == []

    def test_high_memory_alert(self):
        result = parse_memory(FREE_HIGH_USAGE)
        assert result["ok"] is False
        assert any("memory" in a.lower() for a in result["alerts"])

    def test_swap_parsed(self):
        result = parse_memory(FREE_NORMAL)
        assert result["swap_total_mb"] == 8191
        assert result["swap_used_mb"] == 0

    def test_use_pct_calculated(self):
        result = parse_memory(FREE_NORMAL)
        expected = round(12345 / 257870 * 100, 1)
        assert abs(result["use_pct"] - expected) < 0.5


# ── Process health ────────────────────────────────────────────────────────────


SYSTEMCTL_RUNNING = """\
● nvidia-persistenced.service - NVIDIA Persistence Daemon
     Loaded: loaded (/lib/systemd/system/nvidia-persistenced.service; enabled)
     Active: active (running) since Mon 2026-03-20 00:05:00 UTC; 12h ago
"""

SYSTEMCTL_FAILED = """\
● docker.service - Docker Application Container Engine
     Loaded: loaded (/lib/systemd/system/docker.service; enabled)
     Active: failed (Result: exit-code) since Mon 2026-03-20 08:00:00 UTC; 4h ago
"""

SYSTEMCTL_INACTIVE = """\
● cron.service - Regular background program processing daemon
     Loaded: loaded (/lib/systemd/system/cron.service; enabled)
     Active: inactive (dead)
"""


class TestParseProcessHealth:
    def test_service_running(self):
        result = parse_process_health(SYSTEMCTL_RUNNING, "nvidia-persistenced")
        assert result["active"] is True
        assert result["running"] is True
        assert result["alerts"] == []

    def test_service_failed(self):
        result = parse_process_health(SYSTEMCTL_FAILED, "docker")
        assert result["active"] is False
        assert len(result["alerts"]) > 0
        assert "docker" in result["alerts"][0]

    def test_service_inactive(self):
        result = parse_process_health(SYSTEMCTL_INACTIVE, "cron")
        assert result["running"] is False

    def test_service_name_preserved(self):
        result = parse_process_health(SYSTEMCTL_RUNNING, "nvidia-persistenced")
        assert result["service"] == "nvidia-persistenced"


# ── SSH Blacklist ─────────────────────────────────────────────────────────────


FAIL2BAN_WITH_IP = """\
Status for the jail: sshd
|- Filter
|  |- Currently failed: 3
|  `- Total failed: 47
`- Actions
   |- Currently banned: 2
   `- Banned IP list: 10.0.0.5 10.0.1.100
"""

FAIL2BAN_WITHOUT_IP = """\
Status for the jail: sshd
|- Filter
|  `- Total failed: 10
`- Actions
   `- Currently banned: 0
"""

IPTABLES_WITH_IP = """\
Chain INPUT (policy ACCEPT)
target     prot opt source               destination
DROP       all  --  10.0.0.5             0.0.0.0/0
ACCEPT     all  --  0.0.0.0/0            0.0.0.0/0
"""

IPTABLES_WITHOUT_IP = """\
Chain INPUT (policy ACCEPT)
target     prot opt source               destination
ACCEPT     all  --  0.0.0.0/0            0.0.0.0/0
"""


class TestParseSshBlacklist:
    def test_ip_in_fail2ban(self):
        result = parse_ssh_blacklist(FAIL2BAN_WITH_IP, IPTABLES_WITHOUT_IP, "10.0.0.5")
        assert result["blocked"] is True
        assert result["found_in_fail2ban"] is True
        assert result["found_in_iptables"] is False

    def test_ip_in_iptables(self):
        result = parse_ssh_blacklist(FAIL2BAN_WITHOUT_IP, IPTABLES_WITH_IP, "10.0.0.5")
        assert result["blocked"] is True
        assert result["found_in_iptables"] is True
        assert result["found_in_fail2ban"] is False

    def test_ip_in_both(self):
        result = parse_ssh_blacklist(FAIL2BAN_WITH_IP, IPTABLES_WITH_IP, "10.0.0.5")
        assert result["blocked"] is True
        assert len(result["alerts"]) == 2

    def test_ip_not_blocked(self):
        result = parse_ssh_blacklist(FAIL2BAN_WITHOUT_IP, IPTABLES_WITHOUT_IP, "10.0.0.5")
        assert result["blocked"] is False
        assert result["alerts"] == []

    def test_different_ip_not_blocked(self):
        result = parse_ssh_blacklist(FAIL2BAN_WITH_IP, IPTABLES_WITH_IP, "10.99.99.99")
        assert result["blocked"] is False
