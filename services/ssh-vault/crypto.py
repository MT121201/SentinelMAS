"""
AES-256-GCM encryption for vault credential fields.

Master key is loaded ONCE at startup from VAULT_MASTER_KEY env var.
Key material is never written to disk, logs, or returned via API.
"""

import base64
import ctypes
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class VaultCrypto:
    """
    Encrypts/decrypts credential fields with AES-256-GCM.

    Each field gets its own random 12-byte nonce stored alongside the ciphertext.
    The nonce is safe to store in plaintext — security comes from the key + authenticated encryption.
    """

    def __init__(self) -> None:
        key_b64 = os.environ["VAULT_MASTER_KEY"]
        self._key: bytes = base64.b64decode(key_b64)
        if len(self._key) != 32:
            raise ValueError("VAULT_MASTER_KEY must decode to exactly 32 bytes")
        self._aesgcm = AESGCM(self._key)

    def encrypt(self, plaintext: str) -> tuple[bytes, bytes]:
        """
        Encrypt a plaintext string.
        Returns (ciphertext_bytes, nonce_bytes).
        Both must be stored; nonce is required for decryption.
        """
        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return ciphertext, nonce

    def decrypt(self, ciphertext: bytes, nonce: bytes) -> str:
        """
        Decrypt ciphertext back to plaintext string.
        Raises cryptography.exceptions.InvalidTag if ciphertext is tampered.
        """
        plaintext_bytes = self._aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext_bytes.decode("utf-8")

    def __del__(self) -> None:
        """Best-effort zero-out of key material on garbage collection."""
        if hasattr(self, "_key") and self._key:
            try:
                mutable = bytearray(self._key)
                buf = (ctypes.c_char * len(mutable)).from_buffer(mutable)
                ctypes.memset(buf, 0, len(mutable))
            except Exception:
                pass
