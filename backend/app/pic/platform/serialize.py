"""Convert ORM rows to JSON-safe dicts for API responses, audit snapshots and events."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import inspect

SKIP = {"tenant_id", "row_version"}
SECRET_SUFFIXES = ("_enc", "_hash", "sealed_payload", "password_hash")
_PASSTHROUGH = (str, int, float, bool, type(None))  # exact types returned unchanged (subclasses take the full path)
_KEYS: dict = {}  # mapper -> serialised column keys


def jsonable(value: Any) -> Any:
    kind = type(value)
    if kind in _PASSTHROUGH:  # fast path for the common scalars (large responses such as a 50k-material MRP run)
        return value
    if kind is dict:
        return {k: v if type(v) in _PASSTHROUGH else jsonable(v) for k, v in value.items()}
    if kind is list:
        return [v if type(v) in _PASSTHROUGH else jsonable(v) for v in value]
    if isinstance(value, (uuid.UUID,)):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        normalised = value.normalize()
        return format(normalised, "f") if normalised == normalised.to_integral() else str(normalised)
    if isinstance(value, bytes):
        return None
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    return value


def column_keys(mapper) -> list[str]:
    """The column keys ``row`` serialises for a mapper (all columns except SKIP and secrets), in mapper order."""
    keys = _KEYS.get(mapper)
    if keys is None:
        keys = _KEYS[mapper] = [c.key for c in mapper.column_attrs if c.key not in SKIP and not c.key.endswith(SECRET_SUFFIXES)]
    return keys


def row(obj: Any, only: Optional[Iterable[str]] = None, extra: Optional[dict] = None) -> dict:
    if obj is None:
        return None
    mapper = inspect(obj).mapper
    if only:
        keys = [key for key in only if key not in SKIP and not key.endswith(SECRET_SUFFIXES)]
    else:
        keys = column_keys(mapper)
    out = {}
    for key in keys:
        out[key] = jsonable(getattr(obj, key))
    if extra:
        out.update(jsonable(extra))
    return out


def rows(objs: Iterable[Any]) -> list:
    return [row(o) for o in objs]
