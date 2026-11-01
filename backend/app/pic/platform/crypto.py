"""Field-level encryption with per-tenant keys derived from a versioned key ring.

Production deployments replace the master keys with Cloud KMS; the derivation keeps one tenant's ciphertext unreadable
with another tenant's key.

Key versioning: every ciphertext carries the id of the key that wrote it (``pk:<key id>:<Fernet token>``). New writes use
the active key; older ciphertext still decrypts with its own key, so a rotation never needs downtime. Data written before
key ids existed is a bare Fernet token and is read with key id ``v1`` (``PIC_FIELD_KEY``). The re-encryption job
(``python -m app.pic.tools.reencrypt``) moves old ciphertext to the active key; only then may an old key leave the ring.

Configuration: ``PIC_FIELD_KEY`` (always key ``v1``, also the blind-index key), ``PIC_FIELD_KEYS`` (``id:key,id:key``) and
``PIC_FIELD_ACTIVE_KEY`` (default: the first ``PIC_FIELD_KEYS`` entry, else ``v1``).
"""
import base64
import hashlib
import hmac
import re
import uuid
from functools import lru_cache

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.pic.config import get_settings

LEGACY_KEY_ID = "v1"
PREFIX = b"pk:"
KEY_ID = re.compile(r"^[A-Za-z0-9_.-]{1,16}$")


class UnknownKey(ValueError):
    """The ciphertext names a key that is not in the ring (it was retired too early or the configuration is wrong)."""


def _master_bytes(raw: str) -> bytes:
    data = raw.encode()
    try:
        key = base64.urlsafe_b64decode(data)  # exactly the pre-versioning derivation: existing ciphertext must stay readable
        if len(key) == 32:
            return key
    except Exception:
        pass
    return hashlib.sha256(data).digest()


@lru_cache(maxsize=8)
def _ring(field_key: str, field_keys: str, active: str) -> tuple[str, dict]:
    keys = {LEGACY_KEY_ID: _master_bytes(field_key)}
    first = None
    for entry in (field_keys or "").split(","):
        if not entry.strip():
            continue
        key_id, _, value = entry.strip().partition(":")
        if not KEY_ID.match(key_id) or not value:
            raise ValueError("PIC_FIELD_KEYS entries must look like id:key (id up to 16 of A-Za-z0-9_.-)")
        keys[key_id] = _master_bytes(value)
        first = first or key_id
    active_id = active or first or LEGACY_KEY_ID
    if active_id not in keys:
        raise UnknownKey(f"PIC_FIELD_ACTIVE_KEY {active_id} is not in PIC_FIELD_KEYS")
    return active_id, keys


def _config() -> tuple[str, dict]:
    settings = get_settings()
    return _ring(settings.field_key, settings.field_keys or "", settings.field_active_key or "")


def active_key_id() -> str:
    return _config()[0]


def key_ids() -> list[str]:
    return list(_config()[1])


def _master() -> bytes:
    """Blind-index key: PIC_FIELD_KEY, which never changes when keys are rotated (equality search keeps working)."""
    return _config()[1][LEGACY_KEY_ID]


def _fernet(tenant_id: uuid.UUID, purpose: str, key_id: str) -> Fernet:
    keys = _config()[1]
    if key_id not in keys:
        raise UnknownKey(f"Ciphertext was written with key {key_id}, which is not in the key ring")
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=tenant_id.bytes, info=purpose.encode()).derive(keys[key_id])
    return Fernet(base64.urlsafe_b64encode(derived))


def split(token) -> tuple[str, bytes]:
    """(key id, bare Fernet token) of a stored ciphertext; legacy bare tokens belong to key v1."""
    raw = bytes(token)
    if raw.startswith(PREFIX):
        key_id, _, bare = raw[len(PREFIX):].partition(b":")
        return key_id.decode(), bare
    return LEGACY_KEY_ID, raw


def key_id_of(token) -> str:
    return split(token)[0]


def encrypt(tenant_id: uuid.UUID, purpose: str, plaintext: str) -> bytes:
    key_id = active_key_id()
    return PREFIX + key_id.encode() + b":" + _fernet(tenant_id, purpose, key_id).encrypt(plaintext.encode())


def decrypt(tenant_id: uuid.UUID, purpose: str, token: bytes) -> str:
    key_id, bare = split(token)
    return _fernet(tenant_id, purpose, key_id).decrypt(bare).decode()


def needs_rotation(token) -> bool:
    return key_id_of(token) != active_key_id()


def rotate(tenant_id: uuid.UUID, purpose: str, token) -> bytes:
    """The same plaintext under the active key (the input unchanged when it already uses it)."""
    return token if not needs_rotation(token) else encrypt(tenant_id, purpose, decrypt(tenant_id, purpose, token))


def blind_index(tenant_id: uuid.UUID, value: str) -> str:
    """Keyed hash for equality search on encrypted values (e.g. duplicate GSTIN check)."""
    normalised = value.strip().upper().replace(" ", "")
    return hmac.new(_master() + tenant_id.bytes, normalised.encode(), hashlib.sha256).hexdigest()


def mask(value: str, visible: int = 4) -> str:
    value = value.strip()
    return "•" * max(len(value) - visible, 0) + value[-visible:]


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()
