"""D2 purchase types (blueprint §22, principle P08) on the Axion tenant, June 2027.

Every purchase type that the PURCHASE-TYPE-MATRIX configures but the signature case never used, run end to end through the
domain services (requisition → approval → PO → receipt/withdrawal → invoice/settlement), with the controls that make the
type different:

  EXPENSE      E1  safety helmets ₹16,800 (below the ₹25,000 receipt-less threshold): no goods receipt, invoice matched
                   2-way against the PO, PO goes straight to INVOICED; a goods receipt attempt is refused (P08)
               E2  ergonomic chairs ₹1,17,600 (above the threshold): goods receipt required, invoice matched 3-way
  ASSET        A1  vertical machining centre ₹46,50,000 on asset AST-P100-VMC-07: account assignment ASSET, capex committee
                   added to the DMN-01 chain, hard budget check, ASN with e-way bill, GR, 3-way match, budget consumed
               A2  robotic loading cell on WBS CX-2728-04 (₹25 L hard budget): ₹28,40,000 hits the WBS hard stop
                   (BUDGET_EXCEEDED); the requester cuts the scope to ₹22,60,000, it is approved incl. capex committee, ordered
  CONSIGNMENT  C1  VMI hex flange bolts M10 × 30 (20,000 pcs): GR into supplier-owned consignment stock (no liability, the
                   supplier cannot invoice the line), three withdrawals to own stock (411K) create the liability, month-end
                   self-billing (ERS) settles exactly the 15,500 withdrawn; 4,500 stay in consignment stock, not accrued
  SUBCONTRACT  S1  drive shaft SH-2207 heat treatment: forged blanks bought as stock (3-way), the subcontracting PO copies
                   the component list from the material's subcontracting BOM, components are provided to the heat treater
                   (541) in two lots, each receipt of finished shafts consumes the blanks at the subcontractor (543); a
                   receipt before enough blanks were provided is refused (COMPONENTS_MISSING); processing fee invoiced 3-way

New master data (all fictional): five suppliers onboarded through F8, three materials through F9 (four data stewards), the
users for the capex cost objects and the capex committee, and the FY 2027-28 budgets of the new cost objects (initial load,
there is no budget-maintenance service). Nothing of the signature case is changed: no payment run (it would pay other
packs' invoices), no timers fired, only this tenant's outbox is relayed.

The helpers at the top (GSTIN, users, onboarding, F9 materials, tenant-scoped relay) are shared with industry_healthcare.
"""
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, BankChangeRequest, Budget, CostObject, GoodsReceipt, Invoice, Material, MaterialRequest, PurchaseOrder, Requisition,
    Supplier, Tenant,
)
from app.pic.platform import audit, clock
from app.pic.platform.auth import hash_password
from app.pic.platform.errors import Problem
from app.pic.seed import axion
from app.pic.seed.axion import Scenario, at

KEY = "axn-purchase-types"
VERSION = "1"
TITLE = "D2 purchase types: expense, capital asset, consignment, subcontracting (June 2027)"
TENANTS = ('AXN',)
CREATES_TENANT = False
READY = True

FISCAL_YEAR = "2027-28"
L = 100_000 * 100  # one lakh rupees in paise


# ======================================================================== shared helpers (also used by industry_healthcare)
def gstin(state: str, pan: str, entity: str = "1") -> str:
    """GSTIN = state code + PAN + entity number + 'Z' + base-36 check character (the check MDM-04 validates)."""
    from app.pic.services.master_changes import gstin_check_char
    first14 = f"{state}{pan}{entity}Z"
    return first14 + gstin_check_char(first14)


def tenant_id_of(code: str) -> uuid.UUID:
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == code)).scalar_one()


def add_users(sc: Scenario, users: list, password: str) -> list[str]:
    """Internal users (check-then-insert by e-mail)."""
    added = []
    with tenant_tx(sc.tenant_id) as s:
        have = set(s.execute(select(AppUser.email)).scalars())
        hashed = hash_password(password)
        for local, name, roles, attrs in users:
            if sc.email(local) in have:
                continue
            s.add(AppUser(tenant_id=sc.tenant_id, email=sc.email(local), full_name=name, password_hash=hashed, roles=roles, attributes=attrs,
                          mfa_enrolled=any(r in roles for r in ("FINANCE_CONTROLLER", "TENANT_ADMIN", "CPO", "CAPEX_COMMITTEE"))))
            added.append(local)
    return added


def relay(sc: Scenario, when: datetime, timers: bool = False) -> int:
    """Publish this tenant's outbox events (and, for a tenant the pack owns, its due timers and integration retries).
    Never fires another tenant's timers, unlike worker.tick()."""
    from app.pic.platform import integration, outbox, workflow
    from app.pic.worker import system_principal
    clock.set_pinned(when)
    published = outbox.relay_tenant(sc.tenant_id)
    if timers:
        principal = system_principal(sc.tenant_id)
        workflow.run_due_timers(sc.tenant_id, principal)
        integration.run_pending(sc.tenant_id, principal)
        published += outbox.relay_tenant(sc.tenant_id)
    return published


def onboard(sc: Scenario, spec: dict, password: str, day: date) -> uuid.UUID:
    """F8-01..09: register → portal user → profile (bank + certificates) → screening → bank call-back → 2 × finance → qualification."""
    from app.pic.services import supplier as svc
    with sc.act("supplier.manager", at(day, 10)) as s:
        sup = svc.register(s, code=spec["code"], legal_name=spec["name"], gstin=spec["gstin"], pan=spec["gstin"][2:12], state_code=spec["gstin"][:2],
                           contact_email=spec["user"], categories=spec["categories"], payment_terms=spec["terms"],
                           incoterms=spec.get("incoterms"), segment=spec.get("segment", "ROUTINE"), address=spec.get("address"))
        s.add(AppUser(tenant_id=sc.tenant_id, email=spec["user"], full_name=f"{spec['name']} – {spec['user_role']}",
                      password_hash=hash_password(password), roles=["SUPPLIER_USER"], attributes={}, supplier_id=sup.id, mfa_enrolled=True))
        supplier_id = sup.id
    with sc.act(spec["user"], at(day, 15)) as s:
        result = svc.submit_profile(s, s.get(Supplier, supplier_id), bank_account=spec["account"], ifsc=spec["ifsc"], holder_name=spec["name"],
                                    certificates=spec["certificates"])
        if result["screening"]["outcome"] != "CLEAR":
            raise RuntimeError(f"{spec['code']} screening {result['screening']['outcome']}: {result['screening']}")
        change_no = result["bankChange"]
    with sc.act("supplier.manager", at(day + timedelta(days=1), 11)) as s:
        change = s.execute(select(BankChangeRequest).where(BankChangeRequest.number == change_no)).scalar_one()
        svc.callback_verify(s, change, f"Called {spec['name']} on the landline listed on the GST portal; account holder and IFSC confirmed")
        change_id = change.id
    sc.approve_all(change_id, at(day + timedelta(days=1), 15), "Cancelled cheque and bank letter on letterhead verified")
    with sc.act("supplier.manager", at(day + timedelta(days=2), 10)) as s:
        for category in spec["categories"]:
            q = svc.start_qualification(s, s.get(Supplier, supplier_id), category)
            svc.record_assessment(s, q, questionnaire=spec.get("questionnaire", {}), questionnaire_score=Decimal(spec["scores"][0]),
                                  audit_score=Decimal(spec["scores"][1]))
            svc.decide_qualification(s, q, "QUALIFIED", spec["note"])
    sc.note(f"F8 {spec['code']} {spec['name']}: screened CLEAR, bank dual-approved, qualified for {', '.join(spec['categories'])}")
    return supplier_id


def material_via_f9(sc: Scenario, requester: str, when: datetime, **fields) -> str:
    """F9: material request → duplicate check → four domain stewards in parallel → ERP → golden record. Returns the number."""
    from app.pic.services import mdm
    with sc.act(requester, when) as s:
        request = mdm.create_request(s, **fields)
        request_id, request_no, status = request.id, request.number, request.status
    if status != "IN_STEWARDSHIP":
        raise RuntimeError(f"{request_no} stopped at {status} (duplicate check); adjust the description")
    sc.approve_all(request_id, when + timedelta(hours=3), "Domain data complete and checked against the drawing / datasheet")
    with tenant_tx(sc.tenant_id) as s:
        request = s.get(MaterialRequest, request_id)
        material = s.get(Material, request.material_id) if request.material_id else None
        if material is None:
            raise RuntimeError(f"{request_no} did not create a material (status {request.status})")
        sc.note(f"F9 {request_no} → {material.number} {material.description}")
        return material.number


def requisition(sc: Scenario, who: str, when: datetime, *, purpose_code: str, purpose_text: str, plant: str, lines: list,
                justification: Optional[str] = None) -> tuple[uuid.UUID, str, str]:
    from app.pic.services import requisition as req_svc
    with sc.act(who, when) as s:
        pr = req_svc.create(s, origin="MANUAL", purpose_code=purpose_code, purpose_text=purpose_text, plant=plant, lines=lines)
        req_svc.submit(s, pr, justification=justification)
        return pr.id, pr.number, pr.status


def order_from(sc: Scenario, buyer: str, when: datetime, pr_no: str, *, supplier: Optional[str] = None, lines=(10,),
               approve: bool = True) -> tuple[uuid.UUID, str]:
    """F5: PO from an approved requisition; non-touchless POs go through the PO-APPROVAL chain (buyer lead, procurement head)."""
    from app.pic.services import order
    with sc.act(buyer, when) as s:
        po = order.create_from_requisition(s, requisition=pr_no, lines=list(lines), supplier_code=supplier)[0]
        po_id, po_no = po.id, po.number
    if approve:
        sc.approve_all(po_id, when + timedelta(hours=2), "Price and supplier checked against the quotation")
    return po_id, po_no


def confirm(sc: Scenario, supplier_user: str, when: datetime, po_id: uuid.UUID, note: Optional[str] = None) -> str:
    from app.pic.services import order
    with sc.act(supplier_user, when) as s:
        po = s.get(PurchaseOrder, po_id)
        order.confirm(s, po, "CONFIRMED", note=note)
        return po.status


def post_invoice(sc: Scenario, supplier_user: str, ap_user: str, when: datetime, *, supplier: str, number: str, lines: list,
                 channel: str = "PORTAL") -> dict:
    """F7: supplier captures the invoice (duplicate check + match), accounts payable approves and posts it."""
    from app.pic.services import payables
    with sc.act(supplier_user, when) as s:
        invoice = payables.capture(s, supplier=supplier, supplier_invoice_no=number, invoice_date=when.astimezone(clock.IST).date(),
                                   channel=channel, lines=lines)
        invoice_id, status, match_type = invoice.id, invoice.status, invoice.match_type
    if status != "MATCHED":
        raise RuntimeError(f"{number} did not match first time: {status}")
    with sc.act(ap_user, when + timedelta(hours=3)) as s:
        invoice = s.get(Invoice, invoice_id)
        payables.approve(s, invoice)
        posted = payables.post(s, invoice, payables.posting_key(s, invoice))
    return {"invoice": number, "matchType": match_type, "erpDocument": posted.get("erpDocument")}


def load_budgets(sc: Scenario, when: datetime, company_code: str, cost_objects: list, budgets: list, fiscal_year: str, ref: str) -> list[str]:
    """§12.4-style initial load of cost objects and budgets (no maintenance service exists); check-then-insert, audited."""
    clock.set_pinned(when)
    loaded = []
    with tenant_tx(sc.tenant_id) as s:
        have = {(t, c) for t, c in s.execute(select(CostObject.type, CostObject.code))}
        for obj_type, code, name in cost_objects:
            if (obj_type, code) not in have:
                s.add(CostObject(tenant_id=sc.tenant_id, type=obj_type, code=code, name=name, company_code=company_code))
        for obj_type, code, control, amount_minor in budgets:
            exists = s.execute(select(Budget.id).where(Budget.cost_object_type == obj_type, Budget.cost_object_code == code,
                                                       Budget.fiscal_year == fiscal_year)).first()
            if exists:
                continue
            s.add(Budget(tenant_id=sc.tenant_id, cost_object_type=obj_type, cost_object_code=code, fiscal_year=fiscal_year, control=control,
                         amount_minor=amount_minor, committed_minor=0, consumed_minor=0))
            loaded.append(f"{obj_type}:{code}")
        audit.record(s, "MIGRATION", uuid.uuid5(uuid.NAMESPACE_URL, f"{sc.tenant_code}-{ref}"), "INITIAL_LOAD", object_ref=f"budgets {fiscal_year}",
                     after={"costObjects": [f"{t}:{c}" for t, c, _ in cost_objects], "budgets": loaded}, actor="migration")
    return loaded


# ======================================================================== Axion June 2027 data
USERS = [
    ("capex.committee", "Venkatesh Raman (capex committee secretary)", ["CAPEX_COMMITTEE"], {}),
    ("capex.controller", "Nirmala Devi (capex controller)", ["COST_OBJECT_OWNER"],
     {"cost_objects": ["ASSET:AST-P100-VMC-07", "WBS:CX-2728-04"]}),
    ("works.head", "Senthil Kumar (works head, Hosur)", ["DEPT_HEAD"],
     {"cost_objects": ["ASSET:AST-P100-VMC-07", "WBS:CX-2728-04", "COST_CENTER:4150"]}),
    ("admin.manager", "Gayathri Sekar (plant administration)", ["COST_OBJECT_OWNER"], {"cost_objects": ["COST_CENTER:4150"]}),
]
ROLE_USER = {**axion.ROLE_USER, "COST_OBJECT_OWNER": ["capex.controller", "admin.manager", "plant.controller"],
             "DEPT_HEAD": ["works.head", "ops.head"], "CAPEX_COMMITTEE": "capex.committee"}

COST_OBJECTS = [("ASSET", "AST-P100-VMC-07", "Vertical machining centre – Line 4, Hosur (capex FY 2027-28)"),
                ("WBS", "CX-2728-04", "Line 4 machining cell automation (capex FY 2027-28)"),
                ("COST_CENTER", "4150", "Plant administration & safety – Hosur")]
BUDGETS = [("ASSET", "AST-P100-VMC-07", "HARD", 60 * L), ("WBS", "CX-2728-04", "HARD", 25 * L), ("COST_CENTER", "4150", "SOFT", 8 * L)]

ISO9001 = lambda code, n: [{"type": "ISO9001", "number": f"QMS-{code}-{n}", "issued_on": "2025-07-01", "expires_on": "2028-06-30"}]  # noqa: E731

SUPPLIERS = [
    {"code": "NPM201", "name": "Noyyal Precision Machines Pvt Ltd", "pan": "AAKCN4821M", "state": "33", "ifsc": "CNRB0002841", "account": "2841101004417",
     "terms": "N45", "incoterms": "DAP Hosur", "categories": ["CAPEX-MACHINERY"], "user_local": "sales", "user_role": "sales",
     "scores": (84, 82), "note": "Machine-tool builder; service engineer within 24 h in Tamil Nadu; references checked",
     "address": {"line1": "SIDCO Industrial Estate, Kurichi", "city": "Coimbatore", "state_code": "33", "pin": "641021", "country": "IN"}},
    {"code": "VFS202", "name": "Vegavathi Fastening Systems Pvt Ltd", "pan": "AAJCV7314H", "state": "33", "ifsc": "HDFC0004417",
     "account": "50200044173361", "terms": "N30", "incoterms": "DAP Hosur", "categories": ["FASTENERS"], "user_local": "vmi", "user_role": "VMI desk",
     "scores": (81, 79), "note": "VMI partner: consignment stock at Hosur, weekly replenishment, PPAP for bolts",
     "address": {"line1": "SIPCOT Industrial Park, Phase II", "city": "Sriperumbudur", "state_code": "33", "pin": "602105", "country": "IN"}},
    {"code": "THT203", "name": "Thenpennai Heat Treaters Pvt Ltd", "pan": "AAGCT2905L", "state": "33", "ifsc": "ICIC0006215", "account": "621505002217",
     "terms": "N30", "incoterms": None, "categories": ["HEAT-TREATMENT"], "user_local": "planning", "user_role": "planning",
     "scores": (80, 78), "note": "Sealed-quench furnaces, hardness lab; CQI-9 self-assessment reviewed",
     "address": {"line1": "Plot 41, SIPCOT Phase I", "city": "Hosur", "state_code": "33", "pin": "635126", "country": "IN"}},
    {"code": "KFP204", "name": "Kortalaiyar Forgings Pvt Ltd", "pan": "AAFCK6148R", "state": "33", "ifsc": "UTIB0001934", "account": "919020044817362",
     "terms": "N45", "incoterms": "FCA Ambattur", "categories": ["STEEL-FORGINGS"], "user_local": "sales", "user_role": "sales",
     "scores": (83, 81), "note": "Closed-die forging up to 12 kg; EN19 heat certificates per lot",
     "address": {"line1": "Ambattur Industrial Estate, North Phase", "city": "Chennai", "state_code": "33", "pin": "600098", "country": "IN"}},
    {"code": "MOS205", "name": "Melagiri Office & Safety Supplies Pvt Ltd", "pan": "AAHCM3372P", "state": "33", "ifsc": "SBIN0007731",
     "account": "39117731052", "terms": "N30", "incoterms": "DAP Hosur", "categories": ["OFFICE-SAFETY"], "user_local": "orders", "user_role": "orders",
     "scores": (78, 76), "note": "Indirect supplier for PPE, furniture and stationery; BIS-marked PPE",
     "address": {"line1": "Rayakottai Road", "city": "Krishnagiri", "state_code": "33", "pin": "635001", "country": "IN"}},
]


def _june(day: int, hour: int = 10, minute: int = 0) -> datetime:
    return at(date(2027, 6, day), hour, minute)


def _supplier_user(spec: dict) -> str:
    return f"{spec['user_local']}@{spec['code'].lower()}.example"


def apply(tenant_code: str, password: str) -> dict:
    from app.pic.services import receiving, requisition as req_svc
    from app.pic.services import payables

    sc = Scenario(tenant_id_of(tenant_code), tenant_code, axion.DOMAIN, ROLE_USER)
    supplier_user = {}

    # ------------------------------------------------------------ masters: users, cost objects + FY 2027-28 budgets, suppliers, materials
    clock.set_pinned(_june(1, 9))
    added = add_users(sc, USERS, password)
    budgets = load_budgets(sc, _june(1, 9), "1000", COST_OBJECTS, BUDGETS, FISCAL_YEAR, "purchase-types-budgets-2027-28")
    sc.note(f"Users {', '.join(added) or '(present)'}; FY 2027-28 budgets loaded for {', '.join(budgets) or '(present)'}")
    for spec in SUPPLIERS:
        spec = {**spec, "gstin": gstin(spec["state"], spec["pan"]), "user": _supplier_user(spec),
                "certificates": ISO9001(spec["code"], 4400 + SUPPLIERS.index(spec))}
        onboard(sc, spec, password, date(2027, 6, 1))
        supplier_user[spec["code"]] = spec["user"]

    bolt = material_via_f9(sc, "buyer", _june(3, 10), description="Hex flange bolt M10 x 30, class 10.9, zinc flake, VMI consignment",
                           type="STOCK", material_group="FASTENERS", category="FASTENERS", base_uom="EA", hsn_code="73181500",
                           mpn="VFS-HFB-M10X30-109", attributes={"thread": "M10x1.5", "length_mm": "30", "class": "10.9", "coating": "zinc flake"})
    blank = material_via_f9(sc, "buyer", _june(3, 11), description="Forged blank for drive shaft SH-2207, EN19, as forged",
                            type="STOCK", material_group="STEEL-FORGINGS", category="STEEL-FORGINGS", base_uom="EA", hsn_code="73261990",
                            mpn="AXN-SH-2207-FB", attributes={"grade": "EN19", "condition": "as forged", "weight_kg": "3.4"})
    shaft = material_via_f9(sc, "buyer", _june(3, 12), description="Drive shaft SH-2207 hardened and tempered 28-32 HRC",
                            type="STOCK", material_group="SUBCON-HT", category="HEAT-TREATMENT", base_uom="EA", hsn_code="84831099",
                            mpn="AXN-SH-2207-HT", attributes={"hardness": "28-32 HRC", "process": "harden + temper",
                                                              "subcontractingBom": [{"material": blank, "qtyPer": "1"}]})

    # ------------------------------------------------------------ E1 expense below the receipt-less threshold → 2-way
    _, e1_pr, _ = requisition(sc, "requester", _june(7, 10), purpose_code="SAFETY", purpose_text="PPE for the new Line 4 crew", plant="P100", lines=[
        {"item_type": "FREE_TEXT", "purchase_type": "EXPENSE", "description": "Safety helmet with ratchet and chin strap, IS 2925, yellow",
         "material_group": "PPE", "category": "OFFICE-SAFETY", "qty": "40", "uom": "EA", "price_est_minor": 42_000,
         "account_assignment_type": "COST_CENTER", "account_assignment_code": "4150", "need_date": "2027-06-14"}])
    e1_pr_id = _pr_id(sc, e1_pr)
    sc.approve_all(e1_pr_id, _june(7, 14), "PPE within the safety budget")
    e1_po_id, e1_po = order_from(sc, "buyer", _june(8, 10), e1_pr, supplier="MOS205")
    confirm(sc, supplier_user["MOS205"], _june(8, 16), e1_po_id, "Dispatch with the next Hosur route")
    refused = None
    try:  # the stores clerk tries to book a receipt for the helmets: refused, the line is receipt-less (P08)
        with sc.act("receiver", _june(14, 9)) as s:
            receiving.post_gr(s, s.get(PurchaseOrder, e1_po_id), lines=[{"line": 10, "qty": "40"}], delivery_note="MOS-DC-5502")
    except Problem as exc:
        refused = f"{exc.rule_ref}: {exc.detail}"
    if not refused or not refused.startswith("P08") or "receipt-less" not in refused:
        raise RuntimeError(f"E1 expected the receipt-less refusal, got {refused}")
    sc.note(f"E1 goods receipt refused — {refused}")
    e1_inv = post_invoice(sc, supplier_user["MOS205"], "ap.clerk", _june(14, 11), supplier="MOS205", number="MOS/27-28/0142",
                          lines=[{"po": e1_po, "po_line": 10, "qty": "40", "unit_price": "420", "gst_rate": "18"}])
    sc.note(f"E1 {e1_pr} → {e1_po} ₹16,800 receipt-less (below ₹25,000) → MOS/27-28/0142 matched {e1_inv['matchType']} and posted; PO invoiced without GR")

    # ------------------------------------------------------------ E2 expense above the threshold → GR + 3-way
    _, e2_pr, _ = requisition(sc, "requester", _june(8, 11), purpose_code="FACILITIES", purpose_text="Seating for the Line 4 office", plant="P100", lines=[
        {"item_type": "FREE_TEXT", "purchase_type": "EXPENSE", "description": "Ergonomic task chair with lumbar support and 4D armrests",
         "material_group": "FURNITURE", "category": "OFFICE-SAFETY", "qty": "12", "uom": "EA", "price_est_minor": 980_000,
         "account_assignment_type": "COST_CENTER", "account_assignment_code": "4150", "need_date": "2027-06-18", "quotes_attached": 1}])
    sc.approve_all(_pr_id(sc, e2_pr), _june(8, 15), "Quote MOS-Q-2711 attached")
    e2_po_id, e2_po = order_from(sc, "buyer", _june(9, 10), e2_pr, supplier="MOS205")
    confirm(sc, supplier_user["MOS205"], _june(9, 15), e2_po_id)
    with sc.act("receiver", _june(18, 11)) as s:
        e2_gr = receiving.post_gr(s, s.get(PurchaseOrder, e2_po_id), lines=[{"line": 10, "qty": "12"}], delivery_note="MOS-DC-5531").number
    e2_inv = post_invoice(sc, supplier_user["MOS205"], "ap.clerk", _june(18, 15), supplier="MOS205", number="MOS/27-28/0157",
                          lines=[{"po": e2_po, "po_line": 10, "qty": "12", "unit_price": "9800", "gst_rate": "18"}])
    sc.note(f"E2 {e2_pr} → {e2_po} ₹1,17,600 (above threshold) → {e2_gr} → MOS/27-28/0157 {e2_inv['matchType']} posted")

    # ------------------------------------------------------------ A1 capital asset: asset account, capex committee, hard budget, capitalised at GR
    a1_pr_id, a1_pr, _ = requisition(sc, "requester", _june(9, 11), purpose_code="CAPEX", purpose_text="Line 4 capacity for SH-2207 machining",
                                     plant="P100", lines=[
        {"item_type": "FREE_TEXT", "purchase_type": "ASSET", "description": "Vertical machining centre, 3-axis, 850 x 500 mm table, BT40, "
         "with 4th-axis rotary table", "material_group": "MACHINE-TOOLS", "category": "CAPEX-MACHINERY", "qty": "1", "uom": "EA",
         "price_est_minor": 4_650_000_00, "account_assignment_type": "ASSET", "account_assignment_code": "AST-P100-VMC-07",
         "need_date": "2027-06-30", "quotes_attached": 3}])
    with tenant_tx(sc.tenant_id) as s:
        a1_chain = list(s.get(Requisition, a1_pr_id).approval_chain)
    sc.approve_all(a1_pr_id, _june(10, 11), "Capex proposal CX-27-011 approved; three quotations compared")
    a1_po_id, a1_po = order_from(sc, "buyer", _june(11, 10), a1_pr, supplier="NPM201")
    confirm(sc, supplier_user["NPM201"], _june(11, 16), a1_po_id, "Machine ex-stock; dispatch 24 June after run-off")
    with sc.act(supplier_user["NPM201"], _june(24, 9)) as s:
        asn = receiving.create_asn(s, s.get(PurchaseOrder, a1_po_id), lines=[{"line": 10, "qty": "1"}], ship_date=date(2027, 6, 24),
                                   expected_date=date(2027, 6, 25), eway_bill_no="331012846620", vehicle_no="TN37DK8814", distance_km=310,
                                   documents=["Run-off report NPM-RO-1187", "Packing list NPM-PL-1187"])
        asn_id = asn.id
    with sc.act("receiver", _june(25, 12)) as s:
        from app.pic.models import Asn
        a1_gr = receiving.post_gr(s, s.get(PurchaseOrder, a1_po_id), asn=s.get(Asn, asn_id), lines=[{"line": 10, "qty": "1"}],
                                  delivery_note="NPM-DC-1187").number
    a1_inv = post_invoice(sc, supplier_user["NPM201"], "ap.clerk", _june(25, 16), supplier="NPM201", number="NPM/27-28/0057",
                          lines=[{"po": a1_po, "po_line": 10, "qty": "1", "unit_price": "4650000", "gst_rate": "18"}])
    sc.note(f"A1 {a1_pr} VMC ₹46.5 L on ASSET AST-P100-VMC-07: chain {' → '.join(a1_chain)} → {a1_po} → {a1_gr} → NPM/27-28/0057 "
            f"{a1_inv['matchType']} posted; asset budget consumed")

    # ------------------------------------------------------------ A2 WBS hard stop, scope cut, re-submitted and approved
    with sc.act("requester", _june(10, 10)) as s:
        pr = req_svc.create(s, origin="MANUAL", purpose_code="CAPEX", purpose_text="Line 4 cell automation", plant="P100", lines=[
            {"item_type": "FREE_TEXT", "purchase_type": "ASSET", "description": "Robotic loading cell for Line 4 with safety fencing and light curtains",
             "material_group": "AUTOMATION", "category": "CAPEX-MACHINERY", "qty": "1", "uom": "EA", "price_est_minor": 2_840_000_00,
             "account_assignment_type": "WBS", "account_assignment_code": "CX-2728-04", "need_date": "2027-08-31", "quotes_attached": 3}])
        a2_pr_id, a2_pr = pr.id, pr.number
    hard_stop = None
    try:
        with sc.act("requester", _june(10, 10, 5)) as s:
            req_svc.submit(s, s.get(Requisition, a2_pr_id))
    except Problem as exc:
        hard_stop = {"code": exc.code, "detail": exc.detail, "ruleRef": exc.rule_ref}
    if hard_stop is None or hard_stop["code"] != "BUDGET_EXCEEDED":
        raise RuntimeError(f"A2 expected the WBS hard stop, got {hard_stop}")
    with sc.act("requester", _june(10, 15)) as s:
        req_svc.change_line(s, s.get(Requisition, a2_pr_id), 10, {
            "price_est_minor": 2_260_000_00,
            "description": "Robotic loading cell for Line 4, gantry loader (fencing and light curtains by plant maintenance)"})
        req_svc.submit(s, s.get(Requisition, a2_pr_id))
    sc.approve_all(a2_pr_id, _june(11, 11), "Re-scoped within the WBS budget")
    a2_po_id, a2_po = order_from(sc, "buyer", _june(14, 10), a2_pr, supplier="NPM201")
    confirm(sc, supplier_user["NPM201"], _june(14, 16), a2_po_id, "Delivery 20 August; installation by our automation team")
    sc.note(f"A2 {a2_pr} ₹28.4 L on WBS CX-2728-04 → {hard_stop['code']} ({hard_stop['detail']}); cut to ₹22.6 L → approved → {a2_po} open")

    # ------------------------------------------------------------ C1 consignment: GR to consignment stock, withdrawals, ERS
    c1_pr_id, c1_pr, _ = requisition(sc, "requester", _june(11, 10), purpose_code="VMI_CONSIGNMENT",
                                     purpose_text="Opening VMI consignment stock for Line 4 assembly", plant="P100", lines=[
        {"item_type": "MATERIAL", "purchase_type": "CONSIGNMENT", "material": bolt, "qty": "20000", "price_est_minor": 640,
         "need_date": "2027-06-14", "storage_location": "0001"}])
    sc.approve_all(c1_pr_id, _june(11, 14), "VMI agreement: consignment at Hosur")
    c1_po_id, c1_po = order_from(sc, "buyer", _june(11, 16), c1_pr, supplier="VFS202")
    confirm(sc, supplier_user["VFS202"], _june(12, 10), c1_po_id)
    with sc.act("receiver", _june(14, 10)) as s:
        c1_gr = receiving.post_gr(s, s.get(PurchaseOrder, c1_po_id), lines=[{"line": 10, "qty": "20000", "batch": "VFS-2706-0417"}],
                                  delivery_note="VFS-DC-0417").number
    withdrawals = [(15, "6000", "PL-P100-270615-03"), (21, "5500", "PL-P100-270621-01"), (28, "4000", "PL-P100-270628-02")]
    for day_, qty, pick in withdrawals:
        with sc.act("receiver", _june(day_, 8)) as s:
            receiving.withdraw_consignment(s, material=bolt, plant="P100", qty=qty, usage_ref=pick, purpose="TRANSFER", storage_location="0001")
    with sc.act("ap.clerk", _june(30, 18)) as s:
        ers = payables.settle_consignment(s, supplier="VFS202", period_to=date(2027, 6, 30), reference="VFS/27-28/INV-0611")
        ers_id, ers_no, ers_status = ers.id, ers.number, ers.status
    if ers_status != "MATCHED":
        raise RuntimeError(f"{ers_no} did not match: {ers_status}")
    with sc.act("ap.clerk", _june(30, 18, 30)) as s:
        invoice = s.get(Invoice, ers_id)
        payables.approve(s, invoice)
        payables.post(s, invoice, payables.posting_key(s, invoice))
    sc.note(f"C1 {c1_pr} → {c1_po} → {c1_gr} 20,000 into consignment stock; withdrawals 6,000 + 5,500 + 4,000 (411K) → "
            f"{ers_no} self-billing for 15,500 matched ERS and posted; 4,500 remain supplier-owned")

    # ------------------------------------------------------------ S1 subcontracting: blanks bought, provided (541), consumed at GR (543)
    s1a_pr_id, s1a_pr, _ = requisition(sc, "requester", _june(11, 11), purpose_code="PRODUCTION", purpose_text="Forged blanks for SH-2207 launch lot",
                                       plant="P100", lines=[
        {"item_type": "MATERIAL", "purchase_type": "STOCK", "material": blank, "qty": "2000", "price_est_minor": 38_500,
         "need_date": "2027-06-16", "storage_location": "0001"}])
    sc.approve_all(s1a_pr_id, _june(11, 15), "Launch quantity per the SH-2207 PPAP plan")
    s1a_po_id, s1a_po = order_from(sc, "buyer", _june(12, 10), s1a_pr, supplier="KFP204")
    confirm(sc, supplier_user["KFP204"], _june(12, 15), s1a_po_id)
    with sc.act("receiver", _june(16, 10)) as s:
        s1a_gr = receiving.post_gr(s, s.get(PurchaseOrder, s1a_po_id), lines=[{"line": 10, "qty": "2000", "batch": "KFP-H27-0612"}],
                                   delivery_note="KFP-DC-2219").number
    post_invoice(sc, supplier_user["KFP204"], "ap.clerk", _june(16, 15), supplier="KFP204", number="KFP/27-28/0219",
                 lines=[{"po": s1a_po, "po_line": 10, "qty": "2000", "unit_price": "385", "gst_rate": "18"}])

    s1_pr_id, s1_pr, _ = requisition(sc, "requester", _june(12, 11), purpose_code="PRODUCTION", purpose_text="Heat treatment of SH-2207 launch lot",
                                     plant="P100", lines=[
        {"item_type": "MATERIAL", "purchase_type": "SUBCONTRACTING", "material": shaft, "qty": "1200", "price_est_minor": 6_200,
         "need_date": "2027-06-29", "storage_location": "0001"}])
    sc.approve_all(s1_pr_id, _june(12, 15), "Processing fee as per THT rate card")
    s1_po_id, s1_po = order_from(sc, "buyer", _june(14, 11), s1_pr, supplier="THT203")
    confirm(sc, supplier_user["THT203"], _june(14, 17), s1_po_id, "Furnace slot 22–28 June")
    with sc.act("receiver", _june(17, 9)) as s:
        receiving.provide_components(s, s.get(PurchaseOrder, s1_po_id), 10, components=[{"material": blank, "qty": "1000", "batch": "KFP-H27-0612"}])
    with sc.act("receiver", _june(23, 15)) as s:
        s1_gr1 = receiving.post_gr(s, s.get(PurchaseOrder, s1_po_id), lines=[{"line": 10, "qty": "700", "batch": "THT-2706-23A"}],
                                   delivery_note="THT-DC-0923").number
    short = None
    try:
        with sc.act("receiver", _june(26, 10)) as s:
            receiving.post_gr(s, s.get(PurchaseOrder, s1_po_id), lines=[{"line": 10, "qty": "500", "batch": "THT-2706-26B"}], delivery_note="THT-DC-0931")
    except Problem as exc:
        short = exc.code
    if short != "COMPONENTS_MISSING":
        raise RuntimeError(f"S1 expected COMPONENTS_MISSING, got {short}")
    with sc.act("receiver", _june(26, 11)) as s:
        receiving.provide_components(s, s.get(PurchaseOrder, s1_po_id), 10, components=[{"material": blank, "qty": "200", "batch": "KFP-H27-0612"}])
    with sc.act("receiver", _june(29, 15)) as s:
        s1_gr2 = receiving.post_gr(s, s.get(PurchaseOrder, s1_po_id), lines=[{"line": 10, "qty": "500", "batch": "THT-2706-26B"}],
                                   delivery_note="THT-DC-0931").number
    s1_inv = post_invoice(sc, supplier_user["THT203"], "ap.clerk", _june(29, 17), supplier="THT203", number="THT/27-28/0311",
                          lines=[{"po": s1_po, "po_line": 10, "qty": "1200", "unit_price": "62", "gst_rate": "18"}])
    sc.note(f"S1 {s1a_po} 2,000 blanks → {s1a_gr}; {s1_po} heat treatment 1,200: 1,000 blanks provided (541) → {s1_gr1} 700 (543) → "
            f"500 refused ({short}) → 200 more provided → {s1_gr2} 500 → THT/27-28/0311 {s1_inv['matchType']} posted")

    relay(sc, _june(30, 19))
    clock.set_pinned(None)
    with tenant_tx(sc.tenant_id) as s:
        po_count = len([e1_po, e2_po, a1_po, a2_po, c1_po, s1a_po, s1_po])
        receipts = s.execute(select(GoodsReceipt.number).where(GoodsReceipt.po_id.in_([e2_po_id, a1_po_id, c1_po_id, s1a_po_id, s1_po_id]))).scalars().all()
    return {"notes": sc.log,
            "counts": {"suppliers": len(SUPPLIERS), "materials": 3, "requisitions": 7, "purchaseOrders": po_count, "goodsReceipts": len(receipts),
                       "invoices": 6, "ersSettlements": 1, "consignmentWithdrawals": len(withdrawals), "componentProvisions": 2},
            "keys": {"suppliers": [s_["code"] for s_ in SUPPLIERS], "materials": {"bolt": bolt, "blank": blank, "shaft": shaft},
                     "invoices": ["MOS/27-28/0142", "MOS/27-28/0157", "NPM/27-28/0057", "KFP/27-28/0219", "THT/27-28/0311", ers_no],
                     "costObjects": [f"{t}:{c}" for t, c, _ in COST_OBJECTS]}}


def _pr_id(sc: Scenario, number: str) -> uuid.UUID:
    with tenant_tx(sc.tenant_id) as s:
        return s.execute(select(Requisition.id).where(Requisition.number == number)).scalar_one()
