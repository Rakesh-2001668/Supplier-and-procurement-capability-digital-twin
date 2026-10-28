"""AIX-02 Copilot with the answer contract (Technical Document §13.3).

Numbers come from tool queries (SQL), never from a model. Retrieval runs inside the caller's
tenant transaction (RLS) and is filtered by the caller's scopes before anything is phrased.
If PIC_LLM_GATEWAY_URL is configured, the gateway may rephrase the tool output; without it the
answer is assembled deterministically and says so in `explanation.method`.
"""
import re
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.models import (
    Contract, Invoice, InvoiceException, PurchaseOrder, Requisition, Scorecard, SourcingEvent, SpendLine, Supplier, TwinSnapshot,
)
from app.pic.platform import clock, workflow
from app.pic.platform.money import crore, fmt_inr
from app.pic.services import insight, savings

DOC_PATTERNS = [
    (re.compile(r"\bPO-\d+\b", re.I), PurchaseOrder, "PURCHASE_ORDER", "/pic/purchase-orders/{}"),
    (re.compile(r"\bREQ-\d+\b", re.I), Requisition, "REQUISITION", "/pic/requisitions/{}"),
    (re.compile(r"\bRFQ-\d+\b", re.I), SourcingEvent, "SOURCING_EVENT", "/pic/sourcing/{}"),
    (re.compile(r"\bSA-\d+\b", re.I), Contract, "CONTRACT", "/pic/contracts/{}"),
    (re.compile(r"\b(?:INV|HTS|KD)[-/][\w/-]+\b", re.I), Invoice, "INVOICE", "/pic/invoices/{}"),
]


def _contract(answer: str, evidence: list, score: float, method: str, action: Optional[dict], principal, scopes: list[str]) -> dict:
    label = "high" if score >= 0.8 else "medium" if score >= 0.5 else "low"
    return {
        "answer": answer,
        "evidence": evidence,
        "confidence": {"score": score, "label": label,
                       "note": "Computed from live transactions" if score >= 0.8 else "Partial match to your question; check the evidence"},
        "explanation": {"method": method, "modelVersion": "copilot-rules-v1", "dataFreshness": clock.now().isoformat()},
        "recommendedAction": action,
        "permission": {"role": principal.roles[0] if principal.roles else None, "autonomy": "L1", "scopes": scopes},
    }


def ask(session: Session, principal, question: str) -> dict:
    q = question.strip()
    supplier_user = "SUPPLIER_USER" in principal.roles
    for pattern, model, object_type, link in DOC_PATTERNS:
        match = pattern.search(q)
        if match:
            return _document(session, principal, model, object_type, link, match.group(0).upper(), supplier_user)
    if supplier_user:
        return _contract("I can answer questions about your own documents. Mention a PO, invoice or RFQ number.", [], 0.4,
                         "intent routing; supplier users are limited to their own documents", None, principal, ["supplier:portal"])
    text = q.lower()
    if any(w in text for w in ("task", "approval", "pending", "inbox", "waiting")):
        return _tasks(session, principal)
    if "spend" in text or "maverick" in text:
        return _spend(session, principal, "supplier" if "supplier" in text else "category")
    if "saving" in text:
        return _savings(session, principal)
    if "exception" in text or "blocked invoice" in text or "payment block" in text:
        return _exceptions(session, principal)
    if "touchless" in text or "first-pass" in text or "first pass" in text or "kpi" in text:
        return _kpis(session, principal)
    for sup in session.execute(select(Supplier)).scalars():
        if sup.code.lower() in text or sup.legal_name.lower().split()[0] in text:
            return _supplier(session, principal, sup)
    return _contract(
        "I could not match that to a document, supplier or metric. Try: “status of PO-77410”, “spend by supplier”, "
        "“savings”, “open invoice exceptions”, “my approvals”, or a supplier name.",
        [], 0.2, "intent routing (no match)", None, principal, ["pic:read"])


def _document(session, principal, model, object_type, link, ref, supplier_user) -> dict:
    obj = session.execute(select(model).where(model.number == ref)).scalar_one_or_none()
    if obj is None or (supplier_user and getattr(obj, "supplier_id", None) != principal.supplier_id):
        return _contract(f"{ref} was not found or is not visible to you.", [], 0.6, "document lookup", None, principal, ["pic:read"])
    instance = workflow.find(session, object_type, obj.id)
    step = None
    if instance:
        history = workflow.history(session, instance)
        current = [p for p in history["path"] if p["step"] == instance.current_step]
        step = current[-1] if current else None
    parts = [f"{ref} is {obj.status.replace('_', ' ').lower()}."]
    if object_type == "PURCHASE_ORDER":
        parts.append(f"Value {fmt_inr(obj.total_minor)}, risk score {obj.risk_score}, "
                     f"{'released touchless' if obj.touchless else 'released after approval' if obj.released_at else 'not released'}.")
    if object_type == "INVOICE":
        open_exc = session.execute(select(func.count()).select_from(InvoiceException).where(
            InvoiceException.invoice_id == obj.id, InvoiceException.status == "OPEN")).scalar()
        parts.append(f"Gross {fmt_inr(obj.gross_minor)}; {open_exc} open exception(s); ERP document {obj.erp_doc_no or 'not posted yet'}.")
    if step:
        parts.append(f"Workflow position: {step['step']} “{step['name']}” ({step['status'].lower()}{': ' + step['outcome'] if step.get('outcome') else ''}).")
    open_tasks = [t for t in workflow.open_tasks_for(session, principal) if t.object_id == obj.id]
    # Invoices are linked by id: supplier invoice numbers can contain "/".
    target = link.format(obj.id if object_type == "INVOICE" else ref)
    action = {"label": f"Open {ref}", "deepLink": target, "requiresHuman": bool(open_tasks)}
    if open_tasks:
        parts.append(f"You have {len(open_tasks)} open task(s) on it.")
    return _contract(" ".join(parts), [{"type": object_type, "ref": ref, "link": target}], 0.95,
                     "document lookup + workflow history (SQL)", action, principal, ["pic:read"])


def _tasks(session, principal) -> dict:
    tasks = workflow.open_tasks_for(session, principal)
    if not tasks:
        return _contract("You have no open tasks.", [], 0.95, "task inbox query", None, principal, ["tasks:work"])
    overdue = [t for t in tasks if t.due_at and t.due_at < clock.now()]
    lines = "; ".join(f"{t.object_ref} ({t.candidate_role.replace('_', ' ').lower()})" for t in tasks[:6])
    return _contract(f"You have {len(tasks)} open task(s), {len(overdue)} overdue: {lines}.",
                     [{"type": t.object_type, "ref": t.object_ref, "link": "/pic/tasks"} for t in tasks[:6]], 0.95,
                     "task inbox query", {"label": "Open task inbox", "deepLink": "/pic/tasks", "requiresHuman": True}, principal, ["tasks:work"])


def _spend(session, principal, dim) -> dict:
    if "spend:read" not in principal.scopes:
        return _contract("Spend analytics need the spend:read permission.", [], 0.9, "permission check", None, principal, [])
    cube = savings.spend_cube(session, [dim])
    rows = sorted(cube["rows"], key=lambda r: -r["spendMinor"])[:5]
    top = ", ".join(f"{r[dim]} {fmt_inr(r['spendMinor'])}" for r in rows) or "no posted spend yet"
    return _contract(f"Posted spend is {fmt_inr(cube['totalMinor'])}; contracted {cube['contractedPct']}%, maverick {cube['maverickPct']}%. "
                     f"Top by {dim}: {top}.", [{"type": "DATASET", "ref": f"spend_cube[{dim}]", "link": "/pic/spend"}], 0.9,
                     "spend cube aggregation (SQL)", {"label": "Open spend analysis", "deepLink": "/pic/spend", "requiresHuman": False},
                     principal, ["spend:read"])


def _savings(session, principal) -> dict:
    register = savings.register(session)
    if not register:
        return _contract("No savings initiatives yet.", [], 0.9, "savings register query", None, principal, ["pic:read"])
    text = "; ".join(f"{r['number']} {r['stage'].lower()}: negotiated {r['negotiatedCr']} Cr, avoidance {r['avoidanceCr']} Cr, "
                     f"realised {r['realisedCr']} Cr" for r in register)
    return _contract(text + ". Realised savings count only posted invoices.",
                     [{"type": "DATASET", "ref": r["number"], "link": "/pic/savings"} for r in register], 0.95,
                     "savings ledger query", {"label": "Open savings register", "deepLink": "/pic/savings", "requiresHuman": False},
                     principal, ["pic:read"])


def _exceptions(session, principal) -> dict:
    rows = session.execute(select(InvoiceException, Invoice).join(Invoice, Invoice.id == InvoiceException.invoice_id)
                           .where(InvoiceException.status == "OPEN")).all()
    if not rows:
        return _contract("There are no open invoice exceptions.", [], 0.95, "invoice exception query", None, principal, ["pic:read"])
    text = "; ".join(f"{inv.number}: {exc.type.lower()} – {exc.suggested_action}" for exc, inv in rows[:6])
    return _contract(f"{len(rows)} open exception(s): {text}.",
                     [{"type": "INVOICE", "ref": inv.number, "link": f"/pic/invoices/{inv.id}"} for _, inv in rows[:6]], 0.9,
                     "invoice exception query", {"label": "Resolve exceptions", "deepLink": "/pic/invoices", "requiresHuman": True},
                     principal, ["invoice:resolve"])


def _kpis(session, principal) -> dict:
    k = insight.dashboard(session, principal)
    return _contract(f"Touchless PO {k['purchasing']['touchlessPct'] or '–'}%, first-pass match {k['payables']['firstPassMatchPct'] or '–'}%, "
                     f"ERP posting success {k['integration']['postingSuccessPct'] or '–'}%, average PR approval "
                     f"{k['requisitions']['avgApprovalHours'] or '–'} h.", [{"type": "DATASET", "ref": "kpi", "link": "/pic"}], 0.9,
                     "KPI aggregation (SQL)", {"label": "Open command centre", "deepLink": "/pic", "requiresHuman": False}, principal, ["pic:read"])


def _supplier(session, principal, sup: Supplier) -> dict:
    twin = session.execute(select(TwinSnapshot).where(TwinSnapshot.supplier_id == sup.id)).scalars().first()
    card = session.execute(select(Scorecard).where(Scorecard.supplier_id == sup.id).order_by(Scorecard.period.desc())).scalars().first()
    parts = [f"{sup.legal_name} ({sup.code}) is {sup.status.lower()}."]
    if twin:
        parts.append(f"Digital twin: free capacity {twin.free_capacity_per_month:,.0f}/month, late-delivery probability {twin.late_delivery_prob}, "
                     f"trust {twin.trust_score}, evidence {twin.evidence_level}.")
    if card:
        parts.append(f"Scorecard {card.period}: OTIF {card.otif_pct or '–'}%, PPM {card.ppm or '–'}, invoice accuracy {card.invoice_accuracy_pct or '–'}%.")
    return _contract(" ".join(parts), [{"type": "DATASET", "ref": sup.code, "link": f"/pic/suppliers/{sup.code}"}], 0.9,
                     "supplier 360 query (twin + scorecard)", {"label": f"Open {sup.code} 360", "deepLink": f"/pic/suppliers/{sup.code}",
                                                               "requiresHuman": False}, principal, ["pic:read"])
