"""F5 Purchase order → supplier confirmation → delivery (M08)."""
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    CatalogueItem, Contract, ContractLine, Material, PoConfirmation, PoLine, PoScheduleLine, PoVersion, PrLine, PurchaseOrder, Requisition, Supplier, Task,
)
from app.pic.platform import agents, audit, clock, integration, outbox, rules, sod, workflow
from app.pic.platform.auth import agent_principal
from app.pic.platform.core import StateMachine, link, next_number, upstream_chain
from app.pic.platform.errors import Problem, illegal_transition, rule_violation
from app.pic.platform.money import D, line_amount
from app.pic.platform.serialize import jsonable, row
from app.pic.services import requisition as req_svc
from app.pic.services import source
from app.pic.services import supplier as supplier_svc
from app.pic.services import transmission
from app.pic.services.common import by_ref, category_status, principal, require_supplier_user, supplier_by_code

PROCESS = "pic.po"
SM = StateMachine("PURCHASE_ORDER", {
    ("DRAFT", "route"): "IN_APPROVAL",
    ("DRAFT", "release"): "RELEASED",
    ("IN_APPROVAL", "release"): "RELEASED",
    ("IN_APPROVAL", "reject"): "DRAFT",
    ("RELEASED", "transmit"): "TRANSMITTED",
    ("TRANSMITTED", "confirm"): "CONFIRMED",
    ("RELEASED", "change"): "RELEASED",
    ("TRANSMITTED", "change"): "TRANSMITTED",
    ("CONFIRMED", "change"): "TRANSMITTED",
    ("CONFIRMED", "receive_partially"): "PARTIALLY_RECEIVED",
    ("CONFIRMED", "receive"): "RECEIVED",
    ("TRANSMITTED", "receive_partially"): "PARTIALLY_RECEIVED",
    ("TRANSMITTED", "receive"): "RECEIVED",
    ("PARTIALLY_RECEIVED", "receive_partially"): "PARTIALLY_RECEIVED",
    ("PARTIALLY_RECEIVED", "receive"): "RECEIVED",
    ("RECEIVED", "invoice"): "INVOICED",
    ("PARTIALLY_RECEIVED", "invoice"): "PARTIALLY_RECEIVED",
    ("CONFIRMED", "invoice"): "INVOICED",  # receipt-less expense orders (P08): 2-way matched, no goods receipt
    ("INVOICED", "close"): "CLOSED",
    ("DRAFT", "cancel"): "CANCELLED",
    ("RELEASED", "cancel"): "CANCELLED",
    ("TRANSMITTED", "cancel"): "CANCELLED",
    # A reversed goods receipt (movement 102) re-opens the order for the quantity taken back.
    ("RECEIVED", "unreceive_partially"): "PARTIALLY_RECEIVED",
    ("RECEIVED", "unreceive"): "CONFIRMED",
    ("PARTIALLY_RECEIVED", "unreceive"): "CONFIRMED",
    ("RECEIVED", "unreceive_unconfirmed"): "TRANSMITTED",
    ("PARTIALLY_RECEIVED", "unreceive_unconfirmed"): "TRANSMITTED",
    # Closing a fully received order with nothing left to invoice (e.g. a lot rejected in full and returned).
    ("RECEIVED", "close"): "CLOSED",
    # A partly delivered order can still be changed (never below the received quantity) and is re-confirmed by the
    # supplier without losing its receipt status; or it is short-closed once the received value is invoiced.
    ("PARTIALLY_RECEIVED", "change"): "PARTIALLY_RECEIVED",
    ("PARTIALLY_RECEIVED", "confirm"): "PARTIALLY_RECEIVED",
    ("PARTIALLY_RECEIVED", "short_close"): "CLOSED",
    # Withdrawn while still in approval, or after the supplier confirmed but before anything was shipped.
    ("IN_APPROVAL", "cancel"): "CANCELLED",
    ("CONFIRMED", "cancel"): "CANCELLED",
})
TYPE_RANK = {"MRP_RUN": 0, "PLANNED_ORDER": 1, "REQUISITION": 2, "SOURCING_EVENT": 3, "CONTRACT": 4}


def _instance(session: Session, po: PurchaseOrder):
    return workflow.find(session, "PURCHASE_ORDER", po.id, PROCESS)


def lines_of(session: Session, po: PurchaseOrder) -> list[PoLine]:
    return session.execute(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).scalars().all()


def lineage_refs(session: Session, po: PurchaseOrder) -> list[str]:
    """Upstream documents in lifecycle order, e.g. PLO-55821, REQ-2311, RFQ-2231, SA-5520."""
    chain = upstream_chain(session, "PURCHASE_ORDER", po.id)
    return [ref for ref, _ in sorted(chain, key=lambda item: TYPE_RANK.get(item[1], 9)) if _ != "MRP_RUN"]


# ---------------------------------------------------------------- create (F5-01/02)
def create_from_requisition(session: Session, *, requisition: str, lines: list[int], supplier_code: Optional[str] = None,
                            contract_ref: Optional[str] = None, release_qty: Optional[Decimal] = None,
                            need_date: Optional[date] = None, unit_price_minor: Optional[int] = None,
                            deviation_reason: Optional[str] = None, retention_pct: Optional[Decimal] = None) -> list[PurchaseOrder]:
    pr = by_ref(session, Requisition, requisition)
    if pr.status not in ("APPROVED", "PARTIALLY_ORDERED"):
        raise rule_violation(f"{pr.number} is {pr.status}; only approved requisitions can be ordered", "P07")
    groups: dict[uuid.UUID, list[tuple[PrLine, source.Allocation]]] = {}
    determinations = {}
    for line_no in lines:
        pr_line = session.execute(select(PrLine).where(PrLine.requisition_id == pr.id, PrLine.line_no == line_no)).scalar_one()
        open_qty = pr_line.qty - pr_line.ordered_qty
        qty = D(release_qty) if release_qty is not None else open_qty
        if qty <= 0 or qty > open_qty:
            raise rule_violation(f"Line {line_no}: release quantity {qty} exceeds open quantity {open_qty}", "P07")
        when = need_date or pr_line.need_date
        if contract_ref:
            contract = by_ref(session, Contract, contract_ref)
            if contract.status not in ("ACTIVE", "EXPIRING"):
                raise rule_violation(f"{contract.number} is {contract.status}; only executed contracts can be referenced", "CLM-PO")
            contract_line = session.execute(select(ContractLine).where(ContractLine.contract_id == contract.id,
                                                                       ContractLine.material_id == pr_line.material_id)).scalars().first()
            if contract_line is None:
                raise rule_violation(f"{contract.number} has no line for this material", "CLM-PO")
            validity = source.contract_price(session, contract_line.id, when)
            if validity is None:
                raise rule_violation(f"{contract.number} has no published price valid on {when}", "CLM-PO")
            supplier = session.get(Supplier, contract.supplier_id)
            if supplier_code and supplier_code != supplier.code:
                raise rule_violation(f"{contract.number} belongs to {supplier.code}, not {supplier_code}", "CLM-PO")
            allocations = [source.Allocation(supplier.id, supplier.code, qty, validity.unit_price_minor, "CONTRACT",
                                             contract.id, contract_line.id, validity.id)]
            determinations[line_no] = {"method": "CONTRACT_REFERENCE", "contract": contract.number}
        elif supplier_code:
            supplier = supplier_by_code(session, supplier_code)
            price = unit_price_minor or pr_line.price_est_minor
            allocations = [source.Allocation(supplier.id, supplier.code, qty, price,
                                             "CATALOGUE" if pr_line.item_type == "CATALOGUE" else "MANUAL")]
            determinations[line_no] = {"method": "MANUAL_SUPPLIER"}
        else:
            if pr_line.material_id is None:
                raise rule_violation(f"Line {line_no} is free text; choose a supplier or start a sourcing event", "P03")
            material = session.get(Material, pr_line.material_id)
            determination = source.determine(session, material, pr_line.plant, when, qty, reserve=True)
            if determination.method == "NONE":
                raise Problem(422, "NEEDS_SOURCING", f"No source of supply for line {line_no}; start a sourcing event",
                              rule_ref="§9.2", excluded=determination.excluded)
            allocations = determination.allocations
            determinations[line_no] = determination.as_dict()
        for allocation in allocations:
            groups.setdefault(allocation.supplier_id, []).append((pr_line, allocation))
    pos = []
    for supplier_id, items in groups.items():
        pos.append(_create_po(session, pr, supplier_id, items, need_date, unit_price_minor, deviation_reason, determinations))
    _apply_retention(session, pos, retention_pct)
    return pos


def _apply_retention(session: Session, pos: list[PurchaseOrder], retention_pct: Optional[Decimal]) -> None:
    """Retention withheld from every invoice on the order until released (construction / subcontract orders, BP §23).
    Explicit percentage, or the tenant's PROJECT-CONTROLS retentionPct for works orders: service lines assigned to a WBS
    element (material supplies to the project carry no retention unless the buyer sets it)."""
    source_ref = "explicit"
    if retention_pct is None:
        try:
            rule = rules.resolve(session, "PROJECT-CONTROLS")
        except Problem:
            return
        if not rule.body.get("retentionPct"):
            return
        retention_pct, source_ref = D(rule.body["retentionPct"]), rule.ref
    pct = D(retention_pct)
    if pct < 0 or pct > 20:
        raise rule_violation("Retention must be between 0% and 20% of the invoiced value", "RETENTION")
    for po in pos:
        if source_ref != "explicit" and not any(l.account_assignment_type == "WBS" and l.purchase_type == "SERVICE"
                                                for l in lines_of(session, po)):
            continue
        po.retention_pct = pct
        audit.record(session, "PURCHASE_ORDER", po.id, "RETENTION_SET", object_ref=po.number,
                     after={"retentionPct": jsonable(pct), "source": source_ref})


def subcontracting_bom(session: Session, material: Optional[Material], qty: Decimal) -> list[dict]:
    """P08 subcontracting: the components the buyer provides for ``qty`` finished parts, from the finished material's
    subcontracting BOM (material attribute ``subcontractingBom`` = [{"material": number, "qtyPer": "1"}])."""
    bom = ((material.attributes or {}).get("subcontractingBom") if material is not None else None) or []
    if not bom:
        raise rule_violation(f"{material.number if material else 'This line'}: subcontracting needs a component list "
                             "(subcontractingBom on the material master)", "P08")
    out = []
    for entry in bom:
        component = session.execute(select(Material).where(Material.number == entry["material"])).scalar_one_or_none()
        if component is None:
            raise rule_violation(f"Subcontracting component {entry['material']} of {material.number} is not a material master", "P08")
        per = D(entry.get("qtyPer", 1))
        out.append({"material": component.number, "materialId": str(component.id), "description": component.description,
                    "qtyPer": jsonable(per), "qty": jsonable(per * D(qty)), "uom": component.base_uom})
    return out


def _create_po(session: Session, pr: Requisition, supplier_id: uuid.UUID, items, need_date, price_override, deviation_reason,
               determinations) -> PurchaseOrder:
    p = principal(session)
    supplier = session.get(Supplier, supplier_id)
    contract = session.get(Contract, items[0][1].contract_id) if items[0][1].contract_id else None
    matrix = rules.resolve(session, "PURCHASE-TYPE-MATRIX", company_code=pr.company_code)
    receipt_rule = rules.resolve(session, "RCV-TOLERANCE", company_code=pr.company_code)
    tolerance = ({"over_pct": jsonable(contract.over_tolerance_pct), "under_pct": jsonable(contract.under_tolerance_pct),
                  "price_pct": jsonable(contract.price_tolerance_pct)} if contract else receipt_rule.body)
    po = PurchaseOrder(
        tenant_id=current_tenant(session), number=next_number(session, "PURCHASE_ORDER"), version=1,
        company_code=pr.company_code, purch_org="1000", plant=pr.plant, supplier_id=supplier.id, status="DRAFT",
        contract_id=contract.id if contract else None, purpose_code=pr.purpose_code, currency="INR",
        payment_terms=contract.payment_terms if contract else supplier.payment_terms,
        incoterms=contract.incoterms if contract else supplier.incoterms, tolerance=tolerance,
        rule_set_version=rules.refs(matrix, receipt_rule), created_by=p.user_id,
    )
    session.add(po)
    session.flush()
    sod.guard(session, "PO_CREATE", {"supplier_id": supplier.id, "po_id": po.id})
    sod.record(session, "PO_CREATE", {"supplier_id": supplier.id, "po_id": po.id})
    total = 0
    overrides = []
    components: dict[str, list[dict]] = {}  # P08: components provided to the subcontractor, per subcontracting PO line
    for index, (pr_line, allocation) in enumerate(items, start=1):
        material = session.get(Material, pr_line.material_id) if pr_line.material_id else None
        # Catalogue and punch-out lines carry the supplier's HSN/SAC and GST rate from the catalogue item (no material master).
        catalogue_item = session.get(CatalogueItem, pr_line.catalogue_item_id) if (material is None and pr_line.catalogue_item_id) else None
        flags = matrix.body[pr_line.purchase_type]
        inherited_price = allocation.unit_price_minor or pr_line.price_est_minor
        price = price_override or inherited_price
        deviation = False
        if price_override and allocation.contract_line_id:
            tol = D(tolerance.get("price_pct", 0))
            deviation = abs(Decimal(price_override - inherited_price)) > Decimal(inherited_price) * tol / 100
            if deviation and not deviation_reason:
                raise rule_violation("Price deviates from the contract beyond tolerance; a deviation reason is required", "P07")
            overrides.append({"field": "unit_price", "inherited": inherited_price, "value": price_override,
                              "reason": deviation_reason, "outsideTolerance": deviation})
        receiptless = (pr_line.purchase_type == "EXPENSE" and line_amount(allocation.qty, price) < matrix.body["EXPENSE"].get("receiptlessBelowMinor", 0))
        net = line_amount(allocation.qty, price)
        po_line = PoLine(
            tenant_id=po.tenant_id, po_id=po.id, line_no=index * 10, item_type=pr_line.item_type, purchase_type=pr_line.purchase_type,
            material_id=pr_line.material_id, description=pr_line.description, material_group=pr_line.material_group,
            qty=allocation.qty, uom=pr_line.uom, unit_price_minor=price, net_minor=net,
            gst_rate=material.gst_rate if material else (D(catalogue_item.gst_rate) if catalogue_item and catalogue_item.gst_rate is not None else D(18)),
            hsn_code=material.hsn_code if material else (catalogue_item.hsn_code if catalogue_item else None),
            need_date=need_date or pr_line.need_date, plant=pr_line.plant, storage_location=pr_line.storage_location,
            account_assignment_type=pr_line.account_assignment_type, account_assignment_code=pr_line.account_assignment_code,
            gr_required=bool(flags["gr"]) and not receiptless, ir_required=bool(flags["ir"]), ses_required=bool(flags["ses"]),
            ers=bool(flags.get("ers", False)), quality_managed=bool(material.quality_managed) if material else False,
            price_source=allocation.price_source, contract_line_id=allocation.contract_line_id,
            price_validity_id=allocation.price_validity_id, price_deviation=deviation, deviation_reason=deviation_reason if deviation else None,
            requisition_id=pr.id, pr_line_no=pr_line.line_no, created_by=p.user_id,
        )
        session.add(po_line)
        if pr_line.purchase_type == "SUBCONTRACTING":
            components[str(po_line.line_no)] = subcontracting_bom(session, material, allocation.qty)
        total += net
        req_svc.mark_ordered(session, pr, pr_line, allocation.qty)
        link(session, "REQUISITION", pr.id, pr.number, "PURCHASE_ORDER", po.id, po.number, "converted_from",
             from_line=pr_line.line_no, to_line=po_line.line_no)
        if allocation.contract_id:
            c = session.get(Contract, allocation.contract_id)
            cl = session.get(ContractLine, allocation.contract_line_id)
            link(session, "CONTRACT", c.id, c.number, "PURCHASE_ORDER", po.id, po.number, "priced_by_contract",
                 from_line=cl.line_no, to_line=po_line.line_no)
    po.total_minor = total
    po.overrides = overrides
    session.flush()
    for po_line in lines_of(session, po):
        _default_schedule(session, po_line)
    po.inherited = {"price": items[0][1].unit_price_minor, "paymentTerms": po.payment_terms, "incoterms": po.incoterms,
                    "tolerance": tolerance, "contract": contract.number if contract else None,
                    "sourceDetermination": determinations, **({"components": components} if components else {})}
    session.flush()
    audit.record(session, "PURCHASE_ORDER", po.id, "CREATED", object_ref=po.number,
                 after={"supplier": supplier.code, "totalMinor": total, "inherited": po.inherited, "overrides": overrides},
                 rule_set_version=po.rule_set_version)
    instance = workflow.start(session, PROCESS, "PURCHASE_ORDER", po.id, po.number)
    workflow.step(session, instance, "F5-02", outcome=f"{supplier.code}; inherited from {pr.number}" + (f" and {contract.number}" if contract else ""))
    validate(session, po)
    route(session, po)
    return po


# ---------------------------------------------------------------- validation (F5-03) and DMN-02 (F5-04)
def _split_pattern(session: Session, po: PurchaseOrder, rule) -> bool:
    window = clock.now() - timedelta(days=int(rule.body["splitWindowDays"]))
    band = int(rule.body["splitBandMinor"])
    lines = lines_of(session, po)
    if not lines or po.total_minor >= band:
        return False
    group = lines[0].material_group
    cost_object = lines[0].account_assignment_code or po.plant
    others = session.execute(select(PurchaseOrder.id, PurchaseOrder.total_minor).join(PoLine, PoLine.po_id == PurchaseOrder.id).where(
        PurchaseOrder.supplier_id == po.supplier_id, PurchaseOrder.id != po.id, PurchaseOrder.status != "CANCELLED",
        PurchaseOrder.created_at >= window, PoLine.material_group == group,
        func.coalesce(PoLine.account_assignment_code, PurchaseOrder.plant) == cost_object,
        PurchaseOrder.total_minor < band).distinct()).all()
    return bool(others) and po.total_minor + sum(t for _, t in others) >= band


def validate(session: Session, po: PurchaseOrder) -> dict:
    risk_rule = rules.resolve(session, "PO-RISK", company_code=po.company_code)
    dmn = rules.resolve(session, "DMN-02", company_code=po.company_code, plant=po.plant)
    lines = lines_of(session, po)
    material = session.get(Material, lines[0].material_id) if lines[0].material_id else None
    if material is not None:
        category = material.category
    else:
        pr_line = session.execute(select(PrLine).where(PrLine.requisition_id == lines[0].requisition_id,
                                                       PrLine.line_no == lines[0].pr_line_no)).scalar_one_or_none()
        category = (pr_line.category if pr_line and pr_line.category else lines[0].material_group)
    status = category_status(session, po.supplier_id, category)
    twin = supplier_svc.twin(session, po.supplier_id, category)
    late = Decimal(twin.late_delivery_prob) if twin else Decimal(0)
    price_dev = any(l.price_deviation for l in lines)
    account_changed = False
    for line in lines:
        if line.requisition_id:
            pr_line = session.execute(select(PrLine).where(PrLine.requisition_id == line.requisition_id,
                                                           PrLine.line_no == line.pr_line_no)).scalar_one()
            account_changed = account_changed or (pr_line.account_assignment_code != line.account_assignment_code)
    split = _split_pattern(session, po, risk_rule)
    risk = rules.po_risk(risk_rule, late_prob=late, price_deviation=price_dev, supplier_not_qualified=status not in ("QUALIFIED", "PREFERRED"),
                         value_above_band=po.total_minor > risk_rule.body["valueBandMinor"], split_pattern=split,
                         account_changed=account_changed, model_version=twin.model_version if twin else "n/a")
    decision = rules.touchless(dmn, price_sources={l.price_source for l in lines}, supplier_status=status, value_minor=po.total_minor,
                               split_pattern=split, late_prob=late, risk_score=risk["score"], account_changed=account_changed)
    po.risk_score = risk["score"]
    po.risk_factors = risk["factors"]
    po.touchless = decision["touchless"]
    po.touchless_reasons = decision["reasons"]
    if "PO-RISK" not in po.rule_set_version:
        po.rule_set_version = f"{po.rule_set_version};{rules.refs(risk_rule, dmn)}"
    ai_ref = agents.log_run(session, "PO_VALIDATION", object_type="PURCHASE_ORDER", object_id=po.id, object_ref=po.number,
                            inputs={"supplierStatus": status, "lateProb": str(late), "valueMinor": po.total_minor, "split": split},
                            evidence=[f"model {twin.model_version if twin else 'n/a'}: {late}"],
                            output={"riskScore": risk["score"], "touchless": decision["touchless"], "reasons": decision["reasons"]},
                            confidence=0.9, action_taken="EXECUTED")
    instance = _instance(session, po)
    if instance and instance.current_step in ("F5-02", "F5-03"):
        workflow.step(session, instance, "F5-03", outcome=f"risk {risk['score']}/100 (" + ", ".join(f"{f['code']} +{f['points']}" for f in risk["factors"]) + ")" if risk["factors"] else f"risk {risk['score']}/100")
    audit.record(session, "PURCHASE_ORDER", po.id, "VALIDATED", object_ref=po.number,
                 after={"riskScore": risk["score"], "factors": risk["factors"], "touchless": decision["touchless"],
                        "reasons": decision["reasons"]}, rule_set_version=rules.refs(risk_rule, dmn), ai_ref=ai_ref)
    return {"riskScore": risk["score"], "touchless": decision["touchless"], "factors": risk["factors"], "reasons": decision["reasons"],
            "ruleSetVersion": rules.refs(risk_rule, dmn), "aiRef": ai_ref}


def route(session: Session, po: PurchaseOrder) -> None:
    supplier = session.get(Supplier, po.supplier_id)
    if supplier.status == "BLOCKED":
        raise Problem(422, "PO_SUPPLIER_BLOCKED", f"{supplier.code} is blocked; the PO cannot be released", rule_ref="SLM-BLOCK")
    instance = _instance(session, po)
    if po.touchless:
        allowed, reason = agents.guard(session, "TOUCHLESS_PO", required_level="L4", scope="po:release", value_minor=po.total_minor)
        if allowed:
            workflow.step(session, instance, "F5-04", outcome="yes: touchless criteria met (DMN-02)")
            agent = agents.get(session, "TOUCHLESS_PO")
            ai_ref = agents.log_run(session, "TOUCHLESS_PO", object_type="PURCHASE_ORDER", object_id=po.id, object_ref=po.number,
                                    inputs={"riskScore": po.risk_score, "valueMinor": po.total_minor},
                                    evidence=[f["code"] for f in po.risk_factors], output={"action": "RELEASE"}, confidence=0.95,
                                    action_taken="EXECUTED")
            human = session.info["principal"]
            session.info["principal"] = agent_principal(human, "TOUCHLESS_PO", agent.run_as_role)
            try:
                _release(session, po, ai_ref=ai_ref, approved_by="touchless")
            finally:
                session.info["principal"] = human
            return
        workflow.step(session, instance, "F5-04", outcome=f"no: agent not allowed ({reason})")
    else:
        workflow.step(session, instance, "F5-04", outcome="no: " + "; ".join(po.touchless_reasons))
    rule = rules.resolve(session, "PO-APPROVAL", company_code=po.company_code)
    chain = rules.band_chain(rule, po.total_minor)
    if any(l.price_deviation for l in lines_of(session, po)):
        chain = list(dict.fromkeys(chain + rule.body["deviationChain"]))
    SM.apply(session, po, "route", rule_set_version=rule.ref)
    workflow.start_approval(session, instance, "PO_APPROVAL", object_type="PURCHASE_ORDER", object_id=po.id, object_ref=po.number,
                            chain=chain, step_id="F5-05", initiator_id=po.created_by, rule_set_version=rule.ref,
                            evidence={"riskScore": po.risk_score, "factors": po.risk_factors})


@workflow.on_task("PO_APPROVAL")
def _approval_decided(session: Session, task: Task, outcome: str) -> None:
    po = session.get(PurchaseOrder, task.object_id)
    if outcome == "APPROVED":
        _release(session, po, approved_by=task.candidate_role)
    else:
        SM.apply(session, po, "reject", reason=task.comment)
        workflow.wait(session, _instance(session, po), "F5-02", outcome=f"returned to buyer: {task.comment}")


def _release(session: Session, po: PurchaseOrder, ai_ref: Optional[str] = None, approved_by: str = "") -> None:
    p = principal(session)
    supplier = session.get(Supplier, po.supplier_id)
    if supplier.status == "BLOCKED":
        raise Problem(422, "PO_SUPPLIER_BLOCKED", f"{supplier.code} is blocked", rule_ref="SLM-BLOCK")
    SM.apply(session, po, "release", ai_ref=ai_ref, extra_after={"releasedBy": p.actor})
    po.released_by = p.actor
    po.released_at = clock.now()
    instance = _instance(session, po)
    if approved_by == "touchless":
        workflow.step(session, instance, "F5-05", outcome=f"skipped: released by {p.actor} (L4)", status="SKIPPED")
    outbox.emit(session, "purchase_order.released", "PURCHASE_ORDER", po.id, po.number,
                {"supplier": supplier.code, "totalMinor": po.total_minor, "version": po.version, "touchless": po.touchless})
    transmit(session, po)


def transmit(session: Session, po: PurchaseOrder, via: Optional[str] = None) -> None:
    """F5-06: send the order over every channel agreed with the supplier (portal always; EDI and e-mail per order_channel)."""
    channels = transmission.channels_for(session.get(Supplier, po.supplier_id))
    via = via or "+".join(channels)
    SM.apply(session, po, "transmit", extra_after={"via": via})
    po.transmitted_via = via
    po.transmitted_at = clock.now()
    transmission.send(session, po, channels)
    sla_hours = int(rules.resolve(session, "PO-APPROVAL", company_code=po.company_code).body["confirmationSlaHours"])
    po.confirmation_due_at = clock.now() + timedelta(hours=sla_hours)
    workflow.create_timer(session, "PO_CONFIRMATION_SLA", "PURCHASE_ORDER", po.id, po.confirmation_due_at, {"version": po.version})
    instance = _instance(session, po)
    workflow.step(session, instance, "F5-06", outcome=f"v{po.version} via {via.lower()}; confirm within {sla_hours} h")
    workflow.wait(session, instance, "F5-07", outcome="awaiting supplier confirmation")


@outbox.consumer("purchase_order.released", "erp-po-posting")
@outbox.consumer("purchase_order.changed", "erp-po-posting")
def _post_po(session: Session, event) -> None:
    po = session.get(PurchaseOrder, event.object_id)
    supplier = session.get(Supplier, po.supplier_id)
    message = integration.enqueue(session, target_system=integration.target_system(session, po.company_code), message_type="PURCHASE_ORDER",
                                  idempotency_key=f"{po.company_code}|PO|{po.number}|v{po.version}", object_type="PURCHASE_ORDER",
                                  object_id=po.id, object_ref=po.number,
                                  payload={"po": po.number, "version": po.version, "supplier": supplier.code, "companyCode": po.company_code,
                                           "lines": [{"line": l.line_no, "qty": str(l.qty), "priceMinor": l.unit_price_minor}
                                                     for l in lines_of(session, po)]})
    integration.process(session, message)


@integration.on_posted("PURCHASE_ORDER")
def _po_posted(session: Session, message) -> None:
    po = session.get(PurchaseOrder, message.object_id)
    if (message.payload or {}).get("action") == "CANCEL":
        audit.record(session, "PURCHASE_ORDER", po.id, "ERP_CANCELLED", object_ref=po.number,
                     after={"erpDocument": po.erp_doc_no, "cancellationDocument": message.erp_doc_no})
        return  # the order keeps its ERP document number; the cancellation is its own ERP document
    po.erp_doc_no = message.erp_doc_no
    if po.status == "CANCELLED":
        # The order was cancelled while its posting was still pending or retrying: cancel it in the ERP right after.
        from app.pic.models import OutboxEvent
        cancelled = session.execute(select(OutboxEvent.payload).where(OutboxEvent.topic == "purchase_order.cancelled", OutboxEvent.object_id == po.id)
                                    .order_by(OutboxEvent.occurred_at.desc())).scalars().first()
        _enqueue_erp_cancel(session, po, (cancelled or {}).get("reason"))


# ---------------------------------------------------------------- supplier confirmation (F5-07/08) and change orders
def awaiting_confirmation(session: Session, po: PurchaseOrder) -> bool:
    """The supplier owes an order response: TRANSMITTED, or a partly delivered order whose current version (a change after
    the first receipt) is not confirmed yet."""
    if po.status == "TRANSMITTED":
        return True
    if po.status != "PARTIALLY_RECEIVED" or po.version <= 1:
        return False
    return session.execute(select(PoConfirmation.id).where(PoConfirmation.po_id == po.id, PoConfirmation.po_version == po.version,
                                                           PoConfirmation.status == "CONFIRMED")).first() is None


def confirm(session: Session, po: PurchaseOrder, status: str, lines: Optional[list[dict]] = None, note: Optional[str] = None,
            channel: str = "PORTAL") -> dict:
    """Supplier order response. A line may confirm dates per schedule line:
    {"line": 10, "scheduleConfirmations": [{"seq": 1, "confirmedDate": "2026-11-20"}]}; a later date than requested is a change."""
    p = principal(session)
    require_supplier_user(session, po.supplier_id)
    if not awaiting_confirmation(session, po):
        raise illegal_transition("Purchase order", po.number, po.status, "confirm")
    hours = Decimal((clock.now() - po.transmitted_at).total_seconds() / 3600).quantize(Decimal("0.01"))
    instance = _instance(session, po)
    proposed = lines or []
    outside = ["supplier rejected the order"] if status.upper() == "REJECTED" else []
    po_lines = {l.line_no: l for l in lines_of(session, po)}
    confirmed_dates: dict[uuid.UUID, date] = {}
    for change in proposed:
        line = po_lines.get(int(change["line"]))
        if line is None:
            raise Problem(422, "UNKNOWN_LINE", f"{po.number} has no line {change['line']}")
        schedule = {sl.seq: sl for sl in schedule_lines(session, po, line)}
        for entry in change.get("scheduleConfirmations") or []:
            sl = schedule.get(int(entry["seq"]))
            if sl is None:
                raise Problem(422, "UNKNOWN_SCHEDULE_LINE", f"{po.number}/{line.line_no} has no schedule line {entry['seq']}")
            when = date.fromisoformat(str(entry["confirmedDate"]))
            confirmed_dates[sl.id] = when
            if when > sl.delivery_date:
                outside.append(f"line {line.line_no}/{sl.seq}: later date {when.isoformat()} (requested {sl.delivery_date.isoformat()})")
        if "qty" in change:
            qty = D(change["qty"])
            over, under = D(po.tolerance.get("over_pct", 0)), D(po.tolerance.get("under_pct", 0))
            if qty > line.qty * (1 + over / 100) or qty < line.qty * (1 - under / 100):
                outside.append(f"line {line.line_no}: qty {qty} outside +{over}/-{under}%")
        if "need_date" in change and date.fromisoformat(str(change["need_date"])) > line.need_date:
            outside.append(f"line {line.line_no}: later date {change['need_date']}")
        if "unit_price" in change and int(D(change["unit_price"]) * 100) != line.unit_price_minor:
            outside.append(f"line {line.line_no}: price change")
    record = PoConfirmation(tenant_id=po.tenant_id, po_id=po.id, po_version=po.version,
                            status="CHANGE_REQUESTED" if outside else "CONFIRMED", confirmed_by=p.user_id, lines=proposed,
                            note=note, hours_to_confirm=hours, created_by=p.user_id)
    session.add(record)
    transmission.acknowledge(session, po, channel)
    workflow.step(session, instance, "F5-07", outcome=f"{record.status.lower().replace('_', ' ')} in {hours} h")
    if outside:
        workflow.step(session, instance, "F5-08", outcome="no: " + "; ".join(outside) + " → back to buyer")
        workflow.start_approval(session, instance, "PO_CHANGE_REVIEW", object_type="PURCHASE_ORDER", object_id=po.id,
                                object_ref=po.number, chain=["BUYER"], step_id=None, initiator_id=None,
                                evidence={"proposed": proposed, "outside": outside, "note": note, "response": status.upper(),
                                          "version": po.version})
        audit.record(session, "PURCHASE_ORDER", po.id, "SUPPLIER_CHANGE_REQUESTED", object_ref=po.number, after={"changes": proposed}, reason=note)
        return {"status": po.status, "confirmation": "CHANGE_REQUESTED", "outsideTolerance": outside}
    SM.apply(session, po, "confirm", extra_after={"hoursToConfirm": str(hours)})
    for line in po_lines.values():
        for sl in schedule_lines(session, po, line):
            sl.confirmed_date = confirmed_dates.get(sl.id, sl.delivery_date)
    outbox.emit(session, "purchase_order.confirmed", "PURCHASE_ORDER", po.id, po.number, {"version": po.version, "hours": str(hours)})
    workflow.step(session, instance, "F5-08", outcome="yes: confirmed as ordered" if not proposed else "yes: changes within tolerance")
    if all(l.ses_required for l in po_lines.values()):
        workflow.step(session, instance, "F5-09", outcome="service order: performance confirmed by service entry sheet (F6)")
        workflow.end(session, instance, "F5-10", outcome="service in progress")
    else:
        workflow.wait(session, instance, "F5-09", outcome="ship & send ASN")
    return {"status": po.status, "confirmation": "CONFIRMED", "hoursToConfirm": str(hours)}


@workflow.guard_task("PO_CHANGE_REVIEW")
def _guard_change_review(session: Session, task: Task, decision: str) -> None:
    """A supplier rejection (or a response without any line change) proposes nothing: accepting it would only re-send the
    same order as v+1. The buyer declines the review and then changes the order or cancels it."""
    proposed = [c for c in (task.evidence or {}).get("proposed") or [] if set(c) - {"line"}]
    if decision == "APPROVE" and not proposed:
        rejected = (task.evidence or {}).get("response") == "REJECTED" or "supplier rejected the order" in ((task.evidence or {}).get("outside") or [])
        raise Problem(422, "NOTHING_TO_ACCEPT", (f"{task.object_ref}: the supplier rejected the order" if rejected else
                                                 f"{task.object_ref}: the supplier response proposes no change")
                      + "; decline this review, then change the order (new version) or cancel it", rule_ref="F5-08")


@workflow.on_task("PO_CHANGE_REVIEW")
def _change_reviewed(session: Session, task: Task, outcome: str) -> None:
    po = session.get(PurchaseOrder, task.object_id)
    if outcome == "APPROVED":
        changes = [{k: v for k, v in c.items()} for c in task.evidence.get("proposed", [])]
        # A proposed price outside the contract tolerance is a P07 deviation: the buyer's comment is its justification.
        change_order(session, po, changes, reason=f"supplier proposal accepted: {task.comment or ''}".strip(), deviation_reason=task.comment)
    else:
        audit.record(session, "PURCHASE_ORDER", po.id, "SUPPLIER_CHANGE_DECLINED", object_ref=po.number, reason=task.comment)


def _band(rule, value_minor: int) -> int:
    """Index of the PO-APPROVAL value band a value falls in (same bands as rules.band_chain)."""
    for index, band in enumerate(rule.body["bands"]):
        if band["upTo"] is None or value_minor < band["upTo"]:
            return index
    return len(rule.body["bands"])


def _contract_price_minor(session: Session, line: PoLine, on: date) -> Optional[int]:
    """Contract price of a contract-priced line on a date (the published validity covering it, else the one it was priced from)."""
    from app.pic.models import PriceValidity
    if not line.contract_line_id:
        return None
    validity = source.contract_price(session, line.contract_line_id, on)
    if validity is None and line.price_validity_id:
        validity = session.get(PriceValidity, line.price_validity_id)
    return validity.unit_price_minor if validity is not None else None


def _review_change(session: Session, po: PurchaseOrder, lines: dict, changes: list[dict], deviation_reason: Optional[str], rule) -> dict:
    """Value and P07 deviation of a change before it is applied: new order value, lines whose new price is outside the contract
    price tolerance (a deviation needs a reason) and the approval triggers (PO-APPROVAL ``changeApproval``: a price deviation
    always; a value rising into a higher band when ``onBandIncrease`` is set)."""
    state = {no: [l.qty, l.unit_price_minor, l.need_date] for no, l in lines.items()}
    touched, priced = set(), set()
    for change in changes:
        no = int(change["line"])
        if "qty" in change:
            state[no][0] = D(change["qty"])
            touched.add(no)
        if "unit_price" in change:
            state[no][1] = int(D(change["unit_price"]) * 100)
            touched.add(no)
            priced.add(no)
        if "need_date" in change:
            state[no][2] = date.fromisoformat(str(change["need_date"]))
    total = sum(line_amount(state[no][0], state[no][1]) if no in touched else l.net_minor for no, l in lines.items())
    tolerance = D(po.tolerance.get("price_pct", 0))
    deviations = []
    for no in sorted(priced):
        contract_price = _contract_price_minor(session, lines[no], state[no][2])
        if contract_price is not None and abs(Decimal(state[no][1] - contract_price)) > Decimal(contract_price) * tolerance / 100:
            deviations.append({"line": no, "unitPriceMinor": state[no][1], "contractPriceMinor": contract_price, "tolerancePct": jsonable(tolerance)})
    if deviations and not (deviation_reason or "").strip():
        raise rule_violation("Price deviates from the contract beyond tolerance; a deviation reason is required", "P07", deviations=deviations)
    settings = rule.body.get("changeApproval") or {}
    triggers = []
    if deviations and settings.get("onPriceDeviation", True):
        triggers.append("PRICE_DEVIATION")
    if settings.get("onBandIncrease", False) and _band(rule, total) > _band(rule, po.total_minor):
        triggers.append("BAND_INCREASE")
    return {"totalMinor": total, "deviations": deviations, "priced": priced, "triggers": triggers}


def pending_change_approval(session: Session, po: PurchaseOrder) -> Optional[Task]:
    return session.execute(select(Task).where(Task.object_id == po.id, Task.kind == "PO_CHANGE_APPROVAL", Task.status == "OPEN")).scalars().first()


def change_order(session: Session, po: PurchaseOrder, changes: list[dict], reason: str, deviation_reason: Optional[str] = None,
                 change_request: Optional[str] = None) -> dict:
    """Change of qty/price/date creates version n+1 and requires supplier re-confirmation (§6.1). A new price outside the
    contract tolerance needs a deviation reason (P07) and, like a value rising into a higher PO-APPROVAL band (when the rule
    set enables it), is approved before the new version exists: the version in force stays with the supplier, nothing is
    transmitted until the approval chain has approved (task PO_CHANGE_APPROVAL)."""
    if not SM.can(po.status, "change"):
        raise illegal_transition("Purchase order", po.number, po.status, "change")
    lines = {l.line_no: l for l in lines_of(session, po)}
    for change in changes:
        line = lines.get(int(change["line"]))
        if line is None:
            raise Problem(422, "UNKNOWN_LINE", f"{po.number} has no line {change['line']}")
        if "qty" in change and D(change["qty"]) <= 0:
            raise Problem(422, "INVALID_QUANTITY", f"Line {line.line_no}: the quantity must be positive; cancel the order to withdraw it",
                          rule_ref="PO-CHANGE")
        if "qty" in change and D(change["qty"]) < line.received_qty:
            raise Problem(422, "BELOW_RECEIVED", f"Line {line.line_no}: {jsonable(line.received_qty)} already received; the quantity "
                          f"cannot go below it", rule_ref="PO-CHANGE", receivedQty=jsonable(line.received_qty))
        if "unit_price" in change and D(change["unit_price"]) <= 0:
            raise Problem(422, "INVALID_PRICE", f"Line {line.line_no}: the unit price must be positive", rule_ref="PO-CHANGE")
    pending = pending_change_approval(session, po)
    if pending is not None:
        raise Problem(409, "CHANGE_PENDING_APPROVAL", f"{po.number} already has a change awaiting approval ({pending.candidate_role}); "
                      "decide it first", rule_ref="PO-APPROVAL")
    rule = rules.resolve(session, "PO-APPROVAL", company_code=po.company_code)
    review = _review_change(session, po, lines, changes, deviation_reason, rule)
    chain = rules.band_chain(rule, review["totalMinor"]) if "BAND_INCREASE" in review["triggers"] else []
    if "PRICE_DEVIATION" in review["triggers"]:
        chain = list(dict.fromkeys(chain + list(rule.body["deviationChain"])))
    if not chain:
        return _apply_change(session, po, changes, reason, deviation_reason)
    p = principal(session)
    evidence = {"changes": jsonable(changes), "reason": reason, "deviationReason": deviation_reason, "fromVersion": po.version,
                "fromTotalMinor": po.total_minor, "toTotalMinor": review["totalMinor"], "triggers": review["triggers"],
                "deviations": review["deviations"], "changeRequest": change_request}
    workflow.start_approval(session, _instance(session, po), "PO_CHANGE_APPROVAL", object_type="PURCHASE_ORDER", object_id=po.id,
                            object_ref=po.number, chain=chain, step_id=None, initiator_id=p.user_id, rule_set_version=rule.ref,
                            evidence=evidence)
    audit.record(session, "PURCHASE_ORDER", po.id, "CHANGE_APPROVAL_REQUESTED", object_ref=po.number, reason=reason,
                 after={k: v for k, v in evidence.items() if k != "changeRequest" or v}, rule_set_version=rule.ref)
    return {"po": po.number, "version": po.version, "status": po.status, "approval": "PENDING", "chain": chain,
            "triggers": review["triggers"], "proposedVersion": po.version + 1, "toTotalMinor": review["totalMinor"]}


@workflow.on_task("PO_CHANGE_APPROVAL")
def _change_approval_decided(session: Session, task: Task, outcome: str) -> None:
    from app.pic.models import PoChangeRequest
    po = session.get(PurchaseOrder, task.object_id)
    evidence = task.evidence or {}
    pcr = (session.execute(select(PoChangeRequest).where(PoChangeRequest.number == evidence["changeRequest"])).scalar_one_or_none()
           if evidence.get("changeRequest") else None)
    if outcome != "APPROVED":
        audit.record(session, "PURCHASE_ORDER", po.id, "CHANGE_APPROVAL_REJECTED", object_ref=po.number, reason=task.comment,
                     after={"fromVersion": evidence.get("fromVersion"), "triggers": evidence.get("triggers")})
        if pcr is not None:
            pcr.status, pcr.decision_comment = "REJECTED", task.comment
        return
    if po.version != evidence.get("fromVersion") or not SM.can(po.status, "change"):
        raise Problem(409, "CHANGE_SUPERSEDED", f"{po.number} is at version {po.version} ({po.status}); this change was raised on "
                      f"version {evidence.get('fromVersion')}. Reject it and raise the change again", rule_ref="PO-APPROVAL")
    result = _apply_change(session, po, evidence["changes"], evidence["reason"], evidence.get("deviationReason"))
    if pcr is not None:
        pcr.result_version = result["version"]


def _apply_change(session: Session, po: PurchaseOrder, changes: list[dict], reason: str, deviation_reason: Optional[str] = None) -> dict:
    lines = {l.line_no: l for l in lines_of(session, po)}
    rule = rules.resolve(session, "PO-APPROVAL", company_code=po.company_code)
    review = _review_change(session, po, lines, changes, deviation_reason, rule)
    deviating = {d["line"]: d for d in review["deviations"]}
    changes = jsonable(changes)
    snapshot = {"header": row(po), "lines": [row(l) for l in lines.values()],
                "schedule": [row(sl) for sl in schedule_lines(session, po)]}
    session.add(PoVersion(tenant_id=po.tenant_id, po_id=po.id, version=po.version, snapshot=snapshot, change_reason=reason,
                          changes=changes, created_by=principal(session).user_id))
    for change in changes:
        line = lines[int(change["line"])]
        old_need = line.need_date
        if "qty" in change:
            line.qty = D(change["qty"])
        if "need_date" in change:
            line.need_date = date.fromisoformat(str(change["need_date"]))
        if "unit_price" in change:
            line.unit_price_minor = int(D(change["unit_price"]) * 100)
            # P07: the deviation flag follows the new price (back within tolerance clears it).
            deviation = deviating.get(line.line_no)
            line.price_deviation = deviation is not None if line.contract_line_id else line.price_deviation
            line.deviation_reason = deviation_reason.strip() if deviation is not None else (None if line.contract_line_id else line.deviation_reason)
            if deviation is not None:
                po.overrides = [*(po.overrides or []), {"field": "unit_price", "line": line.line_no, "inherited": deviation["contractPriceMinor"],
                                                        "value": line.unit_price_minor, "reason": line.deviation_reason, "outsideTolerance": True,
                                                        "version": po.version + 1}]
        line.net_minor = line_amount(line.qty, line.unit_price_minor)
        if change.get("schedule"):
            _replace_schedule(session, po, line, _parse_schedule(line, change["schedule"]))
        else:
            _fit_schedule(session, po, line, old_need)
        for entry in change.get("scheduleConfirmations") or []:
            # An accepted supplier proposal moves the requested date of that schedule line to the confirmed one.
            sl = next((x for x in schedule_lines(session, po, line) if x.seq == int(entry["seq"])), None)
            if sl is not None:
                sl.delivery_date = date.fromisoformat(str(entry["confirmedDate"]))
        if schedule_lines(session, po, line):
            line.need_date = min(sl.delivery_date for sl in schedule_lines(session, po, line))
    for sl in schedule_lines(session, po):
        sl.confirmed_date = None  # the new version is re-confirmed by the supplier
    po.total_minor = sum(l.net_minor for l in lines.values())
    po.version += 1
    previous = po.status
    SM.apply(session, po, "change", reason=reason, extra_after={"version": po.version})
    outbox.emit(session, "purchase_order.changed", "PURCHASE_ORDER", po.id, po.number, {"version": po.version, "changes": changes})
    if previous in ("TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED"):
        po.transmitted_at = clock.now()
        transmission.send(session, po, transmission.channels_for(session.get(Supplier, po.supplier_id)))
        # Every version has its own confirmation SLA; the timer of an older version is ignored when it fires.
        sla_hours = int(rule.body["confirmationSlaHours"])
        po.confirmation_due_at = clock.now() + timedelta(hours=sla_hours)
        workflow.create_timer(session, "PO_CONFIRMATION_SLA", "PURCHASE_ORDER", po.id, po.confirmation_due_at, {"version": po.version})
        workflow.wait(session, _instance(session, po), "F5-07", outcome=f"v{po.version} sent; re-confirmation required within {sla_hours} h")
    if previous == "PARTIALLY_RECEIVED":
        update_receipt_status(session, po)  # reduced to what was received: the order is fully received
    validate(session, po)
    return {"po": po.number, "version": po.version, "status": po.status}


# ---------------------------------------------------------------- delivery schedule (Technical Document §5 delivery_schedule[])
SCHEDULE_RULE = "PO-SCHEDULE"


def schedule_lines(session: Session, po: PurchaseOrder, line: Optional[PoLine] = None) -> list[PoScheduleLine]:
    query = select(PoScheduleLine).where(PoScheduleLine.po_id == po.id)
    if line is not None:
        query = query.where(PoScheduleLine.po_line_id == line.id)
    return session.execute(query.order_by(PoScheduleLine.po_line_id, PoScheduleLine.delivery_date, PoScheduleLine.seq)).scalars().all()


def _default_schedule(session: Session, line: PoLine) -> None:
    """Every new PO line starts with one schedule line: the full quantity on the need date."""
    session.add(PoScheduleLine(tenant_id=line.tenant_id, po_id=line.po_id, po_line_id=line.id, seq=1, qty=line.qty,
                               delivery_date=line.need_date, received_qty=0, created_by=principal(session).user_id))
    session.flush()


def _parse_schedule(line: PoLine, entries: list[dict]) -> list[tuple[Decimal, date]]:
    if not entries:
        raise rule_violation(f"Line {line.line_no}: give at least one schedule line", SCHEDULE_RULE)
    parsed = []
    for entry in entries:
        try:
            qty = D(entry["qty"])
            when = entry.get("deliveryDate") or entry.get("delivery_date")
            when = when if isinstance(when, date) else date.fromisoformat(str(when))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            raise rule_violation(f"Line {line.line_no}: each schedule line needs qty and deliveryDate (YYYY-MM-DD)", SCHEDULE_RULE)
        if qty <= 0:
            raise rule_violation(f"Line {line.line_no}: schedule quantities must be positive", SCHEDULE_RULE)
        if when < clock.today():
            raise rule_violation(f"Line {line.line_no}: delivery date {when.isoformat()} is in the past", SCHEDULE_RULE)
        parsed.append((qty, when))
    total = sum(q for q, _ in parsed)
    if total != line.qty:
        raise Problem(422, "SCHEDULE_QTY_MISMATCH", f"Line {line.line_no}: schedule quantities add up to {jsonable(total)}, "
                      f"the line quantity is {jsonable(line.qty)}", rule_ref=SCHEDULE_RULE, scheduledQty=jsonable(total),
                      lineQty=jsonable(line.qty))
    return sorted(parsed, key=lambda item: item[1])


def _replace_schedule(session: Session, po: PurchaseOrder, line: PoLine, parsed: list[tuple[Decimal, date]]) -> None:
    for old in schedule_lines(session, po, line):
        session.delete(old)
    session.flush()
    for seq, (qty, when) in enumerate(parsed, start=1):
        session.add(PoScheduleLine(tenant_id=po.tenant_id, po_id=po.id, po_line_id=line.id, seq=seq, qty=qty, delivery_date=when,
                                   received_qty=0, created_by=principal(session).user_id))
    session.flush()
    line.need_date = parsed[0][1]
    allocate_receipts(session, po, line)


def _fit_schedule(session: Session, po: PurchaseOrder, line: PoLine, old_need: date) -> None:
    """Keep the schedule consistent with a line-level qty/date change (version n+1 without an explicit schedule)."""
    current = schedule_lines(session, po, line)
    if not current:
        return  # lines migrated before schedule lines existed
    if len(current) == 1:
        current[0].qty = line.qty
        current[0].delivery_date = line.need_date
    else:
        shift = line.need_date - old_need
        if shift:
            for sl in current:
                if sl.received_qty < sl.qty:
                    sl.delivery_date += shift
        delta = line.qty - sum(sl.qty for sl in current)
        if delta:
            last = current[-1]
            if last.qty + delta <= 0 or last.qty + delta < last.received_qty:
                raise rule_violation(f"Line {line.line_no} is delivered on {len(current)} dates; give the new schedule with the quantity change",
                                     SCHEDULE_RULE)
            last.qty += delta
    session.flush()
    allocate_receipts(session, po, line)


def allocate_receipts(session: Session, po: PurchaseOrder, line: PoLine) -> None:
    """Received quantity fills the earliest open schedule line first; over-delivery stays on the last line."""
    current = schedule_lines(session, po, line)
    remaining = D(line.received_qty)
    for sl in current:
        take = min(remaining, sl.qty) if remaining > 0 else Decimal(0)
        sl.received_qty = take
        remaining -= take
    if current and remaining > 0:
        current[-1].received_qty += remaining


def schedule_view(session: Session, po: PurchaseOrder) -> list[dict]:
    today = clock.today()
    lines = {l.id: l for l in lines_of(session, po)}
    out = []
    for sl in schedule_lines(session, po):
        line = lines[sl.po_line_id]
        open_qty = max(sl.qty - sl.received_qty, Decimal(0))
        due = sl.confirmed_date or sl.delivery_date
        out.append({"line": line.line_no, "seq": sl.seq, "description": line.description, "uom": line.uom, "qty": jsonable(sl.qty),
                    "deliveryDate": sl.delivery_date.isoformat(), "confirmedDate": sl.confirmed_date.isoformat() if sl.confirmed_date else None,
                    "receivedQty": jsonable(sl.received_qty), "openQty": jsonable(open_qty),
                    "status": "DELIVERED" if open_qty == 0 else ("PARTIALLY_RECEIVED" if sl.received_qty > 0 else "OPEN"),
                    "daysLate": (today - due).days if open_qty > 0 and due < today else 0})
    return sorted(out, key=lambda r: (r["line"], r["deliveryDate"], r["seq"]))


def set_schedule(session: Session, po: PurchaseOrder, line_no: int, entries: list[dict], reason: Optional[str] = None) -> dict:
    """PUT schedule: before supplier confirmation the schedule is edited in place (audited); after confirmation the
    change is a new PO version that the supplier re-confirms (§6.1)."""
    line = next((l for l in lines_of(session, po) if l.line_no == line_no), None)
    if line is None:
        raise Problem(404, "NOT_FOUND", f"{po.number} has no line {line_no}")
    parsed = _parse_schedule(line, entries)
    # A transmitted order is the supplier's document: once an EDI/e-mail transmission of this version was delivered, or the
    # supplier answered it, a schedule change is version n+1 (ORDCHG) like after confirmation. While the transmissions are
    # still queued the edit stays in place and the queued documents (and the portal view) are regenerated before delivery.
    transmitted_in_place = po.status == "TRANSMITTED" and not transmission.delivered_outside_portal(session, po) and not session.execute(
        select(PoConfirmation.id).where(PoConfirmation.po_id == po.id, PoConfirmation.po_version == po.version)).first()
    if po.status in ("DRAFT", "IN_APPROVAL", "RELEASED") or transmitted_in_place:
        before = [{"seq": sl.seq, "qty": jsonable(sl.qty), "deliveryDate": sl.delivery_date.isoformat()} for sl in schedule_lines(session, po, line)]
        _replace_schedule(session, po, line, parsed)
        after = [{"seq": seq, "qty": jsonable(q), "deliveryDate": d.isoformat()} for seq, (q, d) in enumerate(parsed, start=1)]
        refreshed = transmission.refresh_undelivered(session, po) if transmitted_in_place else []
        audit.record(session, "PURCHASE_ORDER", po.id, "SCHEDULE_CHANGED", object_ref=po.number,
                     before={"line": line_no, "schedule": before}, after={"line": line_no, "version": po.version, "schedule": after,
                                                                          **({"transmissionsRefreshed": transmission.transmission_summary(refreshed)}
                                                                             if transmitted_in_place else {})},
                     reason=reason or "Delivery schedule edited before supplier confirmation")
        return {"po": po.number, "version": po.version, "status": po.status, "mode": "IN_PLACE", "schedule": schedule_view(session, po)}
    if not SM.can(po.status, "change"):
        raise illegal_transition("Purchase order", po.number, po.status, "change schedule")
    result = change_order(session, po, [{"line": line_no, "schedule": [{"qty": jsonable(q), "deliveryDate": d.isoformat()} for q, d in parsed]}],
                          reason or f"Delivery schedule of line {line_no} changed")
    return {**result, "mode": "NEW_VERSION", "schedule": schedule_view(session, po)}


@workflow.on_timer("PO_CONFIRMATION_SLA")
def _confirmation_overdue(session: Session, timer) -> None:
    po = session.get(PurchaseOrder, timer.object_id)
    if po is None or not awaiting_confirmation(session, po):
        return
    if int((timer.payload or {}).get("version", po.version)) != po.version:
        return  # the SLA of a superseded version; the current version has its own timer
    if session.execute(select(PoConfirmation.id).where(PoConfirmation.po_id == po.id, PoConfirmation.po_version == po.version,
                                                       PoConfirmation.status.in_(("REJECTED", "CHANGE_REQUESTED")))).first():
        return  # the supplier answered this version (rejection / change request): the buyer's review task is open instead
    ai_ref = agents.log_run(session, "EXPEDITING", object_type="PURCHASE_ORDER", object_id=po.id, object_ref=po.number,
                            inputs={"dueAt": po.confirmation_due_at.isoformat()}, evidence=[po.number],
                            output={"draft": f"Please confirm {po.number} v{po.version} today."}, confidence=0.7, action_taken="DRAFTED")
    workflow.start_approval(session, _instance(session, po), "EXPEDITE", object_type="PURCHASE_ORDER", object_id=po.id,
                            object_ref=po.number, chain=["BUYER"], step_id=None, initiator_id=None, evidence={"aiRef": ai_ref})


@workflow.on_task("EXPEDITE")
def _expedited(session: Session, task: Task, outcome: str) -> None:
    audit.record(session, "PURCHASE_ORDER", task.object_id, "EXPEDITED", object_ref=task.object_ref, reason=task.comment)


def update_receipt_status(session: Session, po: PurchaseOrder) -> None:
    lines = lines_of(session, po)
    goods = [l for l in lines if l.gr_required]
    if not goods:
        return
    if all(l.received_qty >= l.qty * (1 - D(po.tolerance.get("under_pct", 0)) / 100) for l in goods):
        command = "receive"
    elif any(l.received_qty > 0 for l in goods):
        command = "receive_partially"
    else:
        return
    if SM.can(po.status, command) and not (command == "receive_partially" and po.status == "PARTIALLY_RECEIVED"):
        SM.apply(session, po, command)


def receipt_reversed(session: Session, po: PurchaseOrder, gr_number: str, reason: Optional[str] = None) -> None:
    """After a goods-receipt reversal (movement 102) the order is open again for the quantity taken back: RECEIVED goes
    back to PARTIALLY_RECEIVED, or to CONFIRMED (TRANSMITTED if the current version was never confirmed) when nothing
    received remains, so the correct receipt can be posted."""
    if po.status not in ("RECEIVED", "PARTIALLY_RECEIVED"):
        return
    goods = [l for l in lines_of(session, po) if l.gr_required]
    under = D(po.tolerance.get("under_pct", 0))
    if goods and all(l.received_qty >= l.qty * (1 - under / 100) for l in goods):
        return
    if any(l.received_qty > 0 for l in goods):
        command = "unreceive_partially"
    else:
        confirmed = session.execute(select(PoConfirmation.id).where(PoConfirmation.po_id == po.id, PoConfirmation.po_version == po.version,
                                                                    PoConfirmation.status == "CONFIRMED")).first()
        command = "unreceive" if confirmed else "unreceive_unconfirmed"
    if SM.can(po.status, command):
        SM.apply(session, po, command, reason=reason or f"goods receipt {gr_number} reversed")


# ---------------------------------------------------------------- cancellation and closure (§6.1 PO states)
def _release_requisition(session: Session, po: PurchaseOrder, line: PoLine, qty: Optional[Decimal] = None) -> None:
    """Give a cancelled line's quantity (or the open quantity of a short-closed line) back to its requisition line so the
    buyer can re-order it."""
    if not line.requisition_id:
        return
    pr = session.get(Requisition, line.requisition_id)
    pr_line = session.execute(select(PrLine).where(PrLine.requisition_id == pr.id, PrLine.line_no == line.pr_line_no)).scalar_one_or_none()
    if pr_line is None:
        return
    pr_line.ordered_qty = max(pr_line.ordered_qty - (line.qty if qty is None else qty), Decimal(0))
    if pr_line.sourcing_status == "ORDERED":
        pr_line.sourcing_status = "SOURCED"
    remaining = [l.ordered_qty for l in req_svc._lines(session, pr)]
    command = "reopen" if all(q == 0 for q in remaining) else "reopen_partially"
    if pr.status == "PARTIALLY_ORDERED" and command == "reopen_partially":
        return
    if req_svc.SM.can(pr.status, command):
        req_svc.SM.apply(session, pr, command, reason=f"{po.number} cancelled")


def cancel(session: Session, po: PurchaseOrder, reason: str) -> dict:
    """Cancel an order that nothing has been shipped, received or invoiced against (e.g. the supplier rejected it). Open
    tasks and the confirmation timer close, the requisition quantity is released for re-ordering, and
    ``purchase_order.cancelled`` informs the ERP, the supplier portal and contract consumption."""
    from app.pic.models import Timer

    if not (reason or "").strip():
        raise Problem(422, "REASON_REQUIRED", "Give the reason for the cancellation", rule_ref="PO-CANCEL")
    if not SM.can(po.status, "cancel"):
        raise illegal_transition("Purchase order", po.number, po.status, "cancel")
    lines = lines_of(session, po)
    if any(l.shipped_qty > 0 or l.received_qty > 0 or l.invoiced_qty > 0 or l.ses_approved_minor > 0 for l in lines):
        raise rule_violation(f"{po.number} has shipments, receipts or invoices; it cannot be cancelled", "PO-CANCEL")
    from app.pic.models import ServiceEntry
    open_entries = session.execute(select(ServiceEntry.number).where(ServiceEntry.po_id == po.id, ServiceEntry.status.in_(("DRAFT", "SUBMITTED")))
                                   .order_by(ServiceEntry.number)).scalars().all()
    if open_entries:
        # A service entry still in approval would otherwise stay approvable against a cancelled order.
        raise Problem(409, "SERVICE_ENTRIES_OPEN", f"{po.number} has service entr{'y' if len(open_entries) == 1 else 'ies'} "
                      f"{', '.join(open_entries)} awaiting approval; have them rejected first", rule_ref="PO-CANCEL", serviceEntries=open_entries)
    before = po.status
    SM.apply(session, po, "cancel", reason=reason.strip(), extra_after={"version": po.version})
    for task in session.execute(select(Task).where(Task.object_id == po.id, Task.status == "OPEN")).scalars():
        task.status = "CANCELLED"
        for timer in session.execute(select(Timer).where(Timer.object_id == task.id, Timer.fired_at.is_(None))).scalars():
            timer.fired_at, timer.payload = clock.now(), {**(timer.payload or {}), "cancelled": True}
    for timer in session.execute(select(Timer).where(Timer.object_id == po.id, Timer.kind == "PO_CONFIRMATION_SLA",
                                                     Timer.fired_at.is_(None))).scalars():
        timer.fired_at, timer.payload = clock.now(), {**(timer.payload or {}), "cancelled": True}
    # Contract consumption is recomputed from the live PO lines by the consumer of purchase_order.cancelled
    # (contract.recompute_consumption); it is not adjusted here.
    for line in lines:
        _release_requisition(session, po, line)
    # F5-06: an order the supplier already received is cancelled over the same channels (portal, EDI ORDCHG, e-mail);
    # EDI and e-mail are delivered by the po-transmission-delivery consumer of purchase_order.cancelled.
    from app.pic.models import PoTransmission
    sent = []
    if session.execute(select(PoTransmission.id).where(PoTransmission.po_id == po.id).limit(1)).first():
        sent = transmission.send_cancellation(session, po, reason.strip())
    outbox.emit(session, "purchase_order.cancelled", "PURCHASE_ORDER", po.id, po.number,
                {"version": po.version, "from": before, "reason": reason.strip(), "supplier": session.get(Supplier, po.supplier_id).code,
                 "transmissions": transmission.transmission_summary(sent)})
    instance = _instance(session, po)
    if instance is not None and instance.status == "RUNNING":
        workflow.end(session, instance, instance.current_step or "F5-07", outcome=f"cancelled: {reason.strip()}", status="CANCELLED")
    return {"po": po.number, "status": po.status, "from": before}


@outbox.consumer("purchase_order.cancelled", "erp-po-posting")
def _post_po_cancellation(session: Session, event) -> None:
    from app.pic.models import IntegrationMessage
    po = session.get(PurchaseOrder, event.object_id)
    if not po.erp_doc_no:
        pending = session.execute(select(IntegrationMessage.idempotency_key).where(
            IntegrationMessage.object_id == po.id, IntegrationMessage.message_type == "PURCHASE_ORDER",
            IntegrationMessage.status.in_(("PENDING", "RETRY")))).scalars().all()
        if pending:
            # The order posting is still being retried: the cancellation follows as soon as it posts (_po_posted).
            audit.record(session, "PURCHASE_ORDER", po.id, "ERP_CANCEL_DEFERRED", object_ref=po.number,
                         after={"waitingFor": pending}, reason=event.payload.get("reason"))
        return  # otherwise it never reached the ERP
    _enqueue_erp_cancel(session, po, event.payload.get("reason"))


def _enqueue_erp_cancel(session: Session, po: PurchaseOrder, reason: Optional[str]) -> None:
    message = integration.enqueue(session, target_system=integration.target_system(session, po.company_code), message_type="PURCHASE_ORDER",
                                  idempotency_key=f"{po.company_code}|PO|{po.number}|CANCEL", object_type="PURCHASE_ORDER",
                                  object_id=po.id, object_ref=po.number,
                                  payload={"po": po.number, "version": po.version, "action": "CANCEL", "erpDocument": po.erp_doc_no,
                                           "companyCode": po.company_code, "reason": reason})
    integration.process(session, message)


def close(session: Session, po: PurchaseOrder, reason: Optional[str] = None) -> dict:
    """Close an order with nothing left to receive or invoice: INVOICED, or RECEIVED where every accepted quantity is
    invoiced (a lot rejected in full and returned). No invoice may still be in process. A requisition whose orders are
    all closed or cancelled is closed with it."""
    from app.pic.models import Invoice, InvoiceLine

    if not SM.can(po.status, "close"):
        raise illegal_transition("Purchase order", po.number, po.status, "close")
    lines = lines_of(session, po)
    open_lines = [l.line_no for l in lines if l.accepted_qty > l.invoiced_qty or (l.ses_required and l.ses_approved_minor > l.invoiced_minor)]
    if open_lines:
        raise rule_violation(f"{po.number} lines {open_lines} still have received value to invoice", "PO-CLOSE")
    pending = session.execute(select(Invoice.number).join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id).where(
        InvoiceLine.po_line_id.in_([l.id for l in lines]), Invoice.status.not_in(("POSTED", "PAID", "REJECTED")))).scalars().first()
    if pending:
        raise rule_violation(f"Invoice {pending} on {po.number} is still in process", "PO-CLOSE")
    before = po.status
    SM.apply(session, po, "close", reason=reason or "nothing left to receive or invoice")
    outbox.emit(session, "purchase_order.closed", "PURCHASE_ORDER", po.id, po.number, {"from": before, "reason": reason})
    closed_requisitions = []
    for requisition_id in {l.requisition_id for l in lines if l.requisition_id}:
        pr = session.get(Requisition, requisition_id)
        others = session.execute(select(PurchaseOrder.status).join(PoLine, PoLine.po_id == PurchaseOrder.id).where(
            PoLine.requisition_id == requisition_id)).scalars().all()
        if pr.status == "ORDERED" and all(status in ("CLOSED", "CANCELLED") for status in others):
            req_svc.SM.apply(session, pr, "close", reason=f"all orders closed ({po.number} last)")
            closed_requisitions.append(pr.number)
    return {"po": po.number, "status": po.status, "from": before, "closedRequisitions": closed_requisitions}


def short_close(session: Session, po: PurchaseOrder, reason: str) -> dict:
    """Short-close a partly delivered order: the rest will not be delivered. Allowed once every received (accepted) quantity
    is invoiced, with no lot still in inspection, no ASN in transit and no invoice or service entry still in process. The
    open quantity goes back to the requisition, open tasks and the confirmation timer close, and ``purchase_order.closed`` (shortClose: true) carries the
    released quantity and value per line (contract consumption is recomputed by its consumer; the line quantity stays as
    ordered, the received quantity is what was consumed)."""
    from app.pic.models import Asn, GoodsReceipt, InspectionLot, Invoice, InvoiceLine, ServiceEntry, Timer

    if len((reason or "").strip()) < 3:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for the short-close", rule_ref="PO-CLOSE")
    if not SM.can(po.status, "short_close"):
        raise illegal_transition("Purchase order", po.number, po.status, "short-close")
    lines = lines_of(session, po)
    blockers = []
    uninvoiced = [l.line_no for l in lines if l.accepted_qty > l.invoiced_qty or (l.ses_required and l.ses_approved_minor > l.invoiced_minor)]
    if uninvoiced:
        blockers.append(f"lines {uninvoiced} still have received value to invoice")
    in_transit = session.execute(select(Asn.number).where(Asn.po_id == po.id, Asn.status == "IN_TRANSIT").order_by(Asn.number)).scalars().all()
    if in_transit:
        blockers.append(f"ASN {', '.join(in_transit)} in transit (receive it first)")
    lots = session.execute(select(InspectionLot.number).join(GoodsReceipt, GoodsReceipt.id == InspectionLot.gr_id).where(
        GoodsReceipt.po_id == po.id, InspectionLot.status == "OPEN")).scalars().all()
    if lots:
        blockers.append(f"inspection lot {', '.join(lots)} awaiting the usage decision")
    pending = session.execute(select(Invoice.number).join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id).where(
        InvoiceLine.po_line_id.in_([l.id for l in lines]), Invoice.status.not_in(("POSTED", "PAID", "REJECTED")))).scalars().first()
    if pending:
        blockers.append(f"invoice {pending} is still in process")
    entries = session.execute(select(ServiceEntry.number).where(ServiceEntry.po_id == po.id, ServiceEntry.status.in_(("DRAFT", "SUBMITTED")))).scalars().all()
    if entries:
        blockers.append(f"service entr{'y' if len(entries) == 1 else 'ies'} {', '.join(entries)} awaiting approval")
    if blockers:
        raise rule_violation(f"{po.number} cannot be short-closed: " + "; ".join(blockers), "PO-CLOSE", blockers=blockers)
    before = po.status
    SM.apply(session, po, "short_close", reason=reason.strip())
    released = []
    for line in lines:
        open_qty = max(line.qty - line.received_qty, Decimal(0))
        if open_qty <= 0:
            continue
        _release_requisition(session, po, line, open_qty)
        released.append({"line": line.line_no, "releasedQty": jsonable(open_qty), "releasedValueMinor": line_amount(open_qty, line.unit_price_minor),
                         "contractLineId": str(line.contract_line_id) if line.contract_line_id else None,
                         "requisitionId": str(line.requisition_id) if line.requisition_id else None, "prLine": line.pr_line_no})
    for task in session.execute(select(Task).where(Task.object_id == po.id, Task.status == "OPEN")).scalars():
        task.status = "CANCELLED"
        for timer in session.execute(select(Timer).where(Timer.object_id == task.id, Timer.fired_at.is_(None))).scalars():
            timer.fired_at, timer.payload = clock.now(), {**(timer.payload or {}), "cancelled": True}
    for timer in session.execute(select(Timer).where(Timer.object_id == po.id, Timer.kind == "PO_CONFIRMATION_SLA", Timer.fired_at.is_(None))).scalars():
        timer.fired_at, timer.payload = clock.now(), {**(timer.payload or {}), "cancelled": True}
    audit.record(session, "PURCHASE_ORDER", po.id, "SHORT_CLOSED", object_ref=po.number, reason=reason.strip(),
                 after={"from": before, "version": po.version, "released": released})
    outbox.emit(session, "purchase_order.closed", "PURCHASE_ORDER", po.id, po.number,
                {"from": before, "reason": reason.strip(), "shortClose": True, "version": po.version, "lines": released,
                 "releasedValueMinor": sum(r["releasedValueMinor"] for r in released)})
    instance = _instance(session, po)
    if instance is not None and instance.status == "RUNNING":
        workflow.end(session, instance, instance.current_step or "F5-10", outcome=f"short-closed: {reason.strip()}")
    return {"po": po.number, "status": po.status, "from": before, "released": released}


def resubmit(session: Session, po: PurchaseOrder, reason: str, changes: Optional[list[dict]] = None,
             deviation_reason: Optional[str] = None) -> dict:
    """An order returned by its approver (IN_APPROVAL → DRAFT) is corrected in place — it was never sent — and routed
    again: line quantity (within the requisition), unit price (P07 deviation against the contract needs a reason) and need
    date; then validation (F5-03) and the approval strategy (F5-04/05) run as for a new order."""
    if po.status != "DRAFT":
        raise illegal_transition("Purchase order", po.number, po.status, "re-submit")
    if len((reason or "").strip()) < 3:
        raise Problem(422, "REASON_REQUIRED", "Say what was corrected for the approver", rule_ref="PO-APPROVAL")
    lines = {l.line_no: l for l in lines_of(session, po)}
    tolerance = D(po.tolerance.get("price_pct", 0))
    applied = []
    for change in changes or []:
        line = lines.get(int(change["line"]))
        if line is None:
            raise Problem(422, "UNKNOWN_LINE", f"{po.number} has no line {change['line']}")
        old_need = line.need_date
        if "qty" in change:
            qty = D(change["qty"])
            if qty <= 0:
                raise Problem(422, "INVALID_QUANTITY", f"Line {line.line_no}: the quantity must be positive", rule_ref="PO-APPROVAL")
            delta = qty - line.qty
            if delta and line.requisition_id:
                pr = session.get(Requisition, line.requisition_id)
                pr_line = session.execute(select(PrLine).where(PrLine.requisition_id == pr.id, PrLine.line_no == line.pr_line_no)).scalar_one()
                if delta > 0:
                    if pr_line.qty - pr_line.ordered_qty < delta:
                        raise rule_violation(f"Line {line.line_no}: {jsonable(qty)} exceeds what {pr.number}/{pr_line.line_no} still has open "
                                             f"({jsonable(pr_line.qty - pr_line.ordered_qty + line.qty)})", "P07")
                    req_svc.mark_ordered(session, pr, pr_line, delta)
                else:
                    _release_requisition(session, po, line, -delta)
            line.qty = qty
        if "need_date" in change:
            line.need_date = date.fromisoformat(str(change["need_date"]))
        if "unit_price" in change:
            price = int(D(change["unit_price"]) * 100)
            if price <= 0:
                raise Problem(422, "INVALID_PRICE", f"Line {line.line_no}: the unit price must be positive", rule_ref="PO-APPROVAL")
            line.unit_price_minor = price
            contract_price = _contract_price_minor(session, line, line.need_date)
            if contract_price is not None:
                deviation = abs(Decimal(price - contract_price)) > Decimal(contract_price) * tolerance / 100
                if deviation and not (deviation_reason or "").strip():
                    raise rule_violation("Price deviates from the contract beyond tolerance; a deviation reason is required", "P07")
                line.price_deviation, line.deviation_reason = deviation, deviation_reason.strip() if deviation else None
        line.net_minor = line_amount(line.qty, line.unit_price_minor)
        _fit_schedule(session, po, line, old_need)
        applied.append(jsonable(change))
    po.total_minor = sum(l.net_minor for l in lines.values())
    audit.record(session, "PURCHASE_ORDER", po.id, "RESUBMITTED", object_ref=po.number, reason=reason.strip(),
                 after={"changes": applied, "totalMinor": po.total_minor, "deviationReason": deviation_reason})
    validate(session, po)
    route(session, po)
    return {"po": po.number, "version": po.version, "status": po.status, "totalMinor": po.total_minor}


# ---------------------------------------------------------------- PO-03 change requests after confirmation
def request_change(session: Session, po: PurchaseOrder, lines: list[dict], reason: str):
    """Supplier (or buyer) proposes a qty/date change on a released order; the buyer decides, acceptance creates version n+1."""
    from app.pic.models import PoChangeRequest
    p = principal(session)
    require_supplier_user(session, po.supplier_id)
    if po.status not in ("RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED"):
        raise illegal_transition("Purchase order", po.number, po.status, "request change")
    if not lines or not reason:
        raise Problem(422, "CHANGE_REQUIRED", "A change request lists the changed lines and a reason")
    po_lines = {l.line_no: l for l in lines_of(session, po)}
    for change in lines:
        line = po_lines.get(int(change["line"]))
        if line is None:
            raise Problem(422, "UNKNOWN_LINE", f"{po.number} has no line {change['line']}")
        if not set(change) & {"qty", "need_date"}:
            raise Problem(422, "CHANGE_REQUIRED", "Each line changes qty and/or need_date (price changes go through the contract)")
        if "qty" in change and D(change["qty"]) < line.received_qty:
            raise Problem(422, "BELOW_RECEIVED", f"Line {line.line_no}: {line.received_qty} already received")
    if session.execute(select(PoChangeRequest.id).where(PoChangeRequest.po_id == po.id, PoChangeRequest.status == "OPEN")).first():
        raise Problem(409, "CHANGE_PENDING", f"{po.number} already has an open change request")
    origin = "SUPPLIER" if "SUPPLIER_USER" in p.roles else "BUYER"
    pcr = PoChangeRequest(tenant_id=po.tenant_id, number=next_number(session, "PO_CHANGE"), po_id=po.id, po_version=po.version, origin=origin,
                          lines=[{k: str(v) for k, v in c.items()} for c in lines], reason=reason, created_by=p.user_id)
    session.add(pcr)
    session.flush()
    workflow.start_approval(session, _instance(session, po), "PO_CHANGE_REQUEST", object_type="PURCHASE_ORDER", object_id=po.id,
                            object_ref=po.number, chain=["BUYER"], step_id=None, initiator_id=p.user_id,
                            evidence={"changeRequest": pcr.number, "lines": pcr.lines, "reason": reason, "origin": origin})
    audit.record(session, "PURCHASE_ORDER", po.id, "CHANGE_REQUESTED", object_ref=po.number, after={"request": pcr.number, "lines": pcr.lines},
                 reason=reason)
    return pcr


@workflow.on_task("PO_CHANGE_REQUEST")
def _change_request_decided(session: Session, task: Task, outcome: str) -> None:
    from app.pic.models import PoChangeRequest
    pcr = session.execute(select(PoChangeRequest).where(PoChangeRequest.number == task.evidence["changeRequest"])).scalar_one()
    po = session.get(PurchaseOrder, pcr.po_id)
    pcr.decided_by, pcr.decided_at, pcr.decision_comment = principal(session).user_id, clock.now(), task.comment
    if outcome == "APPROVED":
        result = change_order(session, po, pcr.lines, reason=f"{pcr.number} ({pcr.origin.lower()}): {pcr.reason}", change_request=pcr.number)
        # A change that needs PO approval first (higher value band) gets its version once approved (_change_approval_decided).
        pcr.status, pcr.result_version = "ACCEPTED", None if result.get("approval") == "PENDING" else result["version"]
    else:
        pcr.status = "REJECTED"
        audit.record(session, "PURCHASE_ORDER", po.id, "CHANGE_REJECTED", object_ref=po.number, after={"request": pcr.number}, reason=task.comment)


def confirmations_view(session: Session) -> dict:
    """PO-03: confirmations by version, change requests and version history."""
    from app.pic.models import PoChangeRequest
    pos = {po.id: po for po in session.execute(select(PurchaseOrder)).scalars()}
    suppliers = {s.id: s.code for s in session.execute(select(Supplier)).scalars()}
    confirmations = [{"po": pos[c.po_id].number, "supplier": suppliers.get(pos[c.po_id].supplier_id), "version": c.po_version, "status": c.status,
                      "hoursToConfirm": str(c.hours_to_confirm) if c.hours_to_confirm is not None else None, "note": c.note, "lines": c.lines,
                      "at": c.created_at.isoformat()} for c in session.execute(select(PoConfirmation).order_by(PoConfirmation.created_at.desc())).scalars()]
    requests = [{"number": r.number, "po": pos[r.po_id].number, "supplier": suppliers.get(pos[r.po_id].supplier_id), "fromVersion": r.po_version,
                 "origin": r.origin, "lines": r.lines, "reason": r.reason, "status": r.status, "resultVersion": r.result_version,
                 "decisionComment": r.decision_comment, "at": r.created_at.isoformat()}
                for r in session.execute(select(PoChangeRequest).order_by(PoChangeRequest.created_at.desc())).scalars()]
    versions = [{"po": pos[v.po_id].number, "version": v.version, "reason": v.change_reason, "changes": v.changes, "at": v.created_at.isoformat()}
                for v in session.execute(select(PoVersion).order_by(PoVersion.created_at.desc())).scalars()]
    awaiting = [{"po": po.number, "supplier": suppliers.get(po.supplier_id), "version": po.version,
                 "dueAt": po.confirmation_due_at.isoformat() if po.confirmation_due_at else None,
                 "overdue": bool(po.confirmation_due_at and po.confirmation_due_at < clock.now())}
                for po in pos.values() if po.status == "TRANSMITTED"]
    timed = [c for c in confirmations if c["status"] == "CONFIRMED" and c["hoursToConfirm"] is not None]
    sla = rules.resolve(session, "PO-APPROVAL").body["confirmationSlaHours"]
    return {"awaiting": awaiting, "confirmations": confirmations, "changeRequests": requests, "versions": versions, "confirmationSlaHours": sla,
            "withinSlaPct": f"{sum(1 for c in timed if Decimal(c['hoursToConfirm']) <= sla) * 100 / len(timed):.1f}" if timed else None,
            "changeRatePct": f"{len({v['po'] for v in versions}) * 100 / len(pos):.1f}" if pos else None}


def expediting_view(session: Session) -> list[dict]:
    """PO-04: open schedule lines with days late, the supplier twin's late-delivery probability and the latest ASN."""
    from app.pic.models import Asn, TwinSnapshot
    today = clock.today()
    suppliers = {s.id: s for s in session.execute(select(Supplier)).scalars()}
    out = []
    for line, po in session.execute(select(PoLine, PurchaseOrder).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
            PurchaseOrder.status.in_(("RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED")), PoLine.gr_required.is_(True),
            PoLine.received_qty < PoLine.qty)).all():
        supplier = suppliers[po.supplier_id]
        material = session.get(Material, line.material_id) if line.material_id else None
        category = material.category if material else line.material_group
        twin = session.execute(select(TwinSnapshot).where(TwinSnapshot.supplier_id == supplier.id, TwinSnapshot.category == category)
                               .order_by(TwinSnapshot.as_of.desc())).scalars().first()
        asn = session.execute(select(Asn).where(Asn.po_id == po.id).order_by(Asn.created_at.desc())).scalars().first()
        late_prob = twin.late_delivery_prob if twin else None
        # With a delivery schedule, lateness is per open schedule line (confirmed date if the supplier gave one).
        schedule = [sl for sl in schedule_lines(session, po, line) if sl.received_qty < sl.qty]
        buckets = [(sl.seq, sl.qty - sl.received_qty, sl.confirmed_date or sl.delivery_date, sl.confirmed_date) for sl in schedule] \
            or [(None, line.qty - line.received_qty, line.need_date, None)]
        for seq, open_qty, due, confirmed in buckets:
            days_late = (today - due).days if due and due < today else 0
            soon = due is not None and (due - today).days <= 7
            risk = "LATE" if days_late > 0 else "AT_RISK" if (late_prob is not None and late_prob >= Decimal("0.30")) or (soon and asn is None) else "ON_TRACK"
            out.append({"po": po.number, "line": line.line_no, "scheduleSeq": seq, "supplier": supplier.code, "description": line.description,
                        "openQty": str(open_qty), "uom": line.uom, "needDate": due.isoformat() if due else None,
                        "confirmedDate": confirmed.isoformat() if confirmed else None, "daysLate": days_late, "status": po.status,
                        "lateProb": str(late_prob) if late_prob is not None else None, "asn": asn.number if asn else None, "risk": risk,
                        "valueAtRiskMinor": line_amount(open_qty, line.unit_price_minor) if risk != "ON_TRACK" else 0})
    return sorted(out, key=lambda r: ({"LATE": 0, "AT_RISK": 1, "ON_TRACK": 2}[r["risk"]], -r["daysLate"], r["needDate"] or ""))


def expedite(session: Session, po: PurchaseOrder, line_no: int, message: Optional[str] = None) -> dict:
    """Expediting Agent (L2) drafts the follow-up; the buyer sends it (audited on the PO and shown in the portal)."""
    line = next((l for l in lines_of(session, po) if l.line_no == line_no), None)
    if line is None:
        raise Problem(404, "NOT_FOUND", f"{po.number} has no line {line_no}")
    due = line.need_date.isoformat() if line.need_date else "as scheduled"
    draft = message or (f"Please confirm delivery of {po.number}/{line_no} ({line.qty - line.received_qty} {line.uom} {line.description}) "
                        f"due {due}, and send the ASN.")
    ai_ref = agents.log_run(session, "EXPEDITING", object_type="PURCHASE_ORDER", object_id=po.id, object_ref=po.number,
                            inputs={"line": line_no}, evidence=[po.number], output={"draft": draft}, confidence=0.7, action_taken="DRAFTED")
    audit.record(session, "PURCHASE_ORDER", po.id, "EXPEDITED", object_ref=po.number, after={"line": line_no, "message": draft}, ai_ref=ai_ref)
    return {"po": po.number, "line": line_no, "message": draft, "aiRef": ai_ref}
