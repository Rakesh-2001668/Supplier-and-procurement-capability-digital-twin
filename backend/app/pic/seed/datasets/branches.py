"""D1 operating cases 9–34: the unexercised F1–F9 gateway branches, run on tenant AXN in April 2027.

Every case runs through the domain services as the people who do the work (requester, approvers, buyers, MRP controller,
stewards, receiver, quality, AP, contract managers) and the suppliers' own portal users. The cases use their own
material (DC-345), suppliers (SPD201, AAC202, Vellore Heat Treaters) and documents, so no signature-case object changes.
Timers are fired one by one for this pack's own objects; the relay only publishes AXN events and ERP messages.

ERP inbound (TD §12.4, no domain service exists for these masters): FY 2027-28 budgets (check-then-insert), material
DC-345 with its MRP view, opening stock 300, and the sales-order / forecast demand deltas of 1, 8 and 15 April. Each load
is audited as ``INITIAL_LOAD`` / ``ERP_DELTA`` by ``integration:SAP_S4``.

Not repeated here: ERS (self-billing) settlement runs on consignment stock and is seeded by the purchase-type pack (D2,
``purchase_types``); a payment run is left out on purpose because it would also pay the signature invoice INV-TF-9031
(due 14 Apr 2027), so the bank-change cooling-off block stays covered by the test suite only.

| Case | Flow · step | Branch exercised | Business keys |
|---|---|---|---|
| 9  | F2-08 | approver RETURNS → requester changes qty → resubmitted with a shorter chain → approved; then a value change after approval restarts approval (budget re-booked) | PR "Die-release agent for HPDC cell 3 – Q1 FY 2027-28" |
| 10 | F2-08 | second approver (department head) REJECTS; budget commitment released | PR "Sit-stand workstations – engineering office" |
| 11 | F1-05 | SIMULATION run: trace only, no planned orders | MRP run SIMULATION, scope DC-345 |
| 12 | F1-06/07 | live run: PAST_DUE (SO-90412), planned orders firmed, one converted to an MRP requisition | SO-90412, PR "MRP replenishment from <PLO>" |
| 13 | F1-06 | next run deletes unfirmed planned orders; FC-2027-05 moved out → RESCHEDULE_OUT on the firmed order | ERP delta 8 Apr, run 2 |
| 14 | F1-06 | new urgent order SO-90437 → RESCHEDULE_IN on the firmed order; quota from the new SA used as source | ERP delta 15 Apr, run 3 |
| 15 | F8-01/06 | invitation → self-registration → profile → bank dual approval → qualification REJECTED (EXITED) | Vellore Heat Treaters Pvt Ltd |
| 16 | F8-08 | mandatory ISO 14001 expires → certificate EXPIRED → ALU-DIECAST CONDITIONAL (timer) | AAC202, EMS-AAC202-1604 |
| 17 | F9-05 | QUALITY steward REJECTS a material request (others cancelled) | MRQ "Hydraulic oil HLP 46, 210 L drum" |
| 18 | F9-04 | duplicate score in the 0.75–0.92 warning band → stewards approve → ERP | MRQ "… DC-345 RH machined" |
| 19 | F9-04 | score ≥ 0.92 blocked → steward OVERRIDE with reason → stewards approve → ERP | MRQ "… DC-345, e-coated" |
| 20 | F4-05/06 | contract approver REJECTS → supplier redlines → resubmitted → below ₹1 Cr chain (CONTRACT_MANAGER) | "DC-345 bridge supply during tool transfer" |
| 21 | F4-09 | consumption alerts 80 / 90 / 100 % from three call-off POs | bridge contract, PO-A/B/C |
| 22 | F4-10 | renewal notice → renewal REJECTED → expiry timer → EXPIRED (F4-10 reached) | bridge contract |
| 23 | F4-10 | renewal APPROVED → EXTENSION amendment → second contract manager approves → ACTIVE v2; obligation completed | "HPDC die maintenance – trial rate contract" |
| 24 | F3-05/07 | single round (no negotiation) → LOWEST_COST award below ₹50 L → no award approval → SA drafted, below ₹1 Cr | RFQ "DC-345 motor mount bracket – annual requirement" |
| 25 | F5-07/08 | supplier REJECTS the PO → buyer declines → PO CANCELLED (requisition re-opened) → re-sourced; confirmation SLA breach → Expediting task | PR "PPAP sample castings DC-345", AAC202 / SPD201 |
| 26 | F5-08 | change outside tolerance: later date ACCEPTED (v2, re-confirmed); price change DECLINED (confirmed as ordered) | PO-B, PO-C |
| 27 | F6-03 | GR posted against the wrong PO → REVERSED (102) → re-posted on the right PO | delivery note DN-SPD-1190 |
| 28 | F6-06/07 | lot rejected in full → return delivery → CAPA → supplier response → verified and CLOSED; PO closed | PO-B, batch SPD-2704-02 |
| 29 | F6-04 | service entry REJECTED → corrected SES approved | PR "Thermal imaging survey of HPDC cell 3" |
| 30 | F7-06 | ERP timeout → retry (GR) and timeout × 8 → DEAD_LETTER → replay (invoice) → posted; PO closed, MRP PR closed | SPD/27-28/0012 |
| 31 | F7-05 | PRICE exception DISPUTED → corrected invoice, original rejected; TAX (IRN) exception → re-issued e-invoice | SPD/27-28/0019 / 0021, SPD/27-28/0017 / 0018 |
| 32 | F5-05 | PO approval REJECTED (rate differs from quote) → PO back to DRAFT → CANCELLED → re-raised and approved | PR "Thermal imaging survey of HPDC cell 3", HTS004 |
| 33 | F8-04 | supplier bank change: call-back → finance controller REJECTS (holder name differs) | AAC202, UTIB0003912 |
| 34 | F5 PO-03 | supplier change request after confirmation REJECTED by the buyer | PO-C, need date 18 Apr |
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, Asn, BankChangeRequest, Budget, Capa, Certificate, Contract, ContractAmendment, DemandElement, GoodsReceipt,
    InspectionLot, IntegrationMessage, Invoice, InvoiceException, Material, MaterialRequest, Obligation, PlannedOrder,
    PurchaseOrder, Qualification, Requisition, ServiceEntry, SourcingEvent, Stock, Supplier, Task, Tenant, Timer,
)
from app.pic.platform import audit, clock, integration, outbox, workflow
from app.pic.platform.auth import hash_password
from app.pic.seed.axion import ROLE_USER, Scenario, at, email
from app.pic.seed.datasets._tenant_kit import AXN_BUDGETS_2027_28

KEY = "axn-branch-cases"
VERSION = "1"
TITLE = "D1 operating cases 9–34: unexercised F1–F9 gateway branches (April 2027)"
TENANTS = ('AXN',)
CREATED_BY = "integration:SAP_S4"  # actor of the ERP inbound loads
CREATES_TENANT = False
READY = True
from app.pic.seed.axion import SIGNATURE_KEY, SIGNATURE_VERSION  # noqa: E402
REQUIRES = {SIGNATURE_KEY: SIGNATURE_VERSION}  # the current signature case (users, documents, identifiers)

L = 100_000 * 100
MATERIAL = "DC-345"
CATEGORY = "ALU-DIECAST"
FY = "2027-28"
# Two contract managers: the drafting one is excluded from approving his own contract (four-eyes).
ROLES = {**ROLE_USER, "CONTRACT_MANAGER": ["contract.manager", "contract.manager2"]}

SUPPLIERS = {
    # code: legal name, GSTIN (state 33 Tamil Nadu, check character valid), bank (IFSC, account), portal user, terms, incoterms,
    #       certificates (type, number, issued, expires)
    "SPD201": ("Sriperumbudur Precision Diecast Pvt Ltd", "33AAICS5813M1Z3", ("HDFC0004821", "50200061234567"), "spd.sales", "N45",
               "FCA Sriperumbudur", {"line1": "Plot B-12, SIPCOT Industrial Park", "city": "Sriperumbudur", "state_code": "33", "pin": "602105"},
               [("IATF16949", "IATF-SPD201-2210", "2026-02-15", "2029-02-14"), ("ISO14001", "EMS-SPD201-0731", "2025-07-01", "2028-06-30")],
               (84, 86)),
    "AAC202": ("Ambattur Alloy Castings Pvt Ltd", "33AAHCA7429Q1Z6", ("IOBA0001523", "152301000045678"), "aac.sales", "N60",
               "FCA Ambattur", {"line1": "No. 47, Industrial Estate North Phase", "city": "Ambattur, Chennai", "state_code": "33", "pin": "600098"},
               [("IATF16949", "IATF-AAC202-0915", "2025-09-01", "2028-08-31"), ("ISO14001", "EMS-AAC202-1604", "2024-04-16", "2027-04-15")],
               (78, 79)),
}
VHT = {"legal_name": "Vellore Heat Treaters Pvt Ltd", "gstin": "33AAFCV3156P1ZX", "pan": "AAFCV3156P", "email": "accounts@velloreheattreat.example",
       "contact": "S. Karthikeyan", "address": {"line1": "Plot 14, SIPCOT Industrial Complex", "city": "Ranipet", "state_code": "33", "pin": "632403"},
       "category": "HEAT-TREATMENT"}

CRITERIA = [{"code": "PRICE_TCO", "name": "Price / TCO", "weight": 50}, {"code": "QUALITY", "name": "Quality", "weight": 20},
            {"code": "DELIVERY", "name": "Delivery", "weight": 15}, {"code": "TECHNICAL", "name": "Technical", "weight": 10},
            {"code": "ESG", "name": "ESG", "weight": 5}]

# Business keys (purpose texts, titles, descriptions) the test and the summary look objects up by.
PR_COOLANT = "Die-release agent for HPDC cell 3 – Q1 FY 2027-28"
PR_DESKS = "Sit-stand workstations – engineering office"
PR_PPAP = "PPAP sample castings DC-345"
PR_THERMAL = "Thermal imaging survey of HPDC cell 3"
PR_ANNUAL = "DC-345 annual requirement May 2027 – Apr 2028 (EV motor housing programme)"
PR_TOPUP = "DC-345 safety top-up for the SO-90412 launch lot"
BRIDGE = "DC-345 bridge supply during tool transfer – Sriperumbudur Precision Diecast"
AMC = "HPDC die maintenance – trial rate contract (cells 1–3)"
RFQ_TITLE = "DC-345 motor mount bracket – annual requirement May 2027 – Apr 2028"
MRQ_OIL = "Hydraulic oil HLP 46, 210 L drum"
MRQ_WARN = "Aluminium die-cast motor mount bracket DC-345 RH machined"
MRQ_BLOCK = "Aluminium die-cast motor mount bracket DC-345, e-coated"


# ---------------------------------------------------------------- helpers
def _tenant_id(code: str) -> uuid.UUID:
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == code)).scalar_one()


def _scheduler(tenant_id: uuid.UUID):
    from app.pic.worker import system_principal
    return system_principal(tenant_id)


def _relay(sc: Scenario, when) -> None:
    """Publish this tenant's events and post its pending ERP messages (no timers: those are fired per object)."""
    clock.set_pinned(when)
    outbox.relay_tenant(sc.tenant_id)
    integration.run_pending(sc.tenant_id, _scheduler(sc.tenant_id))
    outbox.relay_tenant(sc.tenant_id)


def _fire(sc: Scenario, kind: str, object_id: uuid.UUID, when) -> int:
    """Fire the due timers of one of this pack's objects as the scheduler (what the worker does for every due timer)."""
    clock.set_pinned(when)
    p = _scheduler(sc.tenant_id)
    fired = 0
    with tenant_tx(sc.tenant_id, p.user_id, p) as s:
        for timer in s.execute(select(Timer).where(Timer.kind == kind, Timer.object_id == object_id, Timer.fired_at.is_(None),
                                                   Timer.due_at <= clock.now()).order_by(Timer.due_at)).scalars().all():
            timer.fired_at = clock.now()
            with s.begin_nested():
                workflow._timer_handlers[kind](s, timer)
            fired += 1
    return fired


def _message(sc: Scenario, key: str) -> IntegrationMessage:
    with tenant_tx(sc.tenant_id) as s:
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == key)).scalar_one()
        s.expunge(message)
        return message


def _worker_attempt(sc: Scenario, key: str, when) -> IntegrationMessage:
    """One connector-worker attempt on this pack's ERP message (integration.run_pending does the same per due message)."""
    clock.set_pinned(when)
    p = _scheduler(sc.tenant_id)
    with tenant_tx(sc.tenant_id, p.user_id, p) as s:
        message = s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == key)).scalar_one()
        integration.process(s, message)
        s.flush()
        s.expunge(message)
        return message


def _decide(sc: Scenario, who: str, when, object_id: uuid.UUID, kind: str, decision: str, comment: str) -> None:
    with sc.act(who, when) as s:
        task = s.execute(select(Task).where(Task.object_id == object_id, Task.kind == kind, Task.status == "OPEN")
                         .order_by(Task.sequence)).scalars().first()
        if task is None:
            raise RuntimeError(f"no open {kind} task for {object_id}")
        workflow.complete(s, task.id, decision, comment)


def _pr(s, purpose_text: str) -> Requisition:
    return s.execute(select(Requisition).where(Requisition.purpose_text == purpose_text)).scalar_one()


def _invoice(s, supplier_invoice_no: str) -> Invoice:
    return s.execute(select(Invoice).where(Invoice.supplier_invoice_no == supplier_invoice_no)).scalar_one()


def _open_exception(s, invoice: Invoice, etype: str) -> InvoiceException:
    return s.execute(select(InvoiceException).where(InvoiceException.invoice_id == invoice.id, InvoiceException.type == etype,
                                                    InvoiceException.status == "OPEN")).scalar_one()


def _irn(supplier_code: str, number: str, on: date) -> str:
    from app.pic.services.payables import expected_irn
    return expected_irn(SUPPLIERS[supplier_code][1], clock.fiscal_year(on), "INV", number)


def _audit_load(s, ref: str, action: str, after: dict) -> None:
    audit.record(s, "MIGRATION", uuid.uuid5(uuid.NAMESPACE_URL, f"axn-branches:{ref}"), action, object_ref=ref, after=after, actor=CREATED_BY)


# ---------------------------------------------------------------- ERP inbound (TD §12.4): budgets, DC-345, demand
def _masters(sc: Scenario) -> None:
    clock.set_pinned(at(date(2027, 4, 1), 8, 30))
    with tenant_tx(sc.tenant_id) as s:
        budgets = []
        for obj_type, code, control, lakh in AXN_BUDGETS_2027_28:
            exists = s.execute(select(Budget.id).where(Budget.cost_object_type == obj_type, Budget.cost_object_code == code,
                                                       Budget.fiscal_year == FY)).first()
            if exists is None:
                s.add(Budget(tenant_id=sc.tenant_id, cost_object_type=obj_type, cost_object_code=code, fiscal_year=FY, control=control,
                             amount_minor=lakh * L, committed_minor=0, consumed_minor=0))
                budgets.append(f"{obj_type}:{code}")
        if budgets:
            _audit_load(s, f"budgets-{FY}", "INITIAL_LOAD", {"fiscalYear": FY, "budgets": budgets})
        material = Material(
            tenant_id=sc.tenant_id, number=MATERIAL, description="Aluminium die-cast motor mount bracket DC-345", type="STOCK",
            material_group=CATEGORY, category=CATEGORY, base_uom="EA", valuation_class="3000", hsn_code="87089900", gst_rate=Decimal(18),
            mpn="AXN-DC-345", attributes={"alloy": "ADC12", "weight_kg": "0.45", "process": "HPDC", "programme": "EV motor housing"},
            mrp_type="PD", lot_size_policy="EXACT", safety_stock=Decimal(100), planned_delivery_days=7, gr_processing_days=1,
            quality_managed=True, standard_price_minor=18_600, annual_demand=Decimal(18000), status="ACTIVE", erp_synced=True)
        s.add(material)
        s.flush()
        s.add(Stock(tenant_id=sc.tenant_id, material_id=material.id, plant="P100", storage_location="0001", stock_type="UNRESTRICTED",
                    batch="", qty=Decimal(300)))
        changed = clock.now()
        for kind, ref, day, qty in (("SALES_ORDER", "SO-90412", date(2027, 4, 9), 1000), ("FORECAST", "FC-2027-05", date(2027, 5, 17), 2400),
                                    ("FORECAST", "FC-2027-06", date(2027, 6, 14), 2400)):
            s.add(DemandElement(tenant_id=sc.tenant_id, material_id=material.id, plant="P100", type=kind, reference=ref, req_date=day,
                                qty=Decimal(qty), changed_at=changed))
        _audit_load(s, "DC-345", "INITIAL_LOAD", {"material": MATERIAL, "mrpType": "PD", "openingStock": "300",
                                                  "demand": ["SO-90412 9 Apr 1,000", "FC-2027-05 17 May 2,400", "FC-2027-06 14 Jun 2,400"]})


def _demand_delta(sc: Scenario, when, *, move: tuple | None = None, new: tuple | None = None) -> None:
    clock.set_pinned(when)
    with tenant_tx(sc.tenant_id) as s:
        material = s.execute(select(Material).where(Material.number == MATERIAL)).scalar_one()
        after = {}
        if move:
            ref, day = move
            element = s.execute(select(DemandElement).where(DemandElement.reference == ref, DemandElement.material_id == material.id)).scalar_one()
            after["moved"] = {"reference": ref, "from": element.req_date.isoformat(), "to": day.isoformat()}
            element.req_date, element.changed_at = day, clock.now()
        if new:
            kind, ref, day, qty = new
            s.add(DemandElement(tenant_id=sc.tenant_id, material_id=material.id, plant="P100", type=kind, reference=ref, req_date=day,
                                qty=Decimal(qty), changed_at=clock.now()))
            after["new"] = {"type": kind, "reference": ref, "date": day.isoformat(), "qty": str(qty)}
        _audit_load(s, f"demand-{when.date().isoformat()}", "ERP_DELTA", {"material": MATERIAL, **after})


# ---------------------------------------------------------------- F8 onboarding steps (this pack's suppliers)
def _register_suppliers(sc: Scenario, password: str) -> dict:
    from app.pic.services import supplier as svc

    ids = {}
    for offset, (code, (name, gstin, _bank, portal, terms, inco, address, _certs, _scores)) in enumerate(SUPPLIERS.items()):
        with sc.act("supplier.manager", at(date(2027, 4, 1), 10, offset * 10)) as s:
            sup = svc.register(s, code=code, legal_name=name, gstin=gstin, pan=gstin[2:12], state_code="33",
                               contact_email=f"sales@{code.lower()}.example", categories=[CATEGORY], payment_terms=terms, incoterms=inco,
                               segment="STRATEGIC", address=address)
            ids[code] = sup.id
            s.add(AppUser(tenant_id=sc.tenant_id, email=email(portal), full_name=f"{name} – sales", password_hash=hash_password(password),
                          roles=["SUPPLIER_USER"], attributes={}, supplier_id=sup.id, mfa_enrolled=True))
    return ids


def _submit_profiles(sc: Scenario, ids: dict) -> dict:
    from app.pic.services import supplier as svc

    changes = {}
    for offset, (code, (name, _gstin, (ifsc, account), portal, _t, _i, _a, certs, _s)) in enumerate(SUPPLIERS.items()):
        with sc.act(portal, at(date(2027, 4, 1), 15, offset * 10)) as s:
            changes[code] = svc.submit_profile(
                s, s.get(Supplier, ids[code]), bank_account=account, ifsc=ifsc, holder_name=name,
                certificates=[{"type": t, "number": n, "issued_on": i, "expires_on": e, "mandatory_for": [CATEGORY]} for t, n, i, e in certs])["bankChange"]
    return changes


def _bank_callbacks(sc: Scenario, changes: dict) -> dict:
    from app.pic.services import supplier as svc

    ids = {}
    for offset, (code, number) in enumerate(changes.items()):
        name, ifsc = SUPPLIERS[code][0], SUPPLIERS[code][2][0]
        with sc.act("supplier.manager", at(date(2027, 4, 2), 11, offset * 10)) as s:
            change = s.execute(select(BankChangeRequest).where(BankChangeRequest.number == number)).scalar_one()
            svc.callback_verify(s, change, f"Called {name} on the landline in the GST registration; account holder and IFSC {ifsc} confirmed")
            ids[code] = change.id
    return ids


def _qualify(sc: Scenario, ids: dict) -> None:
    from app.pic.services import supplier as svc

    for offset, code in enumerate(SUPPLIERS):
        scores = SUPPLIERS[code][8]
        with sc.act("supplier.manager", at(date(2027, 4, 2), 17, offset * 10)) as s:
            svc.verify_certificates(s, s.get(Supplier, ids[code]), "IATF 16949 and ISO 14001 checked against the IATF database and the CB register")
            q = svc.start_qualification(s, s.get(Supplier, ids[code]), CATEGORY)
            svc.record_assessment(s, q, questionnaire={"capacity": "400 t and 800 t HPDC cells verified", "ppap": "level 3"},
                                  questionnaire_score=Decimal(scores[0]), audit_score=Decimal(scores[1]), sample_approval="PPAP_APPROVED")
            svc.decide_qualification(s, q, "QUALIFIED", f"Process audit {scores[1]}/100; IATF 16949 and ISO 14001 verified")
    sc.note("F8 SPD201 and AAC202 onboarded: bank dual-approved, ALU-DIECAST QUALIFIED")


def _vht_invite(sc: Scenario) -> str:
    from app.pic.services import invitations

    with sc.act("supplier.manager", at(date(2027, 4, 1), 11)) as s:
        return invitations.create(s, email=VHT["email"], legal_name=VHT["legal_name"], categories=[VHT["category"]])["token"]


def _vht_register(sc: Scenario, token: str, password: str) -> None:
    from app.pic.services import invitations

    clock.set_pinned(at(date(2027, 4, 3), 10, 5))
    # The registration rule rejects passwords containing common words; demo logins still use the dataset password (set below).
    portal_password = password if not invitations.password_errors(password, VHT["email"], VHT["legal_name"]) else "Kiln$Survey-2027"
    with tenant_tx(sc.tenant_id) as s:
        invitation = invitations.find(s, token, lock=True)
        invitations.register(s, invitation, s.get(Tenant, sc.tenant_id), legal_name=VHT["legal_name"], gstin=VHT["gstin"], pan=VHT["pan"],
                             state_code="33", address=VHT["address"], contact_name=VHT["contact"], email=VHT["email"],
                             password=portal_password, phone="+91 416 224 1187")
    if portal_password != password:
        with tenant_tx(sc.tenant_id) as s:
            s.execute(select(AppUser).where(AppUser.email == VHT["email"])).scalar_one().password_hash = hash_password(password)


def _vht_supplier_id(sc: Scenario) -> uuid.UUID:
    with tenant_tx(sc.tenant_id) as s:
        return s.execute(select(Supplier.id).where(Supplier.legal_name == VHT["legal_name"])).scalar_one()


# ---------------------------------------------------------------- the April 2027 timeline
def apply(tenant_code: str, password: str) -> dict:
    from app.pic.services import amendments, contract as contract_svc, mdm, order, payables, planning, receiving, requisition, risk, sourcing
    from app.pic.services import supplier as supplier_svc
    from app.pic.services.common import category_status

    sc = Scenario(_tenant_id(tenant_code), role_user=ROLES)
    with tenant_tx(sc.tenant_id) as s:
        if s.execute(select(Material.id).where(Material.number == MATERIAL)).first():
            raise RuntimeError(f"{MATERIAL} already exists in {tenant_code}; the branch cases need a tenant without them")

    # ============================================================ Thu 1 April
    d1 = date(2027, 4, 1)
    _masters(sc)
    supplier_ids = _register_suppliers(sc, password)
    vht_token = _vht_invite(sc)
    with sc.act("requester", at(d1, 11, 30)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="PRODUCTION_CONSUMABLES", purpose_text=PR_COOLANT, plant="P100", lines=[{
            "item_type": "FREE_TEXT", "purchase_type": "NON_STOCK", "description": "Water-based die-release agent for HPDC, 200 L drums",
            "material_group": "CHEM-DIE-RELEASE", "category": "MRO-CHEMICALS", "qty": "1200", "uom": "L", "price_est_minor": 24_500,
            "account_assignment_type": "COST_CENTER", "account_assignment_code": "4100", "need_date": "2027-04-20",
            "quotes": [{"supplier": "SPD201", "reference": "SPD/Q/27-28/0009", "date": "2027-03-29"}, {"supplier": "AAC202", "reference": "AAC-QTN-2703-114", "date": "2027-03-30"}, {"supplier": "Hosur Die Chem Pvt Ltd", "reference": "HDC/Q/0331", "date": "2027-03-31"}]}])
        coolant_chain = requisition.submit(s, pr)["chain"]
        coolant_id = pr.id
    with sc.act("requester", at(d1, 12)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="OFFICE_FACILITIES", purpose_text=PR_DESKS, plant="P100", lines=[{
            "item_type": "FREE_TEXT", "purchase_type": "NON_STOCK", "description": "Electric sit-stand workstation 1600 x 800 mm",
            "material_group": "FURN-OFFICE", "category": "FACILITIES", "qty": "6", "uom": "EA", "price_est_minor": 3_850_000,
            "account_assignment_type": "COST_CENTER", "account_assignment_code": "4100", "need_date": "2027-04-30",
            "quotes": [{"supplier": "Featherlite Workspace Pvt Ltd", "reference": "FWS-Q-27-0412", "date": "2027-03-26"}, {"supplier": "Godrej Interio dealer Hosur", "reference": "GIH/QTN/2703/88", "date": "2027-03-29"}, {"supplier": "Krishna Office Systems", "reference": "KOS-271", "date": "2027-03-30"}]}])
        requisition.submit(s, pr)
        desks_id = pr.id
    with sc.act("requester", at(d1, 12, 30)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="NEW_PART_LAUNCH", purpose_text=PR_PPAP, plant="P100", lines=[{
            "item_type": "FREE_TEXT", "purchase_type": "NON_STOCK", "description": "PPAP sample castings DC-345, 50 pcs off the production tool",
            "material_group": "41-PPAP-SAMPLES", "category": CATEGORY, "qty": "50", "uom": "EA", "price_est_minor": 115_000,
            "account_assignment_type": "COST_CENTER", "account_assignment_code": "4100", "need_date": "2027-04-20",
            "quotes": [{"supplier": "AAC202", "reference": "AAC-QTN-2703-121", "date": "2027-03-31"}]}])
        requisition.submit(s, pr)
        ppap_id, ppap_no = pr.id, pr.number
    with sc.act("requester", at(d1, 13)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="MAINTENANCE", purpose_text=PR_THERMAL, plant="P100", lines=[{
            "item_type": "FREE_TEXT", "purchase_type": "SERVICE", "description": "Thermal imaging survey of HPDC cell 3 dies, ladle and shot sleeve",
            "material_group": "SVC-TOOLING", "category": "TOOLING-SERVICES", "qty": "1", "uom": "EA", "price_est_minor": 4_200_000,
            "account_assignment_type": "COST_CENTER", "account_assignment_code": "4100", "need_date": "2027-04-16",
            "quotes": [{"supplier": "HTS004", "reference": "HTS/Q/27-28/0003", "date": "2027-03-31"}]}])
        requisition.submit(s, pr)
        thermal_id, thermal_no = pr.id, pr.number
    with sc.act("contract.manager", at(d1, 14)) as s:
        material = s.execute(select(Material).where(Material.number == MATERIAL)).scalar_one()
        bridge = contract_svc.create_draft(
            s, type="QUANTITY_CONTRACT", title=BRIDGE, supplier_id=supplier_ids["SPD201"], company_code="1000", valid_from=date(2027, 4, 5),
            valid_to=date(2027, 4, 24), payment_terms="N45", incoterms="FCA Sriperumbudur",
            lines=[{"material_id": material.id, "description": material.description, "plant": "P100", "uom": "EA", "target_qty": "1000",
                    "unit_price_minor": 18_600}],
            owner_id=s.info["principal"].user_id, tolerances={"over_pct": "2", "under_pct": "5", "price_pct": "0"})
        contract_svc.ai_review(s, bridge)
        bridge_chain = contract_svc.submit(s, bridge)["chain"]
        bridge_id, bridge_no = bridge.id, bridge.number
    bank_changes = _submit_profiles(sc, supplier_ids)
    with sc.act("buyer", at(d1, 15, 30)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="ANNUAL_SOURCING", purpose_text=PR_ANNUAL, plant="P100", lines=[{
            "item_type": "MATERIAL", "purchase_type": "STOCK", "material": MATERIAL, "qty": "18000", "price_est_minor": 18_600,
            "need_date": "2027-05-17", "storage_location": "0001"}])
        requisition.submit(s, pr)
        annual_id, annual_no = pr.id, pr.number
    _relay(sc, at(d1, 17))

    # ============================================================ Fri 2 April
    d2 = date(2027, 4, 2)
    with sc.act("mrp.controller", at(d2, 9)) as s:
        simulation = planning.run(s, plant="P100", mode="SIMULATION", materials=[MATERIAL], run_date=d2)
        sim_no, sim_status, sim_net = simulation.number, simulation.status, simulation.results[0]["net"]
    with sc.act("mrp.controller", at(d2, 9, 30)) as s:
        run1 = planning.run(s, plant="P100", mode="NET_CHANGE", materials=[MATERIAL], run_date=d2)
        run1_no, run1_codes = run1.number, sorted(e["code"] for r in run1.results for e in r["exceptions"])
        plo_a_id, plo_b_id = [o.id for o in s.execute(select(PlannedOrder).where(PlannedOrder.mrp_run_id == run1.id)
                                                      .order_by(PlannedOrder.need_date)).scalars()][:2]
    with sc.act("mrp.controller", at(d2, 10)) as s:
        a, b = s.get(PlannedOrder, plo_a_id), s.get(PlannedOrder, plo_b_id)
        planning.firm(s, a)
        planning.firm(s, b)
        mrp_pr = planning.convert(s, a)
        mrp_pr_id, mrp_pr_no, plo_a_no, plo_b_no = mrp_pr.id, mrp_pr.number, a.number, b.number
    _decide(sc, "plant.controller", at(d2, 10, 15), coolant_id, "REQ_APPROVAL", "RETURN",
            "Quantity covers six months of cell 3 consumption (log book ~95 L/week); order the quarter (600 L) at the 600 L price break")
    _decide(sc, "plant.controller", at(d2, 11), desks_id, "REQ_APPROVAL", "APPROVE", "Ergonomics finding EHS-27-014 for the drawing office")
    bank_ids = _bank_callbacks(sc, bank_changes)
    sc.approve_all(ppap_id, at(d2, 11, 30), "PPAP samples for the EV bracket launch")
    sc.approve_all(thermal_id, at(d2, 11, 45), "Annual thermal survey due")
    _decide(sc, "contract.manager2", at(d2, 12), bridge_id, "CONTRACT_APPROVAL", "REJECT",
            "Quality clause must cite drawing AXN-DC-345 rev B and the approved PPAP (level 3) before signature")
    sc.approve_all(mrp_pr_id, at(d2, 14), "SO-90412 launch lot; past-due release accepted, expedite")
    for offset, code in enumerate(bank_ids):
        sc.approve_all(bank_ids[code], at(d2, 15, offset * 10), "Cancelled cheque and bank letter match the call-back")
    sc.approve_all(annual_id, at(d2, 16), "Annual requirement for the EV programme; source by RFQ")
    _qualify(sc, supplier_ids)
    _relay(sc, at(d2, 17, 30))
    sc.note(f"Case 11: {sim_no} {sim_status}, net {sim_net}, no planned orders")
    sc.note(f"Case 12: {run1_no} {run1_codes} → {plo_a_no} (800 for 9 Apr) and {plo_b_no} (2,400 for 17 May) firmed; "
            f"{plo_a_no} → {mrp_pr_no} approved")

    # ============================================================ Sat 3 April
    d3 = date(2027, 4, 3)
    with sc.act("requester", at(d3, 10)) as s:
        pr = s.get(Requisition, coolant_id)
        requisition.change_line(s, pr, 10, {"qty": "600", "price_est_minor": 25_200})
        resubmitted_chain = requisition.submit(s, pr)["chain"]
    _vht_register(sc, vht_token, password)
    with sc.act("spd.sales", at(d3, 10, 30)) as s:
        contract_svc.redline(s, s.get(Contract, bridge_id), "QUALITY",
                             "Goods conform to drawing AXN-DC-345 rev B and the approved PPAP (level 3) submission; a certificate of "
                             "conformity and the X-ray report accompany each lot.", "STANDARD")
    _decide(sc, "ops.head", at(d3, 11), desks_id, "REQ_APPROVAL", "REJECT",
            "Not in the FY 2027-28 facilities plan; office furniture is bought by Administration (CC 4200) in the Q2 wave")
    with sc.act("contract.manager", at(d3, 11, 30)) as s:
        # A supplier redline is non-standard until the contract manager reviews it: the drawing reference is accepted as standard.
        contract_svc.review_redline(s, s.get(Contract, bridge_id), "QUALITY", "ACCEPT", "STANDARD",
                                    "Drawing revision and PPAP reference match the playbook quality clause")
        contract_svc.ai_review(s, s.get(Contract, bridge_id))
        contract_svc.submit(s, s.get(Contract, bridge_id))
    with sc.act("category.manager", at(d3, 12)) as s:
        event = sourcing.create_event(
            s, type="RFQ", title=RFQ_TITLE, category=CATEGORY,
            lines=[{"requisition": annual_no, "line": 10, "annual_qty": "18000", "monthly_qty": "1500"}], criteria=CRITERIA,
            invitees=[{"supplier": "SPD201"}, {"supplier": "AAC202"}], close_at=at(date(2027, 4, 7), 17), baseline_price_minor=18_600,
            should_cost_params={"net_weight_kg": "0.45", "alloy_rate_per_kg": "215", "cycle_time_min": "1.8", "machine_rate_per_min": "18",
                                "tooling_amortisation": "6", "packaging": "3", "overhead_margin_pct": "15"},
            savings_target_pct=Decimal("2.0"))
        sourcing.publish(s, event)
        event_id, event_no = event.id, event.number
    _relay(sc, at(d3, 12, 30))
    sc.note(f"Case 9: coolant PR chain {coolant_chain} → returned → 600 L resubmitted, chain {resubmitted_chain}")
    sc.note("Case 10: workstations PR approved by the cost-object owner, rejected by the department head")

    # ============================================================ Mon 5 April
    d5 = date(2027, 4, 5)
    sc.approve_all(coolant_id, at(d5, 10), "Quarterly quantity at the price break")
    sc.approve_all(bridge_id, at(d5, 10, 15), "PPAP reference added; value below ₹1 Cr, standard clauses")
    with sc.act("buyer", at(d5, 10, 30)) as s:
        po_d = order.create_from_requisition(s, requisition=ppap_no, lines=[10], supplier_code="AAC202", unit_price_minor=115_000)[0]
        po_d_id, po_d_no = po_d.id, po_d.number
    with sc.act("contract.manager", at(d5, 11)) as s:
        contract_svc.sign(s, s.get(Contract, bridge_id), "BUYER", "Ganesh Murthy, Contract Manager")
    sc.approve_all(po_d_id, at(d5, 11, 30), "Quote AAC-Q-2704-06 attached")
    with sc.act("spd.sales", at(d5, 12)) as s:
        contract_svc.sign(s, s.get(Contract, bridge_id), "SUPPLIER", "Authorised signatory, Sriperumbudur Precision Diecast")
    with sc.act("contract.manager", at(d5, 14)) as s:
        contract_svc.activate(s, s.get(Contract, bridge_id))
    renewal_fired = _fire(sc, "CONTRACT_RENEWAL", bridge_id, at(d5, 14, 5))  # the 120-day notice lies before this 3-week bridge started
    with sc.act("buyer", at(d5, 14, 30)) as s:
        po_s0 = order.create_from_requisition(s, requisition=thermal_no, lines=[10], supplier_code="HTS004", unit_price_minor=4_800_000)[0]
        po_s0_id, po_s0_no = po_s0.id, po_s0.number
    _decide(sc, "buyer.lead", at(d5, 14, 45), po_s0_id, "PO_APPROVAL", "REJECT",
            "₹48,000 does not match HTS quote HTS-Q-1288 (₹42,000 incl. report); re-raise at the quoted rate")
    with sc.act("buyer", at(d5, 14, 50)) as s:
        po_s0_status = s.get(PurchaseOrder, po_s0_id).status
        order.cancel(s, s.get(PurchaseOrder, po_s0_id), "Raised at the wrong rate; replaced by a PO at the quoted ₹42,000")
    with sc.act("buyer", at(d5, 15)) as s:
        po_s = order.create_from_requisition(s, requisition=thermal_no, lines=[10], supplier_code="HTS004", unit_price_minor=4_200_000)[0]
        po_s_id, po_s_no = po_s.id, po_s.number
    sc.approve_all(po_s_id, at(d5, 15, 30), "Rate as per HTS quote HTS-Q-1288")
    with sc.act("contract.manager", at(d5, 15, 45)) as s:
        hts_id = s.execute(select(Supplier.id).where(Supplier.code == "HTS004")).scalar_one()
        amc = contract_svc.create_draft(
            s, type="VALUE_CONTRACT", title=AMC, supplier_id=hts_id, company_code="1000", valid_from=date(2027, 4, 6),
            valid_to=date(2027, 7, 31), payment_terms="N30", incoterms=None,
            lines=[{"material_id": None, "description": "Die maintenance technician – rate per hour", "plant": "P100", "uom": "H",
                    "target_qty": "320", "unit_price_minor": 300_000}],
            owner_id=s.info["principal"].user_id, tolerances={"over_pct": "0", "under_pct": "0", "price_pct": "0"})
        contract_svc.ai_review(s, amc)
        contract_svc.submit(s, amc)
        amc_id, amc_no = amc.id, amc.number
    with sc.act("aac.sales", at(d5, 16)) as s:
        order.confirm(s, s.get(PurchaseOrder, po_d_id), "REJECTED",
                      note="Our 400 t cell is committed to another OEM programme until June; we cannot cast PPAP samples before 20 Apr")
    _relay(sc, at(d5, 17))

    # ============================================================ Tue 6 April
    d6 = date(2027, 4, 6)
    with sc.act("buyer", at(d6, 10)) as s:
        po_a = order.create_from_requisition(s, requisition=mrp_pr_no, lines=[10])[0]
        po_a_id, po_a_no, po_a_touchless = po_a.id, po_a.number, po_a.touchless
    _relay(sc, at(d6, 10, 5))
    with sc.act("hts.service", at(d6, 10, 10)) as s:
        order.confirm(s, s.get(PurchaseOrder, po_s_id), "CONFIRMED")
    _decide(sc, "buyer.lead", at(d6, 10, 15), po_d_id, "PO_CHANGE_REVIEW", "REJECT", "Supplier rejected the order; cancel and re-source")
    with sc.act("buyer", at(d6, 10, 30)) as s:
        cancelled = order.cancel(s, s.get(PurchaseOrder, po_d_id), "AAC202 rejected the order on 5 Apr (no capacity before June); re-sourced")
        ppap_after_cancel = s.get(Requisition, ppap_id).status
    _relay(sc, at(d6, 10, 35))
    with sc.act("buyer", at(d6, 11)) as s:
        po_e = order.create_from_requisition(s, requisition=ppap_no, lines=[10], supplier_code="SPD201", unit_price_minor=118_000)[0]
        po_e_id, po_e_no = po_e.id, po_e.number
    sc.approve_all(amc_id, at(d6, 11, 15), "Trial rate contract below ₹1 Cr; standard clauses")
    sc.approve_all(po_e_id, at(d6, 12), "Re-sourced to SPD201 (quote SPD-Q-0406, ₹1,180/pc)")
    with sc.act("contract.manager", at(d6, 12, 15)) as s:
        contract_svc.sign(s, s.get(Contract, amc_id), "BUYER", "Ganesh Murthy, Contract Manager")
    with sc.act("hts.service", at(d6, 13)) as s:
        contract_svc.sign(s, s.get(Contract, amc_id), "SUPPLIER", "Authorised signatory, Hosur Tooling Services")
    with sc.act("contract.manager", at(d6, 14)) as s:
        contract_svc.activate(s, s.get(Contract, amc_id))
    _fire(sc, "CONTRACT_RENEWAL", amc_id, at(d6, 14, 5))
    with sc.act("spd.sales", at(d6, 15)) as s:
        order.confirm(s, s.get(PurchaseOrder, po_a_id), "CONFIRMED", note="Dispatch 8 Apr from the transferred die")
    bids = (("spd.sales", 10, ("182", "1.50", 45, 10, "2500")), ("aac.sales", 70, ("189", "1.20", 60, 21, "1500")))
    for who, minute, (price, freight, terms, lead, capacity) in bids:
        with sc.act(who, at(d6, 15, 0) + timedelta(minutes=minute)) as s:
            sourcing.submit_bid(s, s.get(SourcingEvent, event_id), s.get(Supplier, s.info["principal"].supplier_id),
                                [{"line": 10, "unit_price": price, "freight": freight, "packaging": "0.80", "payment_terms_days": terms,
                                  "lead_time_days": lead, "capacity_per_month": capacity}])
    with sc.act(VHT["email"], at(d6, 15, 30)) as s:
        vht_change_no = supplier_svc.submit_profile(
            s, s.get(Supplier, _vht_supplier_id(sc)), bank_account="2917101004455", ifsc="CNRB0002917", holder_name=VHT["legal_name"],
            certificates=[{"type": "ISO9001", "number": "QMS-VHT-0110", "issued_on": "2025-01-10", "expires_on": "2028-01-09"}])["bankChange"]
    _decide(sc, "contract.manager", at(d6, 16), amc_id, "CONTRACT_RENEWAL", "APPROVE",
            "Trial KPIs met (MTTR 3.1 h against a 4 h target); extend for FY 2027-28")
    _relay(sc, at(d6, 17))

    # ============================================================ Wed 7 April
    d7 = date(2027, 4, 7)
    _decide(sc, "contract.manager", at(d7, 10), bridge_id, "CONTRACT_RENEWAL", "REJECT",
            "Bridge ends with the tool transfer on 24 Apr; the annual requirement from May is out to RFQ")
    with sc.act("buyer", at(d7, 10, 10)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="BUFFER_BUILD", purpose_text=PR_TOPUP, plant="P100", lines=[{
            "item_type": "MATERIAL", "purchase_type": "STOCK", "material": MATERIAL, "qty": "200", "price_est_minor": 18_600,
            "need_date": "2027-04-13", "storage_location": "0001"}])
        requisition.submit(s, pr)
        topup_id, topup_no = pr.id, pr.number
    with sc.act("requester", at(d7, 10, 20)) as s:
        oil = mdm.create_request(s, description=MRQ_OIL, type="NON_STOCK", material_group="LUB-HYD", category="MRO-LUBRICANTS", base_uom="L",
                                 hsn_code="27101980", attributes={"viscosity": "ISO VG 46", "pack": "210 L drum"})
        oil_id = oil.id
    with sc.act("contract.manager", at(d7, 10, 30)) as s:
        draft = s.execute(select(ContractAmendment).where(ContractAmendment.contract_id == amc_id,
                                                          ContractAmendment.status == "DRAFT")).scalar_one()
        amendments.submit(s, draft)
        extension_no = draft.number
    with sc.act("buyer", at(d7, 11)) as s:
        warn = mdm.create_request(s, description=MRQ_WARN, type="STOCK", material_group=CATEGORY, category=CATEGORY, base_uom="EA",
                                  valuation_class="3000", hsn_code="87089900", mpn="AXN-DC-345",
                                  attributes={"alloy": "ADC12", "weight_kg": "0.42", "process": "HPDC + CNC"})
        warn_id, warn_score = warn.id, warn.duplicate_score
        block = mdm.create_request(s, description=MRQ_BLOCK, type="STOCK", material_group=CATEGORY, category=CATEGORY, base_uom="EA",
                                   valuation_class="7920", hsn_code="87089900", mpn="AXN-DC-345",
                                   attributes={"alloy": "ADC12", "weight_kg": "0.45", "process": "HPDC", "programme": "EV motor housing"})
        block_id, block_score, block_status = block.id, block.duplicate_score, block.status
    sla_fired = _fire(sc, "PO_CONFIRMATION_SLA", po_e_id, at(d7, 12, 30))
    _decide(sc, "buyer.lead", at(d7, 14), po_e_id, "EXPEDITE", "APPROVE", "Called SPD201 sales: confirmation promised today")
    sc.approve_all(topup_id, at(d7, 14, 10), "Launch-lot top-up")
    sc.approve_all(amc_id, at(d7, 15), "Extension at the trial rates approved")
    with sc.act("spd.sales", at(d7, 16)) as s:
        order.confirm(s, s.get(PurchaseOrder, po_e_id), "CONFIRMED", note="Samples cast on 10 Apr, dispatch 12 Apr")
    _relay(sc, at(d7, 17))
    _fire(sc, "SOURCING_CLOSE", event_id, at(d7, 17, 5))

    # ============================================================ Thu 8 April
    d8 = date(2027, 4, 8)
    _demand_delta(sc, at(d8, 8), move=("FC-2027-05", date(2027, 6, 7)))
    with sc.act("spd.sales", at(d8, 9)) as s:
        asn_a_id = receiving.create_asn(
            s, s.get(PurchaseOrder, po_a_id), lines=[{"line": 10, "qty": "800", "batches": [{"batch": "SPD-2704-01", "qty": "800"}]}],
            ship_date=d8, expected_date=date(2027, 4, 9), eway_bill_no="331012457890", vehicle_no="TN19AF7342", distance_km=150,
            documents=["CoC-SPD-2704-01", "XRAY-SPD-2704-01"]).id
    with sc.act("mrp.controller", at(d8, 9, 30)) as s:
        run2 = planning.run(s, plant="P100", mode="NET_CHANGE", materials=[MATERIAL], run_date=d8)
        run2_no, run2_codes = run2.number, sorted(e["code"] for r in run2.results for e in r["exceptions"])
    with sc.act("mdm.purchasing", at(d8, 10)) as s:
        task = s.execute(select(Task).where(Task.object_id == oil_id, Task.status == "OPEN",
                                            Task.candidate_scope["steward_domain"].astext == "PURCHASING")).scalar_one()
        workflow.complete(s, task.id, "APPROVE", "Purchasing data complete")
    for who, minute, entries in (("quality.engineer", 15, [("SPD201", "QUALITY", 84), ("AAC202", "QUALITY", 80), ("SPD201", "TECHNICAL", 82),
                                                            ("AAC202", "TECHNICAL", 78)]),
                                 ("category.head", 20, [("SPD201", "QUALITY", 82), ("AAC202", "QUALITY", 79), ("SPD201", "DELIVERY", 85),
                                                        ("AAC202", "DELIVERY", 72), ("SPD201", "ESG", 75), ("AAC202", "ESG", 74)])):
        with sc.act(who, at(d8, 10, minute)) as s:
            sourcing.score(s, s.get(SourcingEvent, event_id), [{"supplier": a, "criterion": b, "score": c} for a, b, c in entries])
    with sc.act("mdm.quality", at(d8, 10, 30)) as s:
        task = s.execute(select(Task).where(Task.object_id == oil_id, Task.status == "OPEN",
                                            Task.candidate_scope["steward_domain"].astext == "QUALITY")).scalar_one()
        workflow.complete(s, task.id, "REJECT", "No technical datasheet; the HPDC hydraulic units need HLP 46 to DIN 51524-2. "
                                                "Resubmit with the datasheet and the machine OEM approval")
    with sc.act("requester", at(d8, 10, 40)) as s:
        reapproval = requisition.change_line(s, s.get(Requisition, coolant_id), 10, {"qty": "720"})
    sc.approve_all(warn_id, at(d8, 11), "Machined RH variant: same casting MPN by design, own routing and valuation")
    with sc.act("supplier.manager", at(d8, 11, 5)) as s:
        change = s.execute(select(BankChangeRequest).where(BankChangeRequest.number == vht_change_no)).scalar_one()
        supplier_svc.callback_verify(s, change, "Called Vellore Heat Treaters accounts on the GST-registered landline; IFSC and holder confirmed")
        vht_change_id = change.id
    with sc.act("buyer", at(d8, 11, 20)) as s:
        po_b = order.create_from_requisition(s, requisition=topup_no, lines=[10], release_qty=Decimal(100))[0]
        po_b_id, po_b_no = po_b.id, po_b.number
    _relay(sc, at(d8, 11, 25))
    with sc.act("mdm.purchasing", at(d8, 11, 30)) as s:
        mdm.steward_override(s, s.get(MaterialRequest, block_id),
                             "E-coated aftermarket variant: same casting and MPN, different finish, valuation class 7920 and sales price; "
                             "separate material number approved by the product owner (ECN-27-118)")
    with sc.act("buyer", at(d8, 11, 35)) as s:
        po_c = order.create_from_requisition(s, requisition=topup_no, lines=[10], release_qty=Decimal(100))[0]
        po_c_id, po_c_no = po_c.id, po_c.number
    _relay(sc, at(d8, 11, 40))
    sc.approve_all(block_id, at(d8, 12), "Aftermarket variant data complete")
    with sc.act("category.manager", at(d8, 14)) as s:
        options = sourcing.build_scenarios(s, s.get(SourcingEvent, event_id))
        lowest = next(o for o in options if o["kind"] == "LOWEST_COST")
        decision = sourcing.propose_award(s, s.get(SourcingEvent, event_id), uuid.UUID(lowest["id"]), None,
                                          "No personal or financial interest in any bidder.")
        award_status, award_value = s.get(SourcingEvent, event_id).status, decision.annual_value_minor
    _relay(sc, at(d8, 14, 5))
    with sc.act("spd.sales", at(d8, 15)) as s:
        order.confirm(s, s.get(PurchaseOrder, po_b_id), "CONFIRMED", lines=[{"line": 10, "need_date": "2027-04-16"}],
                      note="Trial lot from the transferred die: first-off approval on 14 Apr, dispatch 15 Apr")
    sc.approve_all(vht_change_id, at(d8, 15, 15), "Bank letter verified")
    sc.approve_all(coolant_id, at(d8, 15, 20), "Cell 3 trial confirmed the higher consumption")
    with sc.act("spd.sales", at(d8, 15, 30)) as s:
        order.confirm(s, s.get(PurchaseOrder, po_c_id), "CONFIRMED", lines=[{"line": 10, "unit_price": "192"}],
                      note="LME alloy surcharge of ₹6/pc from April")
    _relay(sc, at(d8, 17))

    # ============================================================ Fri 9 April
    d9 = date(2027, 4, 9)
    _decide(sc, "buyer.lead", at(d9, 10), po_b_id, "PO_CHANGE_REVIEW", "APPROVE", "16 Apr still covers the SO-90412 top-up")
    with sc.act("receiver", at(d9, 10, 15)) as s:
        gr_a = receiving.post_gr(s, s.get(PurchaseOrder, po_a_id), asn=s.get(Asn, asn_a_id), delivery_note="DN-SPD-1172",
                                 lines=[{"line": 10, "qty": "800", "batch": "SPD-2704-01"}], posting_date=d9)
        gr_a_id, gr_a_no = gr_a.id, gr_a.number
    _decide(sc, "buyer.lead", at(d9, 10, 30), po_c_id, "PO_CHANGE_REVIEW", "REJECT",
            "Bridge contract price ₹186 is fixed (price tolerance 0 %); the surcharge is not accepted")
    with sc.act("contract.manager", at(d9, 10, 45)) as s:
        sa = s.execute(select(Contract).where(Contract.source_event_id == event_id)).scalar_one()
        contract_svc.ai_review(s, sa)
        sa_chain = contract_svc.submit(s, sa)["chain"]
        sa_id, sa_no = sa.id, sa.number
    integration.FAULTS["fail"] = 1  # the SAP sandbox does not answer the first GR posting
    try:
        with sc.act("quality.inspector", at(d9, 15)) as s:
            receiving.usage_decision(s, s.execute(select(InspectionLot).where(InspectionLot.gr_id == gr_a_id)).scalar_one(),
                                     accepted=Decimal(800), rejected=Decimal(0))
    finally:
        integration.FAULTS["fail"] = 0
    gr_first = _message(sc, f"GR|{gr_a_no}")
    gr_retry = _worker_attempt(sc, f"GR|{gr_a_no}", gr_first.next_attempt_at)
    with sc.act("spd.sales", at(d9, 16)) as s:
        order.confirm(s, s.get(PurchaseOrder, po_b_id), "CONFIRMED", note="v2 accepted: dispatch 15 Apr")
    with sc.act("spd.sales", at(d9, 16, 30)) as s:
        order.confirm(s, s.get(PurchaseOrder, po_c_id), "CONFIRMED", note="Confirmed at ₹186 as per the bridge contract")
    _relay(sc, at(d9, 17))

    # ============================================================ Sat 10 April: invoice posting runs into an ERP outage
    d10 = date(2027, 4, 10)
    with sc.act("spd.sales", at(d10, 10)) as s:
        number = "SPD/27-28/0012"
        payables.capture(s, supplier="SPD201", supplier_invoice_no=number, invoice_date=d10, channel="E_INVOICE", irn=_irn("SPD201", number, d10),
                         lines=[{"po": po_a_no, "po_line": 10, "qty": "800", "unit_price": "186", "gst_rate": "18", "hsn": "87089900"}])
    _decide(sc, "contract.manager2", at(d10, 10, 30), sa_id, "CONTRACT_APPROVAL", "APPROVE", "Award below ₹1 Cr; standard SA clauses")
    posting_key = "AXN|1000|SPD201|SPD/27-28/0012"
    integration.FAULTS["fail"] = 8  # every attempt times out: the posting itself and seven worker retries → dead letter
    try:
        with sc.act("ap.clerk", at(d10, 11)) as s:
            invoice = _invoice(s, "SPD/27-28/0012")
            payables.approve(s, invoice)
            first_post = payables.post(s, invoice, posting_key)
        message = _message(sc, posting_key)
        while message.status == "RETRY":
            message = _worker_attempt(sc, posting_key, message.next_attempt_at)
    finally:
        integration.FAULTS["fail"] = 0
    dead = (message.status, message.attempts, message.last_error)
    _relay(sc, at(d10, 16))

    # ============================================================ Mon 12 April
    d12 = date(2027, 4, 12)
    with sc.act("spd.sales", at(d12, 9, 30)) as s:
        pcr_no = order.request_change(s, s.get(PurchaseOrder, po_c_id), [{"line": 10, "need_date": "2027-04-18"}],
                                      "Shot-blasting machine breakdown at Sriperumbudur; propose to ship on 17 Apr").number
    _decide(sc, "buyer.lead", at(d12, 11, 30), po_c_id, "PO_CHANGE_REQUEST", "REJECT",
            "Line-side stock for SO-90412 is needed on 14 Apr; use the standby shot-blaster at your Oragadam unit")
    with sc.act("spd.sales", at(d12, 9)) as s:
        asn_e_id = receiving.create_asn(
            s, s.get(PurchaseOrder, po_e_id), lines=[{"line": 10, "qty": "50", "batches": [{"batch": "SPD-PPAP-01", "qty": "50"}]}],
            ship_date=d12, expected_date=date(2027, 4, 13), eway_bill_no="331012458112", vehicle_no="TN19AF7342", distance_km=150,
            documents=["PPAP-L3-DC-345", "CoC-SPD-PPAP-01"]).id
    with sc.act("admin", at(d12, 10)) as s:
        replayed = integration.replay(s, s.execute(select(IntegrationMessage).where(IntegrationMessage.idempotency_key == posting_key)).scalar_one().id)
        replay_status, replay_doc = replayed.status, replayed.erp_doc_no
    _relay(sc, at(d12, 10, 5))
    with sc.act("contract.manager", at(d12, 10, 30)) as s:
        contract_svc.sign(s, s.get(Contract, sa_id), "BUYER", "Ganesh Murthy, Contract Manager")
    with sc.act("supplier.manager", at(d12, 11)) as s:
        q = s.execute(select(Qualification).where(Qualification.supplier_id == _vht_supplier_id(sc), Qualification.status == "OPEN")).scalar_one()
        supplier_svc.record_assessment(s, q, questionnaire={"furnaces": "2 sealed-quench, 1 tempering", "tus": "last survey Feb 2026"},
                                       questionnaire_score=Decimal(71), audit_score=Decimal(58))
        vht_result = supplier_svc.decide_qualification(
            s, q, "REJECTED", "Process audit 58/100: temperature uniformity survey overdue (last TUS Feb 2026), no AMS 2750 instrument "
                              "class records for the sealed-quench line, quench-oil analysis not traceable; re-audit after corrective action")
    with sc.act("spd.sales", at(d12, 12)) as s:
        contract_svc.sign(s, s.get(Contract, sa_id), "SUPPLIER", "Authorised signatory, Sriperumbudur Precision Diecast")
    with sc.act("contract.manager", at(d12, 15)) as s:
        contract_svc.activate(s, s.get(Contract, sa_id))
    _relay(sc, at(d12, 17))

    # ============================================================ Tue 13 April
    d13 = date(2027, 4, 13)
    with sc.act("spd.sales", at(d13, 9)) as s:
        asn_c_id = receiving.create_asn(
            s, s.get(PurchaseOrder, po_c_id), lines=[{"line": 10, "qty": "100", "batches": [{"batch": "SPD-2704-03", "qty": "100"}]}],
            ship_date=d13, expected_date=date(2027, 4, 14), vehicle_no="TN19AF7342", distance_km=150, documents=["CoC-SPD-2704-03"]).id
    with sc.act("buyer", at(d13, 10)) as s:
        closed_a = order.close(s, s.get(PurchaseOrder, po_a_id), "Received, inspected and invoiced in full (SPD/27-28/0012 posted)")
    with sc.act("receiver", at(d13, 10, 30)) as s:
        receiving.post_gr(s, s.get(PurchaseOrder, po_e_id), asn=s.get(Asn, asn_e_id), delivery_note="DN-SPD-1185",
                          lines=[{"line": 10, "qty": "50"}], posting_date=d13)
    with sc.act("spd.sales", at(d13, 14)) as s:
        payables.capture(s, supplier="SPD201", supplier_invoice_no="SPD/27-28/0017", invoice_date=d13, channel="E_INVOICE",
                         irn=_irn("SPD201", "SPD/27-28/0071", d13),  # IRN generated for a mistyped document number
                         lines=[{"po": po_e_no, "po_line": 10, "qty": "50", "unit_price": "1180", "gst_rate": "18"}])
    with sc.act("ap.clerk", at(d13, 16)) as s:
        bad = _invoice(s, "SPD/27-28/0017")
        tax_exception = _open_exception(s, bad, "TAX").type
        payables.reject(s, bad, "IRN does not belong to SPD/27-28/0017 (hash mismatch at verification); supplier to cancel the "
                                "e-invoice on the IRP and re-issue")
    _relay(sc, at(d13, 17))

    # ============================================================ Wed 14 April
    d14 = date(2027, 4, 14)
    with sc.act("receiver", at(d14, 10)) as s:
        wrong = receiving.post_gr(s, s.get(PurchaseOrder, po_b_id), delivery_note="DN-SPD-1190",
                                  lines=[{"line": 10, "qty": "100", "batch": "SPD-2704-03"}], posting_date=d14)
        wrong_id, wrong_no = wrong.id, wrong.number
    with sc.act("spd.sales", at(d14, 10, 30)) as s:
        number = "SPD/27-28/0018"
        payables.capture(s, supplier="SPD201", supplier_invoice_no=number, invoice_date=d14, channel="E_INVOICE", irn=_irn("SPD201", number, d14),
                         lines=[{"po": po_e_no, "po_line": 10, "qty": "50", "unit_price": "1180", "gst_rate": "18"}])
    with sc.act("ap.clerk", at(d14, 11)) as s:
        good = _invoice(s, "SPD/27-28/0018")
        payables.approve(s, good)
        payables.post(s, good, "AXN|1000|SPD201|SPD/27-28/0018")
    with sc.act("receiver", at(d14, 11, 30)) as s:
        receiving.reverse_gr(s, s.get(GoodsReceipt, wrong_id), "Delivery note DN-SPD-1190 and its ASN belong to the second call-off; posted "
                                                                "against the first by mistake (both 100 pcs DC-345 from SPD201)")
        po_b_after_reversal = s.get(PurchaseOrder, po_b_id).status
    with sc.act("receiver", at(d14, 11, 45)) as s:
        gr_c_id = receiving.post_gr(s, s.get(PurchaseOrder, po_c_id), asn=s.get(Asn, asn_c_id), delivery_note="DN-SPD-1190",
                                    lines=[{"line": 10, "qty": "100", "batch": "SPD-2704-03"}], posting_date=d14).id
    _relay(sc, at(d14, 12))
    with sc.act("buyer", at(d14, 15)) as s:
        closed_e = order.close(s, s.get(PurchaseOrder, po_e_id), "PPAP samples received and invoiced")
    with sc.act("quality.inspector", at(d14, 16)) as s:
        receiving.usage_decision(s, s.execute(select(InspectionLot).where(InspectionLot.gr_id == gr_c_id)).scalar_one(),
                                 accepted=Decimal(100), rejected=Decimal(0))
    _relay(sc, at(d14, 17))

    # ============================================================ Thu 15 April
    d15 = date(2027, 4, 15)
    _demand_delta(sc, at(d15, 8), new=("SALES_ORDER", "SO-90437", date(2027, 4, 28), 1200))
    with sc.act("spd.sales", at(d15, 9)) as s:
        asn_b_id = receiving.create_asn(
            s, s.get(PurchaseOrder, po_b_id), lines=[{"line": 10, "qty": "100", "batches": [{"batch": "SPD-2704-02", "qty": "100"}]}],
            ship_date=d15, expected_date=date(2027, 4, 16), vehicle_no="TN19AF7342", distance_km=150, documents=["CoC-SPD-2704-02"]).id
    with sc.act("mrp.controller", at(d15, 9, 30)) as s:
        run3 = planning.run(s, plant="P100", mode="NET_CHANGE", materials=[MATERIAL], run_date=d15)
        run3_no, run3_codes = run3.number, sorted(e["code"] for r in run3.results for e in r["exceptions"])
        run3_sources = sorted({o.source.get("method") for o in s.execute(select(PlannedOrder).where(PlannedOrder.mrp_run_id == run3.id)).scalars()})
    with sc.act("spd.sales", at(d15, 10)) as s:
        number = "SPD/27-28/0019"
        payables.capture(s, supplier="SPD201", supplier_invoice_no=number, invoice_date=d15, channel="E_INVOICE", irn=_irn("SPD201", number, d15),
                         lines=[{"po": po_c_no, "po_line": 10, "qty": "100", "unit_price": "192", "gst_rate": "18", "hsn": "87089900"}])
    with sc.act("ap.clerk", at(d15, 14)) as s:
        disputed = _invoice(s, "SPD/27-28/0019")
        payables.resolve_exception(s, disputed, _open_exception(s, disputed, "PRICE").id, "DISPUTE",
                                   "Bridge price ₹186 is fixed; the ₹6 surcharge was declined at confirmation on 9 Apr. SPD201 asked to "
                                   "cancel and re-issue at ₹186")
    _relay(sc, at(d15, 17))

    # ============================================================ Fri 16 April
    d16 = date(2027, 4, 16)
    with tenant_tx(sc.tenant_id) as s:
        aac_cert = s.execute(select(Certificate.id).where(Certificate.supplier_id == supplier_ids["AAC202"], Certificate.type == "ISO14001")).scalar_one()
    cert_fired = _fire(sc, "CERTIFICATE_EXPIRY", aac_cert, at(d16, 0, 5))
    with sc.act("receiver", at(d16, 10)) as s:
        gr_b_id = receiving.post_gr(s, s.get(PurchaseOrder, po_b_id), asn=s.get(Asn, asn_b_id), delivery_note="DN-SPD-1194",
                                    lines=[{"line": 10, "qty": "100", "batch": "SPD-2704-02"}], posting_date=d16).id
    with sc.act("spd.sales", at(d16, 11)) as s:
        number = "SPD/27-28/0021"
        payables.capture(s, supplier="SPD201", supplier_invoice_no=number, invoice_date=d16, channel="E_INVOICE", irn=_irn("SPD201", number, d16),
                         lines=[{"po": po_c_no, "po_line": 10, "qty": "100", "unit_price": "186", "gst_rate": "18", "hsn": "87089900"}])
    with sc.act("ap.clerk", at(d16, 12)) as s:
        payables.reject(s, _invoice(s, "SPD/27-28/0019"), "Dispute closed: superseded by corrected e-invoice SPD/27-28/0021 at the contract price")
        corrected = _invoice(s, "SPD/27-28/0021")
        payables.approve(s, corrected)
        payables.post(s, corrected, "AXN|1000|SPD201|SPD/27-28/0021")
    with sc.act("quality.inspector", at(d16, 15)) as s:
        rejected_lot = receiving.usage_decision(
            s, s.execute(select(InspectionLot).where(InspectionLot.gr_id == gr_b_id)).scalar_one(), accepted=Decimal(0), rejected=Decimal(100),
            defect_code="COLD_SHUT", reason="Cold shuts and flow lines at the mounting boss (X-ray and dye penetrant); lot rejected in full")
    with sc.act("hts.service", at(d16, 17)) as s:
        ses1 = receiving.create_ses(s, s.get(PurchaseOrder, po_s_id), method="UNIT_RATE", period_from=d16, period_to=d16,
                                    lines=[{"line": 10, "description": "Thermal imaging survey – cell 3 dies", "qty": "1", "unit_rate": "42000"}])
        receiving.submit_ses(s, ses1)
        ses1_id = ses1.id
    _relay(sc, at(d16, 18))

    # ============================================================ 17–30 April
    d17, d19, d20, d24 = date(2027, 4, 17), date(2027, 4, 19), date(2027, 4, 20), date(2027, 4, 24)
    with sc.act("aac.sales", at(d19, 10)) as s:
        aac_change = supplier_svc.request_bank_change(s, s.get(Supplier, supplier_ids["AAC202"]), bank_account="39120200017745",
                                                      ifsc="UTIB0003912", holder_name="Ambattur Alloys Trading")
        aac_change_id, aac_change_no = aac_change.id, aac_change.number
    with sc.act("supplier.manager", at(d19, 14)) as s:
        supplier_svc.callback_verify(s, s.get(BankChangeRequest, aac_change_id),
                                     "Call-back to the registered landline: the AAC202 accounts head could not confirm the new account; "
                                     "referred to finance")
    _decide(sc, "finance.controller", at(d20, 11), aac_change_id, "BANK_CHANGE", "REJECT",
            "Holder name on the cancelled cheque (Ambattur Alloys Trading) differs from the registered legal name; suspected "
            "payment-diversion attempt, existing account stays active")
    _decide(sc, "service.owner", at(d17, 10), ses1_id, "SES_APPROVAL", "REJECT",
            "Report covers the dies only; the ladle and shot-sleeve images in the PO scope are missing")
    with sc.act("spd.sales", at(d17, 11)) as s:
        capa = s.execute(select(Capa).where(Capa.source_ref == rejected_lot["lot"])).scalar_one()
        risk.respond_capa(s, capa, root_cause="Die temperature below 180 °C at the mounting boss after the tool transfer; thermocouple TC-4 mis-wired",
                          actions=[{"action": "Rewire TC-4 and add a die-temperature interlock on the 400 t cell", "owner": "SPD201 tooling", "due": "2027-04-20"},
                                   {"action": "100 % X-ray of the next three lots", "owner": "SPD201 quality", "due": "2027-05-10"}])
        capa_id, capa_no = capa.id, capa.number
    with sc.act("hts.service", at(d19, 16)) as s:
        ses2 = receiving.create_ses(s, s.get(PurchaseOrder, po_s_id), method="UNIT_RATE", period_from=d16, period_to=d19,
                                    lines=[{"line": 10, "description": "Thermal imaging survey – cell 3 dies, ladle and shot sleeve (report TS-0419)",
                                            "qty": "1", "unit_rate": "42000"}])
        receiving.submit_ses(s, ses2)
        ses2_id = ses2.id
    sc.approve_all(ses2_id, at(d20, 10), "Full scope covered (report TS-0419)")
    with sc.act("quality.inspector", at(d24, 11)) as s:
        risk.verify_capa(s, s.get(Capa, capa_id), True, "Re-audit 23 Apr: interlock verified, next lot X-ray clean")
    with sc.act("buyer", at(d24, 12)) as s:
        closed_b = order.close(s, s.get(PurchaseOrder, po_b_id), f"Lot rejected in full and returned ({rejected_lot['returnDelivery']}); "
                                                                  "nothing to invoice; the quantity moves to the annual SA")
    _relay(sc, at(d24, 13))
    expiry_fired = _fire(sc, "CONTRACT_EXPIRY", bridge_id, at(date(2027, 4, 25), 0, 5))
    with sc.act("contract.manager", at(date(2027, 4, 30), 11)) as s:
        obligation = s.execute(select(Obligation).where(Obligation.contract_id == amc_id, Obligation.party == "SUPPLIER")
                               .order_by(Obligation.due_date)).scalars().first()
        contract_svc.complete_obligation(s, obligation, "April service-level report received: MTTR 3.1 h, 2 call-outs, no repeat failure")
    for po_id in (po_a_id, po_b_id, po_c_id, po_e_id, po_s_id):
        _fire(sc, "PO_CONFIRMATION_SLA", po_id, at(date(2027, 4, 30), 11, 30))
    _relay(sc, at(date(2027, 4, 30), 12))

    # ============================================================ summary
    with tenant_tx(sc.tenant_id) as s:
        def st(model, ident):
            return s.get(model, ident).status
        bridge_row, amc_row = s.get(Contract, bridge_id), s.get(Contract, amc_id)
        status = {
            "coolant": st(Requisition, coolant_id), "desks": st(Requisition, desks_id), "mrpRequisition": st(Requisition, mrp_pr_id),
            "ppapRequisition": st(Requisition, ppap_id), "topupRequisition": st(Requisition, topup_id),
            "poA": st(PurchaseOrder, po_a_id), "poB": st(PurchaseOrder, po_b_id), "poC": st(PurchaseOrder, po_c_id),
            "poD": st(PurchaseOrder, po_d_id), "poE": st(PurchaseOrder, po_e_id), "poService": st(PurchaseOrder, po_s_id),
            "bridge": bridge_row.status, "bridgeThresholds": bridge_row.thresholds_hit, "amc": amc_row.status,
            "amcValidTo": amc_row.valid_to.isoformat(), "sa": st(Contract, sa_id), "rfq": award_status, "capa": st(Capa, capa_id),
            "ses1": st(ServiceEntry, ses1_id), "ses2": st(ServiceEntry, ses2_id), "oil": st(MaterialRequest, oil_id),
            "warn": st(MaterialRequest, warn_id), "block": st(MaterialRequest, block_id),
            "aac202": category_status(s, supplier_ids["AAC202"], CATEGORY), "vht": vht_result["status"],
            "poServiceRejected": st(PurchaseOrder, po_s0_id), "aacBankChange": st(BankChangeRequest, aac_change_id),
        }
    sc.note(f"Case 9 (re-approval): +120 L after approval → re-approval {reapproval['reapproval']} → {status['coolant']}")
    sc.note(f"Case 13: {run2_no} {run2_codes} (FC-2027-05 moved to 7 Jun; unfirmed orders of {run1_no} deleted)")
    sc.note(f"Case 14: {run3_no} {run3_codes}; planned-order sources {run3_sources}")
    sc.note(f"Case 15: Vellore Heat Treaters self-registered by invitation → bank verified → qualification REJECTED → {status['vht']}")
    sc.note(f"Case 16: AAC202 ISO 14001 expired (timer fired {cert_fired}) → ALU-DIECAST {status['aac202']}")
    sc.note(f"Case 17-19: oil request {status['oil']}; warning band {warn_score} → {status['warn']}; blocked {block_score} ({block_status}) "
            f"→ override → {status['block']}")
    sc.note(f"Case 20-22: {bridge_no} chain {bridge_chain} rejected → redlined → approved → active → renewal notice ({renewal_fired}) rejected → "
            f"thresholds {status['bridgeThresholds']} → {status['bridge']} (expiry timer fired {expiry_fired})")
    sc.note(f"Case 23: {amc_no} renewal approved → {extension_no} → {status['amc']} to {status['amcValidTo']}; obligation completed")
    sc.note(f"Case 24: {event_no} {status['rfq']} without approval (annual {award_value / 100:,.2f}, lowest) → {sa_no} chain {sa_chain} → {status['sa']}")
    sc.note(f"Case 25: {po_d_no} rejected by AAC202 → {cancelled['status']} (requisition {ppap_after_cancel}) → {po_e_no} confirmation SLA "
            f"({sla_fired} timer) → expedited → confirmed → {tax_exception} exception → re-issued → {closed_e['status']}")
    sc.note(f"Case 26: {po_b_no} later date accepted (v2); {po_c_no} surcharge declined, confirmed as ordered")
    sc.note(f"Case 27: {wrong_no} on {po_b_no} reversed → {po_b_no} {po_b_after_reversal} → re-posted on {po_c_no}")
    sc.note(f"Case 28: {rejected_lot['lot']} rejected in full → {rejected_lot['returnDelivery']} → {capa_no} {status['capa']} → {po_b_no} {closed_b['status']}")
    sc.note(f"Case 29: {po_s_no} SES {status['ses1']} → corrected SES {status['ses2']}")
    sc.note(f"Case 30: {gr_a_no} ERP {gr_first.status} → {gr_retry.status} (attempt {gr_retry.attempts}); SPD/27-28/0012 {first_post['status']} → "
            f"{dead[0]} after {dead[1]} attempts → replay {replay_status} ({replay_doc}); {po_a_no} touchless={po_a_touchless} → "
            f"{closed_a['status']}, requisitions closed {closed_a['closedRequisitions']}")
    sc.note("Case 31: SPD/27-28/0019 price DISPUTED → rejected; SPD/27-28/0021 posted")
    sc.note(f"Case 32: {po_s0_no} approval rejected → {po_s0_status} → {status['poServiceRejected']} → re-raised as {po_s_no}")
    sc.note(f"Case 33: AAC202 bank change {aac_change_no} → call-back → finance REJECTED ({status['aacBankChange']})")
    sc.note(f"Case 34: {pcr_no} supplier change request on {po_c_no} after confirmation → buyer REJECTED")
    clock.set_pinned(None)
    counts = {"requisitions": 7, "materialRequests": 3, "mrpRuns": 4, "suppliers": 3, "sourcingEvents": 1, "contracts": 3,
              "contractAmendments": 1, "purchaseOrders": 7, "asns": 4, "goodsReceipts": 5, "serviceEntries": 2, "invoices": 5, "capas": 1}
    return {"notes": sc.log, "counts": counts, "status": status}
