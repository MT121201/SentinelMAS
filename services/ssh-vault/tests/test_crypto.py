"""
Unit tests: VaultCrypto encrypt/decrypt round-trips.
No DB or network required.
"""

import base64
import os

import pytest
from cryptography.exceptions import InvalidTag

# conftest.py sets VAULT_MASTER_KEY before this import
from crypto import VaultCrypto


@pytest.fixture
def crypto():
    return VaultCrypto()


def test_encrypt_returns_bytes(crypto):
    ct, nonce = crypto.encrypt("my-secret-username")
    assert isinstance(ct, bytes)
    assert isinstance(nonce, bytes)
    assert len(nonce) == 12


def test_round_trip_username(crypto):
    plaintext = "gpu_admin"
    ct, nonce = crypto.encrypt(plaintext)
    assert crypto.decrypt(ct, nonce) == plaintext


def test_round_trip_ssh_key(crypto):
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
    ct, nonce = crypto.encrypt(pem)
    assert crypto.decrypt(ct, nonce) == pem


def test_round_trip_unicode(crypto):
    plaintext = "pässwörD_123_!@#"
    ct, nonce = crypto.encrypt(plaintext)
    assert crypto.decrypt(ct, nonce) == plaintext


def test_different_nonces_each_encrypt(crypto):
    """Each encryption must produce a unique nonce (AES-GCM requires this)."""
    _, nonce1 = crypto.encrypt("same_value")
    _, nonce2 = crypto.encrypt("same_value")
    assert nonce1 != nonce2


def test_tampered_ciphertext_raises(crypto):
    ct, nonce = crypto.encrypt("sensitive")
    tampered = bytes([ct[0] ^ 0xFF]) + ct[1:]
    with pytest.raises(InvalidTag):
        crypto.decrypt(tampered, nonce)


def test_wrong_nonce_raises(crypto):
    ct, _ = crypto.encrypt("sensitive")
    wrong_nonce = os.urandom(12)
    with pytest.raises(InvalidTag):
        crypto.decrypt(ct, wrong_nonce)


def test_bad_master_key_length():
    os.environ["VAULT_MASTER_KEY"] = base64.b64encode(b"tooshort").decode()
    with pytest.raises(ValueError, match="32 bytes"):
        VaultCrypto()
    # Restore
    os.environ["VAULT_MASTER_KEY"] = base64.b64encode(b"test_key_32bytes_exactly_padded!").decode()
