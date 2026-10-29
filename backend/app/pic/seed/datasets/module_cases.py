"""D1 operations-module cases for Axion (May 2027), run through the domain services.

Every case uses pack-specific masters (materials DC-340/345/348/350/352, seal kits SK-345/348, suppliers APC007 and the invited
Krishnagiri packaging supplier) so source determination, MRP and stock of the signature-case materials are untouched.

Contracts (M07)
  C1  TF001 DC-340 quantity contract: VARIATION below ₹1 Cr (₹186 → ₹182, approved by the second contract manager), then a
      VARIATION above ₹1 Cr (+1,00,000 pcs, LEGAL → FINANCE_CONTROLLER). E-signature provider not configured → internal signatures.
  C2  KD002 DC-345 interim agreement to 15 Sep 2027: renewal notice (120 days) → EXPIRING → renewal approved → EXTENSION draft
      → submitted → LEGAL → FINANCE_CONTROLLER → active to 15 Sep 2028.
  C3  SLA003 DC-348 quantity contract with an open touchless PO: TERMINATION for convenience (90 days' notice, LEGAL → CPO),
      applied by its own timer on 31 Aug 2027 → contract TERMINATED, open PO flagged with a buyer review task.
  C4  HTS004 die-cell maintenance rate (value) contract: EXTENSION to 31 Mar 2028, approved by the second contract manager.
Sourcing (M05)
  DC-350 annual requirement: Sourcing Strategy recommendation (RFQ) rejected with feedback; reverse auction with a clarification
  board (two questions answered, one withdrawn, one buyer notice), eight live bids, two soft-close extensions, lowest-cost award
  → scheduling-agreement draft from the award consumer.
Order to pay (M08–M10)
  APC007 DC-352 PO: approval → transmission PORTAL + EDI (queued, no gateway) + e-mail (queued, no SMTP); schedule split in place;
  inbound EDI ORDRSP confirms; post-confirmation schedule change → version 2 + ORDCHG → re-confirmed; inbound EDI DESADV → ASN
  with e-way bill; GR → e-invoice (IRN, local checks) waits for inspection (4-way) → usage decision → re-match → post; second
  delivery by portal ASN (e-way validity from distance), 10 rejected; a credit note after posting goes to the ERP as a credit memo
  (KG): the reconciliation run before the connector posted it shows an AMOUNT_MISMATCH item, resolved, next run clean; month-end
  payment run → pain.001 (rejected by the bank) → NEFT bulk file → sent → acknowledged.
Masters & requisitions (M03/M04/M01)
  Invitation → self-registration → onboarding of Krishnagiri Returnable Packaging; MDM-04 TAX change (state move, approved),
  ADDRESS change of APC007 (rejected), CONTACT change by APC007's portal user (approved); HTS004 built-in cXML punch-out →
  requisition → approved; RUBBER-SEALS category plan approved with a HARD category-budget rule: warning at 86% and a hard block.
Platform (M13)
  ERP planned-order import (2 accepted, 5 rejected rows) and a firmed import; notifications from all of the above (some read);
  two agent recommendations decided with feedback.
"""
import html
import re
import secrets
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import (
    AppUser, Asn, BankChangeRequest, Budget, CategoryPlan, Contract, ContractAmendment, InspectionLot, Invoice,
    Material, Notification, PlannedOrder, PurchaseOrder, Qualification, Recommendation, RuleSet, SourcingEvent,
    Supplier, SupplierMasterChange, Task, Tenant, Timer,
)
from app.pic.platform import audit, clock, workflow
from app.pic.platform.auth import hash_password
from app.pic.platform.errors import Problem
from app.pic.seed import reference
from app.pic.seed.axion import ROLE_USER, Scenario, at, email
from app.pic.seed.datasets._tenant_kit import AXN_BUDGETS_2027_28

KEY = "axn-module-cases"
VERSION = "1"
TITLE = "D1 operations-module cases: amendments, auction, EDI, payment files, MDM-04, punch-out, … (May 2027)"
TENANTS = ('AXN',)
CREATES_TENANT = False
READY = True
from app.pic.seed.axion import SIGNATURE_KEY, SIGNATURE_VERSION  # noqa: E402
REQUIRES = {SIGNATURE_KEY: SIGNATURE_VERSION}  # the current signature case (users, documents, identifiers)

D = date
MAY = 2027, 5

# ---------------------------------------------------------------- pack masters (ERP initial load, §12.4)
MATERIALS = [
    # number, description, category/group, hsn, gst, quality managed, standard price (paise)
    ("DC-340", "Aluminium die-cast motor end shield DC-340", "ALU-DIECAST", "87089900", 18, True, 18_600),
    ("DC-345", "Aluminium die-cast inverter housing DC-345", "ALU-DIECAST", "87089900", 18, True, 52_000),
    ("DC-348", "Aluminium die-cast mounting bracket DC-348", "ALU-DIECAST", "87089900", 18, True, 14_200),
    ("DC-350", "Aluminium die-cast sensor cover DC-350", "ALU-DIECAST", "87089900", 18, True, 9_600),
    ("DC-352", "Aluminium die-cast coolant pump housing DC-352", "ALU-DIECAST", "87089900", 18, True, 26_500),
    ("SK-345", "Seal kit DC-345 inverter housing (FKM O-ring set + EPDM gasket)", "RUBBER-SEALS", "401693", 18, False, 14_500),
    ("SK-348", "Seal kit DC-348 bracket damper (NBR grommets)", "RUBBER-SEALS", "401693", 18, False, 12_800),
]
APC = dict(code="APC007", name="Ambattur Pressure Castings Pvt Ltd", pan="AAHCA3318M", user="apc.sales",
           address={"line1": "Plot B-27, SIDCO Industrial Estate", "line2": "Ambattur", "city": "Chennai", "state_code": "33",
                    "pin": "600058"},
           bank=("145002000031876", "IOBA0001450"), edi="APC007EDI", orders="orders@ambattur-castings.example")
KRP = dict(name="Krishnagiri Returnable Packaging Pvt Ltd", pan="AAICK7742P", email="onboarding@krishnagiri-packaging.example",
           address={"line1": "Plot 61, SIPCOT Industrial Complex Phase II", "city": "Hosur", "state_code": "33", "pin": "635109"},
           new_address={"line1": "No. 214, KIADB Industrial Area, Attibele", "line2": "Anekal Taluk", "city": "Bengaluru",
                        "state_code": "29", "pin": "562107"},
           bank=("2871201004433", "CNRB0002871"))
SEALS_RULE = "2027.1-SEALS"


def gstin(state: str, pan: str) -> str:
    from app.pic.services.master_changes import gstin_check_char
    base = f"{state}{pan}1Z"
    return base + gstin_check_char(base)


def _role_user() -> dict:
    return {**ROLE_USER, "CONTRACT_MANAGER": ["contract.manager", "contract.manager2"]}


def _fire(sc: Scenario, kind: str, object_id: uuid.UUID, when: datetime) -> int:
    """Fire this pack's own timers one by one (never the tenant's whole due list)."""
    fired = 0
    with sc.act("contract.manager", when) as s:
        for timer in s.execute(select(Timer).where(Timer.kind == kind, Timer.object_id == object_id, Timer.fired_at.is_(None),
                                                   Timer.due_at <= clock.now())).scalars().all():
            timer.fired_at = clock.now()
            workflow._timer_handlers[kind](s, timer)
            fired += 1
    return fired


def _tasks(sc: Scenario, object_id: uuid.UUID, kind: str) -> list[uuid.UUID]:
    with tenant_tx(sc.tenant_id) as s:
        return list(s.execute(select(Task.id).where(Task.object_id == object_id, Task.kind == kind, Task.status == "OPEN")
                              .order_by(Task.sequence)).scalars())


def _complete(sc: Scenario, who: str, when: datetime, task_id: uuid.UUID, decision: str, comment: str) -> None:
    with sc.act(who, when) as s:
        workflow.complete(s, task_id, decision, comment)


def _decide_group(sc: Scenario, object_id: uuid.UUID, kind: str, when: datetime, decisions: dict) -> None:
    """Complete the open tasks of an object by role: decisions = {role: (user, decision, comment)}."""
    for _ in range(4):
        with tenant_tx(sc.tenant_id) as s:
            open_ = [(t.id, t.candidate_role) for t in s.execute(select(Task).where(Task.object_id == object_id, Task.kind == kind,
                                                                                   Task.status == "OPEN")).scalars()]
        if not open_:
            return
        for task_id, role in open_:
            if role not in decisions:
                continue
            who, decision, comment = decisions[role]
            with sc.act(who, when) as s:
                if s.get(Task, task_id).status == "OPEN":  # a rejection cancels the parallel task
                    workflow.complete(s, task_id, decision, comment)


# ---------------------------------------------------------------- 0. masters and reference rows
def _masters(sc: Scenario, password: str) -> None:
    clock.set_pinned(at(D(*MAY, 3), 8))
    with tenant_tx(sc.tenant_id) as s:
        if s.execute(select(Supplier.id).where(Supplier.code == APC["code"])).first():
            raise RuntimeError(f"{KEY}: supplier {APC['code']} already exists; the pack was partially loaded – restore the database first")
        have = set(s.execute(select(Material.number)).scalars())
        loaded = []
        for number, description, category, hsn, gst, qm, price in MATERIALS:
            if number in have:
                continue
            s.add(Material(tenant_id=sc.tenant_id, number=number, description=description, type="STOCK", material_group=category,
                           category=category, base_uom="EA", valuation_class="3000" if category == "ALU-DIECAST" else "3100",
                           hsn_code=hsn, gst_rate=Decimal(gst), mpn=f"AXN-{number}", attributes={"alloy": "ADC12", "process": "HPDC"}
                           if category == "ALU-DIECAST" else {"elastomer": "FKM/EPDM"}, mrp_type="ND", planned_delivery_days=10,
                           gr_processing_days=1, quality_managed=qm, standard_price_minor=price, status="ACTIVE", erp_synced=True))
            loaded.append(number)
        # FY 2027-28 controlling budgets (the ERP loads one per fiscal year); created only if missing.
        budgets = []
        for type_, code, control, lakh in AXN_BUDGETS_2027_28:
            if not s.execute(select(Budget.id).where(Budget.cost_object_type == type_, Budget.cost_object_code == code,
                                                     Budget.fiscal_year == "2027-28")).first():
                s.add(Budget(tenant_id=sc.tenant_id, cost_object_type=type_, cost_object_code=code, fiscal_year="2027-28", control=control,
                             amount_minor=lakh * reference.L, committed_minor=0, consumed_minor=0))
                budgets.append(f"{type_}:{code}")
        audit.record(s, "MIGRATION", uuid.uuid5(uuid.NAMESPACE_URL, "axn-module-cases-masters"), "INITIAL_LOAD", object_ref="module-cases",
                     after={"materials": loaded, "budgets2027_28": budgets}, actor="migration")
        from app.pic.platform import rules
        # Debtor bank account for payment files (company code 1000), unless the tenant already configured one.
        if not rules.resolve(s, "PAYMENT-FILE", company_code="1000").body.get("debtorName"):
            s.add(RuleSet(tenant_id=sc.tenant_id, key="PAYMENT-FILE", version="2027.1-CC1000", company_code="1000", effective_from=D(2027, 4, 1),
                          body={"format": "ISO20022_PAIN001", "debtorName": "Axion Mobility Systems Pvt Ltd",
                                "debtorAccountRef": "917020012345678", "debtorIfsc": "UTIB0000123"},
                          description="Axion current account, Axis Bank Hosur (payment files for company code 1000)"))
        if not s.execute(select(RuleSet.id).where(RuleSet.key == "CATEGORY-BUDGET", RuleSet.version == SEALS_RULE)).first():
            s.add(RuleSet(tenant_id=sc.tenant_id, key="CATEGORY-BUDGET", version=SEALS_RULE, category="RUBBER-SEALS",
                          effective_from=D(2027, 5, 1), body={"mode": "HARD", "warnAtPct": 85},
                          description="RUBBER-SEALS is a bottleneck category: hard stop at the approved plan budget, warning from 85%"))
        s.add(AppUser(tenant_id=sc.tenant_id, email=email(APC["user"]), full_name=f"{APC['name']} – sales",
                      password_hash=hash_password(password), roles=["SUPPLIER_USER"], attributes={}, mfa_enrolled=True))
    sc.note(f"Masters: {', '.join(m[0] for m in MATERIALS)}; FY 2027-28 budget CC 4100; PAYMENT-FILE debtor; CATEGORY-BUDGET@{SEALS_RULE}")


def _ids(sc: Scenario) -> dict:
    with tenant_tx(sc.tenant_id) as s:
        out = {m.number: m.id for m in s.execute(select(Material)).scalars()}
        out.update({x.code: x.id for x in s.execute(select(Supplier)).scalars()})
        return out


# ---------------------------------------------------------------- 1. suppliers: APC007 (onboarded) and the invited packaging supplier
def _onboard_apc(sc: Scenario, ctx: dict):
    from app.pic.services import supplier as svc
    yield at(D(*MAY, 3), 10)
    with sc.act("supplier.manager", at(D(*MAY, 3), 10)) as s:
        sup = svc.register(s, code=APC["code"], legal_name=APC["name"], gstin=gstin("33", APC["pan"]), pan=APC["pan"], state_code="33",
                           contact_email="sales@ambattur-castings.example", categories=["ALU-DIECAST"], payment_terms="N15",
                           incoterms="FCA Chennai", segment="STRATEGIC", address=dict(APC["address"]))
        # Order channel agreed at onboarding: portal + EDIFACT (partner id) + e-mail (no service exists to maintain it).
        sup.order_channel = {"channels": ["PORTAL", "EDI", "EMAIL"], "ediId": APC["edi"], "email": APC["orders"]}
        audit.record(s, "SUPPLIER", sup.id, "ORDER_CHANNEL_SET", object_ref=sup.code, after=sup.order_channel)
        s.execute(select(AppUser).where(AppUser.email == email(APC["user"]))).scalar_one().supplier_id = sup.id
        sup_id = sup.id
    yield at(D(*MAY, 3), 15)
    with sc.act(APC["user"], at(D(*MAY, 3), 15)) as s:
        result = svc.submit_profile(s, s.get(Supplier, sup_id), bank_account=APC["bank"][0], ifsc=APC["bank"][1], holder_name=APC["name"],
                                    certificates=[{"type": "IATF16949", "number": "IATF-APC007-0512", "issued_on": "2026-06-15",
                                                   "expires_on": "2029-06-14", "mandatory_for": ["ALU-DIECAST"]},
                                                  {"type": "ISO14001", "number": "EMS-APC007-0388", "issued_on": "2025-09-01",
                                                   "expires_on": "2028-08-31", "mandatory_for": ["ALU-DIECAST"]}])
        change_no = result["bankChange"]
    yield at(D(*MAY, 4), 11)
    with sc.act("supplier.manager", at(D(*MAY, 4), 11)) as s:
        change = s.execute(select(BankChangeRequest).where(BankChangeRequest.number == change_no)).scalar_one()
        svc.callback_verify(s, change, "Called Ambattur Pressure Castings on the registered landline; IOB Ambattur account confirmed")
        change_id = change.id
    yield at(D(*MAY, 4), 15)
    sc.approve_all(change_id, at(D(*MAY, 4), 15), "Cancelled cheque and bank letter verified")
    yield at(D(*MAY, 5), 10)
    with sc.act("supplier.manager", at(D(*MAY, 5), 10)) as s:
        svc.verify_certificates(s, s.get(Supplier, sup_id), "IATF 16949 and ISO 14001 checked against the IATF database and the CB register")
        q = svc.start_qualification(s, s.get(Supplier, sup_id), "ALU-DIECAST")
        svc.record_assessment(s, q, questionnaire={"capacity": "2 x 800 t HPDC cells", "ppap": "level 3"}, questionnaire_score=Decimal(82),
                              audit_score=Decimal(81), sample_approval="PPAP_APPROVED")
        svc.decide_qualification(s, q, "QUALIFIED", "Process audit 81/100; IATF 16949 and ISO 14001 verified; PPAP level 3 approved")
    sc.note("APC007 Ambattur Pressure Castings: registered, bank dual-approved, QUALIFIED for ALU-DIECAST; order channel portal+EDI+e-mail")


def _invite_krp(sc: Scenario, password: str, ctx: dict):
    from app.pic.services import invitations
    from app.pic.services import supplier as svc
    yield at(D(*MAY, 3), 11)
    with sc.act("supplier.manager", at(D(*MAY, 3), 11)) as s:
        invitation = invitations.create(s, email=KRP["email"], legal_name=KRP["name"], categories=["PACKAGING"])
        token = invitation["token"]
    portal_password = password if not invitations.password_errors(password, KRP["email"], KRP["name"]) else \
        f"Krg-{secrets.token_urlsafe(12)}-7a"
    yield at(D(*MAY, 4), 9, 30)
    clock.set_pinned(at(D(*MAY, 4), 9, 30))
    with tenant_tx(sc.tenant_id) as s:
        tenant = s.get(Tenant, sc.tenant_id)
        inv = invitations.find(s, token, lock=True)
        reg = invitations.register(s, inv, tenant, legal_name=KRP["name"], gstin=gstin("33", KRP["pan"]), pan=KRP["pan"], state_code="33",
                                   address=dict(KRP["address"]), contact_name="Senthil Kumar R", email=KRP["email"], password=portal_password,
                                   phone="+91 4344 276512")
    code = reg["supplier"]
    yield at(D(*MAY, 4), 11)
    with sc.act(KRP["email"], at(D(*MAY, 4), 11)) as s:
        sup = s.execute(select(Supplier).where(Supplier.code == code)).scalar_one()
        result = svc.submit_profile(s, sup, bank_account=KRP["bank"][0], ifsc=KRP["bank"][1], holder_name=KRP["name"],
                                    certificates=[{"type": "ISO9001", "number": "QMS-KRP-2211", "issued_on": "2025-11-20",
                                                   "expires_on": "2028-11-19"}])
        sup_id = sup.id
    yield at(D(*MAY, 5), 11)
    with sc.act("supplier.manager", at(D(*MAY, 5), 11)) as s:
        change = s.execute(select(BankChangeRequest).where(BankChangeRequest.number == result["bankChange"])).scalar_one()
        svc.callback_verify(s, change, "Call-back to the registered Hosur office; Canara Bank account holder confirmed")
        change_id = change.id
    yield at(D(*MAY, 5), 16)
    sc.approve_all(change_id, at(D(*MAY, 5), 16), "Bank letter verified")
    yield at(D(*MAY, 6), 10)
    with sc.act("supplier.manager", at(D(*MAY, 6), 10)) as s:
        q = s.execute(select(Qualification).where(Qualification.supplier_id == sup_id, Qualification.status == "OPEN")).scalar_one()
        svc.record_assessment(s, q, questionnaire={"crates": "HDPE returnable, 600x400", "capacity": "18,000 crates/month"},
                              questionnaire_score=Decimal(78), audit_score=Decimal(80))
        svc.decide_qualification(s, q, "QUALIFIED", "Site audit 80/100; ISO 9001 verified")
    sc.relay(at(D(*MAY, 6), 11))
    sc.note(f"Invitation → self-registration {code} {KRP['name']} (screening {reg['screening']}) → bank dual-approved → QUALIFIED for PACKAGING")
    ctx["krp"] = {"code": code, "id": sup_id}


# ---------------------------------------------------------------- 2. contracts and amendments
def _contract(sc: Scenario, *, supplier: str, signer: str, type_: str, title: str, valid_from: date, valid_to: date, terms: str,
              incoterms, line: dict, when: datetime, tolerances: dict) -> tuple[uuid.UUID, str]:
    from app.pic.services import contract as contract_svc
    with sc.act("contract.manager", when) as s:
        sup = s.execute(select(Supplier).where(Supplier.code == supplier)).scalar_one()
        contract = contract_svc.create_draft(s, type=type_, title=title, supplier_id=sup.id, company_code="1000", valid_from=valid_from,
                                             valid_to=valid_to, payment_terms=terms, incoterms=incoterms, lines=[line],
                                             owner_id=s.info["principal"].user_id, tolerances=tolerances)
        contract_svc.ai_review(s, contract)
        contract_svc.submit(s, contract)
        contract_id, number = contract.id, contract.number
    sc.approve_all(contract_id, when + timedelta(hours=4), "Clauses standard; value and validity approved")
    return contract_id, number


def _sign_activate(sc: Scenario, contract_id: uuid.UUID, signer: str, when: datetime) -> None:
    from app.pic.services import contract as contract_svc
    with sc.act("contract.manager", when) as s:
        contract_svc.sign(s, s.get(Contract, contract_id), "BUYER", "Ganesh Murthy, Contract Manager")
    with sc.act(signer, when + timedelta(hours=2)) as s:
        contract_svc.sign(s, s.get(Contract, contract_id), "SUPPLIER", "Authorised signatory")
    with sc.act("contract.manager", when + timedelta(hours=3)) as s:
        contract_svc.activate(s, s.get(Contract, contract_id))


def _amend(sc: Scenario, contract_id: uuid.UUID, when: datetime, kind: str, changes: dict, reason: str, effective: date) -> tuple[uuid.UUID, str, dict]:
    from app.pic.services import amendments
    with sc.act("contract.manager", when) as s:
        a = amendments.create(s, s.get(Contract, contract_id), kind=kind, changes=changes, reason=reason, effective_from=effective)
        return a.id, a.number, dict(a.changes)


def _contracts(sc: Scenario, ctx: dict):
    from app.pic.services import contract as contract_svc
    yield at(D(*MAY, 3), 11)
    ids = _ids(sc)
    out = ctx.setdefault("contracts", {})
    tol = {"over_pct": "2", "under_pct": "5", "price_pct": "0"}
    c1, c1_no = _contract(sc, supplier="TF001", signer="tf.sales", type_="QUANTITY_CONTRACT", title="DC-340 motor end shields FY27-28",
                          valid_from=D(2027, 5, 1), valid_to=D(2028, 4, 30), terms="N60", incoterms="FCA Trichy", when=at(D(*MAY, 3), 11),
                          line={"material_id": ids["DC-340"], "description": "Aluminium die-cast motor end shield DC-340", "plant": "P100",
                                "uom": "EA", "target_qty": "300000", "unit_price_minor": 18_600}, tolerances=tol)
    c2, c2_no = _contract(sc, supplier="KD002", signer="kd.sales", type_="QUANTITY_CONTRACT",
                          title="DC-345 inverter housings – interim agreement", valid_from=D(2027, 5, 1), valid_to=D(2027, 9, 15),
                          terms="N45", incoterms="FCA Coimbatore", when=at(D(*MAY, 3), 12), tolerances=tol,
                          line={"material_id": ids["DC-345"], "description": "Aluminium die-cast inverter housing DC-345", "plant": "P100",
                                "uom": "EA", "target_qty": "24000", "unit_price_minor": 52_000})
    c3, c3_no = _contract(sc, supplier="SLA003", signer="sla.sales", type_="QUANTITY_CONTRACT", title="DC-348 mounting brackets FY27-28",
                          valid_from=D(2027, 5, 1), valid_to=D(2028, 3, 31), terms="N30", incoterms="FCA Salem", when=at(D(*MAY, 3), 13),
                          tolerances=tol, line={"material_id": ids["DC-348"], "description": "Aluminium die-cast mounting bracket DC-348",
                                                "plant": "P100", "uom": "EA", "target_qty": "50000", "unit_price_minor": 14_200})
    c4, c4_no = _contract(sc, supplier="HTS004", signer="hts.service", type_="VALUE_CONTRACT",
                          title="HPDC die-cell preventive maintenance rate contract", valid_from=D(2027, 5, 1), valid_to=D(2027, 10, 31),
                          terms="N30", incoterms=None, when=at(D(*MAY, 3), 14), tolerances={"over_pct": "0", "under_pct": "0"},
                          line={"material_id": None, "description": "Preventive maintenance visit – die casting cell", "plant": "P100",
                                "uom": "EA", "target_qty": "24", "unit_price_minor": 1_850_000})
    # F4-07: the e-signature provider adapter needs credentials; without them the internal signature path is used.
    esign = contract_svc.esign_config()
    if esign is None:
        try:
            contract_svc.require_esign()
        except Problem as exc:
            out["esign"] = f"needs supply: {exc.code} – {exc.detail}"
    else:
        out["esign"] = f"provider {esign.provider} configured; envelopes not sent by the dataset (internal signatures used)"
    yield at(D(*MAY, 4), 10)
    for cid, signer in ((c1, "tf.sales"), (c2, "kd.sales"), (c3, "sla.sales"), (c4, "hts.service")):
        _sign_activate(sc, cid, signer, at(D(*MAY, 4), 10))
    sc.relay(at(D(*MAY, 4), 15))
    out.update({"C1": (c1, c1_no), "C2": (c2, c2_no), "C3": (c3, c3_no), "C4": (c4, c4_no)})
    sc.note(f"Contracts {c1_no} (TF001 DC-340), {c2_no} (KD002 DC-345 interim), {c3_no} (SLA003 DC-348), {c4_no} (HTS004 rate) active; "
            f"e-sign: {out.get('esign')}")

    # C1 variation below ₹1 Cr: ₹186 → ₹182 from 10 May on 3,00,000 pcs = −₹12 L → CONTRACT_MANAGER (not the requester).
    yield at(D(*MAY, 10), 10)
    a1, a1_no, ch1 = _amend(sc, c1, at(D(*MAY, 10), 10), "VARIATION", {"lines": [{"line": 10, "unitPriceMinor": 18_200}]},
                            "Q1 FY27-28 cost-down: alloy surcharge reduced after the LME-AL reset (TF001 letter TF/CM/2705-14)", D(*MAY, 10))
    yield at(D(*MAY, 11), 11)
    sc.approve_all(c1, at(D(*MAY, 11), 11), "Cost-down verified against the LME-AL reset")
    # C1 variation above ₹1 Cr: +1,00,000 pcs × ₹182 = ₹1.82 Cr → LEGAL → FINANCE_CONTROLLER.
    yield at(D(*MAY, 17), 10)
    a2, a2_no, ch2 = _amend(sc, c1, at(D(*MAY, 17), 10), "VARIATION", {"lines": [{"line": 10, "targetQty": "400000"}]},
                            "Volume increase for the EV motor programme (OEM schedule SO-88611, +1,00,000 end shields)", D(*MAY, 17))
    yield at(D(*MAY, 18), 12)
    sc.approve_all(c1, at(D(*MAY, 18), 12), "Volume and value verified against the OEM nomination letter")
    sc.note(f"{c1_no}: {a1_no} {ch1['band']} {ch1['approvalChain']} (₹186→₹182) and {a2_no} {ch2['band']} {ch2['approvalChain']} "
            "(+1,00,000 pcs) effective → version 3")

    # C2 renewal: the 120-day notice timer → EXPIRING + renewal task → approved → EXTENSION draft → submitted.
    yield at(D(*MAY, 18), 12, 30)
    _fire(sc, "CONTRACT_RENEWAL", c2, at(D(*MAY, 18), 12, 30))
    [renewal] = _tasks(sc, c2, "CONTRACT_RENEWAL")
    yield at(D(*MAY, 18), 15)
    _complete(sc, "contract.manager", at(D(*MAY, 18), 15), renewal, "APPROVE",
              "Renew on the same terms for 12 months: DC-345 volumes continue on the inverter platform")
    from app.pic.services import amendments
    yield at(D(*MAY, 19), 10)
    with sc.act("contract.manager", at(D(*MAY, 19), 10)) as s:
        draft = s.execute(select(ContractAmendment).where(ContractAmendment.contract_id == c2, ContractAmendment.status == "DRAFT")).scalar_one()
        amendments.submit(s, draft)
        ext_no, ext_chain = draft.number, list(draft.changes["approvalChain"])
    yield at(D(*MAY, 20), 11)
    sc.approve_all(c2, at(D(*MAY, 20), 11), "Extension at unchanged price approved")
    sc.note(f"{c2_no}: renewal notice → EXPIRING → renewal approved → {ext_no} EXTENSION draft → {ext_chain} → active to 15 Sep 2028")

    # C4 extension below ₹1 Cr to the end of the fiscal year → second contract manager.
    yield at(D(*MAY, 24), 10)
    a4, a4_no, ch4 = _amend(sc, c4, at(D(*MAY, 24), 10), "EXTENSION", {"validTo": "2028-03-31"},
                            "Align the maintenance rate contract with the FY27-28 AMC tender (closing March 2028)", D(*MAY, 24))
    yield at(D(*MAY, 25), 10)
    sc.approve_all(c4, at(D(*MAY, 25), 10), "Extension within budget; rates unchanged")
    sc.note(f"{c4_no}: {a4_no} EXTENSION to 31 Mar 2028 ({ch4['band']} {ch4['approvalChain']})")


def _terminate(sc: Scenario, ctx: dict):
    """C3: open PO released from the contract, then termination for convenience with 90 days' notice."""
    from app.pic.services import order, requisition
    yield at(D(*MAY, 6), 10)
    c3, c3_no = ctx["contracts"]["C3"]
    yield at(D(*MAY, 6), 10)
    with sc.act("buyer", at(D(*MAY, 6), 10)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="BUFFER_BUILD", purpose_text="DC-348 September call-off (OEM SO-88540)",
                                plant="P100", lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "DC-348", "qty": "4000",
                                                      "price_est_minor": 14_200, "need_date": "2027-09-06", "storage_location": "0001"}])
        requisition.submit(s, pr)
        pr_id, pr_no = pr.id, pr.number
    yield at(D(*MAY, 6), 14)
    sc.approve_all(pr_id, at(D(*MAY, 6), 14), "September schedule confirmed")
    yield at(D(*MAY, 7), 10)
    with sc.act("buyer", at(D(*MAY, 7), 10)) as s:
        po = order.create_from_requisition(s, requisition=pr_no, lines=[10])[0]
        po_id, po_no, touchless = po.id, po.number, po.touchless
    if not touchless:
        sc.approve_all(po_id, at(D(*MAY, 7), 12), "Contract price")
    yield at(D(*MAY, 7), 16)
    with sc.act("sla.sales", at(D(*MAY, 7), 16)) as s:
        order.confirm(s, s.get(PurchaseOrder, po_id), "CONFIRMED", note="Confirmed for despatch in the first week of September")
    sc.relay(at(D(*MAY, 7), 17))
    yield at(D(*MAY, 20), 10)
    a3, a3_no, ch3 = _amend(sc, c3, at(D(*MAY, 20), 10), "TERMINATION", {"forCause": False},
                            "Termination for convenience: DC-348 is replaced by a bracket integrated into the DC-340 end shield from September",
                            D(2027, 8, 31))
    yield at(D(*MAY, 21), 11)
    sc.approve_all(c3, at(D(*MAY, 21), 11), "Notice period respected; open call-off to be reviewed by the buyer")
    sc.note(f"{c3_no}: {po_no} (touchless={touchless}) open; {a3_no} TERMINATION for convenience {ch3['approvalChain']} approved, "
            f"effective 31 Aug 2027 (90 days' notice)")
    ctx["termination"] = {"amendment": a3, "amendment_no": a3_no, "po": po_no, "po_id": po_id}


# ---------------------------------------------------------------- 3. sourcing: recommendation, clarifications, reverse auction, award
def _auction(sc: Scenario, ctx: dict):
    from app.pic.services import admin, auction, requisition, sourcing, sourcing_strategy
    from app.pic.models import PrLine, Requisition
    yield at(D(*MAY, 6), 11)
    with sc.act("buyer", at(D(*MAY, 6), 11)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="NEW_PART", purpose_text="DC-350 sensor cover – FY27-28 annual requirement",
                                plant="P100", lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "DC-350", "qty": "36000",
                                                      "price_est_minor": 9_600, "need_date": "2027-07-01", "storage_location": "0001"}])
        requisition.submit(s, pr)
        pr_id, pr_no = pr.id, pr.number
    yield at(D(*MAY, 6), 16)
    sc.approve_all(pr_id, at(D(*MAY, 6), 16), "New part for the EV sensor programme; sourcing required")
    yield at(D(*MAY, 7), 9)
    with sc.act("category.manager", at(D(*MAY, 7), 9)) as s:
        req = s.get(Requisition, pr_id)
        line = s.execute(select(PrLine).where(PrLine.requisition_id == pr_id, PrLine.line_no == 10)).scalar_one()
        rec = sourcing_strategy.recommend_for_line(s, req, line)
        rec_id, rec_type = rec.id, rec.proposal["eventType"]
    yield at(D(*MAY, 7), 9, 30)
    with sc.act("category.manager", at(D(*MAY, 7), 9, 30)) as s:
        admin.decide_recommendation(s, s.get(Recommendation, rec_id), False,
                                    f"{rec_type} not used: the drawing is mature and four qualified casters compete on price only – "
                                    "running a reverse auction with a pre-bid clarification window")
    close_at = at(D(*MAY, 12), 11, 30)
    yield at(D(*MAY, 7), 10)
    with sc.act("category.manager", at(D(*MAY, 7), 10)) as s:
        event = sourcing.create_event(
            s, type="REVERSE_AUCTION", title="DC-350 sensor cover – reverse auction FY27-28", category="ALU-DIECAST",
            lines=[{"requisition": pr_no, "line": 10, "annual_qty": "36000", "monthly_qty": "3000"}],
            criteria=[{"code": "PRICE_TCO", "name": "Price / TCO", "weight": 100}],
            invitees=[{"supplier": c} for c in ("TF001", "KD002", "SLA003", "APC007")], close_at=close_at, baseline_method="BUDGET",
            baseline_price_minor=9_600)
        auction.configure(s, event, {"minDecrementPct": "1", "extensionMinutes": 5, "triggerMinutes": 2, "showRank": True,
                                     "showBestPrice": False, "paymentTermsDays": 45, "leadTimeDays": 12})
        sourcing.publish(s, event)
        event_id, event_no = event.id, event.number
    sc.relay(at(D(*MAY, 7), 10, 30))

    def ask(who, when, text):
        with sc.act(who, when) as s:
            return auction.ask(s, s.get(SourcingEvent, event_id, with_for_update=True), text).seq

    yield at(D(*MAY, 8), 10)
    q1 = ask("tf.sales", at(D(*MAY, 8), 10), "Is drawing DC-350 revision C (ECN-2231, wall 2.2 mm) the basis for the bid?")
    yield at(D(*MAY, 8), 14)
    q2 = ask("kd.sales", at(D(*MAY, 8), 14), "May we quote with our returnable 600x400 crates instead of the Axion trays?")
    yield at(D(*MAY, 9), 11)
    q3 = ask("apc.sales", at(D(*MAY, 9), 11), "Is the PPAP sample quantity 300 or 125 pieces?")
    yield at(D(*MAY, 9), 12)
    with sc.act("apc.sales", at(D(*MAY, 9), 12)) as s:
        auction.withdraw(s, s.get(SourcingEvent, event_id, with_for_update=True), q3)
    yield at(D(*MAY, 10), 10)
    with sc.act("category.manager", at(D(*MAY, 10), 10)) as s:
        ev = s.get(SourcingEvent, event_id, with_for_update=True)
        auction.answer(s, ev, q1, "Yes. Revision C (ECN-2231) is frozen; the 2.2 mm wall applies to all cavities.")
        auction.answer(s, ev, q2, "Yes, returnable crates are accepted if they fit the line-side racks (600x400x280 mm max).")
        auction.ask(s, ev, "Live bidding opens on 12 May 2027 at 10:00 IST and closes at 11:30 IST; a bid in the last 2 minutes "
                           "extends the close by 5 minutes. Bids are per piece, FCA supplier works, payment 45 days.")
    sc.relay(at(D(*MAY, 10), 11))
    bids = [("tf.sales", (10, 2), 9_450), ("kd.sales", (10, 5), 9_400), ("apc.sales", (10, 20), 9_300), ("tf.sales", (10, 40), 9_250),
            ("kd.sales", (10, 55), 9_150), ("apc.sales", (11, 10), 9_050), ("tf.sales", (11, 29), 8_960), ("apc.sales", (11, 33), 8_870)]
    yield at(D(*MAY, 12), 10, 2)
    for who, (hh, mm), price in bids:
        with sc.act(who, at(D(*MAY, 12), hh, mm)) as s:
            sup = s.get(Supplier, s.info["principal"].supplier_id)
            auction.place_bid(s, s.get(SourcingEvent, event_id, with_for_update=True), sup, price)
    yield at(D(*MAY, 12), 11, 41)
    _fire(sc, "SOURCING_CLOSE", event_id, at(D(*MAY, 12), 11, 41))
    yield at(D(*MAY, 13), 10)
    with sc.act("category.manager", at(D(*MAY, 13), 10)) as s:
        ev = s.get(SourcingEvent, event_id)
        extensions = sum(1 for b in auction._bids(s, ev) if b.extended_close)
        options = sourcing.build_scenarios(s, ev)
        lowest = next(o for o in options if o["kind"] == "LOWEST_COST")
        sourcing.propose_award(s, ev, uuid.UUID(lowest["id"]), None, "No personal or financial interest in any bidder.")
        status = ev.status
    yield at(D(*MAY, 13), 14)
    sc.approve_all(event_id, at(D(*MAY, 13), 14), "Lowest bid after a competitive auction")
    sc.relay(at(D(*MAY, 13), 15))
    sc.note(f"{event_no}: SOURCING_STRATEGY {rec_type} recommendation rejected; clarifications Q{q1}/Q{q2} answered, Q{q3} withdrawn, "
            f"1 notice; {len(bids)} live bids, {extensions} soft-close extensions; award {lowest['allocations'][0]['supplier']} "
            f"@ ₹{lowest['weightedPriceMinor'] / 100:.2f} ({status}) → scheduling-agreement draft")
    ctx["sourcing"] = {"event": event_no, "event_id": event_id}


# ---------------------------------------------------------------- 4. order to pay with APC007
def _edi(sender: str, message_type: str, reference: str, body: list[str]) -> str:
    now = clock.now().astimezone(clock.IST)
    segments = [f"UNH+1+{message_type}:D:96A:UN", *body]
    segments.append(f"UNT+{len(segments) + 1}+1")
    return ("UNA:+.? '" + f"UNB+UNOC:3+{sender}:ZZZ+AXN:ZZZ+{now:%y%m%d}:{now:%H%M}+{reference}'"
            + "".join(x + "'" for x in segments) + f"UNZ+1+{reference}'")


def _o2p(sc: Scenario, ctx: dict):
    from app.pic.services import order, payables, receiving, requisition, transmission
    from app.pic.services.payables import expected_irn
    apc_gstin = gstin("33", APC["pan"])
    yield at(D(*MAY, 4), 10)
    with sc.act("buyer", at(D(*MAY, 4), 10)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="BUFFER_BUILD", purpose_text="DC-352 pump housings for the May OEM schedule",
                                plant="P100", lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "DC-352", "qty": "4000",
                                                      "price_est_minor": 26_500, "need_date": "2027-05-12", "storage_location": "0001"}])
        requisition.submit(s, pr)
        pr_id, pr_no = pr.id, pr.number
    yield at(D(*MAY, 5), 12)
    sc.approve_all(pr_id, at(D(*MAY, 5), 12), "May schedule SO-88520 confirmed by sales")
    yield at(D(*MAY, 6), 10)
    with sc.act("buyer", at(D(*MAY, 6), 10)) as s:
        po = order.create_from_requisition(s, requisition=pr_no, lines=[10], supplier_code="APC007", unit_price_minor=26_500)[0]
        po_id, po_no = po.id, po.number
    yield at(D(*MAY, 6), 11)
    sc.approve_all(po_id, at(D(*MAY, 6), 11), "Price as per APC quotation Q-APC-2704-31 (second source for DC-352)")
    sc.relay(at(D(*MAY, 6), 11, 30))  # delivery consumer: EDI queued (no gateway), e-mail queued (no SMTP)
    yield at(D(*MAY, 6), 12)
    with sc.act("buyer", at(D(*MAY, 6), 12)) as s:
        order.set_schedule(s, s.get(PurchaseOrder, po_id, with_for_update=True), 10,
                           [{"qty": "2000", "deliveryDate": "2027-05-12"}, {"qty": "2000", "deliveryDate": "2027-05-26"}],
                           "Split delivery: line-side stores take 2,000 housings per lot")
    yield at(D(*MAY, 7), 9, 30)
    with sc.act("admin", at(D(*MAY, 7), 9, 30)) as s:
        raw = _edi(APC["edi"], "ORDRSP", "APC0000000701", [
            "BGM+231+APC-RSP-2705-07+29", "DTM+137:20270507:102", f"RFF+ON:{po_no}", "LIN+10+5", "SCC+1", "DTM+2:20270512:102",
            "SCC+1", "DTM+2:20270526:102", "UNS+S", "CNT+2:1"])
        ordrsp = transmission.inbound(s, raw)
    yield at(D(*MAY, 10), 11)
    with sc.act("buyer", at(D(*MAY, 10), 11)) as s:
        changed = order.set_schedule(s, s.get(PurchaseOrder, po_id, with_for_update=True), 10,
                                     [{"qty": "2000", "deliveryDate": "2027-05-12"}, {"qty": "1200", "deliveryDate": "2027-05-26"},
                                      {"qty": "800", "deliveryDate": "2027-05-28"}],
                                     "OEM schedule SO-88520 revision 3: second lot split 1,200 on 26 May and 800 on 28 May")
    sc.relay(at(D(*MAY, 10), 11, 30))
    yield at(D(*MAY, 10), 16)
    with sc.act(APC["user"], at(D(*MAY, 10), 16)) as s:
        order.confirm(s, s.get(PurchaseOrder, po_id), "CONFIRMED", note="Version 2 accepted: 2,000 / 1,200 / 800")
    yield at(D(*MAY, 11), 18)
    with sc.act("admin", at(D(*MAY, 11), 18)) as s:
        raw = _edi(APC["edi"], "DESADV", "APC0000001101", [
            "BGM+351+APC-DES-2705-11+9", "DTM+137:20270511:102", "DTM+11:20270511:102", "DTM+132:20270512:102", f"RFF+ON:{po_no}",
            "RFF+ZEW:331100458921", "DTM+36:202705132359:203", "TDT+12++30+++++TN05BX4821", "CPS+1", "LIN+10", "QTY+12:2000:EA",
            "GIN+BX+APC-2705-01", "CNT+2:1"])
        desadv = transmission.inbound(s, raw)
        asn1 = desadv["messages"][0]["asn"]
    yield at(D(*MAY, 12), 10)
    with sc.act("receiver", at(D(*MAY, 12), 10)) as s:
        asn = s.execute(select(Asn).where(Asn.number == asn1)).scalar_one()
        gr = receiving.post_gr(s, s.get(PurchaseOrder, po_id), asn=asn, delivery_note="APC-DC-2705-0418",
                               lines=[{"line": 10, "qty": "2000", "batch": "APC-2705-01"}], posting_date=D(*MAY, 12))
        gr1 = gr.id
    sc.relay(at(D(*MAY, 12), 11))
    inv1_no = "APC/27-28/0142"
    yield at(D(*MAY, 12), 15)
    with sc.act(APC["user"], at(D(*MAY, 12), 15)) as s:
        inv = payables.capture(s, supplier="APC007", supplier_invoice_no=inv1_no, invoice_date=D(*MAY, 12), channel="E_INVOICE",
                               irn=expected_irn(apc_gstin, "2027-28", "INV", inv1_no),
                               lines=[{"po": po_no, "po_line": 10, "qty": "2000", "unit_price": "265", "gst_rate": "18", "hsn": "87089900"}])
        inv1, inv1_first = inv.id, inv.status
    yield at(D(*MAY, 13), 11)
    with sc.act("quality.inspector", at(D(*MAY, 13), 11)) as s:
        lot = s.execute(select(InspectionLot).where(InspectionLot.gr_id == gr1)).scalar_one()
        receiving.usage_decision(s, lot, accepted=Decimal(2000), rejected=Decimal(0))
    yield at(D(*MAY, 13), 14)
    with sc.act("ap.clerk", at(D(*MAY, 13), 14)) as s:
        invoice = s.get(Invoice, inv1, with_for_update=True)
        rematch = payables.match(s, invoice)
        payables.approve(s, invoice)
        payables.post(s, invoice, f"AXN|1000|APC007|{inv1_no}")
    sc.relay(at(D(*MAY, 13), 15))
    ctx["o2p"] = {"po": po_no, "po_id": po_id, "inv1": inv1, "inv1_no": inv1_no, "asn1": asn1}
    sc.note(f"{po_no}: v1 schedule split in place → EDI ORDRSP {ordrsp['messages'][0]['result']['confirmation']} → schedule change "
            f"{changed['mode']} v{changed['version']} (ORDCHG) → re-confirmed → EDI DESADV {asn1} (e-way 331100458921) → GR → "
            f"{inv1_no} {inv1_first} (4-way, lot in inspection) → usage decision → {rematch['status']} {rematch['matchType']} → posted")

    # Second delivery through the portal ASN (e-way validity from the distance), 10 rejected for porosity.
    yield at(D(*MAY, 24), 17)
    with sc.act(APC["user"], at(D(*MAY, 24), 17)) as s:
        a2 = receiving.create_asn(s, s.get(PurchaseOrder, po_id), lines=[{"line": 10, "qty": "1200",
                                                                         "batches": [{"batch": "APC-2705-02", "qty": "1200"}]}],
                                  ship_date=D(*MAY, 24), expected_date=D(*MAY, 26), eway_bill_no="331100512276", vehicle_no="TN 05 BX 4821",
                                  distance_km=305, documents=["CoC-APC-2705-02", "PackingList-APC-2705-02"])
        asn2 = a2.number
    yield at(D(*MAY, 26), 10)
    with sc.act("receiver", at(D(*MAY, 26), 10)) as s:
        gr = receiving.post_gr(s, s.get(PurchaseOrder, po_id), asn=s.execute(select(Asn).where(Asn.number == asn2)).scalar_one(),
                               delivery_note="APC-DC-2705-0533", lines=[{"line": 10, "qty": "1200", "batch": "APC-2705-02"}],
                               posting_date=D(*MAY, 26))
        gr2 = gr.id
    yield at(D(*MAY, 26), 16)
    with sc.act("quality.inspector", at(D(*MAY, 26), 16)) as s:
        lot = s.execute(select(InspectionLot).where(InspectionLot.gr_id == gr2)).scalar_one()
        receiving.usage_decision(s, lot, accepted=Decimal(1190), rejected=Decimal(10), defect_code="POROSITY",
                                 reason="Gas porosity at the coolant inlet boss on X-ray (10 housings)")
    sc.relay(at(D(*MAY, 26), 17))
    inv2_no = "APC/27-28/0171"
    yield at(D(*MAY, 27), 10)
    with sc.act(APC["user"], at(D(*MAY, 27), 10)) as s:
        inv = payables.capture(s, supplier="APC007", supplier_invoice_no=inv2_no, invoice_date=D(*MAY, 27), channel="E_INVOICE",
                               irn=expected_irn(apc_gstin, "2027-28", "INV", inv2_no),
                               lines=[{"po": po_no, "po_line": 10, "qty": "1190", "unit_price": "265", "gst_rate": "18", "hsn": "87089900"}])
        inv2, inv2_status = inv.id, inv.status
    yield at(D(*MAY, 27), 15)
    with sc.act("ap.clerk", at(D(*MAY, 27), 15)) as s:
        invoice = s.get(Invoice, inv2)
        payables.approve(s, invoice)
        payables.post(s, invoice, f"AXN|1000|APC007|{inv2_no}")
    sc.relay(at(D(*MAY, 27), 16))
    sc.note(f"{asn2} by portal (e-way 331100512276, 305 km) → GR → 1,190 accepted / 10 rejected → {inv2_no} {inv2_status} first pass → posted; "
            "800 still open on the 28 May schedule line")
    ctx["o2p"].update({"inv2_no": inv2_no, "asn2": asn2})


def _reconcile_and_pay(sc: Scenario, ctx: dict):
    from app.pic.services import bank_files, payables
    yield at(D(*MAY, 20), 11)
    o2p = ctx["o2p"]
    with sc.act(APC["user"], at(D(*MAY, 20), 11)) as s:
        payables.submit_credit_note(s, s.get(Invoice, o2p["inv1"]), supplier_credit_note_no="APC-CN-0019", note_date=D(*MAY, 20),
                                    reason="25 housings with cold shuts found at machining after acceptance; scrapped at Axion and credited",
                                    lines=[{"invoice_line": 10, "qty": "25"}])
    yield at(D(*MAY, 20), 17)
    with sc.act("ap.clerk", at(D(*MAY, 20), 17)) as s:
        first = payables.reconcile(s, "1000")
    mine = [i for i in first["items"] if i["ref"] == o2p["inv1_no"]]
    sc.relay(at(D(*MAY, 20), 18))  # the connector worker posts the SAP credit memo (KG)
    yield at(D(*MAY, 21), 10)
    with sc.act("ap.clerk", at(D(*MAY, 21), 10)) as s:
        from app.pic.models import IntegrationMessage, ReconciliationItem
        memo = s.execute(select(IntegrationMessage).where(IntegrationMessage.message_type == "SUPPLIER_CREDIT_MEMO",
                                                          IntegrationMessage.object_id == o2p["inv1"])).scalar_one()
        for item in mine:
            payables.resolve_reconciliation_item(s, s.get(ReconciliationItem, uuid.UUID(item["id"])),
                                                 f"Timing difference: credit note APC-CN-0019 reached SAP as credit memo {memo.erp_doc_no} "
                                                 f"(connector run 20 May 18:00, status {memo.status}); RE document unchanged. Closed.")
        second = payables.reconcile(s, "1000")
    sc.note(f"Reconciliation {first['number']}: {first['differences']} difference(s) ({', '.join(i['kind'] for i in mine)} on "
            f"{o2p['inv1_no']}) → resolved; {second['number']}: {second['differences']} difference(s)")

    yield at(D(*MAY, 28), 10)
    with sc.act("finance.controller", at(D(*MAY, 28), 10)) as s:
        run = payables.payment_run(s, D(*MAY, 28), supplier_codes=["APC007"])
    sc.relay(at(D(*MAY, 28), 10, 30))
    yield at(D(*MAY, 28), 11)
    with sc.act("finance.controller", at(D(*MAY, 28), 11)) as s:
        pain = bank_files.generate(s, run["run"], "ISO20022_PAIN001")
        bank_files.set_status(s, pain, "SENT")
        pain_no = pain.number
    yield at(D(*MAY, 28), 15)
    with sc.act("finance.controller", at(D(*MAY, 28), 15)) as s:
        bank_files.set_status(s, bank_files.by_number(s, pain_no, lock=True), "REJECTED",
                              reason="Axis Bank: pain.001 host-to-host mandate for this current account is not yet activated; "
                                     "upload the run as a NEFT bulk file")
        neft = bank_files.generate(s, run["run"], "NEFT_CSV")
        bank_files.content_of(s, neft)  # downloaded for the bank portal upload (audited)
        bank_files.set_status(s, neft, "SENT")
        neft_no = neft.number
    yield at(D(*MAY, 29), 10)
    with sc.act("finance.controller", at(D(*MAY, 29), 10)) as s:
        bank_files.set_status(s, bank_files.by_number(s, neft_no, lock=True), "ACKNOWLEDGED", bank_ref="AXIS-NEFT-270528-0417")
    sc.relay(at(D(*MAY, 29), 10, 30))
    sc.note(f"Payment run {run['run']} (28 May): paid {', '.join(p['invoice'] for p in run['paid'])}; {pain_no} pain.001 sent → rejected "
            f"by the bank; {neft_no} NEFT bulk file sent → acknowledged AXIS-NEFT-270528-0417")
    ctx["pay"] = {"rec1": first["number"], "rec2": second["number"], "run": run["run"], "pain": pain_no, "neft": neft_no,
                  "differences_after": second["differences"]}


# ---------------------------------------------------------------- 5. masters: MDM-04, punch-out, category budget
def _mdm(sc: Scenario, ctx: dict):
    from app.pic.services import master_changes
    yield at(D(*MAY, 24), 11)
    with sc.act("supplier.manager", at(D(*MAY, 24), 11)) as s:
        addr = master_changes.request_change(
            s, s.execute(select(Supplier).where(Supplier.code == "APC007")).scalar_one(), field_group="ADDRESS",
            values={"line1": "Plot 112, SIDCO Industrial Estate", "line2": "Thirumudivakkam", "city": "Chennai", "state_code": "33",
                    "pin": "600044"}, reason="Registered office moved to the new Thirumudivakkam unit (supplier letter APC/ADM/27/031)")
        addr_id, addr_no = addr.id, addr.number
    yield at(D(*MAY, 24), 15)
    with sc.act(APC["user"], at(D(*MAY, 24), 15)) as s:
        contact = master_changes.request_change(
            s, s.execute(select(Supplier).where(Supplier.code == "APC007")).scalar_one(), field_group="CONTACT",
            values={"email": "ar@ambattur-castings.example", "phone": "+91 44 2625 7731"},
            reason="Accounts receivable desk now handles purchase-order and remittance correspondence")
        contact_id, contact_no = contact.id, contact.number
    yield at(D(*MAY, 24), 16, 30)
    with sc.act(KRP["email"], at(D(*MAY, 24), 16, 30)) as s:
        tax = master_changes.request_change(
            s, s.get(Supplier, ctx["krp"]["id"]), field_group="TAX",
            values={"gstin": gstin("29", KRP["pan"]), "pan": KRP["pan"], "address": dict(KRP["new_address"])},
            reason="Principal place of business moved to the Attibele (Karnataka) plant; new GST registration certificate (REG-06) attached")
        tax_id, tax_no = tax.id, tax.number
    kind = master_changes.TASK_KIND
    yield at(D(*MAY, 25), 11)
    _decide_group(sc, addr_id, kind, at(D(*MAY, 25), 11),
                  {"FINANCE_CONTROLLER": ("finance.controller", "REJECT",
                                          "Rental agreement and GST amendment for the new place of business not attached")})
    yield at(D(*MAY, 25), 12)
    _decide_group(sc, contact_id, kind, at(D(*MAY, 25), 12),
                  {"FINANCE_CONTROLLER": ("finance.controller", "APPROVE", "Verified by call-back to the registered landline"),
                   "SUPPLIER_MANAGER": ("supplier.manager", "APPROVE", "Confirmed with APC sales head")})
    yield at(D(*MAY, 27), 11)
    _decide_group(sc, tax_id, kind, at(D(*MAY, 27), 11),
                  {"FINANCE_CONTROLLER": ("finance.controller", "APPROVE", "REG-06 verified on the GST portal"),
                   "SUPPLIER_MANAGER": ("supplier.manager", "APPROVE", "Supply continues from the Attibele plant")})
    sc.relay(at(D(*MAY, 27), 12))
    with tenant_tx(sc.tenant_id) as s:
        states = {c.number: c.status for c in s.execute(select(SupplierMasterChange).where(
            SupplierMasterChange.id.in_([addr_id, contact_id, tax_id]))).scalars()}
    sc.note(f"MDM-04: {addr_no} ADDRESS {states[addr_no]}, {contact_no} CONTACT by portal user {states[contact_no]}, "
            f"{tax_no} TAX (Tamil Nadu → Karnataka GSTIN) {states[tax_no]}")


def _punchout(sc: Scenario, ctx: dict):
    from app.pic.services import punchout, requisition
    yield at(D(*MAY, 21), 9)
    with sc.act("supplier.manager", at(D(*MAY, 21), 9)) as s:
        punchout.configure(s, s.execute(select(Supplier).where(Supplier.code == "HTS004")).scalar_one(), protocol="CXML", url="builtin",
                           identity="HTS004-CAT", shared_secret=secrets.token_urlsafe(18))
    yield at(D(*MAY, 21), 10)
    with sc.act("requester", at(D(*MAY, 21), 10)) as s:
        session_view = punchout.start(s, s.execute(select(Supplier).where(Supplier.code == "HTS004")).scalar_one())
        cookie = session_view["buyer_cookie"]
    yield at(D(*MAY, 21), 10, 5)
    with sc.act("requester", at(D(*MAY, 21), 10, 5)) as s:
        page = punchout.simulator_catalogue(s, cookie, {})
        item_id = re.search(r"name='qty_([0-9a-f-]+)'", page).group(1)
        checkout = punchout.simulator_checkout(s, {"cookie": cookie, f"qty_{item_id}": "2"})
        document = html.unescape(re.search(r'name="cxml-urlencoded" value="([^"]*)"', checkout).group(1))
        returned_cookie, protocol, items, raw = punchout.decode_return({"cxml-urlencoded": document}, None)
        punchout.receive(s, returned_cookie, protocol, items, raw)
    yield at(D(*MAY, 21), 10, 15)
    with sc.act("requester", at(D(*MAY, 21), 10, 15)) as s:
        pr = punchout.convert(s, punchout.get(s, cookie), purpose_code="MAINTENANCE",
                              purpose_text="Two preventive-maintenance visits for HPDC cells 3 and 4 before the June shutdown",
                              need_date=D(2027, 6, 5))
        requisition.submit(s, pr)
        pr_id, pr_no = pr.id, pr.number
    yield at(D(*MAY, 21), 14)
    sc.approve_all(pr_id, at(D(*MAY, 21), 14), "Planned maintenance before the June shutdown")
    sc.note(f"Punch-out HTS004 (built-in cXML): cart 2 × HTS-PM-STD → {pr_no} → approved")
    ctx["punchout"] = pr_no


def _category_budget(sc: Scenario, ctx: dict):
    from app.pic.services import admin, requisition, sourcing_strategy, spend
    from app.pic.models import PrLine, Requisition
    yield at(D(*MAY, 17), 15)
    with sc.act("procurement.head", at(D(*MAY, 17), 15)) as s:
        plan = s.execute(select(CategoryPlan).where(CategoryPlan.category == "RUBBER-SEALS", CategoryPlan.fiscal_year == "2027-28")).scalar_one()
        if plan.status == "DRAFT":
            spend.approve_plan(s, plan, "Bottleneck category: single-source risk on FKM seals; budget capped at the plan (hard stop)")
        plan_no, budget = plan.number, plan.budget_minor
    yield at(D(*MAY, 18), 10)
    with sc.act("buyer", at(D(*MAY, 18), 10)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="ANNUAL_REQUIREMENT", purpose_text="FY27-28 seal kits for DC-345 housings",
                                plant="P100", lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "SK-345", "qty": "140000",
                                                      "price_est_minor": 14_500, "need_date": "2027-07-01", "storage_location": "0001"}])
        warn = requisition.submit(s, pr)["categoryBudget"]
        warn_id, warn_no = pr.id, pr.number
    yield at(D(*MAY, 18), 15)
    sc.approve_all(warn_id, at(D(*MAY, 18), 15), "Annual seal requirement; sourcing to follow")
    yield at(D(*MAY, 19), 9)
    with sc.act("category.head", at(D(*MAY, 19), 9)) as s:
        rec = sourcing_strategy.recommend_for_line(s, s.get(Requisition, warn_id), s.execute(select(PrLine).where(
            PrLine.requisition_id == warn_id, PrLine.line_no == 10)).scalar_one())
        rec_type = rec.proposal["eventType"]
        admin.decide_recommendation(s, rec, True, f"Accepted: {rec_type.replace('_', ' ')} for the FY27-28 annual seal requirement, "
                                    "with a second FKM seal source invited to de-risk the bottleneck category")
    block = None
    yield at(D(*MAY, 19), 10)
    with sc.act("buyer", at(D(*MAY, 19), 10)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="ANNUAL_REQUIREMENT", purpose_text="FY27-28 damper grommets for DC-348 brackets",
                                plant="P100", lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "SK-348", "qty": "30000",
                                                      "price_est_minor": 12_800, "need_date": "2027-07-15", "storage_location": "0001"}])
        block_no = pr.number
    for justification in (None, "Line-2 changeover needs the full year's grommets"):
        try:
            with sc.act("buyer", at(D(*MAY, 19), 11)) as s:
                requisition.submit(s, s.execute(select(Requisition).where(Requisition.number == block_no)).scalar_one(), justification)
        except Problem as exc:
            block = {"code": exc.code, "ruleRef": exc.rule_ref}
    sc.note(f"Category budget {plan_no} RUBBER-SEALS approved (₹{budget / 1e9:.2f} Cr): {warn_no} {warn['outcome']} at "
            f"{warn['checks'][0]['usedPct']}%; {block_no} blocked {block and block['code']} (stays DRAFT, also with a justification); "
            f"SOURCING_STRATEGY {rec_type} recommendation accepted")
    ctx["budget"] = {"warn": warn_no, "block": block_no, "plan": plan_no}


# ---------------------------------------------------------------- 6. platform: ERP import, notifications
def _erp_import(sc: Scenario, ctx: dict):
    from app.pic.services import erp_import, planning
    rows = [
        {"externalRef": "S4-PLO-0001184520", "material": "DC-352", "plant": "P100", "qty": 2000, "needDate": "2027-06-21",
         "releaseDate": "2027-06-07", "supplier": "APC007"},
        {"externalRef": "S4-PLO-0001184521", "material": "DC-340", "plant": "P100", "qty": 6000, "needDate": "2027-06-14",
         "releaseDate": "2027-06-01"},
        {"externalRef": "S4-PLO-0001184522", "material": "DC-399", "plant": "P100", "qty": 500, "needDate": "2027-06-14"},
        {"externalRef": "S4-PLO-0001184523", "material": "DC-345", "plant": "P100", "qty": 0, "needDate": "2027-06-14"},
        {"externalRef": "S4-PLO-0001184524", "material": "DC-345", "plant": "P300", "qty": 800, "needDate": "2027-06-14"},
        {"externalRef": "S4-PLO-0001184525", "material": "DC-348", "plant": "P100", "qty": 1500, "needDate": "21/06/2027"},
        {"externalRef": "S4-PLO-0001184520", "material": "DC-352", "plant": "P100", "qty": 400, "needDate": "2027-06-28"},
    ]
    yield at(D(*MAY, 14), 9)
    with sc.act("admin", at(D(*MAY, 14), 9)) as s:
        result = erp_import.import_planned_orders(s, system="SAP_S4", batch_ref="MD01-P100-2027W20", rows=rows)
    accepted = [r["plannedOrder"] for r in result["results"] if r["status"] == "ACCEPTED"]
    yield at(D(*MAY, 14), 11)
    with sc.act("mrp.controller", at(D(*MAY, 14), 11)) as s:
        planning.firm(s, s.execute(select(PlannedOrder).where(PlannedOrder.number == accepted[0])).scalar_one())
    sc.relay(at(D(*MAY, 14), 11, 30))
    sc.note(f"ERP import {result['number']} (MD01-P100-2027W20): {result['accepted']} accepted, {result['rejected']} rejected; "
            f"{accepted[0]} firmed")
    ctx["erp"] = {"batch": result["number"], "accepted": result["accepted"], "rejected": result["rejected"]}


def _notifications(sc: Scenario, refs: set[str]) -> dict:
    from app.pic.services import notifications
    read = 0
    for who in ("contract.manager2", "buyer", "legal", "category.manager"):
        with sc.act(who, at(D(*MAY, 29), 17)) as s:
            uid = s.info["principal"].user_id
            for note in s.execute(select(Notification).where(Notification.user_id == uid, Notification.read_at.is_(None),
                                                            Notification.object_ref.in_(refs), Notification.created_at < at(D(*MAY, 20), 0))
                                  .order_by(Notification.created_at)).scalars().all():
                notifications.mark_read(s, uid, note.id)
                read += 1
    with tenant_tx(sc.tenant_id) as s:
        total = s.execute(select(Notification).where(Notification.object_ref.in_(refs))).scalars().all()
    return {"total": len(total), "read": read}


# ---------------------------------------------------------------- pack entry point
def _run_in_time_order(cases: list) -> None:
    """Interleave the case generators chronologically: each yields the IST time of its next block."""
    import heapq
    queue = []
    for index, case in enumerate(cases):
        try:
            heapq.heappush(queue, (next(case), index, case))
        except StopIteration:
            pass
    while queue:
        when, index, case = heapq.heappop(queue)
        try:
            following = case.send(None)
        except StopIteration:
            continue
        if following < when:
            raise RuntimeError(f"{KEY}: case {case.__name__} goes back in time ({following} < {when})")
        heapq.heappush(queue, (following, index, case))


def apply(tenant_code: str, password: str) -> dict:
    from app.pic.db import system_tx
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == tenant_code)).scalar_one()
    reference.ensure_extensions(tenant_id)
    sc = Scenario(tenant_id, role_user=_role_user())
    _masters(sc, password)
    ctx: dict = {}
    _run_in_time_order([_onboard_apc(sc, ctx), _invite_krp(sc, password, ctx), _contracts(sc, ctx), _o2p(sc, ctx), _terminate(sc, ctx),
                        _auction(sc, ctx), _erp_import(sc, ctx), _category_budget(sc, ctx), _reconcile_and_pay(sc, ctx),
                        _punchout(sc, ctx), _mdm(sc, ctx)])
    contracts, o2p, term, pay = ctx["contracts"], ctx["o2p"], ctx["termination"], ctx["pay"]
    refs = {contracts[k][1] for k in ("C1", "C2", "C3", "C4")} | {o2p["po"], ctx["sourcing"]["event"], term["po"], ctx["budget"]["warn"],
                                                                 ctx["punchout"]}
    with tenant_tx(tenant_id) as s:
        refs |= {c.number for c in s.execute(select(SupplierMasterChange).where(SupplierMasterChange.created_at >= at(D(*MAY, 1), 0))).scalars()}
    notes = _notifications(sc, refs)
    # Last: the approved termination becomes effective on its date (only this pack's own timer is fired, no relay).
    _fire(sc, "CONTRACT_AMENDMENT_EFFECTIVE", term["amendment"], at(D(2027, 8, 31), 0, 30))
    with tenant_tx(tenant_id) as s:
        c3 = s.get(Contract, contracts["C3"][0])
        review = s.execute(select(Task).where(Task.object_id == term["po_id"], Task.kind == "TERMINATED_CONTRACT_REVIEW")).scalars().first()
        sc.note(f"{c3.number} {c3.status} on 31 Aug 2027 by {term['amendment_no']}; open {term['po']} flagged "
                f"(buyer review task {review.status if review else 'missing'})")
    sc.note(f"Notifications on these objects: {notes['total']} ({notes['read']} marked read, the rest unread)")
    clock.set_pinned(None)
    erp = ctx["erp"]
    return {"notes": sc.log, "counts": {
        "contracts": 4, "amendments": 5, "auctionBids": 8, "clarifications": 4, "purchaseOrders": 2, "asns": 2, "invoices": 2,
        "creditNotes": 1, "reconciliationRuns": 2, "paymentFiles": 2, "masterChanges": 3, "invitations": 1, "punchoutSessions": 1,
        "importedPlannedOrders": erp["accepted"], "rejectedImportRows": erp["rejected"], "notifications": notes["total"],
        "notificationsRead": notes["read"], "recommendationsDecided": 2},
        "keys": {"contracts": {k: v[1] for k, v in contracts.items() if k.startswith("C")}, "event": ctx["sourcing"]["event"],
                 "po": o2p["po"], "invoices": [o2p["inv1_no"], o2p["inv2_no"]], "paymentRun": pay["run"],
                 "paymentFiles": [pay["pain"], pay["neft"]], "reconciliation": [pay["rec1"], pay["rec2"]], "erpBatch": erp["batch"],
                 "punchoutRequisition": ctx["punchout"], "supplier": ctx["krp"]["code"], "esign": contracts.get("esign")}}
