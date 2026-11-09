"""D22 default approval decisions on the demo tenants (docs/PIC_Default_Decisions.md): invoice value bands with the CFO, and the expired-offer award
block (D5). MOCK, ILLUSTRATIVE SAMPLE.

  rule       INVOICE-APPROVAL version 2026.11-BANDS (effective 1 November 2026, the month the client approved the defaults): below 10 lakh accounts
             payable alone; 10 lakh to below 1 crore AP then the finance controller; 1 crore and above AP, the finance controller, then the CFO
             (p2p_defaults.INVOICE_APPROVAL_BANDS). Invoices approved before keep their AP-only approval.
  users      a CFO per tenant (cfo@<tenant domain>, the seed password, MFA-enrolled like the finance controllers)

  AXN, September 2027: Hosur Tooling Services (HTS004) delivers the tooling of the DC-330 / DC-331 capacity expansion. One requisition (six free-text
  non-stock lines with three quotes each, DMN-01 four-step chain), six purchase orders, receipts and supplier invoices, one per band and state:

    AP_ONLY        trim-die refurbishment, gross 7.55 lakh          AP approves                        -> APPROVED
    FC_APPROVED    machining fixture set, gross 21.83 lakh          AP, finance controller             -> APPROVED
    FC_PENDING     vacuum die-casting kit, gross 32.10 lakh         AP; waiting for the controller     -> MATCHED, task FINANCE_CONTROLLER
    CFO_PENDING    4-cavity HPDC die set DC-330, gross 1.13 crore   AP, controller; waiting for the CFO -> MATCHED, task CFO
    CFO_APPROVED   2-cavity HPDC die set DC-331, gross 1.04 crore   AP, controller, CFO                -> APPROVED
    CFO_REJECTED   pilot die set DC-335, gross 1.09 crore           AP, controller; the CFO rejects    -> EXCEPTION (APPROVAL), back with AP

  and two new-part RFQs (ALU-DIECAST, free-text requirement) whose lowest offer expired before the award:

    BLOCKED        DC-345 mounting bracket: Trichy Forge's offer ran out on 20 September; the award attempt on 27 September is refused
                   (409 BID_OFFER_EXPIRED, audited AWARD_BLOCKED_OFFER_EXPIRED); the event stays under evaluation for a new round
    OVERRIDDEN     DC-346 sensor cover: Trichy Forge's offer ran out on 18 September; the category head proposes the award with a written
                   override (Trichy Forge confirmed the price by letter), audited and emitted; approved by the ALU-DIECAST category manager, the
                   CPO and the finance controller -> AWARDED

  KAC: the rule version and the CFO only (no documents: the KAC data comes from the client's ERP extract).

Nothing of the signature case or of the other packs is touched: the documents are new and are looked up by their supplier invoice numbers and
event titles. A run that stopped half-way can be repeated: the rule, the CFO, the budget, a complete set of invoice cases and the two RFQs are
found and kept (a partial set is refused with the missing numbers).
"""
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import AppUser, AwardDecision, Budget, Invoice, PurchaseOrder, RuleSet, SourcingEvent, Supplier, Task, Tenant
from app.pic.platform import audit, clock, p2p_defaults, workflow
from app.pic.platform.auth import hash_password
from app.pic.platform.errors import Problem
from app.pic.platform.money import fmt_inr
from app.pic.seed import axion
from app.pic.seed.axion import SIGNATURE_KEY, SIGNATURE_VERSION, Scenario, at

KEY = "approval-bands"
VERSION = "1"
TITLE = ("D22 default approval decisions: invoice value bands with the CFO (every band and state) and the expired-offer award block "
         "(AXN, September 2027; KAC rule and CFO) (MOCK, ILLUSTRATIVE SAMPLE)")
TENANTS = ("AXN", "KAC")
CREATES_TENANT = False
READY = True
# Checked per tenant in apply(): AXN needs the signature case of this release, KAC its ERP client load (pack erp_client_kac).
REQUIRES: dict = {}
PREREQUISITES = {"AXN": {SIGNATURE_KEY: SIGNATURE_VERSION}, "KAC": {"erp-client-kac": "1"}}

RULE_KEY = "INVOICE-APPROVAL"
RULE_VERSION = "2026.11-BANDS"
RULE_FROM = date(2026, 11, 1)
DOMAINS = {"AXN": axion.DOMAIN, "KAC": "kaveri-auto.example"}
CFO_USERS = {"AXN": ("cfo", "Ravi Shankar Iyer"), "KAC": ("cfo", "N. Sundararajan")}
L = 100_000 * 100

SUPPLIER = "HTS004"
QUOTES = ("Sundaram Dies & Moulds Pvt Ltd", "Precision Die Works Hosur")
# key, description, net rupees, supplier invoice number, the approvals given (roles in order), the CFO's decision
CASES = [
    ("AP_ONLY", "Trim die refurbishment DC-331 cover: re-grind, re-harden and trial", 6_40_000, "HTS/TI/27-28/0611", []),
    ("FC_APPROVED", "Machining fixture set DC-330 line 3: four hydraulic fixtures", 18_50_000, "HTS/TI/27-28/0612", ["FINANCE_CONTROLLER"]),
    ("FC_PENDING", "Vacuum die-casting kit for the DC-330 die: valves and chill block", 27_20_000, "HTS/TI/27-28/0613", []),
    ("CFO_PENDING", "4-cavity HPDC die set DC-330, H13 steel with conformal cooling", 96_00_000, "HTS/TI/27-28/0614", ["FINANCE_CONTROLLER"]),
    ("CFO_APPROVED", "2-cavity HPDC die set DC-331 cover, H13 steel", 88_00_000, "HTS/TI/27-28/0615", ["FINANCE_CONTROLLER", "CFO"]),
    ("CFO_REJECTED", "Pilot HPDC die set DC-335 housing, H13 steel", 92_50_000, "HTS/TI/27-28/0616", ["FINANCE_CONTROLLER", "CFO:REJECT"]),
]
CFO_REJECTION = ("The die price is 12% above the should-cost of 82.4 lakh: hold the payment until Hosur Tooling justifies the H13 grade "
                 "and the extra cavity inserts")
APPROVER = {"FINANCE_CONTROLLER": "finance.controller", "CFO": "cfo"}

EVENTS = [
    # key, title, description, bids (supplier user, supplier, price, valid until), override reason
    ("BLOCKED", "DC-345 aluminium die-cast mounting bracket – new part RFQ", "Aluminium die-cast mounting bracket DC-345 (new part, PPAP level 3)",
     [("tf.sales", "TF001", "372", date(2027, 9, 20)), ("kd.sales", "KD002", "379", date(2027, 11, 30)),
      ("sla.sales", "SLA003", "386", date(2027, 11, 15))], None),
    ("OVERRIDDEN", "DC-346 aluminium die-cast sensor cover – new part RFQ", "Aluminium die-cast sensor cover DC-346 (new part, PPAP level 3)",
     [("tf.sales", "TF001", "214", date(2027, 9, 18)), ("kd.sales", "KD002", "221", date(2027, 11, 30))],
     "Trichy Forge confirmed in writing (letter TF/SC/2027/311 of 24 September 2027) that the 214 price holds until 31 December 2027; a new "
     "round would delay PPAP of the sensor cover by three weeks"),
]
DECLARATION = "No personal or financial interest in any bidder."


def _sep(day: int, hour: int = 10, minute: int = 0) -> datetime:
    return at(date(2027, 9, day), hour, minute)


def _tenant_id(code: str):
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == code)).scalar_one()


def _check_prerequisites(tenant_code: str) -> None:
    from app.pic.seed import datasets
    unmet = datasets._unmet(tenant_code, PREREQUISITES.get(tenant_code, {}))
    if unmet:
        raise RuntimeError(f"{KEY} for {tenant_code}: " + "; ".join(unmet))


# ---------------------------------------------------------------- rule and users (both tenants)
def activate_bands(sc: Scenario, who: str = "admin") -> str:
    """INVOICE-APPROVAL version 2026.11-BANDS with the default bands, as the tenant administrator would publish it (audited VERSION_CREATED)."""
    with sc.act(who, at(RULE_FROM, 9)) as s:
        existing = s.execute(select(RuleSet).where(RuleSet.key == RULE_KEY, RuleSet.version == RULE_VERSION)).scalar_one_or_none()
        if existing is not None:
            return existing.version
        body = dict(p2p_defaults.INVOICE_APPROVAL_BANDS)
        rule = RuleSet(tenant_id=sc.tenant_id, key=RULE_KEY, version=RULE_VERSION, effective_from=RULE_FROM, body=body,
                       description="Invoice approval chain by value band: finance controller from 10 lakh, CFO as well from 1 crore "
                                   "(client-approved default, docs/PIC_Default_Decisions.md)", created_by=s.info["user_id"])
        s.add(rule)
        s.flush()
        audit.record(s, "RULE_SET", rule.id, "VERSION_CREATED", object_ref=f"{RULE_KEY}@{RULE_VERSION}",
                     after={"key": RULE_KEY, "version": RULE_VERSION, "effective_from": RULE_FROM.isoformat(), "body": body})
    return RULE_VERSION


def add_cfo(sc: Scenario, tenant_code: str, password: str) -> str:
    local, name = CFO_USERS[tenant_code]
    with tenant_tx(sc.tenant_id) as s:
        email = sc.email(local)
        if s.execute(select(AppUser.id).where(AppUser.email == email)).first() is None:
            s.add(AppUser(tenant_id=sc.tenant_id, email=email, full_name=name, password_hash=hash_password(password), roles=["CFO"],
                          attributes={}, mfa_enrolled=True))
    return email


# ---------------------------------------------------------------- AXN invoices in every band and state
TOOLING_BUDGET = ("COST_CENTER", "4100", "SOFT", 600 * L)   # FY 2027-28 tooling budget of CC 4100 (MOCK), loaded only if missing


def _budget(sc: Scenario) -> Optional[str]:
    """The FY 2027-28 controlling budget of CC 4100 the requisitions are checked against, as the ERP would load it (check-then-insert, audited)."""
    obj_type, code, control, amount = TOOLING_BUDGET
    with sc.act("admin", _sep(1, 8)) as s:
        if s.execute(select(Budget.id).where(Budget.cost_object_type == obj_type, Budget.cost_object_code == code,
                                             Budget.fiscal_year == "2027-28")).first():
            return None
        budget = Budget(tenant_id=sc.tenant_id, cost_object_type=obj_type, cost_object_code=code, fiscal_year="2027-28", control=control,
                        amount_minor=amount, committed_minor=0, consumed_minor=0)
        s.add(budget)
        s.flush()
        audit.record(s, "MIGRATION", budget.id, "INITIAL_LOAD", object_ref=f"budget {obj_type}:{code} 2027-28",
                     after={"budget": f"{obj_type}:{code}", "fiscalYear": "2027-28", "amountMinor": amount, "control": control}, actor="migration")
        return f"{obj_type}:{code}"


def _requisition(sc: Scenario) -> str:
    lines = []
    for i, (key, description, net, number, _) in enumerate(CASES):
        lines.append({"item_type": "FREE_TEXT", "purchase_type": "NON_STOCK", "description": description, "material_group": "41-TOOLING",
                      "category": "TOOLING-SERVICES", "qty": "1", "uom": "EA", "price_est_minor": net * 100,
                      "account_assignment_type": "COST_CENTER", "account_assignment_code": "4100", "need_date": "2027-09-15",
                      "quotes": [{"supplier": SUPPLIER, "reference": f"HTS/Q/27-28/{480 + i:04d}", "date": "2027-08-20"},
                                 {"supplier": QUOTES[0], "reference": f"SDM/QTN/2027/{311 + i}", "date": "2027-08-23"},
                                 {"supplier": QUOTES[1], "reference": f"PDW-Q-{7710 + i}", "date": "2027-08-24"}]})
    from app.pic.services import requisition
    with sc.act("requester", _sep(1, 10)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="TOOLING_UPGRADE",
                                purpose_text="DC-330 / DC-331 capacity expansion tooling (capex plan FY 2027-28, tooling budget CC 4100)", plant="P100",
                                lines=lines)
        requisition.submit(s, pr, justification="Tooling of the approved DC-330 / DC-331 capacity expansion; quotes from three tool rooms each")
        pr_id, pr_no = pr.id, pr.number
    sc.approve_all(pr_id, _sep(1, 15), "Tooling of the approved capacity expansion; three quotes per line")
    return pr_no


def _orders(sc: Scenario, pr_no: str) -> dict:
    from app.pic.services import order, receiving
    numbers = {}
    for i, (key, description, net, number, _) in enumerate(CASES):
        with sc.act("buyer", _sep(2, 10, i)) as s:
            po = order.create_from_requisition(s, requisition=pr_no, lines=[10 * (i + 1)], supplier_code=SUPPLIER, unit_price_minor=net * 100)[0]
            numbers[key] = (po.id, po.number)
        sc.approve_all(numbers[key][0], _sep(2, 14), "Price as quoted; lowest of three tool rooms")
        with sc.act("hts.service", _sep(3, 11, i)) as s:
            po = s.get(PurchaseOrder, numbers[key][0])
            if po.status != "TRANSMITTED":
                raise RuntimeError(f"{po.number} is {po.status} after its approvals, not TRANSMITTED")
            order.confirm(s, po, "CONFIRMED", note="Tooling delivered by 15 September 2027 with the trial-shot report")
        with sc.act("receiver", _sep(13 + i % 5, 11)) as s:
            receiving.post_gr(s, s.get(PurchaseOrder, numbers[key][0]), lines=[{"line": 10, "qty": "1"}],
                              delivery_note=f"HTS/DC/27-28/{2210 + i}")
    return numbers


def _complete(sc: Scenario, who: str, when: datetime, invoice_id, role: str, decision: str, comment: str) -> None:
    with sc.act(who, when) as s:
        task = s.execute(select(Task).where(Task.object_id == invoice_id, Task.kind == "INVOICE_APPROVAL", Task.status == "OPEN",
                                            Task.candidate_role == role)).scalar_one()
        workflow.complete(s, task.id, decision, comment)


def _invoices(sc: Scenario, orders: dict) -> dict:
    from app.pic.services import payables
    out = {}
    for i, (key, description, net, number, steps) in enumerate(CASES):
        with sc.act("hts.service", _sep(20, 10, i)) as s:
            invoice = payables.capture(s, supplier=SUPPLIER, supplier_invoice_no=number, invoice_date=date(2027, 9, 18), channel="PORTAL",
                                       lines=[{"po": orders[key][1], "po_line": 10, "qty": "1", "unit_price": f"{net}.00", "gst_rate": "18"}])
            invoice_id = invoice.id
        with sc.act("ap.clerk", _sep(21, 11, i)) as s:
            payables.approve(s, s.get(Invoice, invoice_id))
        day = 22
        for step in steps:
            role, _, decision = step.partition(":")
            decision = decision or "APPROVE"
            comment = (CFO_REJECTION if decision == "REJECT" else
                       "Checked against the PO, the receipt and the tooling budget" if role == "FINANCE_CONTROLLER" else
                       "Approved: tooling of the approved capacity expansion")
            _complete(sc, APPROVER[role], _sep(day, 12, i), invoice_id, role, decision, comment)
            day += 1
        with tenant_tx(sc.tenant_id) as s:
            out[key] = _invoice_row(s, s.get(Invoice, invoice_id))
    return out


def _invoice_row(s, invoice: Invoice) -> dict:
    from app.pic.services import payables
    state = payables.approval_state(s, invoice)
    return {"invoice": invoice.number, "supplierInvoice": invoice.supplier_invoice_no, "grossMinor": int(invoice.gross_minor), "status": invoice.status,
            "approval": state["status"], "chain": state["requiredChain"], "waitingFor": [st["role"] for st in state["steps"] if st["status"] == "OPEN"]}


def _loaded_invoices(sc: Scenario) -> Optional[dict]:
    """The case invoices when an earlier run of the pack (stopped later, e.g. at the events) already created them; None when there are none.
    A partial set is an error: the documents of one case are created together, so a gap means the tenant needs a look, not a second load."""
    with tenant_tx(sc.tenant_id) as s:
        supplier_id = s.execute(select(Supplier.id).where(Supplier.code == SUPPLIER)).scalar_one()
        found = {inv.supplier_invoice_no: inv for inv in s.execute(select(Invoice).where(
            Invoice.supplier_id == supplier_id, Invoice.supplier_invoice_no.in_([c[3] for c in CASES]))).scalars()}
        if not found:
            return None
        missing = [c[3] for c in CASES if c[3] not in found]
        if missing:
            raise RuntimeError(f"{KEY}: invoices {', '.join(missing)} are missing although {', '.join(sorted(found))} exist (partial earlier load)")
        return {key: _invoice_row(s, found[number]) for key, _, _, number, _ in CASES}


# ---------------------------------------------------------------- AXN sourcing events with an expired offer
def _event_requisition(sc: Scenario) -> str:
    from app.pic.services import requisition
    lines = [{"item_type": "FREE_TEXT", "purchase_type": "NON_STOCK", "description": description, "material_group": "ALU-DIECAST",
              "category": "ALU-DIECAST", "qty": "500", "uom": "EA", "price_est_minor": int(bids[0][2]) * 100,
              "account_assignment_type": "COST_CENTER", "account_assignment_code": "4100", "need_date": "2027-12-15",
              "quotes": [{"supplier": "TF001", "reference": f"TF/BQ/2027/{88 + i}", "date": "2027-08-25"}]}
             for i, (_, _, description, bids, _) in enumerate(EVENTS)]
    with sc.act("requester", _sep(1, 11)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="NEW_PART_LAUNCH", purpose_text="New-part RFQs DC-345 / DC-346 (PPAP samples)",
                                plant="P100", lines=lines)
        requisition.submit(s, pr, justification="PPAP samples of the DC-345 / DC-346 launch, funded from the new-part launch allowance")
        pr_id, pr_no = pr.id, pr.number
    sc.approve_all(pr_id, _sep(1, 16), "New-part samples within the launch budget")
    return pr_no


def _loaded_events(sc: Scenario) -> Optional[dict]:
    """The two RFQs when an earlier run of the pack already created them (see _loaded_invoices); None when there are none."""
    with tenant_tx(sc.tenant_id) as s:
        found = {e.title: e for e in s.execute(select(SourcingEvent).where(SourcingEvent.title.in_([e[1] for e in EVENTS]))).scalars()}
        if not found:
            return None
        if len(found) != len(EVENTS):
            raise RuntimeError(f"{KEY}: only {', '.join(sorted(found))} of the RFQs exist (partial earlier load)")
        out = {}
        for key, title, _, bids, override in EVENTS:
            event = found[title]
            out[key] = {"event": event.number, "title": title, "status": event.status}
            decision = s.execute(select(AwardDecision).where(AwardDecision.event_id == event.id).order_by(AwardDecision.created_at.desc())).scalars().first()
            if override is None:
                out[key].update(blocked="BID_OFFER_EXPIRED", expiredBids=[bids[0][1]])   # the lowest bid, whose offer ran out first
            elif decision is not None:
                out[key].update(decision=decision.status, override=next((e["override"]["reason"] for e in decision.exceptions or []
                                                                         if e.get("code") == "BID_OFFER_EXPIRED"), None))
        return out


def _events(sc: Scenario, pr_no: str) -> dict:
    from app.pic.services import sourcing
    out = {}
    for i, (key, title, _, bids, override) in enumerate(EVENTS):
        with sc.act("category.head", _sep(2, 11, i)) as s:
            event = sourcing.create_event(
                s, type="RFQ", title=title, category="ALU-DIECAST", lines=[{"requisition": pr_no, "line": 10 * (i + 1), "annual_qty": "24000",
                                                                            "monthly_qty": "2000"}],
                criteria=[{"code": "PRICE_TCO", "name": "Price / TCO", "weight": 100}],
                invitees=[{"supplier": code} for _, code, _, _ in bids],
                close_at=_sep(8, 17), baseline_method="BUDGET", baseline_price_minor=int(bids[0][2]) * 100 + 1500,
                constraints={"max_suppliers": 2, "max_share": "1", "min_share": "0"})
            sourcing.publish(s, event)
            event_id, event_no = event.id, event.number
        for j, (who, _, price, until) in enumerate(bids):
            with sc.act(who, _sep(3 + j, 15)) as s:
                sourcing.submit_bid(s, s.get(SourcingEvent, event_id), s.get(Supplier, s.info["principal"].supplier_id),
                                    [{"line": 10, "unit_price": price, "freight": "3.00", "packaging": "1.00", "payment_terms_days": 60,
                                      "lead_time_days": 21, "capacity_per_month": "4000"}], valid_until=until)
        with sc.act("category.head", _sep(8, 17, 10)) as s:
            event = s.get(SourcingEvent, event_id)
            sourcing.close(s, event)
            if event.unsealed_at is None:
                sourcing.open_bids(s, event)
        with sc.act("category.head", _sep(9, 11)) as s:
            built = sourcing.build_scenarios(s, s.get(SourcingEvent, event_id))
            scenario_id = next(x for x in built if x["kind"] == "LOWEST_COST" and x["feasible"])["id"]
        out[key] = {"event": event_no, "title": title}
        blocked: Optional[Problem] = None
        try:
            with sc.act("category.head", _sep(27, 11)) as s:
                sourcing.propose_award(s, s.get(SourcingEvent, event_id), uuid.UUID(scenario_id), None, DECLARATION, override)
        except Problem as exc:
            blocked = exc
        if override is None:
            if blocked is None or blocked.code != "BID_OFFER_EXPIRED":
                raise RuntimeError(f"{event_no}: the award on an expired offer was not blocked ({blocked})")
            out[key].update(status="UNDER_EVALUATION", blocked=blocked.code, expiredBids=[b["supplier"] for b in blocked.extra["expiredBids"]])
            continue
        if blocked is not None:
            raise blocked
        with sc.act("category.manager", _sep(28, 10)) as s:
            task = s.execute(select(Task).where(Task.object_id == event_id, Task.kind == "AWARD_APPROVAL", Task.status == "OPEN")).scalar_one()
            workflow.complete(s, task.id, "APPROVE", "Written price confirmation of Trichy Forge on file; PPAP timing protected")
        sc.approve_all(event_id, _sep(28, 15), "Award on the confirmed price approved")
        with tenant_tx(sc.tenant_id) as s:
            event = s.get(SourcingEvent, event_id)
            decision = s.execute(select(AwardDecision).where(AwardDecision.event_id == event_id).order_by(AwardDecision.created_at.desc())).scalars().first()
            out[key].update(status=event.status, decision=decision.status,
                            override=next(e["override"]["reason"] for e in decision.exceptions if e["code"] == "BID_OFFER_EXPIRED"))
    return out


def _axn(sc: Scenario, password: str) -> dict:
    from app.pic.seed.datasets.purchase_types import relay
    notes, counts = [], {}
    budget = _budget(sc)
    if budget:
        notes.append(f"FY 2027-28 budget {budget} loaded (MOCK, 6 crore, soft control)")
    invoices = _loaded_invoices(sc)
    if invoices is None:
        pr_no = _requisition(sc)
        invoices = _invoices(sc, _orders(sc, pr_no))
    else:
        notes.append("invoice cases found from an earlier run of the pack: kept")
    for key, row in invoices.items():
        ref = row["invoice"] if row["invoice"] == row["supplierInvoice"] else f"{row['invoice']} ({row['supplierInvoice']})"
        notes.append(f"{key}: {ref} gross {fmt_inr(row['grossMinor'])} -> {row['status']}"
                     + (f", waiting for {', '.join(row['waitingFor'])}" if row["waitingFor"] else "")
                     + (f" (chain AP → {' → '.join(row['chain'])})" if row["chain"] else " (AP only)"))
    events = _loaded_events(sc)
    if events is None:
        events = _events(sc, _event_requisition(sc))
    for key, row in events.items():
        notes.append(f"{key}: {row['event']} {row['title']} -> {row['status']}"
                     + (f" ({row['blocked']}: {', '.join(row['expiredBids'])})" if row.get("blocked") else "")
                     + (f" (override: {row['override'][:60]}…)" if row.get("override") else ""))
    relay(sc, _sep(28, 16))
    clock.set_pinned(None)
    counts.update({"requisitions": 2, "purchaseOrders": len(invoices), "invoices": len(invoices), "sourcingEvents": len(events)})
    return {"notes": notes, "counts": counts, "invoices": invoices, "events": events}


def apply(tenant_code: str, password: str) -> dict:
    if tenant_code not in TENANTS:
        raise ValueError(f"{KEY} has no data for tenant {tenant_code}")
    _check_prerequisites(tenant_code)
    sc = Scenario(_tenant_id(tenant_code), tenant_code, DOMAINS[tenant_code])
    version = activate_bands(sc)
    cfo = add_cfo(sc, tenant_code, password)
    summary = {"notes": [f"{RULE_KEY}@{version} effective {RULE_FROM.isoformat()}: FC from 10 lakh, FC + CFO from 1 crore", f"CFO user {cfo}"],
               "counts": {"ruleVersions": 1, "users": 1}, "rule": f"{RULE_KEY}@{version}", "cfo": cfo}
    if tenant_code == "AXN":
        axn = _axn(sc, password)
        summary["notes"] += axn["notes"]
        summary["counts"].update(axn["counts"])
        summary.update({k: v for k, v in axn.items() if k not in ("notes", "counts")})
    clock.set_pinned(None)
    return summary
