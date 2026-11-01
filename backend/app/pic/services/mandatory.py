"""Rule-configurable mandatory fields per document type (TD §6, P14, BP M13 "rule engine for thresholds, mandatory fields, tolerances").

Rule ``MANDATORY-FIELDS`` lists, per document type, the header and line fields that must be filled:

    {"documents": {"REQUISITION": {"header": ["purpose_code"], "lines": ["description", "need_date"]}, "PO_RELEASE": {...}, ...}}

The rule is resolved by scope (company code, plant, category, purchase type, supplier group; the most specific version on the
business date wins and replaces the tenant default entirely for that scope). It is enforced where the document becomes binding:
requisition submit, PO routing / release, goods-receipt post, invoice capture and supplier registration. A document that misses
fields is refused with 422 ``MANDATORY_FIELDS_MISSING`` listing every missing field (``missingFields``) so the form can mark them.
The policy simulator (ADM-03) evaluates the same function (``evaluate``)."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import RuleSet
from app.pic.platform import audit, clock, rules
from app.pic.platform.errors import Problem, rule_violation
from app.pic.services import p2p_rules

KEY = "MANDATORY-FIELDS"

# Fields that can be made mandatory, per document type. Header fields are on the document, line fields on each of its lines.
CATALOGUE: dict[str, dict[str, tuple[str, ...]]] = {
    "REQUISITION": {
        "header": ("purpose_code", "purpose_text", "origin_ref", "plant"),
        "lines": ("description", "material_group", "category", "qty", "uom", "price_est_minor", "need_date", "account_assignment_type",
                  "account_assignment_code", "storage_location", "preferred_supplier_id", "material_id", "catalogue_item_id"),
    },
    "PO_RELEASE": {
        "header": ("payment_terms", "incoterms", "purpose_code", "contract_id", "currency"),
        "lines": ("gst_rate", "hsn_code", "need_date", "plant", "storage_location", "account_assignment_type", "account_assignment_code",
                  "uom", "material_id", "description", "material_group"),
    },
    "GR_POST": {
        "header": ("delivery_note", "asn", "posting_date"),
        "lines": ("qty", "batch", "storage_location", "expiry", "serials"),
    },
    "INVOICE_CAPTURE": {
        "header": ("supplier_invoice_no", "invoice_date", "irn", "company_code"),
        "lines": ("po", "po_line", "qty", "unit_price", "hsn", "gst_rate", "description"),
    },
    "SUPPLIER_REGISTER": {
        "header": ("legal_name", "gstin", "pan", "state_code", "contact_email", "categories", "payment_terms", "incoterms", "segment"),
        "lines": (),
    },
}
LABELS = {"REQUISITION": "Requisition (submit)", "PO_RELEASE": "Purchase order (release)", "GR_POST": "Goods receipt (post)",
          "INVOICE_CAPTURE": "Invoice (capture)", "SUPPLIER_REGISTER": "Supplier (register)"}


def blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def required_fields(body: dict, document: str) -> tuple[list[str], list[str]]:
    spec = ((body or {}).get("documents") or {}).get(document) or {}
    return list(spec.get("header") or []), list(spec.get("lines") or [])


def evaluate(body: dict, document: str, header: dict, lines: Optional[Iterable[dict]] = None) -> list[str]:
    """Missing fields of a document under a rule body: ``field`` for a header field, ``line <no>: field`` for a line field."""
    header_fields, line_fields = required_fields(body, document)
    missing = [f for f in header_fields if blank(header.get(f))]
    for index, line in enumerate(lines or [], start=1):
        label = line.get("_line_no") or index * 10
        missing += [f"line {label}: {f}" for f in line_fields if blank(line.get(f))]
    return missing


def resolve(session: Session, **scope: Optional[str]) -> rules.Rule:
    return p2p_rules.rule(session, KEY, **scope)


def check(session: Session, document: str, header: dict, lines: Optional[Iterable[dict]] = None, **scope: Optional[str]) -> None:
    """Refuse the document (422 MANDATORY_FIELDS_MISSING) when the resolved rule lists fields it does not have."""
    if document not in CATALOGUE:
        raise ValueError(f"unknown document type {document}")
    rule = resolve(session, **{k: v for k, v in scope.items() if v})
    missing = evaluate(rule.body, document, header, list(lines or []))
    if missing:
        raise Problem(422, "MANDATORY_FIELDS_MISSING", f"{LABELS[document]}: {len(missing)} mandatory field(s) missing: {', '.join(missing)}",
                      rule_ref=rule.ref, document=document, missingFields=missing)


def dominant(items: Iterable[tuple[Optional[str], Optional[str], int]]) -> tuple[Optional[str], Optional[str]]:
    """(category, purchase type) of the largest value, the same scope reading as the requisition route (DMN-01)."""
    by_category: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for category, purchase_type, value in items:
        if category:
            by_category[category] = by_category.get(category, 0) + value
        if purchase_type:
            by_type[purchase_type] = by_type.get(purchase_type, 0) + value
    category = max(sorted(by_category), key=lambda k: by_category[k]) if by_category else None
    purchase_type = "ASSET" if "ASSET" in by_type else (max(sorted(by_type), key=lambda k: by_type[k]) if by_type else None)
    return category, purchase_type


def plain(obj: Any, names: Iterable[str]) -> dict:
    """A document's fields by name (model attributes), for ``check``."""
    return {n: getattr(obj, n, None) for n in names}


# ---------------------------------------------------------------- admin editor
def catalogue_view() -> dict:
    return {doc: {"label": LABELS[doc], "header": list(spec["header"]), "lines": list(spec["lines"])} for doc, spec in CATALOGUE.items()}


def normalise(body: dict) -> dict:
    """Validate an editor body: known document types and fields only; unknown ones are refused, duplicates collapse."""
    documents = (body or {}).get("documents")
    if not isinstance(documents, dict):
        raise rule_violation("The rule body needs a 'documents' object", KEY)
    out: dict[str, dict] = {}
    for document, spec in documents.items():
        if document not in CATALOGUE:
            raise rule_violation(f"Unknown document type {document}; known: {', '.join(CATALOGUE)}", KEY)
        spec = spec or {}
        entry = {}
        for part in ("header", "lines"):
            fields = spec.get(part) or []
            unknown = [f for f in fields if f not in CATALOGUE[document][part]]
            if unknown:
                raise rule_violation(f"{document} {part}: unknown field(s) {', '.join(map(str, unknown))}; "
                                     f"allowed: {', '.join(CATALOGUE[document][part]) or 'none'}", KEY, unknown=[str(u) for u in unknown])
            entry[part] = list(dict.fromkeys(fields))
        out[document] = entry
    return {"documents": out}


def save_version(session: Session, principal, *, body: dict, effective_from: Optional[date] = None, company_code: Optional[str] = None,
                 plant: Optional[str] = None, category: Optional[str] = None, purchase_type: Optional[str] = None,
                 supplier_group: Optional[str] = None, reason: Optional[str] = None) -> RuleSet:
    """A new effective-dated version of MANDATORY-FIELDS for a scope (P14: versions are never edited). The version label is generated;
    a second version for the same scope and date supersedes the first (it wins by creation order)."""
    clean = normalise(body)
    when = effective_from or clock.today()
    existing = session.execute(select(RuleSet).where(RuleSet.key == KEY)).scalars().all()
    version = f"{when:%Y.%m.%d}.{len(existing) + 1}"
    while any(r.version == version for r in existing):
        version += "x"
    scope = {"company_code": company_code or None, "plant": plant or None, "category": category or None,
             "purchase_type": purchase_type or None, "supplier_group": supplier_group or None}
    rule = RuleSet(id=uuid.uuid7(), tenant_id=principal.tenant_id, created_by=principal.user_id, key=KEY, version=version,
                   effective_from=when, body=clean, description=reason or "Mandatory fields (admin editor)", **scope)
    session.add(rule)
    session.flush()
    audit.record(session, "RULE_SET", rule.id, "VERSION_CREATED", object_ref=f"{KEY}@{version}",
                 after={"scope": {k: v for k, v in scope.items() if v}, "effectiveFrom": when.isoformat(), "body": clean}, reason=reason)
    return rule


def scope_view(rule: RuleSet) -> dict:
    return {f: getattr(rule, f) for f in rules.SCOPE_FIELDS if getattr(rule, f)}


def versions(session: Session) -> list[dict]:
    rows = session.execute(select(RuleSet).where(RuleSet.key == KEY).order_by(RuleSet.effective_from.desc(), RuleSet.created_at.desc())).scalars()
    return [{"version": r.version, "effectiveFrom": r.effective_from.isoformat(), "effectiveTo": r.effective_to.isoformat() if r.effective_to else None,
             "scope": scope_view(r), "body": r.body, "description": r.description} for r in rows]
