"""
Unit tests for rag-service sanitiser.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sanitiser import sanitise_pattern, sanitise_fix_steps


class TestSanitisePattern:
    def test_ip_redacted(self):
        result = sanitise_pattern("Error on 192.168.1.50 during startup")
        assert "[IP]" in result
        assert "192.168.1.50" not in result

    def test_ipv6_redacted(self):
        result = sanitise_pattern("Host 2001:0db8:85a3:0000:0000:8a2e:0370:7334 down")
        assert "[IPv6]" in result

    def test_hostname_redacted(self):
        result = sanitise_pattern("gpu-node-03.internal is unreachable")
        assert "[HOST]" in result
        assert "gpu-node-03.internal" not in result

    def test_home_path_redacted(self):
        result = sanitise_pattern("File at /home/johndoe/.ssh/id_rsa missing")
        assert "/home/[USER]" in result
        assert "johndoe" not in result

    def test_credentials_redacted(self):
        result = sanitise_pattern("password=supersecret123")
        assert "supersecret123" not in result
        assert "[REDACTED]" in result

    def test_uuid_redacted(self):
        result = sanitise_pattern("Resource 550e8400-e29b-41d4-a716-446655440000 failed")
        assert "[UUID]" in result
        assert "550e8400" not in result

    def test_long_numeric_id_redacted(self):
        result = sanitise_pattern("Job ID 12345678 timed out")
        assert "[ID]" in result
        assert "12345678" not in result

    def test_short_number_preserved(self):
        # 6-digit numbers should be left alone
        result = sanitise_pattern("Error code 123456")
        assert "123456" in result

    def test_pem_key_redacted(self):
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        result = sanitise_pattern(pem)
        assert "[KEY_REDACTED]" in result
        assert "MIIEowIBAAKCAQEA" not in result

    def test_truncation_at_2000(self):
        long_text = "A" * 3000
        result = sanitise_pattern(long_text)
        assert len(result) <= 2000

    def test_clean_text_unchanged(self):
        text = "CUDA out of memory during model forward pass"
        result = sanitise_pattern(text)
        assert result == text

    def test_multiple_rules_applied(self):
        text = "Server 10.0.0.1 at /home/admin/log — token=abc123xyz"
        result = sanitise_pattern(text)
        assert "10.0.0.1" not in result
        assert "admin" not in result
        assert "abc123xyz" not in result


class TestSanitiseFixSteps:
    def test_same_rules_as_pattern(self):
        result = sanitise_fix_steps("ssh user@192.168.0.5 to fix")
        assert "192.168.0.5" not in result
        assert "[IP]" in result

    def test_server_paths_redacted(self):
        result = sanitise_fix_steps("Edit /home/ubuntu/config.yaml")
        assert "ubuntu" not in result

    def test_truncation(self):
        result = sanitise_fix_steps("x" * 5000)
        assert len(result) <= 2000
