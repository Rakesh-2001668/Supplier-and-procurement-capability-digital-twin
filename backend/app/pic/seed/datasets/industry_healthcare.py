"""D6 healthcare demo tenant HLT (blueprint §23 / §23.1): consignment implant KN-77, lot/expiry/serial at receipt,
usage-triggered replenishment, monthly self-billing and a supplier recall traced lot by lot.

Tamravati Health Systems Pvt Ltd (fictional hospital group, Tamil Nadu) runs two hospitals — H100 Chennai and H200
Coimbatore — each with an orthopaedic OT implant store (storage location OT01). Everything below runs through the domain
services on the tenant's own timeline Oct 2026 – Mar 2027:

  bootstrap   tenant HLT from the HEALTHCARE industry template; company code 1000 (GSTIN 33…), plants H100/H200, cost
              centres 6100/6200 orthopaedics and 6900 central stores; OT implant stores; SUPPLIER-QUAL version for category
              ORTHO-IMPLANTS requiring ISO 13485 and the CDSCO manufacturing licence (rule version, audited)
  F8          Vaigai Orthotech Devices Pvt Ltd (fictional, Madurai) onboarded: profile with ISO 13485 + CDSCO licence,
              screening, bank call-back, dual finance approval, qualification for ORTHO-IMPLANTS
  F9          KN-77 primary knee femoral component (HSN 9021 31 00) through the four data stewards, lot-, expiry- and
              serial-managed with 180 days minimum shelf life at receipt; the finance steward then sets the GST rate
  F4          quantity (rate) contract for KN-77 per hospital, Nov 2026 – Oct 2027, approved, signed, active
  F2/F5/F6    opening consignment stock: one requisition (6 Chennai + 4 Coimbatore), touchless contract PO, two ASNs with
              lots and serials, receipts into consignment stock with lot, expiry and serial captured (gr_line.batch/expiry)
  usage       five surgical cases withdraw one implant each (201K to the orthopaedics cost centre, serial recorded); every
              withdrawal raises the replenishment requisition (usage-triggered), approved, touchless PO, new lot received
  F7          month-end self-billing (ERS) for exactly the implants used — Dec, Jan, Feb — approved and posted; payment runs
              in Feb and Mar pay the due settlements
  recall      18 Feb 2027 the supplier's field safety notice VOD-FSN-2027-002 recalls lot VOD-KN77-2610A: the trace shows the
              lot was received at both hospitals, which three cases received which serials, and that three units were still
              on the shelf; those are quarantined and returned (return deliveries), and replacements are ordered

Prices, lots, serials, case numbers and licence numbers are fictional. Case references carry no patient data.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import Asn, Contract, Invoice, Material, PurchaseOrder, Requisition, RuleSet, StorageLocation, Supplier
from app.pic.platform import audit, clock, rules
from app.pic.seed import reference
from app.pic.seed.axion import Scenario, at
from app.pic.seed.datasets.purchase_types import add_users, gstin, material_via_f9, onboard, relay

KEY = "industry-healthcare"
VERSION = "1"
TITLE = "D6 healthcare demo tenant HLT: consignment implant KN-77, lot/expiry, usage-triggered PO, recall trace"
TENANTS = ('HLT',)
CREATES_TENANT = True
READY = True

NAME = "Tamravati Health Systems Pvt Ltd"
DOMAIN = "tamravati.example"
CATEGORY = "ORTHO-IMPLANTS"
PRICE_MINOR = 28_650_00          # contract price per KN-77 femoral component (fictional)
GST_RATE = Decimal(5)            # HSN 9021 31 00 artificial joints; confirm against the current GST rate notification

USERS = [
    ("admin", "Tenant Administrator", ["TENANT_ADMIN"], {}),
    ("ot.coordinator", "Jency Thomas (OT materials coordinator, Chennai)", ["REQUESTER"],
     {"plants": ["H100"], "cost_objects": ["COST_CENTER:6100"]}),
    ("ot.coordinator.cbe", "Revathi Krishnan (OT materials coordinator, Coimbatore)", ["REQUESTER"],
     {"plants": ["H200"], "cost_objects": ["COST_CENTER:6200"]}),
    ("materials.manager", "R. Balasubramanian (materials manager)", ["COST_OBJECT_OWNER"],
     {"plants": ["H100", "H200"], "cost_objects": ["COST_CENTER:6100", "COST_CENTER:6200", "COST_CENTER:6900"]}),
    ("medical.superintendent", "Dr. Kavya Natarajan (medical superintendent)", ["DEPT_HEAD"],
     {"plants": ["H100", "H200"], "cost_objects": ["COST_CENTER:6100", "COST_CENTER:6200", "COST_CENTER:6900"]}),
    ("procurement.head", "Harish Venkatraman (head of procurement)", ["PROCUREMENT_HEAD"], {}),
    ("buyer", "Aishwarya Mohan (buyer, implants)", ["BUYER"], {"plants": ["H100", "H200"]}),
    ("buyer.lead", "Pradeep Kannan (lead buyer)", ["BUYER"], {"plants": ["H100", "H200"]}),
    ("stores.chennai", "Manikandan Selvam (implant store, Chennai)", ["RECEIVER"], {"plants": ["H100"]}),
    ("stores.coimbatore", "Saravanan Palanisamy (implant store, Coimbatore)", ["RECEIVER"], {"plants": ["H200"]}),
    ("contract.manager", "Lavanya Iyer (contract manager)", ["CONTRACT_MANAGER"], {}),
    ("contract.manager2", "Rohit Menon (contract manager)", ["CONTRACT_MANAGER"], {}),
    ("finance.controller", "Shankar Raman (finance controller)", ["FINANCE_CONTROLLER"], {}),
    ("finance.controller2", "Meera Pillai (deputy finance controller)", ["FINANCE_CONTROLLER"], {}),
    ("supplier.manager", "Deepika Rao (vendor management)", ["SUPPLIER_MANAGER"], {"categories": ["*"]}),
    ("mdm.purchasing", "Arjun Prasad", ["MDM_STEWARD"], {"steward_domains": ["PURCHASING"]}),
    ("mdm.quality", "Dr. Sowmya Raghunathan", ["MDM_STEWARD"], {"steward_domains": ["QUALITY"]}),
    ("mdm.finance", "Karthika Murali", ["MDM_STEWARD"], {"steward_domains": ["FINANCE"]}),
    ("mdm.plant", "Vinoth Kumar", ["MDM_STEWARD"], {"steward_domains": ["PLANT"]}),
    ("ap.clerk", "Nasreen Banu (accounts payable)", ["AP_CLERK"], {}),
    ("quality.manager", "Dr. Arvind Shenoy (biomedical engineering & quality)", ["QUALITY_INSPECTOR"], {"plants": ["H100", "H200"]}),
]
ROLE_USER = {
    "COST_OBJECT_OWNER": "materials.manager", "DEPT_HEAD": "medical.superintendent", "PROCUREMENT_HEAD": "procurement.head",
    "FINANCE_CONTROLLER": ["finance.controller", "finance.controller2"], "BUYER": "buyer.lead",
    "CONTRACT_MANAGER": ["contract.manager", "contract.manager2"],
    "MDM_STEWARD": ["mdm.purchasing", "mdm.quality", "mdm.finance", "mdm.plant"],
}
PLANTS = {"H100": ("Tamravati Hospital – Chennai", "ot.coordinator", "stores.chennai", "COST_CENTER:6100", 460),
          "H200": ("Tamravati Hospital – Coimbatore", "ot.coordinator.cbe", "stores.coimbatore", "COST_CENTER:6200", 215)}

SUPPLIER = {
    "code": "VOD001", "name": "Vaigai Orthotech Devices Pvt Ltd", "gstin": gstin("33", "AAKCV6634D"), "ifsc": "IOBA0003318",
    "account": "331802000004417", "terms": "N45", "incoterms": "DAP hospital implant store", "categories": [CATEGORY],
    "segment": "STRATEGIC", "user": "orders@vod001.example", "user_role": "orders & field support", "scores": (86, 84),
    "note": "ISO 13485 and CDSCO manufacturing licence verified; consignment and recall procedure reviewed by biomedical engineering",
    "questionnaire": {"udi": "GS1 labels", "sterilisation": "EtO, validated", "recallProcedure": "SOP-VOD-QA-014"},
    "address": {"line1": "Kappalur Industrial Estate", "city": "Madurai", "state_code": "33", "pin": "625008", "country": "IN"},
    "certificates": [
        {"type": "ISO13485", "number": "MD-QMS-VOD-2291", "issued_on": "2025-04-01", "expires_on": "2028-03-31", "mandatory_for": [CATEGORY]},
        {"type": "CDSCO_MFG_LICENCE", "number": "MFG/MD/2025/000417", "issued_on": "2025-01-15", "expires_on": "2030-01-14",
         "mandatory_for": [CATEGORY]}],
}

# Lots of the opening consignment stock: lot → expiry; serials are <lot>-<nnn>.
LOTS = {"VOD-KN77-2610A": "2031-08-31", "VOD-KN77-2610B": "2031-09-30", "VOD-KN77-2610C": "2031-10-31",
        "VOD-KN77-2611D": "2031-11-30", "VOD-KN77-2612E": "2031-12-31", "VOD-KN77-2702F": "2032-01-31"}
EWAY_BILLS = {"H100": "331011604417", "H200": "331011702285"}  # opening shipments (consignment value above ₹50,000)
RECALLED_LOT = "VOD-KN77-2610A"
NOTICE = "VOD-FSN-2027-002"
# Surgical cases: (date, plant, case reference, serial used, lot of the replenishment delivery, receipt date)
CASES = [
    (date(2026, 12, 3), "H100", "OT-H100-2612-0031", "VOD-KN77-2610A-001", "VOD-KN77-2611D", date(2026, 12, 7)),
    (date(2026, 12, 15), "H200", "OT-H200-2612-0014", "VOD-KN77-2610A-005", "VOD-KN77-2611D", date(2026, 12, 18)),
    (date(2027, 1, 8), "H100", "OT-H100-2701-0007", "VOD-KN77-2610B-001", "VOD-KN77-2612E", date(2027, 1, 12)),
    (date(2027, 1, 21), "H100", "OT-H100-2701-0026", "VOD-KN77-2610A-002", "VOD-KN77-2612E", date(2027, 1, 25)),
    (date(2027, 2, 4), "H200", "OT-H200-2702-0003", "VOD-KN77-2610C-001", "VOD-KN77-2612E", date(2027, 2, 8)),
]


def serials(lot: str, first: int, count: int) -> list[str]:
    return [f"{lot}-{n:03d}" for n in range(first, first + count)]


def _next_serial(sc: Scenario, lot: str) -> int:
    """Next free serial number of a lot (the supplier numbers serials per lot across deliveries)."""
    from app.pic.models import GrLine
    with tenant_tx(sc.tenant_id) as s:
        used = [x for g in s.execute(select(GrLine).where(GrLine.batch == lot)).scalars() for x in (g.serials or [])]
    return max((int(x.rsplit("-", 1)[1]) for x in used), default=0) + 1


def _setup(sc_tenant_code: str, password: str) -> Scenario:
    reference.deploy_process_definitions()
    tenant_id = reference.create_tenant(sc_tenant_code, NAME, "HEALTHCARE")
    reference.bootstrap(tenant_id, company=("1000", NAME, gstin("33", "AAICT5521Q")),
                        plants=[("H100", PLANTS["H100"][0], "33"), ("H200", PLANTS["H200"][0], "33")],
                        cost_objects=[("COST_CENTER", "6100", "Orthopaedics & joint replacement – Chennai"),
                                      ("COST_CENTER", "6200", "Orthopaedics & joint replacement – Coimbatore"),
                                      ("COST_CENTER", "6900", "Central sterile services & stores")],
                        holidays=[date(2026, 11, 8), date(2027, 1, 15), date(2027, 1, 26)])
    sc = Scenario(tenant_id, sc_tenant_code, DOMAIN, ROLE_USER)
    clock.set_pinned(at(date(2026, 10, 1), 9))
    add_users(sc, USERS, password)
    with sc.act("admin", at(date(2026, 10, 1), 10)) as s:
        have = {(x.plant, x.code) for x in s.execute(select(StorageLocation)).scalars()}
        for plant in PLANTS:
            if (plant, "OT01") not in have:
                s.add(StorageLocation(tenant_id=tenant_id, plant=plant, code="OT01", name="Orthopaedic OT implant store (consignment)"))
        # Category-scoped qualification rule (P14 effective-dated version): implants need ISO 13485 and the CDSCO licence.
        if not s.execute(select(RuleSet.id).where(RuleSet.key == "SUPPLIER-QUAL", RuleSet.category == CATEGORY)).first():
            body = {**rules.resolve(s, "SUPPLIER-QUAL").body, "mandatoryCertificates": {CATEGORY: ["ISO13485", "CDSCO_MFG_LICENCE"]},
                    "sampleApprovalRequired": []}
            rule = RuleSet(tenant_id=tenant_id, key="SUPPLIER-QUAL", version="2026.1-ORTHO", category=CATEGORY, effective_from=date(2026, 4, 1),
                           body=body, description="Implant suppliers: ISO 13485 and CDSCO manufacturing licence mandatory (healthcare template)",
                           created_by=s.info["principal"].user_id)
            s.add(rule)
            s.flush()
            audit.record(s, "RULE_SET", rule.id, "VERSION_CREATED", object_ref="SUPPLIER-QUAL@2026.1-ORTHO",
                         after={"category": CATEGORY, "mandatoryCertificates": body["mandatoryCertificates"][CATEGORY]})
    sc.note(f"HLT {NAME}: HEALTHCARE template, plants H100/H200 with OT implant stores, SUPPLIER-QUAL@2026.1-ORTHO")
    return sc


def _approve_requisition(sc: Scenario, pr_no: str, when: datetime, comment: str) -> None:
    with tenant_tx(sc.tenant_id) as s:
        pr_id = s.execute(select(Requisition.id).where(Requisition.number == pr_no)).scalar_one()
    sc.approve_all(pr_id, when, comment)


def _order(sc: Scenario, pr_no: str, when: datetime, lines=(10,)) -> tuple:
    """Buyer converts the approved requisition; the contract price makes the PO touchless (DMN-02); the supplier confirms."""
    from app.pic.services import order
    with sc.act("buyer", when) as s:
        po = order.create_from_requisition(s, requisition=pr_no, lines=list(lines))[0]
        po_id, po_no, touchless = po.id, po.number, po.touchless
    sc.approve_all(po_id, when + timedelta(hours=1), "Contract price, consignment")  # no-op when touchless
    with sc.act(SUPPLIER["user"], when + timedelta(hours=3)) as s:
        order.confirm(s, s.get(PurchaseOrder, po_id), "CONFIRMED", note="Consignment delivery to the OT implant store")
    return po_id, po_no, touchless


def _receive(sc: Scenario, po_id, plant: str, when: datetime, lots: list[tuple[int, str, int]], *, asn: bool, note: str) -> str:
    """ASN (optional) and GR into the OT implant store with lot, expiry and serials: lots = [(po line, lot, qty)]."""
    from app.pic.services import receiving
    gr_lines, asn_lines = [], {}
    for line, lot, qty in lots:
        first = _next_serial(sc, lot)
        numbers = serials(lot, first, qty)
        gr_lines.append({"line": line, "qty": str(qty), "batch": lot, "expiry": LOTS[lot], "serials": numbers, "storage_location": "OT01"})
        asn_lines.setdefault(line, []).append({"batch": lot, "qty": str(qty), "expiry": LOTS[lot], "serials": numbers})
    asn_id = None
    if asn:
        with sc.act(SUPPLIER["user"], when - timedelta(days=1)) as s:
            created = receiving.create_asn(
                s, s.get(PurchaseOrder, po_id), lines=[{"line": line, "qty": str(sum(int(b["qty"]) for b in batches)), "batches": batches}
                                                      for line, batches in asn_lines.items()],
                ship_date=(when - timedelta(days=1)).date(), expected_date=when.date(), eway_bill_no=EWAY_BILLS[plant],
                vehicle_no="TN59AQ2207", distance_km=PLANTS[plant][4], documents=[f"Delivery challan VOD-DC-{when:%y%m%d}-{plant}", "Sterility certificates per lot"])
            asn_id = created.id
    with sc.act(PLANTS[plant][2], when) as s:
        gr = receiving.post_gr(s, s.get(PurchaseOrder, po_id), lines=gr_lines, asn=s.get(Asn, asn_id) if asn_id else None,
                               delivery_note=f"VOD-DC-{when:%y%m%d}-{plant}")
        number = gr.number
    sc.note(f"{note}: {number} at {plant}/OT01 — " + ", ".join(f"{qty} × lot {lot} (exp {LOTS[lot]})" for _, lot, qty in lots))
    return number


def _settle(sc: Scenario, period_to: date, reference_no: str) -> str:
    from app.pic.services import payables
    when = at(period_to, 18)
    with sc.act("ap.clerk", when) as s:
        invoice = payables.settle_consignment(s, supplier=SUPPLIER["code"], period_to=period_to, reference=reference_no)
        invoice_id, number, status = invoice.id, invoice.number, invoice.status
    if status != "MATCHED":
        raise RuntimeError(f"{number}: {status}")
    with sc.act("ap.clerk", when + timedelta(minutes=30)) as s:
        invoice = s.get(Invoice, invoice_id)
        payables.approve(s, invoice)
        payables.post(s, invoice, payables.posting_key(s, invoice))
        sc.note(f"ERS {number}: {invoice.net_minor / 100:,.2f} + GST {invoice.tax_minor / 100:,.2f} for the implants used to {period_to.isoformat()}, posted")
    return number


def apply(tenant_code: str, password: str) -> dict:
    from app.pic.services import contract as contract_svc
    from app.pic.services import payables, receiving
    from app.pic.services import requisition as req_svc

    sc = _setup(tenant_code, password)

    # ------------------------------------------------------------ F8 implant supplier, F9 KN-77, tax classification
    supplier_id = onboard(sc, SUPPLIER, password, date(2026, 10, 5))
    kn77 = material_via_f9(sc, "materials.manager", at(date(2026, 10, 8), 10),
                           description="KN-77 primary knee system femoral component, cobalt-chromium, cemented, size 4",
                           type="STOCK", material_group="ORTHO-KNEE", category=CATEGORY, base_uom="EA", hsn_code="90213100", mpn="KN-77",
                           attributes={"implant": "knee femoral component", "deviceClass": "C", "sterile": True, "batchManaged": True,
                                       "expiryManaged": True, "serialManaged": True, "minShelfLifeDays": 180, "consignment": True})
    with sc.act("mdm.finance", at(date(2026, 10, 8), 16)) as s:
        material = s.execute(select(Material).where(Material.number == kn77)).scalar_one()
        before = {"gstRate": str(material.gst_rate), "plannedDeliveryDays": material.planned_delivery_days}
        material.gst_rate, material.planned_delivery_days = GST_RATE, 2
        audit.record(s, "MATERIAL", material.id, "MAINTAINED", object_ref=kn77, before=before,
                     after={"gstRate": str(GST_RATE), "plannedDeliveryDays": 2, "hsn": material.hsn_code},
                     reason="Finance steward: GST rate for HSN 9021 31 00; supplier replenishes consignment within 2 days")
        material_id = material.id

    # ------------------------------------------------------------ F4 KN-77 rate contract per hospital
    with sc.act("contract.manager", at(date(2026, 10, 20), 10)) as s:
        draft = contract_svc.create_draft(
            s, type="QUANTITY_CONTRACT", title="KN-77 knee femoral component – consignment rate contract FY 2026-27",
            supplier_id=supplier_id, company_code="1000", valid_from=date(2026, 11, 1), valid_to=date(2027, 10, 31),
            payment_terms=SUPPLIER["terms"], incoterms=SUPPLIER["incoterms"], owner_id=s.info["principal"].user_id,
            tolerances={"over_pct": "0", "under_pct": "0", "price_pct": "0"},
            lines=[{"material_id": material_id, "description": "KN-77 femoral component – Chennai", "plant": "H100", "uom": "EA",
                    "target_qty": "80", "unit_price_minor": PRICE_MINOR},
                   {"material_id": material_id, "description": "KN-77 femoral component – Coimbatore", "plant": "H200", "uom": "EA",
                    "target_qty": "40", "unit_price_minor": PRICE_MINOR}])
        contract_svc.ai_review(s, draft)
        contract_svc.submit(s, draft)
        contract_id, contract_no = draft.id, draft.number
    sc.approve_all(contract_id, at(date(2026, 10, 21), 11), "Value-analysis committee recommendation VAC-26-09 attached; clinical sign-off by HOD orthopaedics")
    with sc.act("contract.manager", at(date(2026, 10, 22), 10)) as s:
        contract_svc.sign(s, s.get(Contract, contract_id), "BUYER", "Lavanya Iyer, Contract Manager")
    with sc.act(SUPPLIER["user"], at(date(2026, 10, 22), 15)) as s:
        contract_svc.sign(s, s.get(Contract, contract_id), "SUPPLIER", "Authorised signatory, Vaigai Orthotech Devices")
    with sc.act("contract.manager", at(date(2026, 10, 23), 10)) as s:
        contract_svc.activate(s, s.get(Contract, contract_id))
    relay(sc, at(date(2026, 10, 23), 11), timers=True)
    sc.note(f"F4 {contract_no} KN-77 at ₹{PRICE_MINOR / 100:,.2f}: 80 Chennai + 40 Coimbatore, Nov 2026 – Oct 2027, active")

    # ------------------------------------------------------------ opening consignment stock: 6 Chennai + 4 Coimbatore
    with sc.act("ot.coordinator", at(date(2026, 11, 2), 10)) as s:
        pr = req_svc.create(s, origin="MANUAL", purpose_code="CONSIGNMENT_STOCKING", purpose_text="Opening KN-77 consignment stock in both OT implant stores",
                            plant="H100", lines=[
            {"item_type": "MATERIAL", "purchase_type": "CONSIGNMENT", "material": kn77, "qty": "6", "price_est_minor": PRICE_MINOR,
             "need_date": "2026-11-16", "plant": "H100", "storage_location": "OT01"},
            {"item_type": "MATERIAL", "purchase_type": "CONSIGNMENT", "material": kn77, "qty": "4", "price_est_minor": PRICE_MINOR,
             "need_date": "2026-11-17", "plant": "H200", "storage_location": "OT01"}])
        req_svc.submit(s, pr)
        opening_pr = pr.number
    _approve_requisition(sc, opening_pr, at(date(2026, 11, 2), 15), "Par level 6 / 4 agreed with orthopaedics")
    opening_po_id, opening_po, opening_touchless = _order(sc, opening_pr, at(date(2026, 11, 3), 10), lines=(10, 20))
    opening_grs = [
        _receive(sc, opening_po_id, "H100", at(date(2026, 11, 16), 11), [(10, "VOD-KN77-2610A", 4), (10, "VOD-KN77-2610B", 2)], asn=True,
                 note="Opening stock Chennai"),
        _receive(sc, opening_po_id, "H200", at(date(2026, 11, 17), 11), [(20, "VOD-KN77-2610A", 2), (20, "VOD-KN77-2610C", 2)], asn=True,
                 note="Opening stock Coimbatore"),
    ]
    relay(sc, at(date(2026, 11, 17), 18), timers=True)
    sc.note(f"Opening {opening_pr} → {opening_po} ({'touchless' if opening_touchless else 'approved'}) → {', '.join(opening_grs)}")

    # ------------------------------------------------------------ surgical cases: usage → replenishment (usage-triggered PO)
    replenishment_pos = []
    for day_, plant, case, serial, new_lot, receipt_day in CASES:
        coordinator, cost_object = PLANTS[plant][1], PLANTS[plant][3]
        with sc.act(coordinator, at(day_, 14)) as s:
            used = receiving.withdraw_consignment(s, material=kn77, plant=plant, qty="1", usage_ref=case, purpose="CONSUMPTION",
                                                  storage_location="OT01", serials=[serial], cost_object=cost_object, replenish=True)
        pr_no = used["replenishment"]["requisition"]
        _approve_requisition(sc, pr_no, at(day_, 17), f"Replenish implant used in {case}")
        po_id, po_no, _ = _order(sc, pr_no, at(day_ + timedelta(days=1), 10))
        gr_no = _receive(sc, po_id, plant, at(receipt_day, 11), [(10, new_lot, 1)], asn=False, note=f"Replenishment after {case}")
        replenishment_pos.append(po_no)
        sc.note(f"Usage {case}: serial {serial} ({used['lots'][0]['batch']}) → {used['movement']} to {cost_object}, liability "
                f"₹{used['liabilityMinor'] / 100:,.2f} → {pr_no} → {po_no} → {gr_no}")
        relay(sc, at(receipt_day, 18), timers=True)
    ers = [_settle(sc, date(2026, 12, 31), "VOD/26-27/TI-1412"), _settle(sc, date(2027, 1, 31), "VOD/26-27/TI-1509")]

    # ------------------------------------------------------------ recall of lot VOD-KN77-2610A (field safety notice)
    with sc.act("quality.manager", at(date(2027, 2, 18), 11)) as s:
        before = receiving.trace_lot(s, kn77, RECALLED_LOT)
        recall = receiving.recall_lot(s, material=kn77, batch=RECALLED_LOT, notice_ref=NOTICE,
                                      reason="Supplier field safety notice: sterile barrier pouch seal may be incomplete", replenish=True)
    sc.note(f"Recall {NOTICE} lot {RECALLED_LOT}: received at " + ", ".join(sorted({f"{r['plant']}/{r['storageLocation']}" for r in before["receipts"]}))
            + f"; implanted in {', '.join(u['usageRef'] for u in before['usage'])}; quarantined and returned "
            + ", ".join(f"{int(Decimal(q['qty']))} at {q['plant']} ({q['returnDelivery']})" for q in recall["quarantined"]))
    for replacement in recall["replenishments"]:
        _approve_requisition(sc, replacement["requisition"], at(date(2027, 2, 18), 16), f"Replacement for recalled lot {RECALLED_LOT}")
        po_id, po_no, _ = _order(sc, replacement["requisition"], at(date(2027, 2, 19), 10))
        _receive(sc, po_id, replacement["plant"], at(date(2027, 2, 22), 11), [(10, "VOD-KN77-2702F", int(Decimal(replacement["qty"])))],
                 asn=False, note=f"Recall replacement {replacement['plant']}")
        replenishment_pos.append(po_no)
    relay(sc, at(date(2027, 2, 22), 18), timers=True)
    ers.append(_settle(sc, date(2027, 2, 28), "VOD/26-27/TI-1622"))

    # ------------------------------------------------------------ payment runs (this tenant only)
    paid = []
    for run_day in (date(2027, 2, 15), date(2027, 3, 17)):
        with sc.act("finance.controller", at(run_day, 10)) as s:
            result = payables.payment_run(s, run_day)
            paid += [p["invoice"] for p in result["paid"]]
        relay(sc, at(run_day, 11), timers=True)
    sc.note(f"Payment runs 15 Feb and 17 Mar 2027 paid {', '.join(paid) or 'nothing'}")
    relay(sc, at(date(2027, 3, 31), 18), timers=True)
    clock.set_pinned(None)
    with tenant_tx(sc.tenant_id) as s:
        po_numbers = [opening_po] + replenishment_pos
        pos = s.execute(select(PurchaseOrder).where(PurchaseOrder.number.in_(po_numbers))).scalars().all()
        supplier_code = s.get(Supplier, supplier_id).code
    return {"notes": sc.log,
            "counts": {"suppliers": 1, "materials": 1, "contracts": 1, "requisitions": 1 + len(CASES) + len(recall["replenishments"]),
                       "purchaseOrders": len(pos), "touchlessPurchaseOrders": sum(1 for p in pos if p.touchless), "surgicalCases": len(CASES),
                       "ersSettlements": len(ers), "payments": len(paid), "recalledUnits": sum(int(Decimal(q["qty"])) for q in recall["quarantined"])},
            "keys": {"tenant": tenant_code, "supplier": supplier_code, "material": kn77, "contract": contract_no, "recalledLot": RECALLED_LOT,
                     "notice": NOTICE, "cases": [c[2] for c in CASES], "ers": ers}}
