"""F5 Purchase order → supplier confirmation → delivery (M08)."""
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    Contract, ContractLine, Material, PoConfirmation, PoLine, PoVersion, PrLine, PurchaseOrder, Requisition, Supplier, Task,
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
    ("INVOICED", "close"): "CLOSED",
    ("DRAFT", "cancel"): "CANCELLED",
    ("RELEASED", "cancel"): "CANCELLED",
    ("TRANSMITTED", "cancel"): "CANCELLED",
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
                            deviation_reason: Optional[str] = None) -> list[PurchaseOrder]:
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
    return pos


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
    for index, (pr_line, allocation) in enumerate(items, start=1):
        material = session.get(Material, pr_line.material_id) if pr_line.material_id else None
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
            gst_rate=material.gst_rate if material else D(18), hsn_code=material.hsn_code if material else None,
            need_date=need_date or pr_line.need_date, plant=pr_line.plant, storage_location=pr_line.storage_location,
            account_assignment_type=pr_line.account_assignment_type, account_assignment_code=pr_line.account_assignment_code,
            gr_required=bool(flags["gr"]) and not receiptless, ir_required=bool(flags["ir"]), ses_required=bool(flags["ses"]),
            ers=bool(flags.get("ers", False)), quality_managed=bool(material.quality_managed) if material else False,
            price_source=allocation.price_source, contract_line_id=allocation.contract_line_id,
            price_validity_id=allocation.price_validity_id, price_deviation=deviation, deviation_reason=deviation_reason if deviation else None,
            requisition_id=pr.id, pr_line_no=pr_line.line_no, created_by=p.user_id,
        )
        session.add(po_line)
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
    po.inherited = {"price": items[0][1].unit_price_minor, "paymentTerms": po.payment_terms, "incoterms": po.incoterms,
                    "tolerance": tolerance, "contract": contract.number if contract else None,
                    "sourceDetermination": determinations}
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


def transmit(session: Session, po: PurchaseOrder, via: str = "PORTAL") -> None:
    SM.apply(session, po, "transmit", extra_after={"via": via})
    po.transmitted_via = via
    po.transmitted_at = clock.now()
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
    message = integration.enqueue(session, target_system="SAP_S4", message_type="PURCHASE_ORDER",
                                  idempotency_key=f"{po.company_code}|PO|{po.number}|v{po.version}", object_type="PURCHASE_ORDER",
                                  object_id=po.id, object_ref=po.number,
                                  payload={"po": po.number, "version": po.version, "supplier": supplier.code, "companyCode": po.company_code,
                                           "lines": [{"line": l.line_no, "qty": str(l.qty), "priceMinor": l.unit_price_minor}
                                                     for l in lines_of(session, po)]})
    integration.process(session, message)


@integration.on_posted("PURCHASE_ORDER")
def _po_posted(session: Session, message) -> None:
    po = session.get(PurchaseOrder, message.object_id)
    po.erp_doc_no = message.erp_doc_no


# ---------------------------------------------------------------- supplier confirmation (F5-07/08) and change orders
def confirm(session: Session, po: PurchaseOrder, status: str, lines: Optional[list[dict]] = None, note: Optional[str] = None) -> dict:
    p = principal(session)
    require_supplier_user(session, po.supplier_id)
    if po.status != "TRANSMITTED":
        raise illegal_transition("Purchase order", po.number, po.status, "confirm")
    hours = Decimal((clock.now() - po.transmitted_at).total_seconds() / 3600).quantize(Decimal("0.01"))
    instance = _instance(session, po)
    proposed = lines or []
    outside = ["supplier rejected the order"] if status.upper() == "REJECTED" else []
    po_lines = {l.line_no: l for l in lines_of(session, po)}
    for change in proposed:
        line = po_lines[int(change["line"])]
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
    workflow.step(session, instance, "F5-07", outcome=f"{record.status.lower().replace('_', ' ')} in {hours} h")
    if outside:
        workflow.step(session, instance, "F5-08", outcome="no: " + "; ".join(outside) + " → back to buyer")
        workflow.start_approval(session, instance, "PO_CHANGE_REVIEW", object_type="PURCHASE_ORDER", object_id=po.id,
                                object_ref=po.number, chain=["BUYER"], step_id=None, initiator_id=None,
                                evidence={"proposed": proposed, "outside": outside, "note": note})
        audit.record(session, "PURCHASE_ORDER", po.id, "SUPPLIER_CHANGE_REQUESTED", object_ref=po.number, after={"changes": proposed}, reason=note)
        return {"status": po.status, "confirmation": "CHANGE_REQUESTED", "outsideTolerance": outside}
    SM.apply(session, po, "confirm", extra_after={"hoursToConfirm": str(hours)})
    outbox.emit(session, "purchase_order.confirmed", "PURCHASE_ORDER", po.id, po.number, {"version": po.version, "hours": str(hours)})
    workflow.step(session, instance, "F5-08", outcome="yes: confirmed as ordered" if not proposed else "yes: changes within tolerance")
    if all(l.ses_required for l in po_lines.values()):
        workflow.step(session, instance, "F5-09", outcome="service order: performance confirmed by service entry sheet (F6)")
        workflow.end(session, instance, "F5-10", outcome="service in progress")
    else:
        workflow.wait(session, instance, "F5-09", outcome="ship & send ASN")
    return {"status": po.status, "confirmation": "CONFIRMED", "hoursToConfirm": str(hours)}


@workflow.on_task("PO_CHANGE_REVIEW")
def _change_reviewed(session: Session, task: Task, outcome: str) -> None:
    po = session.get(PurchaseOrder, task.object_id)
    if outcome == "APPROVED":
        changes = [{k: v for k, v in c.items()} for c in task.evidence.get("proposed", [])]
        change_order(session, po, changes, reason=f"supplier proposal accepted: {task.comment or ''}".strip())
    else:
        audit.record(session, "PURCHASE_ORDER", po.id, "SUPPLIER_CHANGE_DECLINED", object_ref=po.number, reason=task.comment)


def change_order(session: Session, po: PurchaseOrder, changes: list[dict], reason: str) -> dict:
    """Change of qty/price/date creates version n+1 and requires supplier re-confirmation (§6.1)."""
    if not SM.can(po.status, "change"):
        raise illegal_transition("Purchase order", po.number, po.status, "change")
    lines = {l.line_no: l for l in lines_of(session, po)}
    snapshot = {"header": row(po), "lines": [row(l) for l in lines.values()]}
    session.add(PoVersion(tenant_id=po.tenant_id, po_id=po.id, version=po.version, snapshot=snapshot, change_reason=reason,
                          changes=changes, created_by=principal(session).user_id))
    for change in changes:
        line = lines[int(change["line"])]
        if "qty" in change:
            line.qty = D(change["qty"])
        if "need_date" in change:
            line.need_date = date.fromisoformat(str(change["need_date"]))
        if "unit_price" in change:
            line.unit_price_minor = int(D(change["unit_price"]) * 100)
        line.net_minor = line_amount(line.qty, line.unit_price_minor)
    po.total_minor = sum(l.net_minor for l in lines.values())
    po.version += 1
    previous = po.status
    SM.apply(session, po, "change", reason=reason, extra_after={"version": po.version})
    outbox.emit(session, "purchase_order.changed", "PURCHASE_ORDER", po.id, po.number, {"version": po.version, "changes": changes})
    if previous in ("TRANSMITTED", "CONFIRMED"):
        po.transmitted_at = clock.now()
        workflow.wait(session, _instance(session, po), "F5-07", outcome=f"v{po.version} sent; re-confirmation required")
    validate(session, po)
    return {"po": po.number, "version": po.version, "status": po.status}


@workflow.on_timer("PO_CONFIRMATION_SLA")
def _confirmation_overdue(session: Session, timer) -> None:
    po = session.get(PurchaseOrder, timer.object_id)
    if po is None or po.status != "TRANSMITTED":
        return
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
        result = change_order(session, po, pcr.lines, reason=f"{pcr.number} ({pcr.origin.lower()}): {pcr.reason}")
        pcr.status, pcr.result_version = "ACCEPTED", result["version"]
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
        days_late = (today - line.need_date).days if line.need_date and line.need_date < today else 0
        soon = line.need_date is not None and (line.need_date - today).days <= 7
        risk = "LATE" if days_late > 0 else "AT_RISK" if (late_prob is not None and late_prob >= Decimal("0.30")) or (soon and asn is None) else "ON_TRACK"
        open_qty = line.qty - line.received_qty
        out.append({"po": po.number, "line": line.line_no, "supplier": supplier.code, "description": line.description, "openQty": str(open_qty),
                    "uom": line.uom, "needDate": line.need_date.isoformat() if line.need_date else None, "daysLate": days_late, "status": po.status,
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
