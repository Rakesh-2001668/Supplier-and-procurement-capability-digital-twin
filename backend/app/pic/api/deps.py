"""Shared API helpers: one tenant-scoped transaction per request and idempotent POSTs."""
from contextlib import contextmanager
from typing import Any, Optional

from fastapi import Header

from app.pic.db import tenant_tx
from app.pic.platform.auth import Principal
from app.pic.platform.core import Idempotent


@contextmanager
def uow(principal: Principal):
    with tenant_tx(principal.tenant_id, principal.user_id, principal) as session:
        yield session


def idempotency_key(key: Optional[str] = Header(default=None, alias="Idempotency-Key")) -> Optional[str]:
    return key


def body_of(model: Any) -> dict:
    return model.model_dump(mode="json") if hasattr(model, "model_dump") else dict(model or {})


def idempotent(session, scope: str, key: Optional[str], body: Any) -> Idempotent:
    return Idempotent(session, scope, key, body_of(body))
