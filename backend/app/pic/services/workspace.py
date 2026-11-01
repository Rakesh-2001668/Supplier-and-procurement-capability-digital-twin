"""Workspace services behind the shared UI (Technical Document §16): per-user saved views, the Approvals and Documents tabs of an
object page, and bulk task decisions with a result per row."""
import uuid
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.pic.models import (
    AppUser, Asn, DocumentLink, ErpDocument, IntegrationMessage, PoTransmission, SavedView, Signature, Task,
)
from app.pic.platform import audit, workflow
from app.pic.platform.core import etag
from app.pic.platform.errors import Problem, not_found
from app.pic.services.common import principal

SCREENS = {"tasks", "requisitions", "purchase-orders", "invoices", "contracts", "sourcing", "suppliers", "materials", "receiving", "spend",
           "spend-analysis", "savings", "savings-pipeline", "kpis"}
MAX_VIEWS_PER_SCREEN = 25
MAX_FILTER_BYTES = 4000
MAX_BULK = 50


# ---------------------------------------------------------------- saved views
def _render(view: SavedView, me: uuid.UUID, owners: dict) -> dict:
    return {"id": str(view.id), "screen": view.screen, "name": view.name, "filters": view.filters, "shared": view.shared, "isDefault": view.is_default,
            "owner": owners.get(view.user_id), "mine": view.user_id == me, "etag": etag(view), "updatedAt": (view.updated_at or view.created_at).isoformat()}


def list_views(session: Session, screen: str) -> list[dict]:
    me = principal(session).user_id
    owners = {u.id: u.full_name for u in session.execute(select(AppUser)).scalars()}
    views = session.execute(select(SavedView).where(SavedView.screen == screen, or_(SavedView.user_id == me, SavedView.shared.is_(True)))
                            .order_by(SavedView.name)).scalars().all()
    return [_render(v, me, owners) for v in views]


def _validate(screen: str, name: str, filters: dict) -> None:
    if screen not in SCREENS:
        raise Problem(422, "UNKNOWN_SCREEN", f"Saved views exist for: {', '.join(sorted(SCREENS))}")
    if not name or not name.strip() or len(name.strip()) > 80:
        raise Problem(422, "INVALID_NAME", "Give the view a name of 1 to 80 characters")
    import json
    if len(json.dumps(filters, default=str)) > MAX_FILTER_BYTES:
        raise Problem(422, "FILTERS_TOO_LARGE", "A saved view holds filters only")
    if any(not isinstance(k, str) for k in filters):
        raise Problem(422, "INVALID_FILTERS", "Filters are a flat set of named values")


def _clear_default(session: Session, me: uuid.UUID, screen: str, keep: Optional[uuid.UUID] = None) -> None:
    for other in session.execute(select(SavedView).where(SavedView.user_id == me, SavedView.screen == screen, SavedView.is_default.is_(True))).scalars():
        if other.id != keep:
            other.is_default = False


def create_view(session: Session, screen: str, name: str, filters: dict, shared: bool = False, is_default: bool = False) -> SavedView:
    p = principal(session)
    name = (name or "").strip()
    _validate(screen, name, filters)
    existing = session.execute(select(SavedView).where(SavedView.user_id == p.user_id, SavedView.screen == screen)).scalars().all()
    if any(v.name.lower() == name.lower() for v in existing):
        raise Problem(409, "VIEW_EXISTS", f"You already have a view named {name} on this screen")
    if len(existing) >= MAX_VIEWS_PER_SCREEN:
        raise Problem(409, "TOO_MANY_VIEWS", f"A screen holds at most {MAX_VIEWS_PER_SCREEN} saved views per user")
    view = SavedView(tenant_id=p.tenant_id, user_id=p.user_id, screen=screen, name=name, filters=filters, shared=shared, is_default=is_default,
                     created_by=p.user_id)
    session.add(view)
    session.flush()
    if is_default:
        _clear_default(session, p.user_id, screen, keep=view.id)
    audit.record(session, "SAVED_VIEW", view.id, "CREATED", object_ref=f"{screen}/{name}", after={"screen": screen, "shared": shared, "default": is_default})
    return view


def get_own_view(session: Session, view_id: uuid.UUID) -> SavedView:
    view = session.get(SavedView, view_id)
    if view is None or (view.user_id != principal(session).user_id and not view.shared):
        raise not_found("Saved view", view_id)
    return view


def update_view(session: Session, view: SavedView, *, name: Optional[str], filters: Optional[dict], shared: Optional[bool],
                is_default: Optional[bool]) -> SavedView:
    p = principal(session)
    if view.user_id != p.user_id:
        raise Problem(403, "FORBIDDEN", "Only the owner changes a saved view", rule_ref="SAVED_VIEW")
    before = {"name": view.name, "shared": view.shared, "default": view.is_default}
    new_name = (name if name is not None else view.name).strip()
    _validate(view.screen, new_name, filters if filters is not None else view.filters)
    clash = session.execute(select(SavedView).where(SavedView.user_id == p.user_id, SavedView.screen == view.screen, SavedView.id != view.id)).scalars().all()
    if any(v.name.lower() == new_name.lower() for v in clash):
        raise Problem(409, "VIEW_EXISTS", f"You already have a view named {new_name} on this screen")
    view.name = new_name
    if filters is not None:
        view.filters = filters
    if shared is not None:
        view.shared = shared
    if is_default is not None:
        view.is_default = is_default
        if is_default:
            _clear_default(session, p.user_id, view.screen, keep=view.id)
    session.flush()
    audit.record(session, "SAVED_VIEW", view.id, "UPDATED", object_ref=f"{view.screen}/{view.name}", before=before,
                 after={"name": view.name, "shared": view.shared, "default": view.is_default})
    return view


def delete_view(session: Session, view: SavedView) -> None:
    if view.user_id != principal(session).user_id:
        raise Problem(403, "FORBIDDEN", "Only the owner deletes a saved view", rule_ref="SAVED_VIEW")
    audit.record(session, "SAVED_VIEW", view.id, "DELETED", object_ref=f"{view.screen}/{view.name}", before={"shared": view.shared})
    session.delete(view)
    session.flush()


# ---------------------------------------------------------------- object page: Approvals tab
def approvals_of(session: Session, object_type: str, obj) -> dict:
    """Every task of the object (open and decided) in order, with who decided and the approval chain the document carries."""
    tasks = session.execute(select(Task).where(Task.object_id == obj.id).order_by(Task.created_at, Task.sequence)).scalars().all()
    users = {u.id: u.full_name for u in session.execute(select(AppUser).where(AppUser.id.in_([t.completed_by for t in tasks if t.completed_by]))).scalars()}
    return {"objectType": object_type.upper(), "ref": getattr(obj, "number", None) or getattr(obj, "code", None) or str(obj.id),
            "chain": list(getattr(obj, "approval_chain", None) or []),
            "tasks": [{"id": str(t.id), "name": t.name, "kind": t.kind, "role": t.candidate_role, "sequence": t.sequence, "status": t.status,
                       "decision": t.decision, "comment": t.comment, "decidedBy": users.get(t.completed_by), "decidedAt": t.completed_at.isoformat() if t.completed_at else None,
                       "dueAt": t.due_at.isoformat() if t.due_at else None, "escalationLevel": t.escalation_level,
                       "createdAt": t.created_at.isoformat()} for t in tasks]}


# ---------------------------------------------------------------- object page: Documents tab
def documents_of(session: Session, object_type: str, obj) -> dict:
    """Printouts and transmissions, EDI / ERP documents, signed documents, supplier-supplied files and linked documents of the object.
    The platform keeps no free-form file store yet: ``attachments`` lists what the document itself references."""
    object_type = object_type.upper()
    ref = getattr(obj, "number", None) or getattr(obj, "code", None) or str(obj.id)
    items: list[dict] = []
    if object_type == "PURCHASE_ORDER":
        for t in session.execute(select(PoTransmission).where(PoTransmission.po_id == obj.id).order_by(PoTransmission.created_at)).scalars():
            items.append({"kind": "PRINTOUT" if t.channel in ("EMAIL", "PORTAL") else "EDI", "title": f"PO {ref} v{t.po_version} via {t.channel} ({t.format})",
                          "status": t.status, "at": (t.sent_at or t.created_at).isoformat(), "hash": t.document_sha256, "recipient": t.recipient,
                          "href": f"/purchase-orders/{ref}/transmissions/{t.id}/document"})
        for a in session.execute(select(Asn).where(Asn.po_id == obj.id)).scalars():
            for name in a.documents or []:
                items.append({"kind": "ATTACHMENT", "title": str(name), "status": a.status, "at": a.created_at.isoformat(), "source": f"ASN {a.number}"})
    if object_type == "CONTRACT":
        for sig in session.execute(select(Signature).where(Signature.contract_id == obj.id)).scalars():
            items.append({"kind": "SIGNED_DOCUMENT", "title": f"Signature by {sig.signer_name} ({sig.party})", "status": "SIGNED" if sig.signed_at else "PENDING",
                          "at": sig.signed_at.isoformat() if sig.signed_at else sig.created_at.isoformat(), "hash": sig.document_hash, "source": sig.envelope_ref})
    for m in session.execute(select(IntegrationMessage).where(IntegrationMessage.object_id == obj.id).order_by(IntegrationMessage.created_at)).scalars():
        items.append({"kind": "EDI" if m.target_system.upper().startswith("EDI") or "EDI" in m.message_type.upper() else "ERP_DOCUMENT",
                      "title": f"{m.message_type} to {m.target_system}" + (f" (ERP doc {m.erp_doc_no})" if m.erp_doc_no else ""), "status": m.status,
                      "at": (m.posted_at or m.created_at).isoformat(), "hash": m.payload_hash, "direction": m.direction})
    for d in session.execute(select(ErpDocument).where(ErpDocument.external_ref == ref).order_by(ErpDocument.created_at)).scalars():
        items.append({"kind": "ERP_DOCUMENT", "title": f"{d.system} {d.doc_type} {d.doc_no}", "status": "POSTED", "at": d.created_at.isoformat(), "amountMinor": d.amount_minor})
    links = session.execute(select(DocumentLink).where(or_(DocumentLink.from_id == obj.id, DocumentLink.to_id == obj.id)).order_by(DocumentLink.created_at)).scalars().all()
    for l in links:
        outgoing = l.from_id == obj.id
        items.append({"kind": "LINK", "title": f"{l.link_type.replace('_', ' ')} {l.to_ref if outgoing else l.from_ref}", "status": None, "at": l.created_at.isoformat(),
                      "linkedType": l.to_type if outgoing else l.from_type, "linkedRef": l.to_ref if outgoing else l.from_ref,
                      "linkedId": str(l.to_id if outgoing else l.from_id), "direction": "OUT" if outgoing else "IN"})
    items.sort(key=lambda i: i["at"])
    return {"objectType": object_type, "ref": ref, "items": items,
            "counts": {k: sum(1 for i in items if i["kind"] == k) for k in sorted({i["kind"] for i in items})}}


# ---------------------------------------------------------------- bulk task decisions
def bulk_decide(session: Session, items: list[dict]) -> dict:
    """Decide many tasks in one call. Each row runs in its own savepoint: a refusal (wrong role, SoD, missing comment, already
    decided) is reported on that row and the others still go through."""
    if not items:
        raise Problem(422, "EMPTY_BULK", "Select at least one task")
    if len(items) > MAX_BULK:
        raise Problem(422, "BULK_TOO_LARGE", f"At most {MAX_BULK} tasks per call")
    seen, results = set(), []
    for item in items:
        task_id, decision, comment = item["task_id"], item["decision"], item.get("comment")
        row = {"taskId": str(task_id), "decision": decision, "ok": False}
        if task_id in seen:
            row["error"] = {"code": "DUPLICATE_ROW", "detail": "The same task is listed twice"}
            results.append(row)
            continue
        seen.add(task_id)
        task = session.get(Task, task_id)
        row["objectRef"] = task.object_ref if task else None
        row["name"] = task.name if task else None
        if decision in ("REJECT", "RETURN") and not (comment and comment.strip()):
            row["error"] = {"code": "COMMENT_REQUIRED", "detail": f"A comment is required to {decision.lower()} a task"}
            results.append(row)
            continue
        savepoint = session.begin_nested()
        try:
            done = workflow.complete(session, task_id, decision, comment)
            savepoint.commit()
            row.update(ok=True, status=done.status)
        except Problem as problem:
            savepoint.rollback()
            row["error"] = {"code": problem.code, "detail": problem.detail}
        results.append(row)
    return {"results": results, "succeeded": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"])}
