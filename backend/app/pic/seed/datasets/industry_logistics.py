"""D5 logistics demo tenant LOG: lane CHE→PNQ, rate per km + fuel index, POD, freight audit (blueprint §23 / §23.1).

Coromandel Logistics Pvt Ltd (fictional third-party logistics company, Chennai) buys full-truck-load capacity from
carriers. Everything below runs through the domain services, on the tenant's own timeline Oct 2026 – Mar 2027:

  bootstrap    tenant LOG from the LOGISTICS industry template (FREIGHT-AUDIT rule, carrier-compliance certificates),
               company code 1000 (GSTIN 33…, Tamil Nadu), sites CHE1 Sriperumbudur DC (33) and PNQ1 Chakan hub (27),
               cost centres 5100 linehaul / 5200 Pune hub / 5900 administration, holidays, budgets (initial load)
  F8           two carriers onboarded (registration → profile with GIT insurance + national permit → bank call-back →
               dual finance approval → qualification for LOGISTICS)
  F9           service master "FTL Chennai → Pune 32 ft MXL – per km" (SAC 996791 goods transport agency, GST 18 % forward
               charge with input tax credit; the carrier's GST option is to be confirmed by the tax team) via the four data stewards
  F4           lane rate contract with Kaveri Roadways: ₹54.00/km, chargeable lane distance 1,180 km, monthly reset
               against DEMO-DIESEL-IDX — a clearly labelled demonstration index (base 100.00, ±2 % absorbed by the carrier);
               its values are illustrative and are NOT published diesel prices
  F2/F5        monthly lane-volume requisitions (lane volume forecast) → one touchless PO per trip (shipment order)
               priced from the contract validity on the loading date
  F6           proof of delivery entered by the carrier as a service entry (method POD, GPS distance) and confirmed by the
               control tower (service owner)
  F7           freight audit on every carrier invoice: contracted rate on the loading date (index included) × POD km;
               invoice KRW/26-27/0436 bills 1,240 km against a POD of 1,177 km → FREIGHT_AUDIT + SERVICE exceptions →
               credit note → re-match → posted; monthly payment runs
  spot buy     one urgent backhaul trip PNQ→CHE from a second carrier (free text, one quote, PO approval, POD, SES match)

Helpers at the top of this module (GSTIN, tenant set-up, users, onboarding, tenant-scoped relay) are shared with the
industry_general pack.
"""
import heapq
import itertools
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select

from app.pic.db import tenant_tx
from app.pic.models import (
    AppUser, BankChangeRequest, Budget, Contract, ContractLine, Invoice, InvoiceException, Material, MaterialRequest, Payment,
    PriceValidity, PurchaseOrder, RuleSet, ServiceEntry, SpendLine, Supplier,
)
from app.pic.platform import audit, clock
from app.pic.platform.auth import hash_password
from app.pic.platform.money import fmt_inr, line_amount, tax_amount
from app.pic.seed import reference
from app.pic.seed.axion import Scenario, at

KEY = "industry-logistics"
VERSION = "1"
TITLE = "D5 logistics demo tenant LOG: lane CHE→PNQ, rate per km + fuel index, POD, freight audit"
TENANTS = ('LOG',)
CREATES_TENANT = True
READY = True


# ======================================================================== shared helpers (also used by industry_general)
def gstin(state: str, pan: str, entity: str = "1") -> str:
    """GSTIN = state code + PAN + entity number + 'Z' + check character (base-36 checksum, as validated by MDM-04)."""
    from app.pic.services.master_changes import gstin_check_char
    first14 = f"{state}{pan}{entity}Z"
    return first14 + gstin_check_char(first14)


def days(n: int) -> timedelta:
    return timedelta(days=n)


def new_tenant(code: str, name: str, template: str, *, company_gstin: str, plants: list, cost_objects: list, holidays: list):
    reference.deploy_process_definitions()
    tenant_id = reference.create_tenant(code, name, template)
    reference.bootstrap(tenant_id, company=("1000", name, company_gstin), plants=plants, cost_objects=cost_objects, holidays=holidays)
    return tenant_id


def create_users(sc: Scenario, users: list, password: str) -> None:
    with tenant_tx(sc.tenant_id) as s:
        if s.execute(select(AppUser.id)).first():
            raise RuntimeError(f"Tenant {sc.tenant_code} already has users but no dataset record; drop the tenant and load the pack again")
        hashed = hash_password(password)
        for local, name, roles, attrs in users:
            s.add(AppUser(tenant_id=sc.tenant_id, email=f"{local}@{sc.domain}", full_name=name, password_hash=hashed, roles=roles,
                          attributes=attrs, mfa_enrolled=any(r in roles for r in ("FINANCE_CONTROLLER", "TENANT_ADMIN", "CPO"))))


def relay(sc: Scenario, when) -> dict:
    """Outbox, integration retries and due timers for this tenant only (never fires another tenant's timers)."""
    from app.pic.platform import integration, outbox, workflow
    from app.pic.worker import system_principal
    clock.set_pinned(when)
    principal = system_principal(sc.tenant_id)
    events = outbox.relay_tenant(sc.tenant_id)
    timers = workflow.run_due_timers(sc.tenant_id, principal)
    messages = integration.run_pending(sc.tenant_id, principal)
    events += outbox.relay_tenant(sc.tenant_id)
    return {"events": events, "timers": timers, "integration": messages}


def new_rule_version(sc: Scenario, key: str, version: str, effective_from: date, body: dict, description: str, when) -> None:
    """A tenant rule change as the admin makes it (POST /v1/admin/rules): a new effective-dated version, audited."""
    with sc.act("admin", when) as s:
        if s.execute(select(RuleSet.id).where(RuleSet.key == key, RuleSet.version == version)).first():
            return
        rule = RuleSet(tenant_id=sc.tenant_id, key=key, version=version, effective_from=effective_from, body=body,
                       description=description, created_by=s.info["principal"].user_id)
        s.add(rule)
        s.flush()
        audit.record(s, "RULE_SET", rule.id, "VERSION_CREATED", object_ref=f"{key}@{version}",
                     after={"key": key, "version": version, "effectiveFrom": effective_from.isoformat(), "description": description})


def current_rule_body(sc: Scenario, key: str, when) -> dict:
    from app.pic.platform import rules
    with sc.act("admin", when) as s:
        return dict(rules.resolve(s, key).body)


def load_budgets(sc: Scenario, budgets: list, when, ref: str) -> None:
    """§12.4 initial load of the 2026-27 budgets (no budget-maintenance service exists; audited as MIGRATION)."""
    clock.set_pinned(when)
    with tenant_tx(sc.tenant_id) as s:
        for obj_type, code, control, amount_minor in budgets:
            s.add(Budget(tenant_id=sc.tenant_id, cost_object_type=obj_type, cost_object_code=code, fiscal_year="2026-27", control=control,
                         amount_minor=amount_minor, committed_minor=0, consumed_minor=0))
        audit.record(s, "MIGRATION", uuid.uuid5(uuid.NAMESPACE_URL, f"{sc.tenant_code}-{ref}"), "INITIAL_LOAD", object_ref="budgets 2026-27",
                     after={"budgets": [f"{t}:{c}" for t, c, _, _ in budgets]}, actor="migration")


def onboard(sc: Scenario, spec: dict, password: str, day: date) -> uuid.UUID:
    """F8-01..09: register → portal user → profile (bank + certificates) → screening → call-back → 2 × finance → qualification."""
    from app.pic.services import supplier as svc
    with sc.act("supplier.manager", at(day, 10)) as s:
        sup = svc.register(s, code=spec["code"], legal_name=spec["name"], gstin=spec["gstin"], pan=spec["gstin"][2:12],
                           state_code=spec["gstin"][:2], contact_email=spec["user"], categories=spec["categories"],
                           payment_terms=spec["terms"], incoterms=spec.get("incoterms"), segment=spec.get("segment"), address=spec["address"])
        s.add(AppUser(tenant_id=sc.tenant_id, email=spec["user"], full_name=spec["user_name"], password_hash=hash_password(password),
                      roles=["SUPPLIER_USER"], attributes={}, supplier_id=sup.id, mfa_enrolled=True))
        supplier_id = sup.id
    with sc.act(spec["user"], at(day, 15)) as s:
        result = svc.submit_profile(s, s.get(Supplier, supplier_id), bank_account=spec["account"], ifsc=spec["ifsc"],
                                    holder_name=spec["name"], certificates=spec["certificates"])
        change_no = result["bankChange"]
        if result["screening"]["outcome"] != "CLEAR":
            raise RuntimeError(f"{spec['code']} screening {result['screening']['outcome']}: {result['screening']}")
    with sc.act("supplier.manager", at(day + days(1), 11)) as s:
        change = s.execute(select(BankChangeRequest).where(BankChangeRequest.number == change_no)).scalar_one()
        svc.callback_verify(s, change, f"Called {spec['name']} accounts on the landline from the GST portal; holder and IFSC confirmed")
        change_id = change.id
    sc.approve_all(change_id, at(day + days(1), 15), "Cancelled cheque and bank letter on letterhead verified")
    with sc.act("supplier.manager", at(day + days(2), 10)) as s:
        for category in spec["categories"]:
            q = svc.start_qualification(s, s.get(Supplier, supplier_id), category)
            svc.record_assessment(s, q, questionnaire=spec.get("questionnaire", {}), questionnaire_score=Decimal(spec["scores"][0]),
                                  audit_score=Decimal(spec["scores"][1]))
            svc.decide_qualification(s, q, "QUALIFIED", spec["qualification_note"])
    sc.note(f"F8 {spec['code']} {spec['name']}: screened CLEAR, bank dual-approved, qualified for {', '.join(spec['categories'])}")
    return supplier_id


def service_master(sc: Scenario, requester: str, when, *, description: str, material_group: str, category: str, uom: str, sac: str,
                   attributes: dict) -> tuple[str, str]:
    """F9: service master request → duplicate check → four domain stewards → ERP → golden record. Returns (request, material)."""
    from app.pic.services import mdm
    with sc.act(requester, when) as s:
        request = mdm.create_request(s, description=description, type="SERVICE", material_group=material_group, category=category,
                                     base_uom=uom, hsn_code=sac, attributes=attributes)
        request_id, request_no = request.id, request.number
    sc.approve_all(request_id, when + timedelta(hours=4), "Description, unit, SAC and category checked")
    with tenant_tx(sc.tenant_id) as s:
        request = s.get(MaterialRequest, request_id)
        material = s.get(Material, request.material_id)
        if material is None:
            raise RuntimeError(f"{request_no} did not create a material (status {request.status})")
        return request_no, material.number


def run_timeline(processes: list) -> None:
    """Interleave business processes written as generators that yield the date-time of their next step, earliest first."""
    heap, order = [], itertools.count()
    for process in processes:
        try:
            heapq.heappush(heap, (next(process), next(order), process))
        except StopIteration:
            pass
    while heap:
        _, _, process = heapq.heappop(heap)
        try:
            heapq.heappush(heap, (process.send(None), next(order), process))
        except StopIteration:
            pass


def post_invoice(sc: Scenario, invoice_id: uuid.UUID, when, supplier_code: str) -> dict:
    from app.pic.services import payables
    with sc.act("ap.clerk", when) as s:
        invoice = s.get(Invoice, invoice_id)
        payables.approve(s, invoice)
        return payables.post(s, invoice, f"{sc.tenant_code}|1000|{supplier_code}|{invoice.supplier_invoice_no}")


# ======================================================================== the LOG tenant
TENANT = ("LOG", "Coromandel Logistics Pvt Ltd")
DOMAIN = "coromandel-logistics.example"
COMPANY_PAN = "AAKCC4821Q"
LANE_KM = 1180          # chargeable lane distance CHE1 Sriperumbudur → PNQ1 Chakan (contract Schedule A)
BASE_RATE = 5400        # ₹54.00 per km
INDEX = {"index": "DEMO-DIESEL-IDX", "base": "100.00", "band_pct": "2", "reset": "MONTHLY",
         "label": "Demonstration fuel index for the LOG demo tenant – illustrative values, not published diesel prices",
         "realFeed": "DIESEL_IN (to be supplied)"}
# Monthly resets: (decided on, effective from, demo index value). ±2 % is absorbed by the carrier.
INDEX_RESETS = [(date(2026, 11, 27), date(2026, 12, 1), "101.50"), (date(2026, 12, 29), date(2027, 1, 1), "103.20"),
                (date(2027, 1, 28), date(2027, 2, 1), "104.60"), (date(2027, 2, 25), date(2027, 3, 1), "102.80")]

USERS = [
    ("admin", "Tenant Administrator", ["TENANT_ADMIN"], {}),
    ("lane.planner", "Saravanan Velu", ["REQUESTER"], {"cost_objects": ["COST_CENTER:5100", "COST_CENTER:5200"], "plants": ["CHE1", "PNQ1"]}),
    ("linehaul.manager", "Revathi Natarajan", ["COST_OBJECT_OWNER"], {"cost_objects": ["COST_CENTER:5100"], "plants": ["CHE1"]}),
    ("hub.manager", "Amol Deshpande", ["COST_OBJECT_OWNER"], {"cost_objects": ["COST_CENTER:5200"], "plants": ["PNQ1"]}),
    ("ops.head", "Gopal Krishnan", ["DEPT_HEAD"], {"cost_objects": ["COST_CENTER:5100", "COST_CENTER:5200"], "plants": ["CHE1", "PNQ1"]}),
    ("freight.buyer", "Nandhini Prakash", ["BUYER"], {"plants": ["CHE1", "PNQ1"]}),
    ("buyer.lead", "Joseph Antony", ["BUYER"], {"plants": ["CHE1", "PNQ1"]}),
    ("category.manager", "Lakshmi Sundar", ["CATEGORY_MANAGER"], {"categories": ["LOGISTICS"]}),
    ("contract.manager", "Senthil Kumar", ["CONTRACT_MANAGER"], {}),
    ("procurement.head", "Usha Rangarajan", ["PROCUREMENT_HEAD"], {}),
    ("supplier.manager", "Farida Begum", ["SUPPLIER_MANAGER"], {"categories": ["*"]}),
    ("finance.controller", "Venkatesh Iyer", ["FINANCE_CONTROLLER"], {}),
    ("finance.controller2", "Priya Ramanathan", ["FINANCE_CONTROLLER"], {}),
    ("mdm.purchasing", "Arjun Mehta", ["MDM_STEWARD"], {"steward_domains": ["PURCHASING"]}),
    ("mdm.quality", "Kavya Srinivas", ["MDM_STEWARD"], {"steward_domains": ["QUALITY"]}),
    ("mdm.finance", "Rafiq Ahmed", ["MDM_STEWARD"], {"steward_domains": ["FINANCE"]}),
    ("mdm.plant", "Deepika Rao", ["MDM_STEWARD"], {"steward_domains": ["PLANT"]}),
    ("control.tower", "Mahesh Patil", ["SERVICE_OWNER"], {"cost_objects": ["COST_CENTER:5100", "COST_CENTER:5200"], "plants": ["PNQ1"]}),
    ("ap.clerk", "Bhuvana Shankar", ["AP_CLERK"], {}),
]
ROLE_USER = {
    "COST_OBJECT_OWNER": ["linehaul.manager", "hub.manager"], "DEPT_HEAD": "ops.head", "BUYER": "buyer.lead",
    "CATEGORY_MANAGER": "category.manager", "CONTRACT_MANAGER": "contract.manager", "PROCUREMENT_HEAD": "procurement.head",
    "FINANCE_CONTROLLER": ["finance.controller", "finance.controller2"], "SERVICE_OWNER": "control.tower",
    "MDM_STEWARD": ["mdm.purchasing", "mdm.quality", "mdm.finance", "mdm.plant"],
}

KRW = {
    "code": "KRW01", "name": "Kaveri Roadways Pvt Ltd", "gstin": gstin("33", "AAGCK7314H"), "ifsc": "KVBL0001782", "account": "1782135000004417",
    "terms": "N30", "categories": ["LOGISTICS"], "segment": "LEVERAGE", "user": "ops@kaveriroadways.example",
    "user_name": "Kaveri Roadways – operations desk",
    "address": {"line1": "Plot 14, SIDCO Truck Terminal", "city": "Madhavaram, Chennai", "state_code": "33", "pin": "600110", "country": "IN"},
    "certificates": [
        {"type": "GIT_INSURANCE", "number": "GIT-KRW-2026-118804", "issued_on": "2026-04-01", "expires_on": "2027-03-31", "mandatory_for": ["LOGISTICS"]},
        {"type": "NATIONAL_PERMIT", "number": "NP-TN-KRW-FLEET-2026", "issued_on": "2026-01-15", "expires_on": "2031-01-14", "mandatory_for": ["LOGISTICS"]},
        {"type": "ISO9001", "number": "QMS-KRW-4471", "issued_on": "2025-06-01", "expires_on": "2028-05-31"}],
    "questionnaire": {"fleet": "42 owned 32 ft MXL closed-body trucks", "gps": "all vehicles GPS-tracked", "lanes": "South – West"},
    "scores": (84, 82), "qualification_note": "Fleet audit 82/100; GIT insurance and national permits verified",
}
WGC = {
    "code": "WGC02", "name": "Western Ghats Carriers Pvt Ltd", "gstin": gstin("27", "AAFCW2958L"), "ifsc": "UTIB0002964", "account": "926020045178203",
    "terms": "N15", "categories": ["LOGISTICS"], "segment": "ROUTINE", "user": "dispatch@westernghatscarriers.example",
    "user_name": "Western Ghats Carriers – dispatch",
    "address": {"line1": "Gat No. 318, Chakan–Talegaon Road", "city": "Chakan, Pune", "state_code": "27", "pin": "410501", "country": "IN"},
    "certificates": [
        {"type": "GIT_INSURANCE", "number": "GIT-WGC-2026-55021", "issued_on": "2026-07-01", "expires_on": "2027-06-30", "mandatory_for": ["LOGISTICS"]},
        {"type": "NATIONAL_PERMIT", "number": "NP-MH-WGC-FLEET-2025", "issued_on": "2025-09-01", "expires_on": "2030-08-31", "mandatory_for": ["LOGISTICS"]}],
    "questionnaire": {"fleet": "18 trucks incl. 6 × 32 ft MXL", "gps": "GPS on MXL fleet", "lanes": "West – South backhaul"},
    "scores": (76, 78), "qualification_note": "Spot / backhaul carrier; GIT insurance and national permits verified",
}

# Lane-volume plan (requisition per month) and trips: loading date, POD km (GPS), payload tonnes, vehicle.
MONTHS = [
    ("2026-11", date(2026, 10, 26), [(date(2026, 11, 4), 1178, "14.6", "TN 18 BK 4521"), (date(2026, 11, 12), 1172, "15.1", "TN 18 BK 4522"),
                                     (date(2026, 11, 20), 1180, "13.8", "TN 18 BK 4530")]),
    ("2026-12", date(2026, 11, 26), [(date(2026, 12, 3), 1176, "15.4", "TN 18 BK 4521"), (date(2026, 12, 11), 1169, "14.9", "TN 18 BK 4533"),
                                     (date(2026, 12, 19), 1180, "15.8", "TN 18 BK 4522")]),
    ("2027-01", date(2026, 12, 28), [(date(2027, 1, 5), 1174, "14.2", "TN 18 BK 4530"), (date(2027, 1, 12), 1177, "15.6", "TN 18 BK 4521"),
                                     (date(2027, 1, 19), 1180, "15.0", "TN 18 BK 4533"), (date(2027, 1, 27), 1171, "14.4", "TN 18 BK 4522")]),
    ("2027-02", date(2027, 1, 27), [(date(2027, 2, 3), 1179, "15.2", "TN 18 BK 4530"), (date(2027, 2, 11), 1175, "15.9", "TN 18 BK 4521"),
                                    (date(2027, 2, 19), 1180, "14.7", "TN 18 BK 4522")]),
    ("2027-03", date(2027, 2, 24), [(date(2027, 3, 4), 1173, "15.3", "TN 18 BK 4533"), (date(2027, 3, 15), 1176, "14.8", "TN 18 BK 4530")]),
]
OVERBILLED = (date(2027, 1, 12), 1240)   # the trip whose invoice bills 1,240 km against a POD of 1,177 km
PAYMENT_RUNS = [date(2026, 12, 10), date(2027, 1, 11), date(2027, 2, 10), date(2027, 3, 10)]


def _playbook(sc: Scenario) -> None:
    """Lane rate contracts (BP §23: 'rate contracts by lane with fuel surcharge indexation, accessorial rates') replace the
    generic value-contract clauses for this tenant: a new CLM-PLAYBOOK version, as the admin would publish it."""
    body = current_rule_body(sc, "CLM-PLAYBOOK", at(date(2026, 10, 1), 9))
    templates = dict(body["templates"])
    templates["VALUE_CONTRACT"] = [
        {"code": "PAYMENT", "title": "Payment terms",
         "text": "Payment {terms} from receipt of a correct freight invoice supported by the approved proof of delivery."},
        {"code": "LANE_RATES", "title": "Lane rates",
         "text": "Rates per km per lane and vehicle type are as per Schedule A. The billable distance is the distance on the signed proof "
                 "of delivery, capped at the lane's chargeable distance in Schedule A."},
        {"code": "FUEL_INDEX", "title": "Fuel indexation",
         "text": "The per-km rate is reset monthly against the fuel index named in Schedule A (base 100.00). Index movements within "
                 "±{band}% are absorbed by the carrier; beyond the band the rate moves by the excess."},
        {"code": "POD", "title": "Proof of delivery",
         "text": "Each trip is confirmed by a proof of delivery (consignee-signed lorry receipt with delivery time and GPS distance) "
                 "entered within 48 hours of delivery. Invoices without an approved proof of delivery are not payable."},
        {"code": "ACCESSORIALS", "title": "Accessorial charges",
         "text": "Detention, multi-point loading and toll pass-through are payable only at the Schedule B rates and only when recorded "
                 "on the proof of delivery."},
        {"code": "COMPLIANCE", "title": "Carrier compliance",
         "text": "The carrier keeps goods-in-transit insurance and a national permit valid for every vehicle placed; a lapse suspends "
                 "new trip allocations."},
        {"code": "LIABILITY", "title": "Liability", "text": "Liability for loss or damage in transit is capped at the declared consignment value."},
        {"code": "TERMINATION", "title": "Termination", "text": "Either party may terminate with 30 days' written notice."}]
    obligations = dict(body["obligations"])
    obligations["VALUE_CONTRACT"] = [
        {"party": "SUPPLIER", "description": "Monthly on-time pickup / delivery report per lane", "dueAfterDays": 30},
        {"party": "BUYER", "description": "Quarterly lane volume forecast to the carrier", "dueAfterDays": 90},
        {"party": "SUPPLIER", "description": "Renew goods-in-transit insurance before expiry", "dueAfterDays": 150}]
    new_rule_version(sc, "CLM-PLAYBOOK", "2026.1-LOG", date(2026, 10, 1), {**body, "templates": templates, "obligations": obligations},
                     "Clause library: lane rate contract with fuel indexation, POD and accessorials (Logistics template)",
                     at(date(2026, 10, 1), 9, 30))


def _contract(sc: Scenario, krw_id: uuid.UUID, material_no: str) -> tuple[uuid.UUID, str, uuid.UUID]:
    from app.pic.services import contract as contract_svc
    with sc.act("category.manager", at(date(2026, 10, 15), 11)) as s:
        material = s.execute(select(Material).where(Material.number == material_no)).scalar_one()
        owner = s.info["principal"].user_id
        contract = contract_svc.create_draft(
            s, type="VALUE_CONTRACT", title="Lane rate contract CHE1 Sriperumbudur → PNQ1 Chakan, 32 ft MXL – Kaveri Roadways",
            supplier_id=krw_id, company_code="1000", valid_from=date(2026, 11, 1), valid_to=date(2027, 10, 31), payment_terms="N30",
            incoterms=None, owner_id=owner, tolerances={"over_pct": "0", "under_pct": "0", "price_pct": "0"}, index_ref=INDEX,
            lines=[{"material_id": material.id, "description": "FTL Chennai (Sriperumbudur) → Pune (Chakan), 32 ft MXL closed body – per km",
                    "plant": "CHE1", "uom": "KM", "target_qty": str(48 * LANE_KM), "unit_price_minor": BASE_RATE}],
            trigger="lane rate negotiation (Schedule A: 48 trips/yr × 1,180 km)")
        contract_id, number = contract.id, contract.number
        line_id = s.execute(select(ContractLine.id).where(ContractLine.contract_id == contract_id)).scalar_one()
    with sc.act("contract.manager", at(date(2026, 10, 16), 10)) as s:
        contract_svc.ai_review(s, s.get(Contract, contract_id))
        contract_svc.submit(s, s.get(Contract, contract_id))
    sc.approve_all(contract_id, at(date(2026, 10, 19), 11), "Lane rate within budget; fuel clause per playbook")
    with sc.act("contract.manager", at(date(2026, 10, 21), 10)) as s:
        contract_svc.sign(s, s.get(Contract, contract_id), "BUYER", "Senthil Kumar, Contract Manager")
    with sc.act(KRW["user"], at(date(2026, 10, 21), 15)) as s:
        contract_svc.sign(s, s.get(Contract, contract_id), "SUPPLIER", "R. Elango, Director – Kaveri Roadways Pvt Ltd")
    with sc.act("contract.manager", at(date(2026, 10, 22), 10)) as s:
        contract_svc.activate(s, s.get(Contract, contract_id))
    relay(sc, at(date(2026, 10, 22), 11))
    sc.note(f"F4 {number}: lane rate ₹54.00/km × 1,180 km, {INDEX['index']} (demo) ±2 % band – approved, signed, active from 1 Nov 2026")
    return contract_id, number, line_id


# ------------------------------------------------------------------------ business processes on the timeline (generators)
# Each process yields the business date-time of its next step and performs that step when resumed; run_timeline
# interleaves them so the clock only moves forward (audit, workflow history and timers stay in business order).
def _lane_plan(sc: Scenario, state: dict, month: str, created: date, trips: int):
    from app.pic.services import requisition
    last = (date(int(month[:4]), int(month[5:]), 28) + days(4)).replace(day=1) - days(1)
    t = at(created, 10)
    yield t
    with sc.act("lane.planner", t) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="LANE_VOLUME", plant="CHE1",
                                purpose_text=f"Lane volume plan {month}: {trips} FTL trips CHE→PNQ (customer shipment orders)",
                                lines=[{"item_type": "CONTRACT", "purchase_type": "SERVICE", "material": state["material"],
                                        "contract_line_id": str(state["contractLine"]), "qty": str(trips * LANE_KM),
                                        "account_assignment_type": "COST_CENTER", "account_assignment_code": "5100",
                                        "need_date": last.isoformat()}])
        result = requisition.submit(s, pr)
        pr_id, pr_no = pr.id, pr.number
    t = at(created + days(1), 11)
    yield t
    sc.approve_all(pr_id, t, f"Lane volume {month} in line with the customer forecast")
    state["plans"][month] = pr_no
    state["planChains"][month] = result["chain"]
    sc.note(f"F2 {pr_no} lane plan {month}: {trips} × {LANE_KM} km, route {' → '.join(result['chain'])}")


def _index_reset(sc: Scenario, state: dict, decided: date, effective: date, value: str):
    from app.pic.services import contract as contract_svc
    t = at(decided, 11)
    yield t
    with sc.act("contract.manager", t) as s:
        reset = contract_svc.index_reset(s, s.get(Contract, state["contractId"]), Decimal(value), effective)
    state["resets"].append(reset)
    new_rate = reset["lines"][0]["newPriceMinor"] / 100
    effect = "inside the ±2 % band, absorbed by the carrier" if Decimal(reset["adjustPct"]) == 0 else f"rate {reset['adjustPct']} % above base"
    sc.note(f"F4 index reset {reset['contract']} from {effective}: {INDEX['index']} (demo) {value} = {reset['changePct']} % vs base → "
            f"{effect}: ₹{new_rate:.2f}/km")


def _payment_run(sc: Scenario, state: dict, run_day: date):
    from app.pic.services import payables
    t = at(run_day, 10)
    yield t
    with sc.act("finance.controller", t) as s:
        run = payables.payment_run(s, run_day)
    relay(sc, at(run_day, 11))
    state["runs"].append(run)
    sc.note(f"F7 payment run {run['run']} ({run_day}): {len(run['paid'])} invoice(s) paid" +
            (f", {len(run['skipped'])} skipped" if run["skipped"] else ""))


def _trip(sc: Scenario, state: dict, month: str, seq: int, loaded: date, km: int, tonnes: str, vehicle: str):
    from app.pic.services import order, payables, receiving
    delivered = loaded + days(3)
    lr = f"KRW/LR/{loaded:%y%m}/{seq:04d}"
    t = at(loaded - days(1), 16)
    yield t
    with sc.act("freight.buyer", t) as s:   # shipment order: one PO per trip, released against the month's lane plan
        po = order.create_from_requisition(s, requisition=state["plans"][month], lines=[10], contract_ref=state["contract"],
                                           release_qty=Decimal(LANE_KM), need_date=loaded)[0]
        po_id, po_no, rate, touchless = po.id, po.number, order.lines_of(s, po)[0].unit_price_minor, po.touchless
    relay(sc, at(loaded - days(1), 16, 30))
    t = at(loaded - days(1), 18)
    yield t
    with sc.act(KRW["user"], t) as s:
        order.confirm(s, s.get(PurchaseOrder, po_id), "CONFIRMED", note=f"Vehicle {vehicle} (32 ft MXL) placed for loading {loaded:%d %b} 07:00; {lr}")
    t = at(delivered, 18)
    yield t
    with sc.act(KRW["user"], t) as s:   # proof of delivery entered by the carrier as the service entry
        ses = receiving.create_ses(s, s.get(PurchaseOrder, po_id), method="POD", period_from=loaded, period_to=delivered,
                                   lines=[{"line": 10, "qty": str(km),
                                           "description": f"POD {lr} · {vehicle} · delivered Chakan {delivered:%d %b} 14:30 · GPS {km} km · "
                                                          f"{tonnes} t · consignee signed, no shortage"}])
        receiving.submit_ses(s, ses)
        ses_id, ses_no = ses.id, ses.number
    t = at(delivered + days(1), 10)
    yield t
    sc.approve_all(ses_id, t, f"POD {lr} checked against the GPS trail and the consignee copy")
    billed = OVERBILLED[1] if loaded == OVERBILLED[0] else km
    invoice_no = f"KRW/26-27/{400 + seq:04d}"
    invoice_day = delivered + days(1)
    t = at(invoice_day, 15)
    yield t
    with sc.act(KRW["user"], t) as s:
        invoice = payables.capture(s, supplier="KRW01", supplier_invoice_no=invoice_no, invoice_date=invoice_day, channel="E_INVOICE",
                                   irn=payables.expected_irn(KRW["gstin"], "2026-27", "INV", invoice_no),
                                   lines=[{"po": po_no, "po_line": 10, "qty": str(billed), "unit_price": f"{rate / 100:.2f}", "gst_rate": "18",
                                           "hsn": "996791", "description": f"Freight CHE→PNQ {lr} {billed} km @ {rate / 100:.2f}"}])
        invoice_id, status = invoice.id, invoice.status
    trip = {"po": po_no, "rateMinor": rate, "touchless": touchless, "ses": ses_no, "lr": lr, "km": km, "tonnes": tonnes,
            "invoice": invoice_no, "billedKm": billed, "status": status, "loaded": loaded}
    state["trips"].append(trip)
    if billed != km:
        with tenant_tx(sc.tenant_id) as s:
            raised = s.execute(select(InvoiceException).where(InvoiceException.invoice_id == invoice_id,
                                                              InvoiceException.status == "OPEN")).scalars().all()
            audit_exc = next(e for e in raised if e.type == "FREIGHT_AUDIT")
            trip.update(exceptions=sorted(e.type for e in raised), recoveryMinor=int(audit_exc.delta["overbilledMinor"]))
            detail = audit_exc.detail
        credit_no = "KRW/CN/26-27/0007"
        t = at(invoice_day + days(2), 11)
        yield t
        with sc.act(KRW["user"], t) as s:
            payables.submit_credit_note(s, s.get(Invoice, invoice_id), supplier_credit_note_no=credit_no, note_date=invoice_day + days(2),
                                        reason=f"Credit for {billed - km} km billed above the proof-of-delivery distance (freight audit)",
                                        lines=[{"invoice_line": 10, "qty": str(billed - km)}])
        t = at(invoice_day + days(2), 15)
        yield t
        with sc.act("ap.clerk", t) as s:
            invoice = s.get(Invoice, invoice_id)
            for exc in s.execute(select(InvoiceException).where(InvoiceException.invoice_id == invoice_id, InvoiceException.status == "OPEN")
                                 .order_by(InvoiceException.type)).scalars().all():
                payables.resolve_exception(s, invoice, exc.id, "CREDIT_NOTE_RECEIVED",
                                           f"Freight audit recovery: {credit_no} credits {billed - km} km", credit_no)
            trip.update(creditNote=credit_no, statusAfterCredit=invoice.status)
        sc.note(f"F7 {invoice_no}: {detail} → credit note {credit_no} → re-matched ({trip['statusAfterCredit']})")
        post_on = invoice_day + days(3)
    else:
        post_on = invoice_day + days(1)
    t = at(post_on, 11)
    yield t
    post_invoice(sc, invoice_id, t, "KRW01")
    relay(sc, at(post_on, 12))


def _spot_trip(sc: Scenario, state: dict):
    """Urgent backhaul PNQ→CHE from the spot carrier: free text with one quote, buyer-lead PO approval, POD, SES match."""
    from app.pic.services import order, payables, receiving, requisition
    t = at(date(2026, 12, 14), 10)
    yield t
    with sc.act("lane.planner", t) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="SPOT_FREIGHT", plant="PNQ1",
                                purpose_text="Urgent return of 38 empty returnable racks Chakan → Sriperumbudur (customer line-stoppage risk)",
                                lines=[{"item_type": "FREE_TEXT", "purchase_type": "SERVICE",
                                        "description": "Spot FTL Pune (Chakan) → Chennai (Sriperumbudur), 32 ft MXL – returnable racks",
                                        "material_group": "LOG-SPOT", "category": "LOGISTICS", "qty": "1", "uom": "TRIP",
                                        "price_est_minor": 6_600_000, "account_assignment_type": "COST_CENTER", "account_assignment_code": "5200",
                                        "need_date": "2026-12-15", "quotes_attached": 1, "plant": "PNQ1"}])
        requisition.submit(s, pr)
        pr_id, pr_no = pr.id, pr.number
    t = at(date(2026, 12, 14), 11, 30)
    yield t
    sc.approve_all(pr_id, t, "Spot quote WGC-Q-2612 attached; the contract carrier has no vehicle at Chakan")
    t = at(date(2026, 12, 14), 14)
    yield t
    with sc.act("freight.buyer", t) as s:
        po = order.create_from_requisition(s, requisition=pr_no, lines=[10], supplier_code="WGC02", unit_price_minor=6_600_000)[0]
        po_id, po_no, touchless = po.id, po.number, po.touchless
    t = at(date(2026, 12, 14), 15)
    yield t
    approvals = sc.approve_all(po_id, t, "Spot rate ₹66,000 as per quote WGC-Q-2612")
    relay(sc, at(date(2026, 12, 14), 15, 30))
    t = at(date(2026, 12, 14), 18)
    yield t
    with sc.act(WGC["user"], t) as s:
        order.confirm(s, s.get(PurchaseOrder, po_id), "CONFIRMED", note="Vehicle MH 14 KQ 7391 (32 ft MXL) placed 15 Dec 06:00")
    t = at(date(2026, 12, 18), 13)
    yield t
    with sc.act(WGC["user"], t) as s:
        ses = receiving.create_ses(s, s.get(PurchaseOrder, po_id), method="POD", period_from=date(2026, 12, 15), period_to=date(2026, 12, 18),
                                   lines=[{"line": 10, "qty": "1", "description": "POD WGC/LR/2612/0219 · MH 14 KQ 7391 · delivered "
                                                                                    "Sriperumbudur 18 Dec 11:10 · 38 racks · consignee signed"}])
        receiving.submit_ses(s, ses)
        ses_id = ses.id
    t = at(date(2026, 12, 18), 17)
    yield t
    sc.approve_all(ses_id, t, "Racks received at the DC; POD verified")
    t = at(date(2026, 12, 19), 12)
    yield t
    with sc.act(WGC["user"], t) as s:
        invoice = payables.capture(s, supplier="WGC02", supplier_invoice_no="WGC/2026-27/1184", invoice_date=date(2026, 12, 19), channel="PORTAL",
                                   lines=[{"po": po_no, "po_line": 10, "qty": "1", "unit_price": "66000.00", "gst_rate": "18"}])
        invoice_id, status = invoice.id, invoice.status
    t = at(date(2026, 12, 21), 12)
    yield t
    post_invoice(sc, invoice_id, t, "WGC02")
    relay(sc, at(date(2026, 12, 21), 12, 30))
    state["spot"] = {"requisition": pr_no, "po": po_no, "touchless": touchless, "poApprovals": approvals, "invoiceStatus": status}
    sc.note(f"Spot {pr_no} → {po_no} (buyer-lead approval, not touchless) → POD → WGC/2026-27/1184 SES match ({status}) → posted")


def apply(tenant_code: str, password: str) -> dict:
    if tenant_code != TENANT[0]:
        raise ValueError(f"{KEY} creates tenant {TENANT[0]} only")
    clock.set_pinned(at(date(2026, 10, 1), 9))
    tenant_id = new_tenant(*TENANT, "LOGISTICS", company_gstin=gstin("33", COMPANY_PAN),
                           plants=[("CHE1", "Chennai DC – Sriperumbudur", "33"), ("PNQ1", "Pune hub – Chakan", "27")],
                           cost_objects=[("COST_CENTER", "5100", "Linehaul – South–West lanes"), ("COST_CENTER", "5200", "Pune hub operations"),
                                         ("COST_CENTER", "5900", "Administration")],
                           holidays=[date(2026, 10, 2), date(2026, 11, 8), date(2026, 12, 25), date(2027, 1, 15), date(2027, 1, 26)])
    sc = Scenario(tenant_id, TENANT[0], DOMAIN, ROLE_USER)
    create_users(sc, USERS, password)
    load_budgets(sc, [("COST_CENTER", "5100", "SOFT", 36 * reference.L), ("COST_CENTER", "5200", "SOFT", 6 * reference.L),
                      ("COST_CENTER", "5900", "SOFT", 3 * reference.L)], at(date(2026, 10, 1), 9, 15), "budgets")
    _playbook(sc)
    sc.note("Tenant LOG from the LOGISTICS template: FREIGHT-AUDIT (0 % rate tolerance), carrier-compliance certificates, lane playbook")

    # ------------------------------------------------------------ F8 carriers, F9 lane service master, F4 lane rate contract
    krw_id = onboard(sc, KRW, password, date(2026, 10, 5))
    onboard(sc, WGC, password, date(2026, 10, 7))
    mrq_no, material_no = service_master(sc, "freight.buyer", at(date(2026, 10, 12), 10),
                                         description="FTL Chennai (Sriperumbudur) to Pune (Chakan) 32 ft MXL closed body - per km",
                                         material_group="LOG-FTL", category="LOGISTICS", uom="KM", sac="996791",
                                         attributes={"lane": "CHE1-PNQ1", "vehicle": "32 ft MXL", "body": "closed container", "basis": "per km"})
    sc.note(f"F9 {mrq_no} → service master {material_no} (SAC 996791, unit KM) approved by four stewards and synced to the ERP")
    contract_id, contract_no, line_id = _contract(sc, krw_id, material_no)

    # ------------------------------------------------------------ Nov 2026 – Mar 2027: lane plans, trips, index resets, payment runs
    state = {"material": material_no, "contract": contract_no, "contractId": contract_id, "contractLine": line_id,
             "plans": {}, "planChains": {}, "trips": [], "resets": [], "runs": [], "spot": None}
    processes, seq = [], 0
    for month, created, month_trips in MONTHS:
        processes.append(_lane_plan(sc, state, month, created, len(month_trips)))
        for loaded, km, tonnes, vehicle in month_trips:
            seq += 1
            processes.append(_trip(sc, state, month, seq, loaded, km, tonnes, vehicle))
    processes += [_index_reset(sc, state, *reset) for reset in INDEX_RESETS]
    processes += [_payment_run(sc, state, run_day) for run_day in PAYMENT_RUNS]
    processes.append(_spot_trip(sc, state))
    run_timeline(processes)
    relay(sc, at(date(2027, 3, 31), 18))

    # ------------------------------------------------------------ summary and KPIs (BP §23: cost per tonne-km, audit recoveries)
    trips = state["trips"]
    with tenant_tx(tenant_id) as s:
        counts = {
            "suppliers": s.execute(select(func.count()).select_from(Supplier)).scalar(),
            "contracts": s.execute(select(func.count()).select_from(Contract)).scalar(),
            "priceValidities": s.execute(select(func.count()).select_from(PriceValidity)).scalar(),
            "purchaseOrders": s.execute(select(func.count()).select_from(PurchaseOrder)).scalar(),
            "serviceEntries": s.execute(select(func.count()).select_from(ServiceEntry)).scalar(),
            "invoices": s.execute(select(func.count()).select_from(Invoice)).scalar(),
            "freightAuditExceptions": s.execute(select(func.count()).select_from(InvoiceException)
                                                .where(InvoiceException.type == "FREIGHT_AUDIT")).scalar(),
            "payments": s.execute(select(func.count()).select_from(Payment)).scalar(),
            "spendLines": s.execute(select(func.count()).select_from(SpendLine)).scalar(),
        }
        line = s.get(ContractLine, line_id)
        consumption = {"releasedKm": str(line.released_qty), "targetKm": str(line.target_qty), "releasedValueMinor": line.released_value_minor}
    freight_minor = sum(line_amount(t["km"], t["rateMinor"]) for t in trips)
    tonne_km = sum(Decimal(t["tonnes"]) * t["km"] for t in trips)
    recovery = sum(t.get("recoveryMinor", 0) for t in trips)
    kpis = {"contractTrips": len(trips), "freightNetMinor": freight_minor,
            "costPerKm": f"{Decimal(freight_minor) / sum(t['km'] for t in trips) / 100:.2f}",
            "costPerTonneKm": f"{(Decimal(freight_minor) / tonne_km / 100).quantize(Decimal('0.0001'), ROUND_HALF_UP)}",
            "auditRecoveriesMinor": recovery, "auditRecoveriesGrossMinor": recovery + tax_amount(recovery, 18),
            "rateByMonthMinor": {t["loaded"].strftime("%Y-%m"): t["rateMinor"] for t in trips},
            "touchlessTripPOs": sum(1 for t in trips if t["touchless"])}
    sc.note(f"{len(trips)} contract trips + 1 spot trip; contract freight {fmt_inr(freight_minor)} net; cost/km ₹{kpis['costPerKm']}, "
            f"cost/tonne-km ₹{kpis['costPerTonneKm']}; freight-audit recoveries {fmt_inr(recovery)} net; {len(state['runs'])} payment runs")
    clock.set_pinned(None)
    return {"notes": sc.log, "counts": {**counts, "contractConsumption": consumption, "kpis": kpis, "contract": contract_no,
                                        "serviceMaster": material_no, "lanePlans": state["plans"], "spotPo": (state["spot"] or {}).get("po"),
                                        "paymentRuns": [r["run"] for r in state["runs"]], "paid": sum(len(r["paid"]) for r in state["runs"])}}
