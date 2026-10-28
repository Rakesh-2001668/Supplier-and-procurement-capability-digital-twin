"""Field-level encryption with per-tenant keys derived from the master key.

Production deployments replace the master key with Cloud KMS; the derivation
keeps one tenant's ciphertext unreadable with another tenant's key.
"""
import base64
import hashlib
import hmac
import uuid

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.pic.config import get_settings


def _master() -> bytes:
    raw = get_settings().field_key.encode()
    try:
        key = base64.urlsafe_b64decode(raw)
        if len(key) == 32:
            return key
    except Exception:
        pass
    return hashlib.sha256(raw).digest()


def _fernet(tenant_id: uuid.UUID, purpose: str) -> Fernet:
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=tenant_id.bytes, info=purpose.encode()).derive(_master())
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt(tenant_id: uuid.UUID, purpose: str, plaintext: str) -> bytes:
    return _fernet(tenant_id, purpose).encrypt(plaintext.encode())


def decrypt(tenant_id: uuid.UUID, purpose: str, token: bytes) -> str:
    return _fernet(tenant_id, purpose).decrypt(bytes(token)).decode()


def blind_index(tenant_id: uuid.UUID, value: str) -> str:
    """Keyed hash for equality search on encrypted values (e.g. duplicate GSTIN check)."""
    normalised = value.strip().upper().replace(" ", "")
    return hmac.new(_master() + tenant_id.bytes, normalised.encode(), hashlib.sha256).hexdigest()


def mask(value: str, visible: int = 4) -> str:
    value = value.strip()
    return "•" * max(len(value) - visible, 0) + value[-visible:]


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()
