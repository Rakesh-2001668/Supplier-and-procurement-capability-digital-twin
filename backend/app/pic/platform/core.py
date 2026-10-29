"""Numbering, idempotency, lineage, state machines and concurrency checks."""
import hashlib
import json
import re
import uuid
from collections import deque
from typing import Any, Iterable, Optional

from sqlalchemy import or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, current_user
from app.pic.models import DocumentLink, IdempotencyRecord, NumberRange
from app.pic.platform import audit
from app.pic.platform.errors import Problem, illegal_transition
from app.pic.platform.serialize import jsonable


# ---------------------------------------------------------------- numbering
def next_number(session: Session, object_type: str) -> str:
    """Gap-free per-tenant document numbers (REQ-2311, PO-77410, ...)."""
    result = session.execute(
        update(NumberRange)
        .where(NumberRange.object_type == object_type)
        .values(next_value=NumberRange.next_value + 1)
        .returning(NumberRange.prefix, NumberRange.next_value, NumberRange.padding)
        .execution_options(synchronize_session=False)
    ).first()
    if result is None:
        raise Problem(500, "NUMBER_RANGE_MISSING", f"No number range configured for {object_type}")
    prefix, next_value, padding = result
    value = next_value - 1
    return f"{prefix}{str(value).zfill(padding) if padding else value}"


def next_numbers(session: Session, object_type: str, count: int) -> list[str]:
    """``count`` consecutive numbers in one update: the same numbers as ``count`` calls of ``next_number`` (bulk creation)."""
    if count <= 0:
        return []
    result = session.execute(
        update(NumberRange)
        .where(NumberRange.object_type == object_type)
        .values(next_value=NumberRange.next_value + count)
        .returning(NumberRange.prefix, NumberRange.next_value, NumberRange.padding)
        .execution_options(synchronize_session=False)
    ).first()
    if result is None:
        raise Problem(500, "NUMBER_RANGE_MISSING", f"No number range configured for {object_type}")
    prefix, next_value, padding = result
    return [f"{prefix}{str(value).zfill(padding) if padding else value}" for value in range(next_value - count, next_value)]


# ---------------------------------------------------------------- idempotency
def _request_hash(body: Any) -> str:
    return hashlib.sha256(json.dumps(jsonable(body), sort_keys=True, default=str).encode()).hexdigest()


class Idempotent:
    """Every POST accepts an Idempotency-Key; a replay returns the original response (§10.1)."""

    def __init__(self, session: Session, scope: str, key: Optional[str], body: Any):
        self.session = session
        self.scope = scope
        self.key = key
        self.request_hash = _request_hash(body)
        self.replay: Optional[dict] = None
        if key:
            self._reserve()

    def _reserve(self) -> None:
        tenant_id = current_tenant(self.session)
        inserted = self.session.execute(
            insert(IdempotencyRecord)
            .values(tenant_id=tenant_id, scope=self.scope, key=self.key, request_hash=self.request_hash)
            .on_conflict_do_nothing()
            .returning(IdempotencyRecord.key)
        ).first()
        if inserted:
            return
        existing = self.session.get(IdempotencyRecord, (tenant_id, self.scope, self.key))
        if existing.request_hash != self.request_hash:
            raise Problem(422, "IDEMPOTENCY_KEY_REUSED", "This Idempotency-Key was already used with a different request body")
        if existing.response is None:
            raise Problem(409, "REQUEST_IN_PROGRESS", "A request with this Idempotency-Key is still being processed")
        self.replay = dict(existing.response, replayed=True)

    def store(self, response: dict, status_code: int = 200) -> dict:
        response = jsonable(response)
        if self.key:
            record = self.session.get(IdempotencyRecord, (current_tenant(self.session), self.scope, self.key))
            record.response = response
            record.status_code = status_code
        return response


# ---------------------------------------------------------------- lineage
def link(session: Session, from_type: str, from_id: uuid.UUID, from_ref: str, to_type: str, to_id: uuid.UUID,
         to_ref: str, link_type: str, from_line: Optional[int] = None, to_line: Optional[int] = None) -> None:
    session.add(DocumentLink(
        id=uuid.uuid7(), tenant_id=current_tenant(session), from_type=from_type, from_id=from_id, from_ref=from_ref,
        from_line=from_line, to_type=to_type, to_id=to_id, to_ref=to_ref, to_line=to_line, link_type=link_type,
        created_by=current_user(session),
    ))


def link_many(session: Session, from_type: str, from_id: uuid.UUID, from_ref: str,
              targets: Iterable[tuple[str, uuid.UUID, str]], link_type: str, batch: int = 2000) -> int:
    """``link`` from one document to many (to_type, to_id, to_ref) targets as multi-row INSERTs (e.g. an MRP run's orders)."""
    tenant_id, user_id = current_tenant(session), current_user(session)
    rows = [{"id": uuid.uuid7(), "tenant_id": tenant_id, "from_type": from_type, "from_id": from_id, "from_ref": from_ref,
             "from_line": None, "to_type": to_type, "to_id": to_id, "to_ref": to_ref, "to_line": None, "link_type": link_type,
             "created_by": user_id} for to_type, to_id, to_ref in targets]
    return insert_rows(session, DocumentLink.__table__, rows, batch)


_TYPE_MODIFIERS = re.compile(r"\(.*?\)")


def insert_rows(session: Session, table, rows: list[dict], batch: int = 5000) -> int:
    """Bulk INSERT, one ``INSERT ... SELECT * FROM unnest(<one array per column>)`` per batch.

    Stores the same values as ``session.execute(insert(table), rows)``: columns missing from the rows get their Python
    defaults (scalar or callable, per row) or are left to the database; each value goes through the column type's bind
    processing for this dialect. Arrays are cast to the unmodified base type (VARCHAR, NUMERIC), so the column's own
    length/scale rules apply on assignment as for a plain INSERT. Every row must have the same keys. Bulk loads of tens of
    thousands of rows (MRP planned orders, exceptions, links) send a few array parameters instead of one bind per value.
    """
    if not rows:
        return 0
    keys = set(rows[0])
    if any(set(r) != keys for r in rows):
        raise ValueError("insert_rows: every row needs the same keys")
    dialect = session.get_bind().dialect
    quote = dialect.identifier_preparer
    columns = []
    for column in table.columns:
        if column.key in keys:
            columns.append((column, None))
        elif column.default is not None:
            if not (column.default.is_scalar or column.default.is_callable):
                raise ValueError(f"insert_rows: unsupported default on {table.name}.{column.key}")
            columns.append((column, column.default))
    casts = ", ".join(f"CAST(:c{i} AS {_TYPE_MODIFIERS.sub('', column.type.compile(dialect=dialect))}[])"
                      for i, (column, _) in enumerate(columns))
    statement = text(f"INSERT INTO {quote.format_table(table)} ({', '.join(quote.quote(c.name) for c, _ in columns)}) "
                     f"SELECT * FROM unnest({casts})")
    processors = [column.type.bind_processor(dialect) for column, _ in columns]
    for start in range(0, len(rows), batch):
        part = rows[start:start + batch]
        params = {}
        for i, (column, default) in enumerate(columns):
            if default is None:
                values = [r[column.key] for r in part]
            elif default.is_scalar:
                values = [default.arg] * len(part)
            else:
                values = [default.arg(None) for _ in part]
            params[f"c{i}"] = [processors[i](v) for v in values] if processors[i] else values
        session.execute(statement, params)
    return len(rows)


def lineage(session: Session, object_type: str, object_id: uuid.UUID, max_nodes: int = 200) -> dict:
    """Breadth-first walk of upstream and downstream document links."""
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    seen_edges: set = set()
    queue = deque([(object_type, object_id)])
    visited = set()
    while queue and len(visited) < max_nodes:
        otype, oid = queue.popleft()
        if (otype, oid) in visited:
            continue
        visited.add((otype, oid))
        links = session.execute(select(DocumentLink).where(or_(
            (DocumentLink.from_type == otype) & (DocumentLink.from_id == oid),
            (DocumentLink.to_type == otype) & (DocumentLink.to_id == oid),
        ))).scalars()
        for l in links:
            nodes[f"{l.from_type}:{l.from_id}"] = {"type": l.from_type, "id": str(l.from_id), "ref": l.from_ref}
            nodes[f"{l.to_type}:{l.to_id}"] = {"type": l.to_type, "id": str(l.to_id), "ref": l.to_ref}
            if l.id not in seen_edges:
                seen_edges.add(l.id)
                edges.append({"from": l.from_ref, "fromLine": l.from_line, "to": l.to_ref, "toLine": l.to_line,
                              "type": l.link_type})
            queue.append((l.from_type, l.from_id))
            queue.append((l.to_type, l.to_id))
    return {"nodes": list(nodes.values()), "edges": edges}


def upstream_chain(session: Session, object_type: str, object_id: uuid.UUID) -> list[tuple[str, str]]:
    """Predecessor (reference, type) pairs, nearest first (e.g. REQ, SA, then PLO, RFQ for a PO)."""
    chain: list[tuple[str, str]] = []
    frontier = [(object_type, object_id)]
    seen = set()
    while frontier:
        nxt = []
        for otype, oid in frontier:
            for l in session.execute(select(DocumentLink).where(DocumentLink.to_type == otype, DocumentLink.to_id == oid)).scalars():
                if (l.from_type, l.from_id) in seen:
                    continue
                seen.add((l.from_type, l.from_id))
                chain.append((l.from_ref, l.from_type))
                nxt.append((l.from_type, l.from_id))
        frontier = nxt
    return chain


# ---------------------------------------------------------------- state machines
class StateMachine:
    """Explicit document state machine. Illegal transitions return 409 (§6)."""

    def __init__(self, object_type: str, transitions: dict[tuple[str, str], str], field: str = "status"):
        self.object_type = object_type
        self.transitions = transitions
        self.field = field

    def can(self, status: str, command: str) -> bool:
        return (status, command) in self.transitions

    def apply(self, session: Session, doc: Any, command: str, *, reason: Optional[str] = None,
              rule_set_version: Optional[str] = None, ai_ref: Optional[str] = None, extra_after: Optional[dict] = None) -> str:
        current = getattr(doc, self.field)
        key = (current, command)
        if key not in self.transitions:
            raise illegal_transition(self.object_type, getattr(doc, "number", str(doc.id)), current, command)
        setattr(doc, self.field, self.transitions[key])
        after = {self.field: self.transitions[key]}
        if extra_after:
            after.update(extra_after)
        audit.record(session, self.object_type, doc.id, command.upper(), object_ref=getattr(doc, "number", None),
                     before={self.field: current}, after=after, reason=reason, rule_set_version=rule_set_version, ai_ref=ai_ref)
        return self.transitions[key]


def check_if_match(doc: Any, if_match: Optional[str]) -> None:
    """ETag/If-Match optimistic concurrency: 412 on a stale write (§10.1)."""
    if if_match is None:
        return
    expected = if_match.strip().strip('"').removeprefix("W/").strip('"')
    if expected != str(doc.row_version):
        raise Problem(412, "STALE_WRITE", f"Document is at version {doc.row_version}; you sent {expected}")


def etag(doc: Any) -> str:
    return f'"{doc.row_version}"'
