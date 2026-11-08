"""F4 Contract lifecycle: author → execute → consume → renew (M07).

Renewal (TD §6 Active → Expiring → Expired | Terminated | Renewed; flow fixes B5). At the renewal notice date (rule
CONTRACT-APPROVAL.renewalNoticeDays before the end) the contract becomes EXPIRING, the owner and the contract managers get a
CONTRACT_EXPIRING notification and a CONTRACT_RENEWAL decision task is opened. There are two ways to renew:
- EXTENSION of the same contract: the renewal task approved drafts an EXTENSION amendment; once effective the contract is ACTIVE again
  with a later end date (same number, version + 1);
- SUCCESSOR contract (``renew_as_successor``, POST /v1/contracts/{ref}/renewals): a new draft with the current lines and prices and its
  own number, which goes through negotiation, approval and signature like any contract. When the successor is activated and its validity
  has started, the predecessor becomes RENEWED (terminal: no more prices to source determination, open renewal tasks closed, the
  workflow instance ended); a successor that starts later turns the predecessor RENEWED on its start date (timer CONTRACT_SUCCESSION).

ERP: an activated or amended call-off contract (scheduling agreement, quantity / value contract, rate card, SOW) is posted to the ERP as an
OUTLINE_AGREEMENT message (exactly once per contract version, key ``<company>|OA|<number>|v<version>``); a master agreement or NDA carries
no lines and is not an ERP outline agreement. A target connector that does not map OUTLINE_AGREEMENT leaves the contract active in PIC
and records ERP_NOT_MAPPED in the audit trail.
"""
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
from app.pic.platform import abac
from app.pic.platform import agents, audit, clock, outbox, rules, workflow
from app.pic.platform.auth import Principal, scopes_for
from app.pic.platform.core import StateMachine, link, next_number
from app.pic.platform.errors import Problem, illegal_transition, rule_violation
from app.pic.platform.money import D, fmt_inr, line_amount
from app.pic.seed import clause_library
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
    ("ACTIVE", "renew"): "RENEWED",  # a successor contract took over before the renewal notice date
    # An approved EXTENSION amendment (renewal of the same contract) brings an expiring contract back to active.
    ("EXPIRING", "extend"): "ACTIVE",
})


FRAMEWORK_TYPES = ("MASTER_AGREEMENT", "NDA")  # no value and no consumption (pending workflow 24)
CALL_OFF_TYPES = ("SCHEDULING_AGREEMENT", "QUANTITY_CONTRACT", "VALUE_CONTRACT", "RATE_CARD", "SOW")
FRAMEWORK_LIVE = ("ACTIVE", "EXPIRING")
# Built-in clause library for the framework types; the CLM-PLAYBOOK rule set wins when it carries the type (tenant-specific wording).
FRAMEWORK_TEMPLATES = {
    "MASTER_AGREEMENT": [
        {"code": "SCOPE", "title": "Scope", "text": "This master agreement sets the commercial terms for call-off contracts and purchase orders placed with "
                                                    "{supplier}; each call-off refers to it and states its own items, quantities and prices."},
        {"code": "PAYMENT", "title": "Payment terms", "text": "Payment {terms} from receipt of a correct invoice, unless a call-off states otherwise."},
        {"code": "PRICE", "title": "Pricing", "text": "Prices are agreed per call-off; this agreement fixes no volume or value commitment."},
        {"code": "QUALITY", "title": "Quality", "text": "Goods and services conform to the specification of the call-off; the supplier's quality certificates "
                                                         "stay valid throughout."},
        {"code": "CONFIDENTIALITY", "title": "Confidentiality", "text": "Each party keeps the other's information confidential for five years after "
                                                                          "this agreement ends."},
        {"code": "LIABILITY", "title": "Liability", "text": "Liability under each call-off is capped at 100% of that call-off's annual value."},
        {"code": "TERMINATION", "title": "Termination", "text": "Either party may terminate with 90 days' written notice; running call-offs continue "
                                                                 "to their end."}],
    "NDA": [
        {"code": "DEFINITION", "title": "Confidential information", "text": "Confidential information is all non-public information disclosed by "
                                                                            "either party to the other, in any form, including information about {supplier}."},
        {"code": "USE", "title": "Use and disclosure", "text": "The recipient uses confidential information only for the stated purpose and discloses it "
                                                                "only to staff and advisers bound by equal duties."},
        {"code": "TERM", "title": "Term of the duty", "text": "The duty of confidentiality lasts for five years from the date of disclosure; trade secrets "
                                                              "stay protected as long as they are secret."},
        {"code": "RETURN", "title": "Return and destruction", "text": "On request or at the end of the purpose the recipient returns or destroys "
                                                                      "the information and confirms in writing."},
        {"code": "REMEDIES", "title": "Remedies", "text": "A breach may cause harm that damages cannot repair; the discloser may seek injunctive relief "
                                                           "in addition to other remedies."}],
}
FRAMEWORK_OBLIGATIONS = {
    "MASTER_AGREEMENT": [{"party": "BUYER", "description": "Annual review of the master agreement terms", "dueAfterDays": 330}],
    "NDA": [{"party": "SUPPLIER", "description": "Confirm return or destruction of confidential information when the purpose ends", "dueAfterDays": 360}],
}
# Built-in wording for the remaining blueprint 13.1 types; CLM-PLAYBOOK.templates / .obligations win when they carry the type.
BUILTIN_TEMPLATES = {
    **FRAMEWORK_TEMPLATES,
    "RATE_CARD": [
        {"code": "SCOPE", "title": "Scope", "text": "{supplier} provides the services priced in the rate card below on request, at the rates stated for each role or "
                                                    "service."},
        {"code": "RATES", "title": "Rates", "text": "Rates are per unit as listed on the contract lines, fixed for the contract term unless revised by an approved "
                                                     "amendment; no rate applies that is not on the rate card."},
        {"code": "PAYMENT", "title": "Payment terms", "text": "Payment {terms} from receipt of a correct invoice and approved service entry."},
        {"code": "SLA", "title": "Service levels", "text": "Response and resolution times as per Schedule A; service credits apply below target."},
        {"code": "CONFIDENTIALITY", "title": "Confidentiality", "text": "Each party keeps the other's information confidential for five years."},
        {"code": "LIABILITY", "title": "Liability", "text": "Liability is capped at 100% of the annual contract value."},
        {"code": "TERMINATION", "title": "Termination", "text": "Either party may terminate with 60 days' written notice."}],
    "SOW": [
        {"code": "SCOPE", "title": "Scope of work", "text": "{supplier} performs the work and delivers the deliverables described in this statement of work."},
        {"code": "DELIVERABLES", "title": "Deliverables and milestones", "text": "Deliverables are accepted milestone by milestone; a milestone is "
                                                                                 "complete only when the buyer has accepted it in writing."},
        {"code": "ACCEPTANCE", "title": "Acceptance", "text": "The buyer accepts or rejects a deliverable within 10 working days of delivery; silence is not acceptance."},
        {"code": "PAYMENT", "title": "Payment terms", "text": "Payment {terms} from receipt of a correct invoice, released against accepted milestones."},
        {"code": "IP", "title": "Intellectual property", "text": "Deliverables paid for belong to the buyer; the supplier keeps its pre-existing "
                                                                  "materials and grants the buyer a licence to use them with the deliverables."},
        {"code": "CONFIDENTIALITY", "title": "Confidentiality", "text": "Each party keeps the other's information confidential for five years."},
        {"code": "LIABILITY", "title": "Liability", "text": "Liability is capped at 100% of the statement-of-work value."},
        {"code": "TERMINATION", "title": "Termination", "text": "Either party may terminate with 30 days' written notice; work accepted to date is paid."}],
}
BUILTIN_OBLIGATIONS = {
    **FRAMEWORK_OBLIGATIONS,
    "RATE_CARD": [{"party": "BUYER", "description": "Annual review of the rate card against market rates", "dueAfterDays": 330}],
    "SOW": [{"party": "SUPPLIER", "description": "Deliver milestone 1 for acceptance", "dueAfterDays": 30, "kind": "MILESTONE"},
            {"party": "BUYER", "description": "Accept or reject milestone 1 in writing", "dueAfterDays": 40, "kind": "MILESTONE"},
            {"party": "SUPPLIER", "description": "Deliver the final milestone for acceptance", "dueAfterDays": 90, "kind": "MILESTONE"}],
}
OBLIGATION_KINDS = ("OBLIGATION", "MILESTONE")
_IN_DATA = "the Digital Personal Data Protection Act, 2023"
# Governing-law variants of the clause library (pending workflow 25). The wording is a starting point that Legal reviews; a tenant overrides
# it through CLM-PLAYBOOK.jurisdictions. For India the code is IN-<state> and the seat of arbitration and the courts follow the state.
JURISDICTIONS = {
    "IN": {"name": "India", "law": "the laws of India", "seat": "New Delhi", "forum": "the courts at New Delhi",
           "stamp": "the Indian Stamp Act, 1899 and the stamp law applicable at the place of execution", "data": _IN_DATA},
    "IN-MH": {"name": "Maharashtra", "law": "the laws of India", "seat": "Mumbai", "forum": "the courts at Mumbai",
              "stamp": "the Maharashtra Stamp Act, 1958", "data": _IN_DATA},
    "IN-DL": {"name": "Delhi", "law": "the laws of India", "seat": "New Delhi", "forum": "the courts at New Delhi",
              "stamp": "the Indian Stamp Act, 1899 as applicable in Delhi", "data": _IN_DATA},
    "IN-KA": {"name": "Karnataka", "law": "the laws of India", "seat": "Bengaluru", "forum": "the courts at Bengaluru",
              "stamp": "the Karnataka Stamp Act, 1957", "data": _IN_DATA},
    "IN-TN": {"name": "Tamil Nadu", "law": "the laws of India", "seat": "Chennai", "forum": "the courts at Chennai",
              "stamp": "the Indian Stamp Act, 1899 as amended for Tamil Nadu", "data": _IN_DATA},
    "IN-GJ": {"name": "Gujarat", "law": "the laws of India", "seat": "Ahmedabad", "forum": "the courts at Ahmedabad",
              "stamp": "the Gujarat Stamp Act, 1958", "data": _IN_DATA},
    "IN-WB": {"name": "West Bengal", "law": "the laws of India", "seat": "Kolkata", "forum": "the courts at Kolkata",
              "stamp": "the Indian Stamp Act, 1899 as amended for West Bengal", "data": _IN_DATA},
    "IN-TG": {"name": "Telangana", "law": "the laws of India", "seat": "Hyderabad", "forum": "the courts at Hyderabad",
              "stamp": "the Indian Stamp Act, 1899 as applicable in Telangana", "data": _IN_DATA},
    "IN-HR": {"name": "Haryana", "law": "the laws of India", "seat": "Gurugram", "forum": "the courts at Gurugram",
              "stamp": "the Indian Stamp Act, 1899 as applicable in Haryana", "data": _IN_DATA},
    "SG": {"name": "Singapore", "law": "the laws of Singapore", "seat": "Singapore", "forum": "the courts of Singapore",
           "stamp": "the Stamp Duties Act 1929 of Singapore", "data": "the Personal Data Protection Act 2012"},
    "GB": {"name": "England and Wales", "law": "the laws of England and Wales", "seat": "London", "forum": "the courts of England and Wales",
           "stamp": "the stamp taxes applicable in England and Wales", "data": "the UK GDPR and the Data Protection Act 2018"},
}
JURISDICTION_CLAUSES = [
    {"code": "GOVERNING_LAW", "title": "Governing law and forum",
     "text": "This contract is governed by {law}. Subject to the arbitration clause, {forum} have exclusive jurisdiction."},
    {"code": "DISPUTES", "title": "Dispute resolution",
     "text": "Disputes are referred to arbitration by a sole arbitrator appointed by agreement; the seat and venue are {seat} and the language is "
             "English. For contracts governed by Indian law the Arbitration and Conciliation Act, 1996 applies."},
    {"code": "STAMP_DUTY", "title": "Stamp duty",
     "text": "Stamp duty under {stamp} is paid before the contract is relied on; the contract is executed on stamp paper or e-stamped as the law requires."},
    {"code": "DATA_PROTECTION", "title": "Personal data",
     "text": "Each party processes personal data under this contract in line with {data} and the other party's written instructions."},
]


def jurisdiction_variants(playbook_body: dict) -> dict:
    """The jurisdiction library: the built-in entries overlaid with the tenant's CLM-PLAYBOOK.jurisdictions."""
    return {**JURISDICTIONS, **{k: {**JURISDICTIONS.get(k, {}), **v} for k, v in (playbook_body.get("jurisdictions") or {}).items()}}


def jurisdiction_clauses(playbook_body: dict, code: str) -> list[dict]:
    library = jurisdiction_variants(playbook_body)
    entry = library.get(code) or library.get(code.split("-")[0])
    if entry is None:
        raise Problem(422, "UNKNOWN_JURISDICTION", f"No clause-library variant for {code}; available: {', '.join(sorted(library))}",
                      rule_ref="CLM-JURISDICTION")
    templates = playbook_body.get("jurisdictionClauses") or JURISDICTION_CLAUSES
    return [{"code": t["code"], "title": t["title"], "text": t["text"].format(**entry)} for t in templates]


def _templates_for(playbook_body: dict, type: str) -> list[dict]:
    return playbook_body["templates"].get(type) or BUILTIN_TEMPLATES.get(type) or []


def _obligations_for(playbook_body: dict, type: str) -> list[dict]:
    return playbook_body["obligations"].get(type) or BUILTIN_OBLIGATIONS.get(type) or []


def _num(value) -> str:
    """A number as clause text: no trailing zeros, so 2, 2.0 and 2.00 draft the same wording."""
    return format(D(value).normalize(), "f")


def check_index_ref(index_ref: Optional[dict]) -> None:
    """The price-index clause: the index, its base value and the absorption band. Anything else would fail later, in a reset."""
    if index_ref is None:
        return
    missing = [k for k in ("index", "base", "band_pct") if index_ref.get(k) in (None, "")]
    if missing:
        raise Problem(422, "INVALID_INDEX", f"index_ref needs {', '.join(missing)}", rule_ref="CLM-INDEX")
    try:
        base, band = D(index_ref["base"]), D(index_ref["band_pct"])
    except ArithmeticError:
        raise Problem(422, "INVALID_INDEX", "index_ref base and band_pct must be numbers", rule_ref="CLM-INDEX")
    if base <= 0 or not (0 <= band < 100):
        raise Problem(422, "INVALID_INDEX", "index_ref base must be positive and band_pct between 0 and 100", rule_ref="CLM-INDEX")


def _library(playbook_body: dict, *, type: str, payment_terms: str, incoterms: Optional[str], supplier_name: str, index_ref: Optional[dict],
             tolerances: dict, jurisdiction: Optional[str], category: Optional[str]) -> dict[str, dict]:
    """The clause library for a draft, code -> {title, text}: the type's template, then the category overlay
    (CLM-PLAYBOOK.categoryClauses[category], optionally limited to some types), then the governing-law variant."""
    band = (index_ref or {}).get("band_pct")
    params = {"terms": payment_terms, "incoterms": incoterms or "", "supplier": supplier_name, "band": _num(band) if band not in (None, "") else "",
              "over": _num(tolerances.get("over_pct", 0)), "under": _num(tolerances.get("under_pct", 0))}
    overlay = (playbook_body.get("categoryClauses") or {}).get(category or "", []) if category else []
    library: dict[str, dict] = {}
    # The clause library of the playbook (seed/clause_library.py or the client's legal-approved file) adds its clauses of this type to the
    # built-in template; where both have a code the library wins, unless the playbook says clauseLibrary.precedence = TEMPLATE.
    base = _templates_for(playbook_body, type)
    from_library = clause_library.library_clauses(playbook_body, type)
    ordered = [*from_library, *base] if (playbook_body.get("clauseLibrary") or {}).get("precedence") == "TEMPLATE" else [*base, *from_library]
    for template in [*ordered, *[t for t in overlay if not t.get("types") or type in t["types"]]]:
        library[template["code"]] = {"title": template["title"], "text": template["text"].format(**params)}
    if jurisdiction:
        for variant in jurisdiction_clauses(playbook_body, jurisdiction):
            library[variant["code"]] = {"title": variant["title"], "text": variant["text"]}
    return library


def active_framework(session: Session, supplier_id: uuid.UUID, company_code: str, valid_from: date, valid_to: date) -> Optional[Contract]:
    """The live master agreement of the supplier for the company code that covers the whole validity, if any."""
    return session.execute(select(Contract).where(
        Contract.type == "MASTER_AGREEMENT", Contract.supplier_id == supplier_id, Contract.company_code == company_code,
        Contract.status.in_(FRAMEWORK_LIVE), Contract.valid_from <= valid_from, Contract.valid_to >= valid_to)
        .order_by(Contract.valid_to.desc(), Contract.number)).scalars().first()


def _check_framework(framework: Optional[Contract], *, supplier_id: uuid.UUID, company_code: str, valid_from: date, valid_to: date) -> None:
    if framework is None:
        return
    if framework.type != "MASTER_AGREEMENT":
        raise rule_violation(f"{framework.number} is a {framework.type.lower().replace('_', ' ')}, not a master agreement", "CLM-FRAMEWORK")
    if framework.status not in FRAMEWORK_LIVE:
        raise rule_violation(f"Master agreement {framework.number} is {framework.status}; a call-off refers to a live one", "CLM-FRAMEWORK")
    if framework.supplier_id != supplier_id or framework.company_code != company_code:
        raise rule_violation(f"Master agreement {framework.number} is with another supplier or company code", "CLM-FRAMEWORK")
    if valid_from < framework.valid_from or valid_to > framework.valid_to:
        raise rule_violation(f"The contract period must lie within the master agreement's ({framework.valid_from} to {framework.valid_to})",
                             "CLM-FRAMEWORK")


def _instance(session: Session, contract: Contract):
    return workflow.find(session, "CONTRACT", contract.id, PROCESS)


# Own number range per contract type for new contracts (flow fixes B6): the scheduling agreement keeps the original CONTRACT range
# (SA-5520 of the signature case); the other types get their own prefix. A tenant without the new range rows keeps numbering from
# CONTRACT until migration 0024 / reference.ensure_extensions adds them; existing numbers are never renumbered.
CONTRACT_NUMBER_RANGES = {
    "SCHEDULING_AGREEMENT": "CONTRACT", "QUANTITY_CONTRACT": "CONTRACT_QC", "VALUE_CONTRACT": "CONTRACT_VC", "RATE_CARD": "CONTRACT_RC",
    "SOW": "CONTRACT_SOW", "MASTER_AGREEMENT": "CONTRACT_MA", "NDA": "CONTRACT_NDA",
}


def contract_number(session: Session, type: str) -> str:
    object_type = CONTRACT_NUMBER_RANGES.get((type or "").upper(), "CONTRACT")
    try:
        return next_number(session, object_type)
    except Problem as exc:
        if exc.code != "NUMBER_RANGE_MISSING" or object_type == "CONTRACT":
            raise
        return next_number(session, "CONTRACT")


def _lines(session: Session, contract: Contract) -> list[ContractLine]:
    return session.execute(select(ContractLine).where(ContractLine.contract_id == contract.id).order_by(ContractLine.line_no)).scalars().all()


def create_draft(session: Session, *, type: str, title: str, supplier_id: uuid.UUID, company_code: str, valid_from: date,
                 valid_to: date, payment_terms: str, incoterms: Optional[str], lines: list[dict], owner_id: uuid.UUID,
                 tolerances: dict, index_ref: Optional[dict] = None, source_event_id: Optional[uuid.UUID] = None,
                 trigger: str = "manual", framework_contract_id: Optional[uuid.UUID] = None, jurisdiction: Optional[str] = None,
                 category: Optional[str] = None) -> Contract:
    p = principal(session)
    if valid_to <= valid_from:
        raise Problem(422, "INVALID_VALIDITY", "valid_to must be after valid_from")
    check_index_ref(index_ref)
    playbook = rules.resolve(session, "CLM-PLAYBOOK")
    if type in FRAMEWORK_TYPES:
        if lines or framework_contract_id or index_ref:
            raise rule_violation(f"A {type.replace('_', ' ').lower()} carries no lines, prices, index or framework reference: it sets terms, "
                                 "not quantities", "CLM-FRAMEWORK")
    elif not lines:
        raise Problem(422, "LINES_REQUIRED", "A contract needs at least one line; only a master agreement or an NDA has none")
    framework = session.get(Contract, framework_contract_id) if framework_contract_id else None
    _check_framework(framework, supplier_id=supplier_id, company_code=company_code, valid_from=valid_from, valid_to=valid_to)
    jurisdiction = jurisdiction.upper() if jurisdiction else None
    category = category.strip().upper() if category and category.strip() else None
    supplier = session.get(Supplier, supplier_id)
    library = _library(playbook.body, type=type, payment_terms=payment_terms, incoterms=incoterms, supplier_name=supplier.legal_name,
                       index_ref=index_ref, tolerances=tolerances, jurisdiction=jurisdiction, category=category)
    contract = Contract(
        tenant_id=current_tenant(session), number=contract_number(session, type), type=type, title=title,
        supplier_id=supplier_id, company_code=company_code, status="DRAFT", valid_from=valid_from, valid_to=valid_to,
        payment_terms=payment_terms, incoterms=incoterms, over_tolerance_pct=D(tolerances.get("over_pct", 0)),
        under_tolerance_pct=D(tolerances.get("under_pct", 0)), price_tolerance_pct=D(tolerances.get("price_pct", 0)),
        index_ref=index_ref, source_event_id=source_event_id, owner_id=owner_id, rule_set_version=playbook.ref,
        framework_contract_id=framework.id if framework else None, jurisdiction=jurisdiction, category=category, created_by=p.user_id,
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
    clauses = {code: Clause(tenant_id=contract.tenant_id, contract_id=contract.id, code=code, title=entry["title"], text=entry["text"],
                            standard_text=entry["text"], position="STANDARD", risk_score=0, created_by=p.user_id)
               for code, entry in library.items()}  # the governing-law variant already replaced a base clause of the same code
    session.add_all(clauses.values())
    for ob in _obligations_for(playbook.body, type):
        session.add(Obligation(tenant_id=contract.tenant_id, contract_id=contract.id, party=ob["party"], description=ob["description"],
                               kind=ob.get("kind", "OBLIGATION"), due_date=valid_from + timedelta(days=int(ob["dueAfterDays"])),
                               status="OPEN", created_by=p.user_id))
    session.flush()
    instance = workflow.start(session, PROCESS, "CONTRACT", contract.id, contract.number, {"trigger": trigger})
    workflow.step(session, instance, "F4-02", outcome=f"drafted from {type.lower()} template with {len(clauses)} clauses"
                  + (f" ({jurisdiction} variant)" if jurisdiction else ""))
    audit.record(session, "CONTRACT", contract.id, "DRAFTED", object_ref=contract.number,
                 after={"supplier": supplier.code, "targetValueMinor": target_value, "trigger": trigger,
                        **({"framework": framework.number} if framework else {}), **({"jurisdiction": jurisdiction} if jurisdiction else {}),
                        **({"category": category} if category else {})},
                 rule_set_version=playbook.ref)
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
    if data.get("multiLine"):
        return _from_award_lines(session, sourcing_event, data, defaults, valid_from, valid_to)
    for allocation in data["allocations"]:
        supplier = session.get(Supplier, uuid.UUID(allocation["supplierId"]))
        contract = create_draft(
            session, type="SCHEDULING_AGREEMENT" if material else "VALUE_CONTRACT", title=f"{description} – {supplier.legal_name}",
            supplier_id=supplier.id, company_code=_award_company_code(session, data), valid_from=valid_from, valid_to=valid_to,
            payment_terms=supplier.payment_terms, incoterms=supplier.incoterms,
            lines=[{"material_id": material.id if material else None, "description": description, "plant": data["plant"], "uom": data["uom"],
                    "target_qty": allocation["annualQty"], "unit_price_minor": allocation["priceMinor"]}],
            owner_id=uuid.UUID(data["ownerId"]), tolerances=defaults["tolerances"], index_ref=defaults["index"] if material else None,
            source_event_id=sourcing_event.id, trigger=f"award {sourcing_event.number}", category=sourcing_event.category,
            framework_contract_id=getattr(active_framework(session, supplier.id, _award_company_code(session, data), valid_from, valid_to), "id", None),
        )
        link(session, "SOURCING_EVENT", sourcing_event.id, sourcing_event.number, "CONTRACT", contract.id, contract.number, "awarded_to")


def _from_award_lines(session: Session, sourcing_event: SourcingEvent, data: dict, defaults: dict, valid_from: date, valid_to: date) -> None:
    """An award of several lines (and lots): one contract per awarded supplier covering all the lines it won, each line with its own
    quantity and price. A live master agreement of the supplier that covers the period is referenced."""
    by_line = {l["line"]: l for l in data["lines"]}
    company_code = _award_company_code(session, data)
    for allocation in data["allocations"]:
        supplier = session.get(Supplier, uuid.UUID(allocation["supplierId"]))
        lines, all_material = [], True
        for won in sorted(allocation["lines"], key=lambda l: l["line"]):
            if D(won["annualQty"]) <= 0:
                continue
            item = by_line[won["line"]]
            all_material = all_material and bool(item.get("materialId"))
            lines.append({"material_id": uuid.UUID(item["materialId"]) if item.get("materialId") else None, "description": item["description"],
                          "plant": item["plant"], "uom": item["uom"], "target_qty": won["annualQty"], "unit_price_minor": won["priceMinor"]})
        framework = active_framework(session, supplier.id, company_code, valid_from, valid_to)
        contract = create_draft(
            session, type="SCHEDULING_AGREEMENT" if all_material else "VALUE_CONTRACT", title=f"{sourcing_event.title} – {supplier.legal_name}",
            supplier_id=supplier.id, company_code=company_code, valid_from=valid_from, valid_to=valid_to,
            payment_terms=supplier.payment_terms, incoterms=supplier.incoterms, lines=lines, owner_id=uuid.UUID(data["ownerId"]),
            tolerances=defaults["tolerances"], index_ref=defaults["index"] if all_material else None, source_event_id=sourcing_event.id,
            trigger=f"award {sourcing_event.number}", framework_contract_id=framework.id if framework else None, category=sourcing_event.category)
        link(session, "SOURCING_EVENT", sourcing_event.id, sourcing_event.number, "CONTRACT", contract.id, contract.number, "awarded_to")


def _award_company_code(session: Session, data: dict) -> str:
    """The company code of the requisition the award sources (payload companyCode; older events: looked up)."""
    if data.get("companyCode"):
        return data["companyCode"]
    from app.pic.models import Requisition
    requisition = session.get(Requisition, uuid.UUID(data["requisitionId"])) if data.get("requisitionId") not in (None, "None") else None
    return requisition.company_code if requisition else "1000"


# ---------------------------------------------------------------- F4-03 AI redline, F4-04 supplier review
def _norm(text: Optional[str]) -> str:
    return " ".join((text or "").split())


def risk_band(risk: int) -> str:
    return "HIGH" if risk >= 70 else "MEDIUM" if risk >= 30 else "LOW"


def clause_findings(playbook_body: dict, clauses: list[Clause]) -> list[dict]:
    """Every clause against the playbook: its position, whether the wording left the library text, the risk score and the fallback
    the playbook suggests. A reworded clause still on STANDARD was never classified: it carries at least fallback-level risk until
    the contract manager gives it a position."""
    positions, fallbacks = playbook_body["positionRisk"], playbook_body["fallbacks"]
    meta = clause_library.metadata(playbook_body)   # risk weight, escalation role and fallback positions of the clause library
    out = []
    for clause in sorted(clauses, key=lambda c: c.code):
        deviates = clause.standard_text is not None and _norm(clause.text) != _norm(clause.standard_text)
        risk = int(positions[clause.position])
        if clause.position == "STANDARD" and deviates:
            risk = int(positions["FALLBACK"])
        fallback = fallbacks.get(clause.code)
        suggested = "FALLBACK" if (clause.position == "NON_STANDARD" and fallback) or (clause.position == "STANDARD" and deviates) else None
        out.append({"clause": clause.code, "title": clause.title, "position": clause.position, "risk": risk, "textDeviates": deviates,
                    "deviation": clause.position != "STANDARD" or deviates, "fallback": fallback, "suggestedPosition": suggested,
                    "text": clause.text, "standardText": clause.standard_text,
                    **({"riskWeight": meta[clause.code]["riskWeight"], "escalationRole": meta[clause.code]["escalationRole"],
                        "fallbackPositions": meta[clause.code]["fallbackPositions"]} if clause.code in meta else {})})
    return out


def approval_route(session: Session, contract: Contract, clauses: Optional[list[Clause]] = None):
    """(rule, large, non_standard, chain): value at or above the threshold, or any non-standard clause, needs legal and finance."""
    rule = rules.resolve(session, "CONTRACT-APPROVAL", company_code=contract.company_code)
    if clauses is None:
        clauses = session.execute(select(Clause).where(Clause.contract_id == contract.id)).scalars().all()
    non_standard = any(c.position == "NON_STANDARD" for c in clauses)
    large = contract.target_value_minor >= rule.body["thresholdMinor"]
    return rule, large, non_standard, list(rule.body["above"]) if (large or non_standard) else list(rule.body["below"])


def ai_review(session: Session, contract: Contract) -> dict:
    if contract.status not in ("DRAFT", "IN_NEGOTIATION"):  # the process would be rewound on a contract that is already past negotiation
        raise illegal_transition("Contract", contract.number, contract.status, "review")
    playbook = rules.resolve(session, "CLM-PLAYBOOK")
    clauses = session.execute(select(Clause).where(Clause.contract_id == contract.id)).scalars().all()
    by_code = {c.code: c for c in clauses}
    everything = clause_findings(playbook.body, clauses)
    for item in everything:
        by_code[item["clause"]].risk_score = item["risk"]
    findings = [{k: f[k] for k in ("clause", "position", "risk", "fallback", "textDeviates", "suggestedPosition")} for f in everything if f["deviation"]]
    risk = max([f["risk"] for f in everything], default=0)
    ai_ref = (agents.log_run(session, "CONTRACT_REVIEW", object_type="CONTRACT", object_id=contract.id, object_ref=contract.number,
                            inputs={"clauses": len(clauses)}, evidence=[c.code for c in clauses],
                            output={"risk": risk, "findings": findings}, confidence=0.82, action_taken="DRAFTED")
             if agents.permit(session, "CONTRACT_REVIEW", object_type="CONTRACT", object_id=contract.id, object_ref=contract.number, required_level="L2") else None)
    if contract.status == "DRAFT":
        SM.apply(session, contract, "review", ai_ref=ai_ref, rule_set_version=playbook.ref)
    instance = _instance(session, contract)
    workflow.step(session, instance, "F4-03", outcome=f"contract risk {risk}; {len(findings)} deviation(s)")
    workflow.wait(session, instance, "F4-04", outcome="supplier review / redline")
    return {"risk": risk, "riskBand": risk_band(risk), "findings": findings, "aiRef": ai_ref}


def clause_review(session: Session, contract: Contract) -> dict:
    """CLM-02: each clause with the playbook standard wording, its deviation, risk score and fallback suggestion, the supplier redline
    waiting for review, and the approval route the contract would take now."""
    playbook = rules.resolve(session, "CLM-PLAYBOOK")
    clauses = session.execute(select(Clause).where(Clause.contract_id == contract.id)).scalars().all()
    pending = pending_redlines(session, contract)
    items = clause_findings(playbook.body, clauses)
    for item in items:
        item["pendingRedline"] = pending.get(item["clause"])
    rule, large, non_standard, chain = approval_route(session, contract, clauses)
    risk = max([i["risk"] for i in items], default=0)
    return {"contract": contract.number, "status": contract.status, "ruleSet": playbook.ref, "risk": risk, "riskBand": risk_band(risk),
            "deviations": sum(1 for i in items if i["deviation"]), "pendingReview": sorted(pending), "clauses": items,
            "approval": {"chain": chain, "aboveThresholdMinor": int(rule.body["thresholdMinor"]), "valueMinor": contract.target_value_minor,
                         "reason": ("value at or above the threshold" if large else "") + (" and " if large and non_standard else "")
                         + ("non-standard clause" if non_standard else "") or "below threshold, standard clauses"}}


POSITIONS = ("STANDARD", "FALLBACK", "NON_STANDARD")


def _clause(session: Session, contract: Contract, clause_code: str) -> Clause:
    clause = session.execute(select(Clause).where(Clause.contract_id == contract.id, Clause.code == clause_code)).scalar_one_or_none()
    if clause is None:
        raise Problem(404, "NOT_FOUND", f"Clause {clause_code} not found in {contract.number}")
    return clause


def redline(session: Session, contract: Contract, clause_code: str, text: str, position: Optional[str] = None) -> Clause:
    """F4-04. A supplier redline is always NON_STANDARD and waits for the buyer's review (review_redline); the supplier cannot
    classify its own deviation. A contract manager's redline carries the position the buyer gives it."""
    p = principal(session)
    require_supplier_user(session, contract.supplier_id)
    if contract.status != "IN_NEGOTIATION":
        raise illegal_transition("Contract", contract.number, contract.status, "redline")
    text = (text or "").strip()
    if not text:
        raise Problem(422, "TEXT_REQUIRED", "Give the proposed clause text")
    clause = _clause(session, contract, clause_code)
    by_supplier = "SUPPLIER_USER" in p.roles
    if by_supplier:
        proposed, final = (position or "").upper() or None, "NON_STANDARD"
    else:
        final = (position or clause.position).upper()
        proposed = final
    if final not in POSITIONS or (proposed and proposed not in POSITIONS):
        raise Problem(422, "INVALID_POSITION", f"position must be one of {', '.join(POSITIONS)}")
    before = {"clause": clause_code, "text": clause.text, "position": clause.position}
    clause.text = text
    clause.position = final
    clause.risk_score = int(rules.resolve(session, "CLM-PLAYBOOK").body["positionRisk"][clause.position])
    audit.record(session, "CONTRACT", contract.id, "CLAUSE_REDLINED", object_ref=contract.number, before=before,
                 after={"clause": clause_code, "text": text, "position": clause.position, "party": "SUPPLIER" if by_supplier else "BUYER",
                        "pendingReview": by_supplier, "proposedPosition": proposed})
    return clause


def pending_redlines(session: Session, contract: Contract) -> dict[str, dict]:
    """Supplier redlines the buyer has not reviewed yet, per clause, from the contract's audit trail (append-only): the latest
    CLAUSE_REDLINED by the supplier with no later buyer redline or REDLINE_REVIEWED on that clause. ``originalText`` is the text
    before the first unreviewed supplier redline (what RESTORE puts back)."""
    from app.pic.models import AuditEvent

    pending: dict[str, dict] = {}
    for entry in session.execute(select(AuditEvent).where(
            AuditEvent.object_type == "CONTRACT", AuditEvent.object_id == contract.id,
            AuditEvent.action.in_(("CLAUSE_REDLINED", "REDLINE_REVIEWED"))).order_by(AuditEvent.seq)).scalars():
        after, before = entry.after or {}, entry.before or {}
        code = after.get("clause")
        if not code:
            continue
        if entry.action == "CLAUSE_REDLINED" and after.get("pendingReview"):
            first = pending.get(code)
            pending[code] = {"clause": code, "proposedText": after.get("text"), "proposedPosition": after.get("proposedPosition"),
                             "originalText": first["originalText"] if first else before.get("text"),
                             "originalPosition": first["originalPosition"] if first else before.get("position"),
                             "by": entry.actor, "at": entry.ts.isoformat()}
        else:
            pending.pop(code, None)
    return pending


def review_redline(session: Session, contract: Contract, clause_code: str, decision: str, position: Optional[str] = None,
                   comment: Optional[str] = None) -> Clause:
    """Contract manager decision on a supplier redline: ACCEPT the supplier's text with the playbook position the buyer assigns
    (STANDARD, FALLBACK, or NON_STANDARD which routes the approval through LEGAL), or RESTORE the text and position it replaced."""
    p = principal(session)
    if "CONTRACT_MANAGER" not in p.roles or "SUPPLIER_USER" in p.roles:
        raise Problem(403, "FORBIDDEN", "Only a contract manager reviews supplier redlines", rule_ref="CLM-REDLINE")
    if contract.status != "IN_NEGOTIATION":
        raise illegal_transition("Contract", contract.number, contract.status, "review redline")
    decision = (decision or "").upper()
    if decision not in ("ACCEPT", "RESTORE"):
        raise Problem(422, "INVALID_DECISION", "decision must be ACCEPT or RESTORE")
    clause = _clause(session, contract, clause_code)
    pending = pending_redlines(session, contract).get(clause_code)
    if pending is None:
        raise Problem(409, "NO_PENDING_REDLINE", f"Clause {clause_code} of {contract.number} has no supplier redline to review")
    before = {"clause": clause_code, "text": clause.text, "position": clause.position}
    if decision == "ACCEPT":
        position = (position or "").upper()
        if position not in POSITIONS:
            raise Problem(422, "INVALID_POSITION", f"Accepting a redline needs the playbook position ({', '.join(POSITIONS)})")
        clause.position = position
    else:
        clause.text = pending["originalText"] if pending.get("originalText") is not None else clause.text
        clause.position = pending.get("originalPosition") or "STANDARD"
    clause.risk_score = int(rules.resolve(session, "CLM-PLAYBOOK").body["positionRisk"][clause.position])
    audit.record(session, "CONTRACT", contract.id, "REDLINE_REVIEWED", object_ref=contract.number, before=before,
                 after={"clause": clause_code, "decision": decision, "text": clause.text, "position": clause.position,
                        "supplierRedlineBy": pending["by"], "supplierRedlineAt": pending["at"]}, reason=comment)
    return clause


def submit(session: Session, contract: Contract) -> dict:
    p = principal(session)
    unreviewed = sorted(pending_redlines(session, contract))
    if unreviewed:
        raise Problem(409, "REDLINE_REVIEW_PENDING", f"Review the supplier redline(s) on {', '.join(unreviewed)} before submitting "
                      f"{contract.number} for approval", rule_ref="CLM-REDLINE", clauses=unreviewed)
    rule, large, non_standard, chain = approval_route(session, contract)
    SM.apply(session, contract, "submit", rule_set_version=rule.ref)
    instance = _instance(session, contract)
    workflow.step(session, instance, "F4-04", outcome="review complete")
    workflow.step(session, instance, "F4-05", outcome=("yes" if (large or non_standard) else "no") +
                  f": value {fmt_inr(contract.target_value_minor)}" + (", non-standard clause" if non_standard else ""))
    workflow.start_approval(session, instance, "CONTRACT_APPROVAL", object_type="CONTRACT", object_id=contract.id,
                            object_ref=contract.number, chain=chain, step_id="F4-06", initiator_id=contract.owner_id,
                            exclude=[p.user_id], rule_set_version=rule.ref)  # four-eyes: neither the owner nor the submitter approves
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
    abac.guard(session, "CONTRACT_SIGN", contract)
    party = party.upper()
    if party not in ("BUYER", "SUPPLIER"):
        raise Problem(422, "INVALID_PARTY", "party must be BUYER or SUPPLIER")
    if contract.status != "OUT_FOR_SIGNATURE":
        raise illegal_transition("Contract", contract.number, contract.status, "sign")
    if session.execute(select(Signature.id).where(Signature.contract_id == contract.id, Signature.party == party)).first():
        raise Problem(409, "ALREADY_SIGNED", f"The {party.lower()} has already signed {contract.number}", rule_ref="CLM-ESIGN")
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
    provider = signature_provider(envelope_ref or "ESIGN-")
    audit.record(session, "CONTRACT", contract.id, "SIGNED", object_ref=contract.number,
                 after={"party": party, "hash": doc_hash, "envelope": envelope_ref, "provider": provider,
                        **({"demoSignature": True, "notice": DEMO_SIGNATURE_LABEL} if provider == MOCK_PROVIDER else {})})
    parties = {s.party for s in session.execute(select(Signature).where(Signature.contract_id == contract.id)).scalars()}
    if parties >= {"BUYER", "SUPPLIER"}:
        workflow.step(session, _instance(session, contract), "F4-07", outcome="signed by buyer and supplier")
    return {"contract": contract.number, "signedBy": sorted(parties)}


def activate(session: Session, contract: Contract) -> Contract:
    if contract.status != "OUT_FOR_SIGNATURE":
        raise illegal_transition("Contract", contract.number, contract.status, "activate")
    if contract.valid_to < clock.today():
        raise rule_violation(f"The validity ended on {contract.valid_to}; extend it by a new draft before activation", "CLM-ACTIVATE")
    supplier = session.get(Supplier, contract.supplier_id)
    if supplier.status in ("BLOCKED", "EXITED", "REJECTED", "MERGED"):
        raise Problem(409, "SUPPLIER_BLOCKED", f"{supplier.code} is {supplier.status}; its prices cannot be published", rule_ref="CLM-ACTIVATE")
    if contract.framework_contract_id:
        _check_framework(session.get(Contract, contract.framework_contract_id), supplier_id=contract.supplier_id,
                         company_code=contract.company_code, valid_from=contract.valid_from, valid_to=contract.valid_to)
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
    _succeed(session, contract)
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
# PO statuses whose full ordered quantity counts against the contract; CLOSED counts what was delivered (short close), and
# DRAFT / IN_APPROVAL / CANCELLED count nothing.
CONSUMING_PO = ("RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED", "RECEIVED", "INVOICED")


def live_consumption(session: Session, contract_line: ContractLine) -> tuple[Decimal, int]:
    """Released quantity and value of a contract line from the live purchase-order lines that reference it (read only)."""
    released_qty, released_value = Decimal(0), 0
    for po_line, status in session.execute(select(PoLine, PurchaseOrder.status).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
                                           .where(PoLine.contract_line_id == contract_line.id)).all():
        if status in CONSUMING_PO:
            released_qty += po_line.qty
            released_value += po_line.net_minor
        elif status == "CLOSED":
            delivered = max(po_line.accepted_qty or Decimal(0), po_line.invoiced_qty or Decimal(0))
            released_qty += delivered
            released_value += (line_amount(delivered, po_line.unit_price_minor) if delivered
                               else max(po_line.ses_approved_minor or 0, po_line.invoiced_minor or 0) if po_line.ses_required else 0)
    return released_qty, released_value


def committed_qty(session: Session, contract_line: ContractLine) -> Decimal:
    """What the line has promised: the live consumption plus the quantity on draft and in-approval orders that reference it."""
    released, _ = live_consumption(session, contract_line)
    pending = session.execute(select(func.coalesce(func.sum(PoLine.qty), 0)).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
        PoLine.contract_line_id == contract_line.id, PurchaseOrder.status.in_(("DRAFT", "IN_APPROVAL")))).scalar()
    return released + D(pending)


def recompute_consumption(session: Session, contract_line: ContractLine) -> tuple[Decimal, int]:
    """Store the live consumption on the line. Idempotent, so the result is right whatever order the release / change / cancel /
    close events are relayed in."""
    released_qty, released_value = live_consumption(session, contract_line)
    contract_line.released_qty, contract_line.released_value_minor = released_qty, released_value
    return released_qty, released_value


@outbox.consumer("purchase_order.released", "contract-consumption")
@outbox.consumer("purchase_order.changed", "contract-consumption")
@outbox.consumer("purchase_order.cancelled", "contract-consumption")
@outbox.consumer("purchase_order.closed", "contract-consumption")
def _consume(session: Session, event) -> None:
    po = session.get(PurchaseOrder, event.object_id)
    if po is None:
        return
    rule = None
    line_ids = {line.contract_line_id for line in session.execute(
        select(PoLine).where(PoLine.po_id == po.id, PoLine.contract_line_id.is_not(None))).scalars()}
    for contract_line_id in sorted(line_ids):
        contract_line = session.get(ContractLine, contract_line_id, with_for_update=True)
        if contract_line is None:
            continue
        recompute_consumption(session, contract_line)
        contract = session.get(Contract, contract_line.contract_id)
        rule = rule or rules.resolve(session, "CONTRACT-APPROVAL", company_code=contract.company_code)
        pct = (contract_line.released_qty / contract_line.target_qty * 100) if contract_line.target_qty else Decimal(0)
        hit = list(contract_line.thresholds_hit or [])  # each line alerts on its own: line 2 reaching 80% is news even if line 1 did earlier
        for threshold in sorted(rule.body["consumptionThresholds"]):
            if pct >= threshold and threshold not in hit:
                hit.append(threshold)
                contract.thresholds_hit = sorted(set(contract.thresholds_hit or []) | {threshold})
                outbox.emit(session, "contract.consumption.threshold", "CONTRACT", contract.id, contract.number,
                            {"threshold": threshold, "consumedPct": str(pct.quantize(Decimal("0.01"))), "line": contract_line.line_no,
                             "description": contract_line.description, "releasedQty": str(contract_line.released_qty),
                             "targetQty": str(contract_line.target_qty), "ownerId": str(contract.owner_id)})
        contract_line.thresholds_hit = hit


def consumption(session: Session, contract: Contract) -> dict:
    """Released against target per line, and the compliance picture of the contract: off-contract buying of the contracted items
    (a PO line for the same material and plant that did not use the contract) and price leakage (a contract-priced PO line whose
    price left the tolerance and was flagged, and off-contract lines bought above the contract price)."""
    lines, off_value, off_leak, deviation_excess, released_value, target_value = [], 0, 0, 0, 0, 0
    starts, ends = clock.at_ist(contract.valid_from, 0), clock.at_ist(contract.valid_to + timedelta(days=1), 0)
    for line in _lines(session, contract):
        validity = session.execute(select(PriceValidity).where(PriceValidity.contract_line_id == line.id, PriceValidity.published.is_(True),
                                                               PriceValidity.valid_from <= clock.today())
                                   .order_by(PriceValidity.valid_from.desc(), PriceValidity.created_at.desc())).scalars().first()
        price = validity.unit_price_minor if validity else 0
        leakage = []
        if line.material_id:
            for po_line, po in session.execute(select(PoLine, PurchaseOrder).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
                    PoLine.material_id == line.material_id, PoLine.plant == line.plant, PoLine.contract_line_id.is_(None),
                    PurchaseOrder.status.not_in(("DRAFT", "CANCELLED")), PurchaseOrder.created_at >= starts, PurchaseOrder.created_at < ends)
                    .order_by(PurchaseOrder.number, PoLine.line_no)).all():
                excess = max(0, line_amount(po_line.qty, po_line.unit_price_minor - price))
                off_value += po_line.net_minor
                off_leak += excess
                leakage.append({"po": po.number, "line": po_line.line_no, "qty": str(po_line.qty), "unitPriceMinor": po_line.unit_price_minor,
                                "valueMinor": po_line.net_minor, "leakageMinor": excess})
        deviations = []
        for po_line, po in session.execute(select(PoLine, PurchaseOrder).join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id).where(
                PoLine.contract_line_id == line.id, PoLine.price_deviation.is_(True), PurchaseOrder.status.not_in(("DRAFT", "CANCELLED")))
                .order_by(PurchaseOrder.number, PoLine.line_no)).all():
            reference = session.get(PriceValidity, po_line.price_validity_id).unit_price_minor if po_line.price_validity_id else price
            excess = max(0, line_amount(po_line.qty, po_line.unit_price_minor - reference))
            deviation_excess += excess
            deviations.append({"po": po.number, "line": po_line.line_no, "qty": str(po_line.qty), "unitPriceMinor": po_line.unit_price_minor,
                               "contractPriceMinor": reference, "excessMinor": excess, "reason": po_line.deviation_reason})
        released_value += line.released_value_minor
        target_value += line_amount(line.target_qty, price)
        lines.append({"line": line.line_no, "description": line.description, "targetQty": str(line.target_qty),
                      "releasedQty": str(line.released_qty), "releasedValueMinor": line.released_value_minor,
                      "consumedPct": str((line.released_qty / line.target_qty * 100).quantize(Decimal("0.01"))) if line.target_qty else "0",
                      "thresholdsHit": line.thresholds_hit or [], "currentPriceMinor": validity.unit_price_minor if validity else None,
                      "offContract": leakage, "priceDeviations": deviations})
    obligations = session.execute(select(Obligation).where(Obligation.contract_id == contract.id).order_by(Obligation.due_date)).scalars().all()
    on_contract = released_value
    compliance = {"targetValueMinor": contract.target_value_minor, "releasedValueMinor": released_value,
                  "consumedValuePct": str((Decimal(released_value) / contract.target_value_minor * 100).quantize(Decimal("0.01")))
                  if contract.target_value_minor else "0",
                  "offContractValueMinor": off_value, "offContractLeakageMinor": off_leak, "priceDeviationExcessMinor": deviation_excess,
                  "priceLeakageMinor": off_leak + deviation_excess,
                  "offContractLines": sum(len(l["offContract"]) for l in lines), "priceDeviationLines": sum(len(l["priceDeviations"]) for l in lines),
                  "complianceRatePct": str((Decimal(on_contract) / (on_contract + off_value) * 100).quantize(Decimal("0.01")))
                  if (on_contract + off_value) else None,
                  "definition": "released on contract / (released on contract + bought off-contract) for the contracted items; "
                                "price leakage = amount paid above the contract price on off-contract and flagged contract-priced lines"}
    return {"contract": contract.number, "status": contract.status, "thresholdsHit": contract.thresholds_hit, "lines": lines, "compliance": compliance,
            "obligations": [{"id": str(o.id), "party": o.party, "kind": o.kind, "description": o.description, "dueDate": o.due_date.isoformat(),
                             "status": o.status, "completedAt": o.completed_at.isoformat() if o.completed_at else None} for o in obligations]}


def index_reset(session: Session, contract: Contract, index_value: Decimal, effective_from: date) -> dict:
    """Quarterly index reset: always a new validity period. Inside the band the price is unchanged (absorbed)."""
    from app.pic.services import savings

    if contract.status not in ("ACTIVE", "EXPIRING") or not contract.index_ref:
        raise rule_violation("Only active indexed contracts can be reset", "CLM-INDEX")
    index_value = D(index_value)
    if index_value <= 0:
        raise Problem(422, "INVALID_INDEX", "The index value must be positive", rule_ref="CLM-INDEX")
    if not (contract.valid_from <= effective_from <= contract.valid_to):
        raise rule_violation(f"The reset must take effect inside the contract validity ({contract.valid_from} to {contract.valid_to})", "CLM-INDEX")
    last = session.execute(select(func.max(PriceValidity.valid_from)).where(
        PriceValidity.contract_line_id.in_(select(ContractLine.id).where(ContractLine.contract_id == contract.id)),
        PriceValidity.reason.like("INDEX_RESET%"))).scalar()
    if last is not None and effective_from <= last:  # periods are never overwritten: a reset adds a period after the last one
        raise Problem(409, "INDEX_RESET_NOT_LATER", f"An index reset already takes effect from {last}; the next one must be later",
                      rule_ref="CLM-INDEX", lastReset=last.isoformat())
    base = D(contract.index_ref["base"])
    band = D(contract.index_ref["band_pct"])
    change_pct = ((D(index_value) / base) - 1) * 100
    adjust_pct = Decimal(0) if abs(change_pct) <= band else (change_pct - band if change_pct > 0 else change_pct + band)
    results = []
    for line in _lines(session, contract):
        # indexing applies to the latest negotiated price (initial, award or amendment), never compounds earlier resets; an
        # extension period only carries the price in force (possibly index-adjusted) forward, so it is not a negotiated base either
        original = session.execute(select(PriceValidity).where(
            PriceValidity.contract_line_id == line.id, PriceValidity.valid_from <= effective_from,
            PriceValidity.reason.not_like("INDEX_RESET%"), PriceValidity.reason.not_like("EXTENSION%"))
            .order_by(PriceValidity.valid_from.desc(), PriceValidity.created_at.desc())).scalars().first()
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
    if results:
        session.flush()
        post_to_erp(session, contract)  # the new price period reaches the ERP outline agreement (flow fixes B5)
    return {"contract": contract.number, "changePct": str(change_pct.quantize(Decimal("0.01"))), "adjustPct": str(adjust_pct.quantize(Decimal("0.01"))),
            "lines": results}


def add_obligation(session: Session, contract: Contract, *, party: str, description: str, due_date: date, kind: str = "OBLIGATION") -> Obligation:
    """A buyer or supplier obligation, or a milestone, added to a contract after drafting (blueprint 13.1)."""
    p = principal(session)
    party, kind = (party or "").upper(), (kind or "OBLIGATION").upper()
    if party not in ("BUYER", "SUPPLIER"):
        raise Problem(422, "INVALID_PARTY", "party must be BUYER or SUPPLIER")
    if kind not in OBLIGATION_KINDS:
        raise Problem(422, "INVALID_KIND", f"kind must be one of {', '.join(OBLIGATION_KINDS)}")
    if contract.status in ("EXPIRED", "TERMINATED", "RENEWED"):
        raise illegal_transition("Contract", contract.number, contract.status, "add an obligation")
    description = (description or "").strip()
    if len(description) < 3:
        raise Problem(422, "DESCRIPTION_REQUIRED", "Describe the obligation")
    if due_date < contract.valid_from:
        raise rule_violation(f"The due date {due_date} is before the contract starts ({contract.valid_from})", "CLM-OBLIGATION")
    obligation = Obligation(tenant_id=contract.tenant_id, contract_id=contract.id, party=party, kind=kind, description=description[:2000],
                            due_date=due_date, status="OPEN", created_by=p.user_id)
    session.add(obligation)
    session.flush()
    audit.record(session, "CONTRACT", contract.id, "OBLIGATION_ADDED", object_ref=contract.number,
                 after={"obligation": obligation.description, "party": party, "kind": kind, "dueDate": due_date.isoformat()})
    return obligation


def complete_obligation(session: Session, obligation: Obligation, note: str) -> Obligation:
    p = principal(session)
    note = (note or "").strip()
    if len(note) < 3:
        raise Problem(422, "NOTE_REQUIRED", "Record the evidence that the obligation was met")
    if obligation.status != "OPEN":
        raise Problem(409, "ALREADY_COMPLETED", "This obligation is already completed", rule_ref="CLM-OBLIGATION")
    contract = session.get(Contract, obligation.contract_id)
    obligation.status = "DONE"
    obligation.completed_at, obligation.completed_by, obligation.completion_note = clock.now(), p.user_id, note
    on_time = obligation.completed_at.astimezone(clock.IST).date() <= obligation.due_date
    audit.record(session, "CONTRACT", obligation.contract_id, "OBLIGATION_DONE", object_ref=contract.number if contract else None,
                 after={"obligation": obligation.description, "party": obligation.party, "dueDate": obligation.due_date.isoformat(), "onTime": on_time},
                 reason=note)
    return obligation


@workflow.on_timer("CONTRACT_RENEWAL")
def _renewal_due(session: Session, timer) -> None:
    contract = session.get(Contract, timer.object_id)
    if contract and contract.status == "ACTIVE":
        SM.apply(session, contract, "expiring", reason="renewal notice period reached")
        outbox.emit(session, "contract.expiring", "CONTRACT", contract.id, contract.number,
                    {"validTo": contract.valid_to.isoformat(), "daysToExpiry": (contract.valid_to - clock.today()).days,
                     "ownerId": str(contract.owner_id), "supplierId": str(contract.supplier_id), "targetValueMinor": contract.target_value_minor})
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


def terminate(session: Session, contract: Contract, *, reason: str, effective_from: Optional[date] = None, for_cause: bool = False):
    """Terminate an active contract: the termination amendment (CLM-AMEND) with the notice period and the approval chain of the
    CONTRACT-AMENDMENT rule. Without cause the default effective date is the end of the notice period; the contract becomes
    TERMINATED when the approved amendment takes effect (open POs are flagged for review, prices stop, timers are cancelled)."""
    from app.pic.services import amendments

    if contract.status not in ("ACTIVE", "EXPIRING"):
        raise illegal_transition("Contract", contract.number, contract.status, "terminate")
    if effective_from is None:
        notice = 0 if for_cause else int(rules.resolve(session, "CONTRACT-AMENDMENT", company_code=contract.company_code).body["noticeDays"])
        effective_from = clock.today() + timedelta(days=notice)
    return amendments.create(session, contract, kind="TERMINATION", changes={"forCause": bool(for_cause)}, reason=reason,
                             effective_from=effective_from, submit_now=True)



@workflow.on_timer("CONTRACT_EXPIRY")
def _expired(session: Session, timer) -> None:
    from app.pic.services import amendments

    contract = session.get(Contract, timer.object_id)
    if contract and contract.status in ("ACTIVE", "EXPIRING") and contract.valid_to < clock.today():
        SM.apply(session, contract, "expire")
        amendments.close_pending(session, contract, f"contract expired on {contract.valid_to.isoformat()}")
        for task in session.execute(select(Task).where(Task.kind == "CONTRACT_RENEWAL", Task.object_id == contract.id, Task.status == "OPEN")).scalars():
            task.status = "CANCELLED"  # nobody decides the renewal of a contract that has ended
            amendments._cancel_timers(session, "TASK_SLA", task.id)
        instance = _instance(session, contract)
        if instance is not None and instance.status == "RUNNING":
            workflow.step(session, instance, "F4-09", outcome="consumption tracking ended at expiry")
            workflow.end(session, instance, "F4-10", outcome=f"expired on {contract.valid_to.isoformat()}")


@outbox.consumer("contract.expiring", "notify-contract-expiring")
def _notify_expiring(session: Session, event) -> None:
    """CONTRACT_EXPIRING (rule NOTIFICATIONS): the owner and the contract managers, at the renewal notice date."""
    from app.pic.services.notifications import _user, link_for, notify, users_with_role
    contract = session.get(Contract, event.object_id)
    if contract is None:
        return
    internal = _user(session, contract.owner_id) + [u for u in users_with_role(session, "CONTRACT_MANAGER") if u.supplier_id is None]
    notify(session, internal, kind="CONTRACT_EXPIRING", dedup_key=f"CONTRACT_EXPIRING:{contract.id}:{contract.valid_to.isoformat()}",
           title=f"Contract {contract.number} expires on {contract.valid_to.strftime('%d %b %Y')}",
           body=f"{contract.number} ({contract.title}) expires in {event.payload.get('daysToExpiry')} days, on {contract.valid_to.isoformat()}. "
                "Decide the renewal: extend this contract (renewal task), draft a successor contract, run a new sourcing event or let it expire.",
           link=link_for("CONTRACT", contract.number), object_type="CONTRACT", object_ref=contract.number)


# ---------------------------------------------------------------- renewal by a successor contract (TD §6 Renewed)
def renew_as_successor(session: Session, contract: Contract, *, reason: str, valid_from: Optional[date] = None,
                       valid_to: Optional[date] = None, title: Optional[str] = None) -> Contract:
    """Draft the successor of a live contract: same type, supplier, company code, terms and lines, at the prices valid at the end of
    the current contract, for the next period (default: the day after the end, for rule CONTRACT-AMENDMENT.renewalExtensionMonths).
    The predecessor becomes RENEWED when the successor takes effect (``_succeed``)."""
    from app.pic.services import amendments

    reason = (reason or "").strip()
    if not reason:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for the renewal", rule_ref="CLM-RENEW")
    if contract.status not in FRAMEWORK_LIVE:
        raise illegal_transition("Contract", contract.number, contract.status, "renew")
    existing = session.execute(select(Contract.number).where(Contract.renews_contract_id == contract.id,
                                                             Contract.status.not_in(("TERMINATED", "EXPIRED")))).scalars().first()
    if existing:
        raise Problem(409, "SUCCESSOR_EXISTS", f"{existing} already renews {contract.number}", rule_ref="CLM-RENEW", successor=existing)
    pending = amendments._pending(session, contract)
    if pending is not None and pending.kind == "EXTENSION":
        raise Problem(409, "EXTENSION_PENDING", f"Extension {pending.number} of {contract.number} is {pending.status}: decide it or withdraw it first",
                      rule_ref="CLM-RENEW")
    valid_from = valid_from or contract.valid_to + timedelta(days=1)
    if valid_to is None:
        months = int(rules.resolve(session, "CONTRACT-AMENDMENT", company_code=contract.company_code).body.get("renewalExtensionMonths", 12))
        valid_to = amendments.add_months(valid_from, months) - timedelta(days=1)
    if valid_from <= contract.valid_from:
        raise rule_violation(f"The successor must start after {contract.valid_from.isoformat()}, the start of {contract.number}", "CLM-RENEW")
    lines = []
    for line in _lines(session, contract):
        validity = session.execute(select(PriceValidity).where(PriceValidity.contract_line_id == line.id, PriceValidity.published.is_(True))
                                   .order_by(PriceValidity.valid_to.desc(), PriceValidity.valid_from.desc(), PriceValidity.created_at.desc())
                                   .limit(1)).scalar_one_or_none()
        if validity is None:
            continue
        lines.append({"material_id": line.material_id, "description": line.description, "plant": line.plant, "uom": line.uom,
                      "target_qty": line.target_qty, "unit_price_minor": validity.unit_price_minor})
    successor = create_draft(
        session, type=contract.type, title=title or contract.title, supplier_id=contract.supplier_id, company_code=contract.company_code,
        valid_from=valid_from, valid_to=valid_to, payment_terms=contract.payment_terms, incoterms=contract.incoterms, lines=lines,
        owner_id=contract.owner_id, tolerances={"over_pct": contract.over_tolerance_pct, "under_pct": contract.under_tolerance_pct,
                                                "price_pct": contract.price_tolerance_pct},
        index_ref=contract.index_ref, trigger=f"renewal of {contract.number}", framework_contract_id=contract.framework_contract_id,
        jurisdiction=contract.jurisdiction, category=contract.category)
    successor.renews_contract_id = contract.id
    link(session, "CONTRACT", contract.id, contract.number, "CONTRACT", successor.id, successor.number, "renewed_by")
    audit.record(session, "CONTRACT", contract.id, "RENEWAL_SUCCESSOR_DRAFTED", object_ref=contract.number, reason=reason,
                 after={"successor": successor.number, "validFrom": valid_from.isoformat(), "validTo": valid_to.isoformat(), "lines": len(lines)})
    instance = _instance(session, contract)
    if instance is not None and instance.status == "RUNNING":
        workflow.step(session, instance, "F4-09", outcome=f"renewal: successor {successor.number} drafted ({valid_from.isoformat()} to {valid_to.isoformat()})")
        workflow.wait(session, instance, "F4-09", outcome="tracking consumption & obligations")
    return successor


def _succeed(session: Session, successor: Contract) -> None:
    """The successor was activated: its predecessor becomes RENEWED now (validity started) or on the successor's start date."""
    if not successor.renews_contract_id:
        return
    predecessor = session.get(Contract, successor.renews_contract_id)
    if predecessor is None or predecessor.status not in FRAMEWORK_LIVE:
        return
    if successor.valid_from <= clock.today():
        _mark_renewed(session, predecessor, successor)
    else:
        workflow.create_timer(session, "CONTRACT_SUCCESSION", "CONTRACT", successor.id, clock.at_ist(successor.valid_from, 0, 5))


@workflow.on_timer("CONTRACT_SUCCESSION")
def _succession_due(session: Session, timer) -> None:
    successor = session.get(Contract, timer.object_id)
    if successor is None or successor.status not in FRAMEWORK_LIVE or not successor.renews_contract_id:
        return
    predecessor = session.get(Contract, successor.renews_contract_id)
    if predecessor is not None and predecessor.status in FRAMEWORK_LIVE:
        _mark_renewed(session, predecessor, successor)


def _mark_renewed(session: Session, predecessor: Contract, successor: Contract) -> None:
    from app.pic.services import amendments

    SM.apply(session, predecessor, "renew", reason=f"renewed by {successor.number}")
    amendments.close_pending(session, predecessor, f"renewed by {successor.number}")
    for task in session.execute(select(Task).where(Task.kind == "CONTRACT_RENEWAL", Task.object_id == predecessor.id, Task.status == "OPEN")).scalars():
        task.status = "CANCELLED"  # decided by the successor contract
        amendments._cancel_timers(session, "TASK_SLA", task.id)
    outbox.emit(session, "contract.renewed", "CONTRACT", predecessor.id, predecessor.number,
                {"successor": successor.number, "successorId": str(successor.id), "validFrom": successor.valid_from.isoformat(),
                 "validTo": successor.valid_to.isoformat(), "supplierId": str(predecessor.supplier_id), "ownerId": str(predecessor.owner_id)})
    instance = _instance(session, predecessor)
    if instance is not None and instance.status == "RUNNING":
        workflow.step(session, instance, "F4-09", outcome=f"consumption tracking ended: renewed by {successor.number}")
        workflow.end(session, instance, "F4-10", outcome=f"renewed by {successor.number} from {successor.valid_from.isoformat()}")


# ---------------------------------------------------------------- ERP outline agreement (flow fixes B5)
ERP_MESSAGE = "OUTLINE_AGREEMENT"


@outbox.consumer("contract.activated", "erp-contract-posting")
@outbox.consumer("contract.amended", "erp-contract-posting")
def _post_contract(session: Session, event) -> Optional[dict]:
    return post_to_erp(session, session.get(Contract, event.object_id))


def post_to_erp(session: Session, contract: Optional[Contract]) -> Optional[dict]:
    """Queue the contract's current version for the ERP (exactly once per version) and process it."""
    from app.pic.platform import connectors, integration

    if contract is None or contract.type in FRAMEWORK_TYPES or contract.status not in FRAMEWORK_LIVE:
        return None
    target = integration.target_system(session, contract.company_code)
    if not connectors.maps(target, ERP_MESSAGE):
        audit.record(session, "CONTRACT", contract.id, "ERP_NOT_MAPPED", object_ref=contract.number,
                     after={"system": target, "messageType": ERP_MESSAGE, "version": contract.version},
                     reason=f"The ERP connector does not map {ERP_MESSAGE}; the contract stands in PIC only")
        return {"status": "NOT_MAPPED", "system": target}
    supplier = session.get(Supplier, contract.supplier_id)
    material_numbers = {m.id: m.number for m in session.execute(select(Material).where(Material.id.in_(
        [l.material_id for l in _lines(session, contract) if l.material_id]))).scalars()} if _lines(session, contract) else {}
    lines = []
    for line in _lines(session, contract):
        validity = session.execute(select(PriceValidity).where(PriceValidity.contract_line_id == line.id, PriceValidity.published.is_(True))
                                   .order_by(PriceValidity.valid_from.desc(), PriceValidity.created_at.desc()).limit(1)).scalar_one_or_none()
        lines.append({"line": line.line_no, "material": material_numbers.get(line.material_id), "description": line.description,
                      "plant": line.plant, "uom": line.uom, "targetQty": str(line.target_qty),
                      "priceMinor": validity.unit_price_minor if validity else None,
                      "priceValidFrom": validity.valid_from.isoformat() if validity else None,
                      "priceValidTo": validity.valid_to.isoformat() if validity else None})
    payload = {"contract": contract.number, "version": contract.version, "type": contract.type, "supplier": supplier.code,
               "companyCode": contract.company_code, "currency": contract.currency, "validFrom": contract.valid_from.isoformat(),
               "validTo": contract.valid_to.isoformat(), "paymentTerms": contract.payment_terms, "incoterms": contract.incoterms,
               "targetValueMinor": contract.target_value_minor, "lines": lines}
    # Exactly once per content of a version: an index reset adds a price period without a new contract version, so the key carries a
    # digest of what is sent (a replay of the same content is the same message; new prices are a new message).
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:12]
    message = integration.enqueue(
        session, target_system=target, message_type=ERP_MESSAGE, idempotency_key=f"{contract.company_code}|OA|{contract.number}|v{contract.version}|{digest}",
        object_type="CONTRACT", object_id=contract.id, object_ref=contract.number, payload=payload)
    integration.process(session, message)
    return {"status": message.status, "system": target, "erpDocument": message.erp_doc_no}


def _contract_posted(session: Session, message) -> None:
    contract = session.get(Contract, message.object_id)
    if contract is not None and (message.payload or {}).get("version") == contract.version:
        contract.erp_doc_no = message.erp_doc_no


def _register_erp_callback() -> None:
    from app.pic.platform import integration
    integration.on_posted(ERP_MESSAGE)(_contract_posted)


_register_erp_callback()


# ---------------------------------------------------------------- consumption re-checked at PO release (flow fixes B3)
def check_release(session: Session, po: PurchaseOrder, po_lines: list) -> list[dict]:
    """At release (not only at creation) the contract must still be live and the order must still fit the contract: quantity per line
    within target + over-delivery tolerance, and for a value contract the released value within the target value + tolerance. What
    other orders released since this one was created counts. Raises 422 CONTRACT_EXHAUSTED / CONTRACT_NOT_LIVE (rule CLM-PO); returns
    the checks made (kept in the release audit)."""
    checks = []
    by_line: dict = {}
    for po_line in po_lines:
        if po_line.contract_line_id:
            by_line.setdefault(po_line.contract_line_id, []).append(po_line)
    value_by_contract: dict = {}
    for contract_line_id, lines in sorted(by_line.items(), key=lambda kv: str(kv[0])):
        contract_line = session.get(ContractLine, contract_line_id)
        if contract_line is None:
            continue
        contract = session.get(Contract, contract_line.contract_id)
        if contract.status not in FRAMEWORK_LIVE:
            raise Problem(422, "CONTRACT_NOT_LIVE", f"{contract.number} is {contract.status}; {po.number} cannot be released against it",
                          rule_ref="CLM-PO", contract=contract.number)
        released_qty, released_value = live_consumption(session, contract_line)
        qty = sum((D(l.qty) for l in lines), Decimal(0))
        limit = contract_line.target_qty * (1 + D(contract.over_tolerance_pct) / 100)
        checks.append({"contract": contract.number, "line": contract_line.line_no, "releasedQty": jsonable_str(released_qty),
                       "orderQty": jsonable_str(qty), "limitQty": jsonable_str(limit)})
        if released_qty + qty > limit:
            raise Problem(422, "CONTRACT_EXHAUSTED",
                          f"{contract.number} line {contract_line.line_no}: {released_qty} of {contract_line.target_qty} {contract_line.uom} already released; "
                          f"{qty} more on {po.number} exceeds the contract quantity (+{contract.over_tolerance_pct}% tolerance). Reduce the order, "
                          "amend the contract or order the rest without the contract", rule_ref="CLM-PO", contract=contract.number,
                          line=contract_line.line_no, releasedQty=str(released_qty), orderQty=str(qty), limitQty=str(limit))
        entry = value_by_contract.setdefault(contract.id, [contract, 0])
        entry[1] += sum(l.net_minor for l in lines)
    for contract, order_value in value_by_contract.values():
        if contract.type != "VALUE_CONTRACT" or not contract.target_value_minor:
            continue
        released = sum(live_consumption(session, l)[1] for l in _lines(session, contract))
        limit = int(contract.target_value_minor * (1 + D(contract.over_tolerance_pct) / 100))
        checks.append({"contract": contract.number, "releasedValueMinor": released, "orderValueMinor": order_value, "limitValueMinor": limit})
        if released + order_value > limit:
            raise Problem(422, "CONTRACT_EXHAUSTED",
                          f"{contract.number}: {fmt_inr(released)} of {fmt_inr(contract.target_value_minor)} already released; {po.number} "
                          f"({fmt_inr(order_value)}) exceeds the contract value (+{contract.over_tolerance_pct}% tolerance)", rule_ref="CLM-PO",
                          contract=contract.number, releasedValueMinor=released, orderValueMinor=order_value, limitValueMinor=limit)
    return checks


def jsonable_str(value) -> str:
    return format(D(value).normalize(), "f") if value is not None else "0"


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
        on_time = None
        if o.status in ("DONE", "COMPLETED"):
            state = "COMPLETED"
            on_time = True if o.completed_at is None else o.completed_at.astimezone(clock.IST).date() <= o.due_date
        elif o.status != "OPEN":
            state = o.status
        else:
            state = "OVERDUE" if o.due_date < today else "DUE_SOON" if (o.due_date - today).days <= 30 else "OPEN"
        items.append({"id": str(o.id), "contract": c.number, "contractStatus": c.status, "supplier": suppliers.get(c.supplier_id), "party": o.party,
                      "kind": o.kind, "description": o.description, "dueDate": o.due_date.isoformat(), "status": state,
                      "daysToDue": (o.due_date - today).days, "completedAt": o.completed_at.isoformat() if o.completed_at else None, "onTime": on_time})
    done = [i for i in items if i["status"] == "COMPLETED"]
    on_time_done = sum(1 for i in done if i["onTime"])
    overdue = sum(1 for i in items if i["status"] == "OVERDUE")
    due_basis = len(done) + overdue  # obligations that fell due: completed (on time or late) plus still open past the date
    return {"items": items, "overdue": overdue, "dueSoon": sum(1 for i in items if i["status"] == "DUE_SOON"), "completed": len(done),
            "completedOnTime": on_time_done, "onTimePct": str((Decimal(on_time_done) / due_basis * 100).quantize(Decimal("0.1"))) if due_basis else None}


def renewals(session: Session) -> list[dict]:
    notice = int(rules.resolve(session, "CONTRACT-APPROVAL").body["renewalNoticeDays"])
    today = clock.today()
    suppliers = {s.id: s.code for s in session.execute(select(Supplier)).scalars()}
    out = []
    decisions = {t.object_id: t for t in session.execute(select(Task).where(Task.kind == "CONTRACT_RENEWAL", Task.status == "OPEN")).scalars()}
    for c in session.execute(select(Contract).where(Contract.status.in_(("ACTIVE", "EXPIRING", "OUT_FOR_SIGNATURE", "IN_APPROVAL")))
                             .order_by(Contract.valid_to)).scalars():
        notice_on = c.valid_to - timedelta(days=notice)
        task = decisions.get(c.id)
        out.append({"contract": c.number, "title": c.title, "supplier": suppliers.get(c.supplier_id), "status": c.status,
                    "validTo": c.valid_to.isoformat(), "noticeOn": notice_on.isoformat(), "daysToExpiry": (c.valid_to - today).days,
                    "noticeDue": today >= notice_on, "expiringIn90": 0 <= (c.valid_to - today).days <= 90, "targetValueMinor": c.target_value_minor,
                    "renewalTask": {"id": str(task.id), "dueAt": task.due_at.isoformat()} if task else None})
    return out


def templates(session: Session, jurisdiction: Optional[str] = None) -> dict:
    playbook = rules.resolve(session, "CLM-PLAYBOOK")
    library = jurisdiction_variants(playbook.body)
    all_templates = {**BUILTIN_TEMPLATES, **playbook.body["templates"]}
    out = {"ruleSet": playbook.ref, "types": sorted(all_templates), "frameworkTypes": list(FRAMEWORK_TYPES),
           "templates": all_templates, "obligations": {**BUILTIN_OBLIGATIONS, **playbook.body["obligations"]},
           "categories": sorted((playbook.body.get("categoryClauses") or {}).keys()),
           "fallbacks": playbook.body["fallbacks"],
           "library": {k: (playbook.body.get("clauseLibrary") or {}).get(k) for k in ("version", "source", "disclaimer", "precedence")},
           "libraryClauses": {t: [{k: c[k] for k in ("code", "title", "text", "riskWeight", "escalationRole", "fallbacks")}
                                  for c in clause_library.library_clauses(playbook.body, t)] for t in clause_library.CONTRACT_TYPES},
           "jurisdictions": [{"code": k, "name": v["name"], "seat": v["seat"], "law": v["law"]} for k, v in sorted(library.items())]}
    if jurisdiction:
        out["jurisdictionClauses"] = jurisdiction_clauses(playbook.body, jurisdiction.upper())
    return out


# ---------------------------------------------------------------- F4-07 e-signature provider adapter
ESIGN_PROVIDERS = ("DOCUSIGN", "ADOBE_SIGN", "LEEGALITY", "EMUDHRA")   # the real providers
ESIGN_SIGNATURE_HEADER = "X-Esign-Signature"
ESIGN_ENV = ("PIC_ESIGN_PROVIDER", "PIC_ESIGN_URL", "PIC_ESIGN_API_KEY", "PIC_ESIGN_WEBHOOK_SECRET")
# The MOCK provider (tools/esign_mock.py) exists for demos and tests. It is accepted only outside production, and a signature it
# produces is a demo signature: recorded with the provider MOCK and shown as not legally binding.
MOCK_PROVIDER = "MOCK"
MOCK_ENVELOPE_PREFIX = "MOCK-"
DEMO_SIGNATURE_LABEL = "Demo signature - not legally binding"


def is_production() -> bool:
    """PIC_ENV at call time (the environment first, then the settings file)."""
    value = os.environ.get("PIC_ENV")
    if value is None:
        try:
            from app.pic.config import get_settings
            return get_settings().is_production
        except Exception:  # noqa: BLE001 - no settings available (a tool run): not production
            return False
    return value.strip().lower() in ("production", "prod")


def esign_providers() -> tuple:
    """The providers PIC accepts now: the real ones, plus MOCK when PIC_ENV is not production."""
    return ESIGN_PROVIDERS if is_production() else (*ESIGN_PROVIDERS, MOCK_PROVIDER)


def signature_provider(envelope_ref: Optional[str]) -> str:
    """Where a recorded signature came from, from its envelope reference: MOCK (demo), INTERNAL (signed in PIC), MIGRATED (signed
    contract loaded from the client's repository) or PROVIDER (a real e-signature provider)."""
    ref = envelope_ref or ""
    return ("MOCK" if ref.startswith(MOCK_ENVELOPE_PREFIX) else "INTERNAL" if ref.startswith("ESIGN-") else "MIGRATED" if ref.startswith("MIG-") else "PROVIDER")


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
    if provider == MOCK_PROVIDER and is_production():
        raise Problem(409, "ESIGN_MOCK_FORBIDDEN", "PIC_ESIGN_PROVIDER=MOCK is a demo provider and is refused when PIC_ENV is production: "
                      "configure a real provider (DOCUSIGN, ADOBE_SIGN, LEEGALITY or EMUDHRA) or unset PIC_ESIGN_PROVIDER", rule_ref="CLM-ESIGN")
    if not all(values.values()) or provider not in esign_providers():
        return None
    return EsignConfig(provider, values["PIC_ESIGN_URL"].rstrip("/"), values["PIC_ESIGN_API_KEY"], values["PIC_ESIGN_WEBHOOK_SECRET"])


def require_esign() -> EsignConfig:
    config = esign_config()
    if config is None:
        provider = os.environ.get("PIC_ESIGN_PROVIDER", "").strip().upper()
        if provider and provider not in esign_providers():
            detail = f"PIC_ESIGN_PROVIDER {provider} is not supported ({', '.join(esign_providers())})"
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
        if self.config.provider == MOCK_PROVIDER and not envelope_id.startswith(MOCK_ENVELOPE_PREFIX):
            raise Problem(502, "ESIGN_PROVIDER_ERROR", f"The MOCK provider must return envelope ids starting with {MOCK_ENVELOPE_PREFIX}: "
                          "this is not the mock e-signature server")
        return {"envelopeId": envelope_id[:60], "status": str(data.get("status") or "SENT").upper(), "signingUrls": data.get("signingUrls") or {}}


def _envelope_reference(tenant_code: str, contract: Contract) -> str:
    return f"PIC:{tenant_code}:{contract.number}"


def _signer_user(session: Session, party: str, contract: Contract, email: Optional[str]) -> AppUser:
    if party == "BUYER":
        user = session.execute(select(AppUser).where(AppUser.email == email)).scalar_one_or_none() if email else None
        if user is None or not user.active or "contract:sign" not in scopes_for(list(user.roles), session):
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
                              roles=list(user.roles), scopes=scopes_for(list(user.roles), session), attributes=user.attributes or {},
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
