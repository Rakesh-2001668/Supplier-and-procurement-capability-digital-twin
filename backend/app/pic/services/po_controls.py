"""Purchase-order controls of wave 1 (BP M06, M08, M09, §24): the one-time-vendor gate, the price check against the contract (+2%) and
the last price paid (+5%), supplier-and-material split detection, mandatory fields at release and the receipt tolerances per
material and supplier.

All thresholds are tenant rules (platform/p2p_defaults.py): ONE-TIME-VENDOR, PO-PRICE-CHECK, PO-SPLIT, MANDATORY-FIELDS."""
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.models import (
    Contract, ContractLine, Invoice, InvoiceLine, Material, PoLine, PrLine, PurchaseOrder, ReceiptTolerance, Supplier, Task,
)
from app.pic.platform import audit, clock
from app.pic.platform.errors import Problem, rule_violation
from app.pic.platform.money import D, fmt_inr
from app.pic.platform.serialize import jsonable
from app.pic.services import mandatory, p2p_rules, source
from app.pic.services.common import category_status

QUALIFIED = ("QUALIFIED", "PREFERRED")


# ---------------------------------------------------------------- supplier standing for the order's category
def category_and_status(session: Session, po: PurchaseOrder, lines: list[PoLine]) -> tuple[str, str]:
    material = session.get(Material, lines[0].material_id) if lines[0].material_id else None
    if material is not None:
        category = material.category
    else:
        pr_line = session.execute(select(PrLine).where(PrLine.requisition_id == lines[0].requisition_id,
                                                       PrLine.line_no == lines[0].pr_line_no)).scalar_one_or_none()
        category = pr_line.category if pr_line and pr_line.category else lines[0].material_group
    return category, category_status(session, po.supplier_id, category)


# ---------------------------------------------------------------- BP M06 one-time vendor
def one_time_vendor_gate(session: Session, po: PurchaseOrder, lines: list[PoLine], *, releasing: bool = False) -> Optional[dict]:
    """Hard block on routing / releasing a PO to a supplier that is not Qualified or Preferred for the category, unless rule
    ONE-TIME-VENDOR allows the exception: within the value cap, with a reason and approved by one of the rule's approver roles.
    Returns the exception record (None for a qualified supplier); raises 422 when the order may not go to this supplier."""
    category, status = category_and_status(session, po, lines)
    if status in QUALIFIED:
        return None
    rule = p2p_rules.rule(session, "ONE-TIME-VENDOR", company_code=po.company_code)
    supplier = session.get(Supplier, po.supplier_id)
    body = rule.body
    common = dict(rule_ref=rule.ref, supplierStatus=status, category=category, supplier=supplier.code)
    if status in body.get("blockedStatuses", ["BLOCKED", "MERGED"]) or not body.get("enabled", True):
        raise Problem(422, "SUPPLIER_NOT_QUALIFIED", f"{supplier.code} is {status.replace('_', ' ').lower()} for {category}: only Qualified or "
                      "Preferred suppliers receive purchase orders" + ("" if body.get("enabled", True) else " (no one-time-vendor exception is allowed)"),
                      **common)
    cap = int(body.get("maxValueMinor", 0))
    if po.total_minor > cap:
        raise Problem(422, "ONE_TIME_VENDOR_LIMIT", f"{supplier.code} is {status.replace('_', ' ').lower()} for {category} and the order "
                      f"({fmt_inr(po.total_minor)}) exceeds the one-time-vendor limit {fmt_inr(cap)}: qualify the supplier first",
                      limitMinor=cap, valueMinor=po.total_minor, **common)
    record = po.one_time_vendor or {}
    reason = (record.get("reason") or "").strip()
    if len(reason) < int(body.get("minReasonLength", 10)):
        raise Problem(422, "ONE_TIME_VENDOR_REASON_REQUIRED",
                      f"{supplier.code} is {status.replace('_', ' ').lower()} for {category}: a one-time-vendor exception needs a reason "
                      f"of at least {body.get('minReasonLength', 10)} characters and the approval of "
                      f"{' / '.join(body.get('approverRoles') or []) or 'an approver'} (oneTimeVendorReason)", **common)
    roles = list(body.get("approverRoles") or [])
    if releasing and roles:
        approvers = session.execute(select(Task.completed_by, Task.candidate_role).where(
            Task.kind == "PO_APPROVAL", Task.object_id == po.id, Task.decision == "APPROVE", Task.candidate_role.in_(roles))).all()
        if not approvers:
            raise Problem(422, "ONE_TIME_VENDOR_NOT_APPROVED", f"{po.number}: the one-time-vendor exception for {supplier.code} is not "
                          f"approved by {' / '.join(roles)}; the order cannot be released", **common)
        record = {**record, "approvedBy": [str(u) for u, _ in approvers if u], "approvedAt": clock.now().isoformat()}
    return {**record, "status": status, "category": category, "rule": rule.ref, "valueMinor": po.total_minor, "approverRoles": roles}


def record_one_time_vendor(session: Session, po: PurchaseOrder, reason: Optional[str], actor: str) -> None:
    """Keep the buyer's one-time-vendor request on the order (audited) so routing and release can check it."""
    if reason and reason.strip():
        po.one_time_vendor = {"reason": reason.strip(), "requestedBy": actor, "requestedAt": clock.now().isoformat()}
        audit.record(session, "PURCHASE_ORDER", po.id, "ONE_TIME_VENDOR_REQUESTED", object_ref=po.number, reason=reason.strip(),
                     after={"requestedBy": actor})


def settle_one_time_vendor(session: Session, po: PurchaseOrder, record: dict) -> None:
    po.one_time_vendor = record
    audit.record(session, "PURCHASE_ORDER", po.id, "ONE_TIME_VENDOR_RELEASED", object_ref=po.number, reason=record.get("reason"),
                 after={k: record.get(k) for k in ("status", "category", "rule", "valueMinor", "approvedBy")})


# ---------------------------------------------------------------- BP §24 / APR-8 price check
def contract_reference_price(session: Session, material_id: uuid.UUID, plant: str, on: date) -> Optional[tuple[int, str]]:
    """Lowest valid contract price of the material (any supplier) on the date, with the contract number."""
    best: Optional[tuple[int, str]] = None
    for line, contract in session.execute(select(ContractLine, Contract).join(Contract, Contract.id == ContractLine.contract_id).where(
            ContractLine.material_id == material_id, Contract.status.in_(("ACTIVE", "EXPIRING")), Contract.valid_from <= on,
            Contract.valid_to >= on)).all():
        validity = source.contract_price(session, line.id, on)
        if validity is not None and (best is None or validity.unit_price_minor < best[0]):
            best = (validity.unit_price_minor, contract.number)
    return best


def last_paid_price(session: Session, material_id: uuid.UUID, supplier_id: uuid.UUID, on: date, basis: str, months: int,
                    exclude_po: Optional[uuid.UUID] = None) -> Optional[tuple[int, str, str]]:
    """(unit price, invoice number, scope) of the latest posted / paid invoice line for the material: same supplier first, then any."""
    since = on - timedelta(days=int(months) * 30)

    def latest(supplier_only: bool):
        query = (select(InvoiceLine.unit_price_minor, Invoice.number).join(Invoice, Invoice.id == InvoiceLine.invoice_id)
                 .join(PoLine, PoLine.id == InvoiceLine.po_line_id).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
                 .where(PoLine.material_id == material_id, Invoice.status.in_(("POSTED", "PAID")),
                        func.coalesce(Invoice.match_type, "") != "RETENTION", Invoice.invoice_date >= since, Invoice.invoice_date <= on))
        if supplier_only:
            query = query.where(PurchaseOrder.supplier_id == supplier_id)
        if exclude_po:
            query = query.where(PurchaseOrder.id != exclude_po)
        return session.execute(query.order_by(Invoice.invoice_date.desc(), Invoice.created_at.desc()).limit(1)).first()

    if basis in ("SUPPLIER_THEN_MATERIAL", "SUPPLIER"):
        row = latest(True)
        if row:
            return row[0], row[1], "SUPPLIER"
    if basis in ("SUPPLIER_THEN_MATERIAL", "MATERIAL"):
        row = latest(False)
        if row:
            return row[0], row[1], "MATERIAL"
    return None


def price_findings(session: Session, *, supplier_id: uuid.UUID, material_id: Optional[uuid.UUID], unit_price_minor: int, plant: str,
                   on: Optional[date] = None, exclude_po: Optional[uuid.UUID] = None, company_code: Optional[str] = None) -> list[dict]:
    """Findings for a NON-contract priced line: above the contract price of the material by more than ``contractBandPct`` (default 2%)
    and above the last price paid by more than ``lastPriceBandPct`` (default 5%). Empty when the price is within both bands."""
    rule = p2p_rules.rule(session, "PO-PRICE-CHECK", company_code=company_code)
    if not rule.body.get("enabled", True) or material_id is None:
        return []
    on = on or clock.today()
    findings = []
    contract = contract_reference_price(session, material_id, plant, on)
    if contract is not None:
        band = D(rule.body.get("contractBandPct", 2))
        limit = int(Decimal(contract[0]) * (1 + band / 100))
        if unit_price_minor > limit:
            findings.append({"basis": "CONTRACT", "referencePriceMinor": contract[0], "reference": contract[1], "bandPct": str(band),
                             "limitMinor": limit, "unitPriceMinor": unit_price_minor,
                             "overPct": str(((D(unit_price_minor) / D(contract[0]) - 1) * 100).quantize(Decimal("0.01"))), "rule": rule.ref})
    last = last_paid_price(session, material_id, supplier_id, on, rule.body.get("lastPriceBasis", "SUPPLIER_THEN_MATERIAL"),
                           int(rule.body.get("lookbackMonths", 12)), exclude_po)
    if last is not None:
        band = D(rule.body.get("lastPriceBandPct", 5))
        limit = int(Decimal(last[0]) * (1 + band / 100))
        if unit_price_minor > limit:
            findings.append({"basis": "LAST_PAID", "referencePriceMinor": last[0], "reference": last[1], "scope": last[2], "bandPct": str(band),
                             "limitMinor": limit, "unitPriceMinor": unit_price_minor,
                             "overPct": str(((D(unit_price_minor) / D(last[0]) - 1) * 100).quantize(Decimal("0.01"))), "rule": rule.ref})
    return findings


def findings_text(findings: list[dict]) -> str:
    return "; ".join(f"{f['unitPriceMinor'] / 100:,.2f} is {f['overPct']}% above the {'contract price' if f['basis'] == 'CONTRACT' else 'last price paid'} "
                     f"{f['referencePriceMinor'] / 100:,.2f} ({f['reference']}; band +{f['bandPct']}%)" for f in findings)


# ---------------------------------------------------------------- BP M08-C3 split detection by supplier and material
def split_by_material(session: Session, po: PurchaseOrder, lines: list[PoLine]) -> Optional[dict]:
    """Many small POs of the same supplier and material within N days (rule PO-SPLIT): this order and at least ``minOrders - 1``
    others, each below ``perOrderBelowMinor``. Returns the evidence, or None."""
    rule = p2p_rules.rule(session, "PO-SPLIT", company_code=po.company_code)
    body = rule.body
    if not body.get("enabled", True) or po.total_minor >= int(body["perOrderBelowMinor"]):
        return None
    since = clock.now() - timedelta(days=int(body["windowDays"]))
    for material_id in sorted({l.material_id for l in lines if l.material_id}, key=str):
        others = session.execute(select(PurchaseOrder.number).join(PoLine, PoLine.po_id == PurchaseOrder.id).where(
            PurchaseOrder.supplier_id == po.supplier_id, PurchaseOrder.id != po.id, PurchaseOrder.status != "CANCELLED",
            PurchaseOrder.created_at >= since, PoLine.material_id == material_id,
            PurchaseOrder.total_minor < int(body["perOrderBelowMinor"])).distinct().order_by(PurchaseOrder.number)).scalars().all()
        if len(others) + 1 >= int(body["minOrders"]):
            material = session.get(Material, material_id)
            return {"material": material.number if material else str(material_id), "orders": [po.number, *others],
                    "windowDays": int(body["windowDays"]), "perOrderBelowMinor": int(body["perOrderBelowMinor"]), "rule": rule.ref}
    return None


# ---------------------------------------------------------------- TD §6 / P14 mandatory fields at PO release
def check_mandatory(session: Session, po: PurchaseOrder, lines: list[PoLine]) -> None:
    category, purchase_type = mandatory.dominant(((l.material_group, l.purchase_type, l.net_minor) for l in lines))
    supplier = session.get(Supplier, po.supplier_id)
    header = mandatory.plain(po, mandatory.CATALOGUE["PO_RELEASE"]["header"])
    body = [{**mandatory.plain(l, mandatory.CATALOGUE["PO_RELEASE"]["lines"]), "_line_no": l.line_no} for l in lines]
    mandatory.check(session, "PO_RELEASE", header, body, company_code=po.company_code, plant=po.plant, category=category,
                    purchase_type=purchase_type, supplier_group=supplier.supplier_group if supplier else None)


# ---------------------------------------------------------------- BP M09 receipt tolerance per material and supplier
def receipt_tolerance(session: Session, material_id: Optional[uuid.UUID], supplier_id: Optional[uuid.UUID]) -> Optional[ReceiptTolerance]:
    """Most specific override: material + supplier, then supplier, then material."""
    by_material = ReceiptTolerance.material_id.is_(None) if material_id is None else (
        (ReceiptTolerance.material_id == material_id) | ReceiptTolerance.material_id.is_(None))
    by_supplier = ReceiptTolerance.supplier_id.is_(None) if supplier_id is None else (
        (ReceiptTolerance.supplier_id == supplier_id) | ReceiptTolerance.supplier_id.is_(None))
    rows = session.execute(select(ReceiptTolerance).where(by_material, by_supplier)).scalars().all()
    return max(rows, key=lambda r: 2 if r.material_id and r.supplier_id else 1 if r.supplier_id else 0) if rows else None


def tolerance_view(row: ReceiptTolerance, material: Optional[str], supplier: Optional[str]) -> dict:
    return {"id": str(row.id), "material": material, "supplier": supplier, "overPct": jsonable(row.over_pct), "underPct": jsonable(row.under_pct),
            "reason": row.reason, "setBy": str(row.set_by), "updatedAt": (row.updated_at or row.created_at).isoformat(), "rowVersion": row.row_version}


def line_tolerance(po: PurchaseOrder, line: PoLine) -> tuple[Decimal, Decimal]:
    """(over %, under %) in force for a line: its receipt-tolerance override, else the order's (contract or RCV-TOLERANCE rule)."""
    over = line.over_tol_pct if line.over_tol_pct is not None else (po.tolerance or {}).get("over_pct", 0)
    under = line.under_tol_pct if line.under_tol_pct is not None else (po.tolerance or {}).get("under_pct", 0)
    return D(over), D(under)
