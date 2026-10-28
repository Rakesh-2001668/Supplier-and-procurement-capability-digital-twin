"""F4 Contract lifecycle: author → execute → consume → renew (M07)."""
import hashlib
import hmac
import json
import os
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, system_tx, tenant_tx
from app.pic.models import (
    AppUser, Clause, Contract, ContractLine, Material, Obligation, PoLine, PriceValidity, PurchaseOrder, QuotaArrangement, QuotaLine,
    Signature, SourcingEvent, Supplier, Task, Tenant,
)
from app.pic.platform import agents, audit, clock, outbox, rules, workflow
from app.pic.platform.auth import Principal, scopes_for
from app.pic.platform.core import StateMachine, link, next_number
from app.pic.platform.errors import Problem, illegal_transition, rule_violation
from app.pic.platform.money import D, fmt_inr, line_amount
from app.pic.services.common import principal, require_supplier_user

PROCESS = "pic.contract"
SM = StateMachine("CONTRACT", {
    ("DRAFT", "review"): "IN_NEGOTIATION",
    ("IN_NEGOTIATION", "submit"): "IN_APPROVAL",
    ("IN_APPROVAL", "approve"): "OUT_FOR_SIGNATURE",
    ("IN_APPROVAL", "reject"): "IN_NEGOTIATION",
    ("OUT_FOR_SIGNATURE", "activate"): "ACTIVE",
    ("ACTIVE", "expiring"): "EXPIRING",
    ("EXPIRING", "expire"): "EXPIRED",
    ("ACTIVE", "expire"): "EXPIRED",
    ("ACTIVE", "terminate"): "TERMINATED",
    ("EXPIRING", "terminate"): "TERMINATED",
    ("EXPIRING", "renew"): "RENEWED",
    # An approved EXTENSION amendment (renewal of the same contract) brings an expiring contract back to active.
    ("EXPIRING", "extend"): "ACTIVE",
})


def _instance(session: Session, contract: Contract):
    return workflow.find(session, "CONTRACT", contract.id, PROCESS)


def _lines(session: Session, contract: Contract) -> list[ContractLine]:
    return session.execute(select(ContractLine).where(ContractLine.contract_id == contract.id).order_by(ContractLine.line_no)).scalars().all()


def create_draft(session: Session, *, type: str, title: str, supplier_id: uuid.UUID, company_code: str, valid_from: date,
                 valid_to: date, payment_terms: str, incoterms: Optional[str], lines: list[dict], owner_id: uuid.UUID,
                 tolerances: dict, index_ref: Optional[dict] = None, source_event_id: Optional[uuid.UUID] = None,
                 trigger: str = "manual") -> Contract:
    p = principal(session)
    playbook = rules.resolve(session, "CLM-PLAYBOOK")
    contract = Contract(
        tenant_id=current_tenant(session), number=next_number(session, "CONTRACT"), type=type, title=title,
        supplier_id=supplier_id, company_code=company_code, status="DRAFT", valid_from=valid_from, valid_to=valid_to,
        payment_terms=payment_terms, incoterms=incoterms, over_tolerance_pct=D(tolerances.get("over_pct", 0)),
        under_tolerance_pct=D(tolerances.get("under_pct", 0)), price_tolerance_pct=D(tolerances.get("price_pct", 0)),
        index_ref=index_ref, source_event_id=source_event_id, owner_id=owner_id, rule_set_version=playbook.ref,
        created_by=p.user_id,
    )
    session.add(contract)
    session.flush()
    target_value = 0
    for index, data in enumerate(lines, start=1):
        line = ContractLine(tenant_id=contract.tenant_id, contract_id=contract.id, line_no=index * 10,
                            material_id=data.get("material_id"), description=data["description"], plant=data["plant"],
                            uom=data["uom"], target_qty=D(data["target_qty"]), created_by=p.user_id)
        session.add(line)
        session.flush()
        session.add(PriceValidity(tenant_id=contract.tenant_id, contract_line_id=line.id, valid_from=valid_from, valid_to=valid_to,
                                  unit_price_minor=int(data["unit_price_minor"]),
                                  index_value=D(index_ref["base"]) if index_ref else None, reason="AWARD" if source_event_id else "INITIAL",
                                  published=False, created_by=p.user_id))
        target_value += line_amount(line.target_qty, int(data["unit_price_minor"]))
    contract.target_value_minor = target_value
    supplier = session.get(Supplier, supplier_id)
    for template in playbook.body["templates"].get(type, []):
        text = template["text"].format(terms=payment_terms, incoterms=incoterms or "", supplier=supplier.legal_name,
                                       band=(index_ref or {}).get("band_pct", ""), over=tolerances.get("over_pct", 0),
                                       under=tolerances.get("under_pct", 0))
        session.add(Clause(tenant_id=contract.tenant_id, contract_id=contract.id, code=template["code"], title=template["title"],
                           text=text, position="STANDARD", risk_score=0, created_by=p.user_id))
    for ob in playbook.body["obligations"].get(type, []):
        session.add(Obligation(tenant_id=contract.tenant_id, contract_id=contract.id, party=ob["party"], description=ob["description"],
                               due_date=valid_from + timedelta(days=int(ob["dueAfterDays"])), status="OPEN", created_by=p.user_id))
    session.flush()
    instance = workflow.start(session, PROCESS, "CONTRACT", contract.id, contract.number, {"trigger": trigger})
    workflow.step(session, instance, "F4-02", outcome=f"drafted from {type.lower()} template with {len(playbook.body['templates'].get(type, []))} clauses")
    audit.record(session, "CONTRACT", contract.id, "DRAFTED", object_ref=contract.number,
                 after={"supplier": supplier.code, "targetValueMinor": target_value, "trigger": trigger}, rule_set_version=playbook.ref)
    return contract


@outbox.consumer("sourcing.event.awarded", "contract-from-award")
def _from_award(session: Session, event) -> None:
    data = event.payload
    sourcing_event = session.get(SourcingEvent, event.object_id)
    # a free-text requisition line has no material: the award becomes a value contract (no index, no material)
    material = session.get(Material, uuid.UUID(data["materialId"])) if data.get("materialId") else None
    description = material.description if material else (data.get("description") or sourcing_event.number)
    contract_rule = rules.resolve(session, "CLM-PLAYBOOK")
    defaults = contract_rule.body["awardDefaults"]
    start = clock.today().replace(day=1) + timedelta(days=32)
    valid_from = start.replace(day=1)
    valid_to = valid_from.replace(year=valid_from.year + 1) - timedelta(days=1)
    for allocation in data["allocations"]:
        supplier = session.get(Supplier, uuid.UUID(allocation["supplierId"]))
        contract = create_draft(
            session, type="SCHEDULING_AGREEMENT" if material else "VALUE_CONTRACT", title=f"{description} – {supplier.legal_name}",
            supplier_id=supplier.id, company_code="1000", valid_from=valid_from, valid_to=valid_to,
            payment_terms=supplier.payment_terms, incoterms=supplier.incoterms,
            lines=[{"material_id": material.id if material else None, "description": description, "plant": data["plant"], "uom": data["uom"],
                    "target_qty": allocation["annualQty"], "unit_price_minor": allocation["priceMinor"]}],
            owner_id=uuid.UUID(data["ownerId"]), tolerances=defaults["tolerances"], index_ref=defaults["index"] if material else None,
            source_event_id=sourcing_event.id, trigger=f"award {sourcing_event.number}",
        )
        link(session, "SOURCING_EVENT", sourcing_event.id, sourcing_event.number, "CONTRACT", contract.id, contract.number, "awarded_to")


# ---------------------------------------------------------------- F4-03 AI redline, F4-04 supplier review
def ai_review(session: Session, contract: Contract) -> dict:
    playbook = rules.resolve(session, "CLM-PLAYBOOK")
    positions = playbook.body["positionRisk"]
    clauses = session.execute(select(Clause).where(Clause.contract_id == contract.id)).scalars().all()
    findings = []
    for clause in clauses:
        clause.risk_score = int(positions[clause.position])
        if clause.position != "STANDARD":
            findings.append({"clause": clause.code, "position": clause.position, "risk": clause.risk_score,
                             "fallback": playbook.body["fallbacks"].get(clause.code)})
    risk = max([c.risk_score for c in clauses], default=0)
    ai_ref = agents.log_run(session, "CONTRACT_REVIEW", object_type="CONTRACT", object_id=contract.id, object_ref=contract.number,
                            inputs={"clauses": len(clauses)}, evidence=[c.code for c in clauses],
                            output={"risk": risk, "findings": findings}, confidence=0.82, action_taken="DRAFTED")
    if contract.status == "DRAFT":
        SM.apply(session, contract, "review", ai_ref=ai_ref, rule_set_version=playbook.ref)
    instance = _instance(session, contract)
    workflow.step(session, instance, "F4-03", outcome=f"contract risk {risk}; {len(findings)} deviation(s)")
    workflow.wait(session, instance, "F4-04", outcome="supplier review / redline")
    return {"risk": risk, "findings": findings, "aiRef": ai_ref}


def redline(session: Session, contract: Contract, clause_code: str, text: str, position: str) -> Clause:
    require_supplier_user(session, contract.supplier_id)
    if contract.status != "IN_NEGOTIATION":
        raise illegal_transition("Contract", contract.number, contract.status, "redline")
    clause = session.execute(select(Clause).where(Clause.contract_id == contract.id, Clause.code == clause_code)).scalar_one()
    before = {"text": clause.text, "position": clause.position}
    clause.text = text
    clause.position = position.upper()
    clause.risk_score = int(rules.resolve(session, "CLM-PLAYBOOK").body["positionRisk"][clause.position])
    audit.record(session, "CONTRACT", contract.id, "CLAUSE_REDLINED", object_ref=contract.number, before=before,
                 after={"clause": clause_code, "position": clause.position})
    return clause


def submit(session: Session, contract: Contract) -> dict:
    rule = rules.resolve(session, "CONTRACT-APPROVAL", company_code=contract.company_code)
    clauses = session.execute(select(Clause).where(Clause.contract_id == contract.id)).scalars().all()
    non_standard = any(c.position == "NON_STANDARD" for c in clauses)
    large = contract.target_value_minor >= rule.body["thresholdMinor"]
    chain = list(rule.body["above"]) if (large or non_standard) else list(rule.body["below"])
    SM.apply(session, contract, "submit", rule_set_version=rule.ref)
    instance = _instance(session, contract)
    workflow.step(session, instance, "F4-04", outcome="review complete")
    workflow.step(session, instance, "F4-05", outcome=("yes" if (large or non_standard) else "no") +
                  f": value {fmt_inr(contract.target_value_minor)}" + (", non-standard clause" if non_standard else ""))
    workflow.start_approval(session, instance, "CONTRACT_APPROVAL", object_type="CONTRACT", object_id=contract.id,
                            object_ref=contract.number, chain=chain, step_id="F4-06", initiator_id=contract.owner_id,
                            rule_set_version=rule.ref)
    return {"status": contract.status, "chain": chain}


@workflow.on_task("CONTRACT_APPROVAL")
def _approved(session: Session, task: Task, outcome: str) -> None:
    contract = session.get(Contract, task.object_id)
    instance = _instance(session, contract)
    if outcome == "APPROVED":
        SM.apply(session, contract, "approve", rule_set_version=task.rule_set_version)
        workflow.wait(session, instance, "F4-07", outcome="out for e-signature")
    else:
        SM.apply(session, contract, "reject", reason=task.comment)
        workflow.wait(session, instance, "F4-04", outcome=f"back to negotiation: {task.comment}")


# ---------------------------------------------------------------- F4-07 signature, F4-08 activation
def _document_hash(session: Session, contract: Contract) -> str:
    body = {
        "number": contract.number, "supplier": str(contract.supplier_id), "validity": [contract.valid_from.isoformat(), contract.valid_to.isoformat()],
        "terms": contract.payment_terms, "clauses": [(c.code, c.text) for c in session.execute(select(Clause).where(Clause.contract_id == contract.id).order_by(Clause.code)).scalars()],
        "lines": [(l.line_no, str(l.target_qty)) for l in _lines(session, contract)],
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def sign(session: Session, contract: Contract, party: str, signer_name: str, envelope_ref: Optional[str] = None) -> dict:
    p = principal(session)
    party = party.upper()
    if contract.status != "OUT_FOR_SIGNATURE":
        raise illegal_transition("Contract", contract.number, contract.status, "sign")
    if party == "SUPPLIER":
        require_supplier_user(session, contract.supplier_id)
        if "SUPPLIER_USER" not in p.roles:
            raise Problem(403, "FORBIDDEN", "The supplier signs from the supplier portal")
    elif "contract:sign" not in p.scopes:
        raise Problem(403, "FORBIDDEN", "Missing scope contract:sign")
    doc_hash = _document_hash(session, contract)
    session.add(Signature(tenant_id=contract.tenant_id, contract_id=contract.id, party=party, signer_name=signer_name,
                          signer_user_id=p.user_id, signed_at=clock.now(), envelope_ref=(envelope_ref or f"ESIGN-{contract.number}-{party[:1]}")[:60],
                          document_hash=doc_hash, created_by=p.user_id))
    session.flush()
    audit.record(session, "CONTRACT", contract.id, "SIGNED", object_ref=contract.number,
                 after={"party": party, "hash": doc_hash, "envelope": envelope_ref})
    parties = {s.party for s in session.execute(select(Signature).where(Signature.contract_id == contract.id)).scalars()}
    if parties >= {"BUYER", "SUPPLIER"}:
        workflow.step(session, _instance(session, contract), "F4-07", outcome="signed by buyer and supplier")
    return {"contract": contract.number, "signedBy": sorted(parties)}


def activate(session: Session, contract: Contract) -> Contract:
    signatures = session.execute(select(Signature).where(Signature.contract_id == contract.id)).scalars().all()
    if {s.party for s in signatures} < {"BUYER", "SUPPLIER"}:
        raise rule_violation("All signatures are required before activation", "CLM-ACTIVATE")
    if len({s.document_hash for s in signatures}) != 1 or signatures[0].document_hash != _document_hash(session, contract):
        raise rule_violation("The signed document differs from the current contract text", "CLM-ACTIVATE")
    SM.apply(session, contract, "activate")
    contract.activated_at = clock.now()
    published = 0
    for line in _lines(session, contract):
        for validity in session.execute(select(PriceValidity).where(PriceValidity.contract_line_id == line.id)).scalars():
            validity.published = True
            published += 1
        if contract.source_event_id and line.material_id:
            _add_quota(session, contract, line)
    outbox.emit(session, "contract.activated", "CONTRACT", contract.id, contract.number,
                {"supplierId": str(contract.supplier_id), "sourceEventId": str(contract.source_event_id) if contract.source_event_id else None,
                 "validFrom": contract.valid_from.isoformat(), "validTo": contract.valid_to.isoformat()})
    rule = rules.resolve(session, "CONTRACT-APPROVAL", company_code=contract.company_code)
    notice = int(rule.body["renewalNoticeDays"])
    workflow.create_timer(session, "CONTRACT_RENEWAL", "CONTRACT", contract.id, clock.at_ist(contract.valid_to - timedelta(days=notice), 9))
    workflow.create_timer(session, "CONTRACT_EXPIRY", "CONTRACT", contract.id, clock.at_ist(contract.valid_to + timedelta(days=1), 0, 5))
    instance = _instance(session, contract)
    workflow.step(session, instance, "F4-08", outcome=f"active; {published} price validity period(s) published to source determination")
    workflow.wait(session, instance, "F4-09", outcome="tracking consumption & obligations")
    return contract


def _add_quota(session: Session, contract: Contract, line: ContractLine) -> None:
    quota = session.execute(select(QuotaArrangement).where(QuotaArrangement.material_id == line.material_id,
                                                           QuotaArrangement.plant == line.plant,
                                                           QuotaArrangement.source_event_id == contract.source_event_id)).scalar_one_or_none()
    if quota is None:
        quota = QuotaArrangement(tenant_id=contract.tenant_id, material_id=line.material_id, plant=line.plant,
                                 valid_from=contract.valid_from, valid_to=contract.valid_to, source_event_id=contract.source_event_id,
                                 created_by=principal(session).user_id)
        session.add(quota)
        session.flush()
    siblings = session.execute(select(ContractLine).join(Contract, Contract.id == ContractLine.contract_id).where(
        Contract.source_event_id == contract.source_event_id, ContractLine.material_id == line.material_id)).scalars().all()
    total = sum(l.target_qty for l in siblings)
    session.add(QuotaLine(tenant_id=contract.tenant_id, quota_id=quota.id, supplier_id=contract.supplier_id, contract_id=contract.id,
                          share=(line.target_qty / total).quantize(Decimal("0.0001")), allocated_qty=0,
                          created_by=principal(session).user_id))
    session.flush()


# ---------------------------------------------------------------- consumption, indexation, renewal
@outbox.consumer("purchase_order.released", "contract-consumption")
def _consume(session: Session, event) -> None:
    po = session.get(PurchaseOrder, event.object_id)
    if po.status == "CANCELLED":
        return  # cancelled before the release event was relayed: nothing was consumed (order.cancel)
    rule = None
    for line in session.execute(select(PoLine).where(PoLine.po_id == po.id, PoLine.contract_line_id.is_not(None))).scalars():
        contract_line = session.get(ContractLine, line.contract_line_id)
        contract_line.released_qty += line.qty
        contract_line.released_value_minor += line.net_minor
        contract = session.get(Contract, contract_line.contract_id)
        rule = rule or rules.resolve(session, "CONTRACT-APPROVAL", company_code=contract.company_code)
        pct = (contract_line.released_qty / contract_line.target_qty * 100) if contract_line.target_qty else Decimal(0)
        for threshold in rule.body["consumptionThresholds"]:
            if pct >= threshold and threshold not in (contract.thresholds_hit or []):
                contract.thresholds_hit = (contract.thresholds_hit or []) + [threshold]
                outbox.emit(session, "contract.consumption.threshold", "CONTRACT", contract.id, contract.number,
                            {"threshold": threshold, "consumedPct": str(pct.quantize(Decimal("0.01")))})


def consumption(session: Session, contract: Contract) -> dict:
    lines = []
    for line in _lines(session, contract):
        validity = session.execute(select(PriceValidity).where(PriceValidity.contract_line_id == line.id, PriceValidity.published.is_(True))
                                   .order_by(PriceValidity.valid_from.desc())).scalars().first()
        leakage = []
        if line.material_id:
            for po_line, po in session.execute(select(PoLine, PurchaseOrder).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
                    PoLine.material_id == line.material_id, PoLine.plant == line.plant, PoLine.contract_line_id.is_(None),
                    PurchaseOrder.status.not_in(("DRAFT", "CANCELLED")), PurchaseOrder.created_at >= clock.at_ist(contract.valid_from, 0))).all():
                leakage.append({"po": po.number, "line": po_line.line_no, "qty": str(po_line.qty), "unitPriceMinor": po_line.unit_price_minor,
                                "leakageMinor": max(0, line_amount(po_line.qty, po_line.unit_price_minor - (validity.unit_price_minor if validity else 0)))})
        lines.append({"line": line.line_no, "description": line.description, "targetQty": str(line.target_qty),
                      "releasedQty": str(line.released_qty), "releasedValueMinor": line.released_value_minor,
                      "consumedPct": str((line.released_qty / line.target_qty * 100).quantize(Decimal("0.01"))) if line.target_qty else "0",
                      "currentPriceMinor": validity.unit_price_minor if validity else None, "offContract": leakage})
    obligations = session.execute(select(Obligation).where(Obligation.contract_id == contract.id).order_by(Obligation.due_date)).scalars().all()
    return {"contract": contract.number, "status": contract.status, "thresholdsHit": contract.thresholds_hit, "lines": lines,
            "obligations": [{"id": str(o.id), "party": o.party, "description": o.description, "dueDate": o.due_date.isoformat(),
                             "status": o.status} for o in obligations]}


def index_reset(session: Session, contract: Contract, index_value: Decimal, effective_from: date) -> dict:
    """Quarterly index reset: always a new validity period. Inside the band the price is unchanged (absorbed)."""
    from app.pic.services import savings

    if contract.status not in ("ACTIVE", "EXPIRING") or not contract.index_ref:
        raise rule_violation("Only active indexed contracts can be reset", "CLM-INDEX")
    base = D(contract.index_ref["base"])
    band = D(contract.index_ref["band_pct"])
    change_pct = ((D(index_value) / base) - 1) * 100
    adjust_pct = Decimal(0) if abs(change_pct) <= band else (change_pct - band if change_pct > 0 else change_pct + band)
    results = []
    for line in _lines(session, contract):
        # indexing applies to the latest negotiated price (initial, award or amendment), never compounds earlier resets
        original = session.execute(select(PriceValidity).where(
            PriceValidity.contract_line_id == line.id, PriceValidity.valid_from <= effective_from,
            PriceValidity.reason.not_like("INDEX_RESET%")).order_by(PriceValidity.valid_from.desc(), PriceValidity.created_at.desc())).scalars().first()
        if original is None:
            original = session.execute(select(PriceValidity).where(PriceValidity.contract_line_id == line.id)
                                       .order_by(PriceValidity.valid_from)).scalars().first()
        new_price = int((Decimal(original.unit_price_minor) * (1 + adjust_pct / 100)).quantize(Decimal("1"), ROUND_HALF_UP))
        session.add(PriceValidity(tenant_id=contract.tenant_id, contract_line_id=line.id, valid_from=effective_from,
                                  valid_to=contract.valid_to, unit_price_minor=new_price, index_value=D(index_value),
                                  reason="INDEX_RESET_ABSORBED" if adjust_pct == 0 else "INDEX_RESET_ADJUSTED", published=True,
                                  created_by=principal(session).user_id))
        remaining = line.target_qty - line.released_qty
        if change_pct > 0 and contract.source_event_id:
            market_price = (Decimal(original.unit_price_minor) * (1 + change_pct / 100)).quantize(Decimal("1"), ROUND_HALF_UP)
            savings.record_avoidance(session, source_event_id=contract.source_event_id, requested_price_minor=int(market_price),
                                     agreed_price_minor=new_price, volume=remaining, reason=f"{contract.index_ref['index']} +{change_pct:.2f}% (band ±{band}%)",
                                     source_ref=f"{contract.number}@{effective_from.isoformat()}")
        results.append({"line": line.line_no, "oldPriceMinor": original.unit_price_minor, "newPriceMinor": new_price})
    audit.record(session, "CONTRACT", contract.id, "INDEX_RESET", object_ref=contract.number,
                 after={"index": str(index_value), "changePct": str(change_pct.quantize(Decimal("0.01"))),
                        "adjustPct": str(adjust_pct.quantize(Decimal("0.01"))), "effectiveFrom": effective_from.isoformat(), "lines": results})
    return {"contract": contract.number, "changePct": str(change_pct.quantize(Decimal("0.01"))), "adjustPct": str(adjust_pct.quantize(Decimal("0.01"))),
            "lines": results}


def complete_obligation(session: Session, obligation: Obligation, note: str) -> Obligation:
    obligation.status = "DONE"
    audit.record(session, "CONTRACT", obligation.contract_id, "OBLIGATION_DONE", after={"obligation": obligation.description}, reason=note)
    return obligation


@workflow.on_timer("CONTRACT_RENEWAL")
def _renewal_due(session: Session, timer) -> None:
    contract = session.get(Contract, timer.object_id)
    if contract and contract.status == "ACTIVE":
        SM.apply(session, contract, "expiring", reason="renewal notice period reached")
        workflow.start_approval(session, _instance(session, contract), "CONTRACT_RENEWAL", object_type="CONTRACT",
                                object_id=contract.id, object_ref=contract.number, chain=["CONTRACT_MANAGER"], step_id=None,
                                initiator_id=None, evidence={"validTo": contract.valid_to.isoformat()})


@workflow.on_task("CONTRACT_RENEWAL")
def _renewal_decided(session: Session, task: Task, outcome: str) -> None:
    from app.pic.services import amendments

    contract = session.get(Contract, task.object_id)
    draft = amendments.renewal_draft(session, contract, task) if outcome == "APPROVED" and contract is not None else None
    audit.record(session, "CONTRACT", task.object_id, "RENEWAL_DECISION", object_ref=task.object_ref, reason=task.comment,
                 after={"outcome": outcome, "extensionDraft": draft.number if draft else None,
                        "next": "extension amendment ready for approval" if draft else "contract proceeds to expiry"})
    instance = _instance(session, contract) if contract is not None else None
    if instance is not None and instance.status == "RUNNING":
        workflow.step(session, instance, "F4-09", outcome=(f"renewal approved: extension {draft.number} drafted to "
                                                          f"{draft.changes['validTo']}") if draft else
                      f"renewal {outcome.lower()}: expires on {contract.valid_to.isoformat()}")
        workflow.wait(session, instance, "F4-09", outcome="tracking consumption & obligations")


@workflow.on_timer("CONTRACT_EXPIRY")
def _expired(session: Session, timer) -> None:
    from app.pic.services import amendments

    contract = session.get(Contract, timer.object_id)
    if contract and contract.status in ("ACTIVE", "EXPIRING"):
        SM.apply(session, contract, "expire")
        amendments.close_pending(session, contract, f"contract expired on {contract.valid_to.isoformat()}")
        instance = _instance(session, contract)
        if instance is not None and instance.status == "RUNNING":
            workflow.step(session, instance, "F4-09", outcome="consumption tracking ended at expiry")
            workflow.end(session, instance, "F4-10", outcome=f"expired on {contract.valid_to.isoformat()}")


# ---------------------------------------------------------------- CLM-04 obligation tracker and CLM-03 renewals calendar
def obligations_tracker(session: Session, party: Optional[str] = None) -> dict:
    today = clock.today()
    contracts = {c.id: c for c in session.execute(select(Contract)).scalars()}
    suppliers = {s.id: s.code for s in session.execute(select(Supplier)).scalars()}
    query = select(Obligation).order_by(Obligation.due_date)
    if party:
        query = query.where(Obligation.party == party)
    items = []
    for o in session.execute(query).scalars():
        c = contracts[o.contract_id]
        if o.status in ("DONE", "COMPLETED"):
            state = "COMPLETED"
        elif o.status != "OPEN":
            state = o.status
        else:
            state = "OVERDUE" if o.due_date < today else "DUE_SOON" if (o.due_date - today).days <= 30 else "OPEN"
        items.append({"id": str(o.id), "contract": c.number, "contractStatus": c.status, "supplier": suppliers.get(c.supplier_id), "party": o.party,
                      "description": o.description, "dueDate": o.due_date.isoformat(), "status": state, "daysToDue": (o.due_date - today).days})
    done = [i for i in items if i["status"] == "COMPLETED"]
    return {"items": items, "overdue": sum(1 for i in items if i["status"] == "OVERDUE"),
            "dueSoon": sum(1 for i in items if i["status"] == "DUE_SOON"), "completed": len(done)}


def renewals(session: Session) -> list[dict]:
    notice = int(rules.resolve(session, "CONTRACT-APPROVAL").body["renewalNoticeDays"])
    today = clock.today()
    suppliers = {s.id: s.code for s in session.execute(select(Supplier)).scalars()}
    out = []
    for c in session.execute(select(Contract).where(Contract.status.in_(("ACTIVE", "EXPIRING", "OUT_FOR_SIGNATURE", "IN_APPROVAL")))
                             .order_by(Contract.valid_to)).scalars():
        notice_on = c.valid_to - timedelta(days=notice)
        out.append({"contract": c.number, "title": c.title, "supplier": suppliers.get(c.supplier_id), "status": c.status,
                    "validTo": c.valid_to.isoformat(), "noticeOn": notice_on.isoformat(), "daysToExpiry": (c.valid_to - today).days,
                    "expiringIn90": 0 <= (c.valid_to - today).days <= 90, "targetValueMinor": c.target_value_minor})
    return out


def templates(session: Session) -> dict:
    playbook = rules.resolve(session, "CLM-PLAYBOOK")
    return {"ruleSet": playbook.ref, "types": sorted(playbook.body["templates"]),
            "templates": playbook.body["templates"], "obligations": playbook.body["obligations"], "fallbacks": playbook.body["fallbacks"]}


# ---------------------------------------------------------------- F4-07 e-signature provider adapter
ESIGN_PROVIDERS = ("DOCUSIGN", "ADOBE_SIGN", "LEEGALITY", "EMUDHRA")
ESIGN_SIGNATURE_HEADER = "X-Esign-Signature"
ESIGN_ENV = ("PIC_ESIGN_PROVIDER", "PIC_ESIGN_URL", "PIC_ESIGN_API_KEY", "PIC_ESIGN_WEBHOOK_SECRET")


@dataclass
class EsignConfig:
    provider: str
    url: str
    api_key: str
    webhook_secret: str


def esign_config() -> Optional[EsignConfig]:
    """Read from the process environment at call time. Without a complete configuration the internal signature path (sign()) is
    the only one."""
    values = {k: os.environ.get(k, "").strip() for k in ESIGN_ENV}
    provider = values["PIC_ESIGN_PROVIDER"].upper()
    if not all(values.values()) or provider not in ESIGN_PROVIDERS:
        return None
    return EsignConfig(provider, values["PIC_ESIGN_URL"].rstrip("/"), values["PIC_ESIGN_API_KEY"], values["PIC_ESIGN_WEBHOOK_SECRET"])


def require_esign() -> EsignConfig:
    config = esign_config()
    if config is None:
        provider = os.environ.get("PIC_ESIGN_PROVIDER", "").strip().upper()
        if provider and provider not in ESIGN_PROVIDERS:
            detail = f"PIC_ESIGN_PROVIDER {provider} is not supported ({', '.join(ESIGN_PROVIDERS)})"
        else:
            missing = [k for k in ESIGN_ENV if not os.environ.get(k, "").strip()]
            detail = f"No e-signature provider is configured (missing {', '.join(missing)}); sign in the platform instead"
        raise Problem(404, "ESIGN_NOT_CONFIGURED", detail)
    return config


class EsignProvider:
    """HTTP adapter to the provider's envelope API. The envelope carries the SHA-256 of the contract document (the same hash every
    internal signature is bound to), the signers in routing order and our reference, which the provider echoes in its webhooks."""

    def __init__(self, config: EsignConfig):
        self.config = config

    def create_envelope(self, *, reference: str, document_name: str, document_hash: str, signers: list[dict]) -> dict:
        body = {"provider": self.config.provider, "reference": reference, "documentName": document_name,
                "documentHash": {"algorithm": "SHA-256", "value": document_hash},
                "signers": [{"party": s["party"], "name": s["name"], "email": s["email"], "routingOrder": i}
                            for i, s in enumerate(signers, start=1)],
                "webhook": {"events": ["SIGNER_COMPLETED", "ENVELOPE_COMPLETED", "ENVELOPE_DECLINED", "ENVELOPE_VOIDED"],
                            "signatureHeader": ESIGN_SIGNATURE_HEADER, "algorithm": "HMAC-SHA256"}}
        try:
            response = httpx.post(f"{self.config.url}/envelopes", json=body, timeout=15.0,
                                  headers={"Authorization": f"Bearer {self.config.api_key}", "Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise Problem(502, "ESIGN_PROVIDER_UNAVAILABLE", f"{self.config.provider} could not be reached: {exc.__class__.__name__}")
        if response.status_code >= 300:
            raise Problem(502, "ESIGN_PROVIDER_ERROR", f"{self.config.provider} rejected the envelope (HTTP {response.status_code})",
                          providerStatus=response.status_code)
        try:
            data = response.json()
        except ValueError:
            data = {}
        envelope_id = next((str(data[k]) for k in ("envelopeId", "envelope_id", "id", "documentId") if data.get(k)), None)
        if not envelope_id:
            raise Problem(502, "ESIGN_PROVIDER_ERROR", f"{self.config.provider} returned no envelope id")
        return {"envelopeId": envelope_id[:60], "status": str(data.get("status") or "SENT").upper(), "signingUrls": data.get("signingUrls") or {}}


def _envelope_reference(tenant_code: str, contract: Contract) -> str:
    return f"PIC:{tenant_code}:{contract.number}"


def _signer_user(session: Session, party: str, contract: Contract, email: Optional[str]) -> AppUser:
    if party == "BUYER":
        user = session.execute(select(AppUser).where(AppUser.email == email)).scalar_one_or_none() if email else None
        if user is None or not user.active or "contract:sign" not in scopes_for(list(user.roles)):
            raise rule_violation("The buyer signer must be an active user allowed to sign contracts (contract:sign)", "CLM-ESIGN")
        return user
    query = select(AppUser).where(AppUser.supplier_id == contract.supplier_id, AppUser.active.is_(True))
    if email:
        query = query.where(AppUser.email == email)
    user = session.execute(query.order_by(AppUser.email)).scalars().first()
    if user is None or "SUPPLIER_USER" not in user.roles:
        raise rule_violation("No active portal user of the contract's supplier" + (f" with e-mail {email}" if email else ""), "CLM-ESIGN")
    return user


def create_envelope(session: Session, contract: Contract, buyer_email: Optional[str] = None, supplier_email: Optional[str] = None) -> dict:
    config = require_esign()
    p = principal(session)
    if contract.status != "OUT_FOR_SIGNATURE":
        raise illegal_transition("Contract", contract.number, contract.status, "send for e-signature")
    instance = _instance(session, contract)
    current = (instance.variables or {}).get("esign") if instance else None
    if current and current.get("status") == "SENT":
        raise Problem(409, "ENVELOPE_PENDING", f"Envelope {current['envelopeId']} is still out for signature", envelope=current["envelopeId"])
    signed = {s.party for s in session.execute(select(Signature).where(Signature.contract_id == contract.id)).scalars()}
    signers = []
    for party, email in (("BUYER", buyer_email or p.email), ("SUPPLIER", supplier_email)):
        if party in signed:
            continue
        user = _signer_user(session, party, contract, email)
        signers.append({"party": party, "userId": str(user.id), "name": user.full_name, "email": user.email, "status": "SENT"})
    if not signers:
        raise Problem(409, "ALREADY_SIGNED", f"{contract.number} is signed by both parties")
    document_hash = _document_hash(session, contract)
    reference = _envelope_reference(p.tenant_code, contract)
    result = EsignProvider(config).create_envelope(reference=reference, document_name=f"{contract.number} {contract.title}",
                                                   document_hash=document_hash, signers=signers)
    envelope = {"provider": config.provider, "envelopeId": result["envelopeId"], "reference": reference, "status": "SENT",
                "documentHash": document_hash, "signers": signers, "sentAt": clock.now().isoformat(), "sentBy": p.email}
    if instance is not None:
        instance.variables = {**(instance.variables or {}), "esign": envelope}
    audit.record(session, "CONTRACT", contract.id, "ESIGN_ENVELOPE_SENT", object_ref=contract.number,
                 after={"provider": config.provider, "envelope": result["envelopeId"], "hash": document_hash,
                        "signers": [{"party": s["party"], "email": s["email"]} for s in signers]})
    return {**envelope, "signingUrls": result["signingUrls"]}


def verify_webhook(config: EsignConfig, body: bytes, signature: Optional[str]) -> None:
    expected = hmac.new(config.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    given = (signature or "").strip()
    if given.lower().startswith("sha256="):
        given = given.split("=", 1)[1]
    if not given or not hmac.compare_digest(expected, given.lower()):
        raise Problem(401, "ESIGN_SIGNATURE_INVALID", "Webhook signature does not match", rule_ref="CLM-ESIGN")


def handle_webhook(body: bytes, signature: Optional[str]) -> dict:
    """Provider callback, verified by HMAC-SHA256 over the raw body; the tenant comes from our envelope reference.
    A completed signer is recorded through sign(), acting as that signer, so activation works unchanged."""
    config = require_esign()
    verify_webhook(config, body, signature)
    try:
        event = json.loads(body)
    except ValueError:
        raise Problem(422, "INVALID_PAYLOAD", "Webhook body is not JSON")
    parts = str(event.get("reference") or "").split(":")
    if len(parts) != 3 or parts[0] != "PIC":
        raise Problem(422, "INVALID_REFERENCE", "Unknown envelope reference")
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == parts[1])).scalar_one_or_none()
    if tenant_id is None:
        raise Problem(404, "ENVELOPE_UNKNOWN", "No such envelope for this reference")
    kind = str(event.get("event") or "").upper().replace(".", "_")
    gateway = Principal(user_id=uuid.UUID(int=0), tenant_id=tenant_id, tenant_code=parts[1], email=f"{config.provider.lower()}@esign.pic",
                        name=f"{config.provider} e-signature", roles=[], scopes=set(), agent_code="ESIGN_GATEWAY")
    with tenant_tx(tenant_id, gateway.user_id, gateway) as session:
        contract = session.execute(select(Contract).where(Contract.number == parts[2]).with_for_update()).scalar_one_or_none()
        instance = _instance(session, contract) if contract else None
        envelope = json.loads(json.dumps((instance.variables or {}).get("esign") or {})) if instance else {}
        if contract is None or not envelope or envelope.get("envelopeId") != str(event.get("envelopeId")):
            raise Problem(404, "ENVELOPE_UNKNOWN", "No such envelope for this reference")
        result = {"contract": contract.number, "envelope": envelope["envelopeId"], "event": kind}
        if kind in ("SIGNER_COMPLETED", "RECIPIENT_COMPLETED"):
            party = str(event.get("party") or "").upper()
            signer = next((x for x in envelope["signers"] if x["party"] == party), None)
            if signer is None:
                raise Problem(422, "INVALID_PAYLOAD", f"{party or 'party'} is not a signer of this envelope")
            if event.get("documentHash") and event["documentHash"] != envelope["documentHash"]:
                raise Problem(409, "DOCUMENT_CHANGED", "The provider signed a different document than the one sent", rule_ref="CLM-ESIGN")
            if session.execute(select(Signature).where(Signature.contract_id == contract.id, Signature.party == party)).first():
                return {**result, "duplicate": True}
            user = session.get(AppUser, uuid.UUID(signer["userId"]))
            actor = Principal(user_id=user.id, tenant_id=tenant_id, tenant_code=parts[1], email=user.email, name=user.full_name,
                              roles=list(user.roles), scopes=scopes_for(list(user.roles)), attributes=user.attributes or {},
                              supplier_id=user.supplier_id)
            session.info["principal"], session.info["user_id"] = actor, user.id
            signed = sign(session, contract, party, str(event.get("signerName") or signer["name"])[:200], envelope_ref=envelope["envelopeId"])
            signer["status"] = "SIGNED"
            signer["signedAt"] = str(event.get("signedAt") or clock.now().isoformat())
            if all(x["status"] == "SIGNED" for x in envelope["signers"]):
                envelope["status"] = "COMPLETED"
            result["signedBy"] = signed["signedBy"]
        elif kind in ("ENVELOPE_DECLINED", "ENVELOPE_VOIDED"):
            envelope["status"] = kind.split("_", 1)[1]
            audit.record(session, "CONTRACT", contract.id, f"ESIGN_{envelope['status']}", object_ref=contract.number,
                         reason=str(event.get("reason") or "")[:500] or None, after={"envelope": envelope["envelopeId"]})
        elif kind == "ENVELOPE_COMPLETED":
            if all(x["status"] == "SIGNED" for x in envelope["signers"]):
                envelope["status"] = "COMPLETED"
        else:
            return {**result, "ignored": True}
        instance.variables = {**(instance.variables or {}), "esign": envelope}
        return {**result, "status": envelope["status"]}
