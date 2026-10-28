"""Cursor pagination (Technical Document §10.1): stable order by (created_at desc, id desc), max page 200."""
import base64
import json
import uuid
from datetime import datetime
from typing import Any, Callable, Optional

from fastapi import Query
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.pic.platform.errors import Problem
from app.pic.platform.serialize import row

MAX_PAGE = 200


class Page:
    def __init__(self, cursor: Optional[str] = Query(default=None, description="Opaque cursor from nextCursor"),
                 limit: int = Query(default=50, ge=1, le=MAX_PAGE)):
        self.cursor = cursor
        self.limit = limit


def _decode(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(data["t"]), uuid.UUID(data["i"])
    except Exception:
        raise Problem(400, "INVALID_CURSOR", "The cursor is not valid; start again without it")


def _encode(created_at: datetime, id_: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(json.dumps({"t": created_at.isoformat(), "i": str(id_)}).encode()).decode()


def paginate(session: Session, query, model, page: Page, render: Optional[Callable[[Any], dict]] = None) -> dict:
    if page.cursor:
        created, id_ = _decode(page.cursor)
        query = query.where(or_(model.created_at < created, and_(model.created_at == created, model.id < id_)))
    items = session.execute(query.order_by(model.created_at.desc(), model.id.desc()).limit(page.limit + 1)).scalars().all()
    more = len(items) > page.limit
    items = items[: page.limit]
    return {"items": [render(i) if render else row(i) for i in items],
            "nextCursor": _encode(items[-1].created_at, items[-1].id) if more and items else None}
