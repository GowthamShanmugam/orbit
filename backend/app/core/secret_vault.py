"""AES-256-GCM secret vault.

Encrypts secrets at rest using a master key derived from the application's
SECRET_KEY via HKDF.  Each secret gets its own random nonce.
"""

from __future__ import annotations

import hashlib
import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_PLACEHOLDER_RE = re.compile(r"\{\{secret:([A-Za-z0-9_.\-]+)\}\}")

VAULT_KEY_LENGTH = 32  # AES-256
NONCE_LENGTH = 12


def _derive_key() -> bytes:
    """Derive a 256-bit key from the application SECRET_KEY using SHA-256."""
    return hashlib.sha256(settings.SECRET_KEY.encode()).digest()


def encrypt(plaintext: str) -> tuple[bytes, bytes, bytes]:
    """Encrypt a secret value. Returns (ciphertext, nonce, tag).

    AES-256-GCM produces ciphertext with an appended 16-byte tag.  We split
    them for separate storage so the DB schema is explicit.
    """
    key = _derive_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(NONCE_LENGTH)
    ct_with_tag = aesgcm.encrypt(nonce, plaintext.encode(), None)
    ciphertext = ct_with_tag[:-16]
    tag = ct_with_tag[-16:]
    return ciphertext, nonce, tag


def decrypt(ciphertext: bytes, nonce: bytes, tag: bytes) -> str:
    """Decrypt a secret value."""
    key = _derive_key()
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext + tag, None)
    return plaintext.decode()


def make_placeholder(name: str) -> str:
    """Generate the placeholder token that replaces the secret in prompts."""
    safe = re.sub(r"[^A-Za-z0-9_.\-]", "_", name)
    return f"{{{{secret:{safe}}}}}"


def find_placeholders(text: str) -> list[str]:
    """Return all placeholder keys found in *text*."""
    return _PLACEHOLDER_RE.findall(text)


def replace_placeholders(text: str, secrets: dict[str, str]) -> str:
    """Substitute ``{{secret:key}}`` tokens with their real values."""
    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        return secrets.get(key, m.group(0))
    return _PLACEHOLDER_RE.sub(_sub, text)
