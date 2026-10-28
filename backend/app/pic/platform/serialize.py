"""Convert ORM rows to JSON-safe dicts for API responses, audit snapshots and events."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import inspect

SKIP = {"tenant_id", "row_version"}
SECRET_SUFFIXES = ("_enc", "_hash", "sealed_payload", "password_hash")


def jsonable(value: Any) -> Any:
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


def row(obj: Any, only: Optional[Iterable[str]] = None, extra: Optional[dict] = None) -> dict:
    if obj is None:
        return None
    mapper = inspect(obj).mapper
    keys = list(only) if only else [c.key for c in mapper.column_attrs]
    out = {}
    for key in keys:
        if key in SKIP or key.endswith(SECRET_SUFFIXES):
            continue
        out[key] = jsonable(getattr(obj, key))
    if extra:
        out.update(jsonable(extra))
    return out


def rows(objs: Iterable[Any]) -> list:
    return [row(o) for o in objs]
