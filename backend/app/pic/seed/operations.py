"""Operating cases after the signature case (Jan–Mar 2027), run through the same services.

1. February DC-330 release: manual stock requisition → quota split 60/40 → touchless POs → Kovai ships 5 % short
   (inside tolerance) → Kovai invoices 410 against the 405 contract → price exception → variance accepted
   → savings leakage (price drift). Trichy Forge matches first time.
2. MRO catalogue buy: ₹18,500 preventive-maintenance visit auto-approved (DMN-01) → touchless catalogue PO →
   service entry → SES match.
3. Duplicate invoice: Kovai resubmits the same amount under a new number → duplicate hold → rejected.
4. MPC005 completes onboarding as CONDITIONAL with a written waiver (ISO 14001 pending).
5. Fasteners from an unqualified supplier: risk +40 routes to approval; the stores buyer who created the PO is
   blocked from posting its goods receipt (SOD-03) and the receiver posts it instead.
6. Sanctions screening: a new caster whose name matches a screening-list entry is blocked at registration (F8-03).
7. Change order: DC-331 is sourced from the ERP source list (Trichy Forge fixed, info-record price), approved and
   confirmed; the OEM pulls the schedule in, the buyer raises quantity and moves the date → version 2 → re-confirmed.
8. Supplier change request after confirmation (PO-03): Trichy Forge asks to ship the same PO two days later because of
   a furnace relining; the buyer accepts → version 3 → re-confirmed.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import (
    AppUser, Asn, BankChangeRequest, CatalogueItem, InspectionLot, Invoice, InvoiceException, PurchaseOrder, Qualification,
    ServiceEntry, Supplier,
)
from app.pic.platform.auth import hash_password
from app.pic.platform.errors import Problem
from app.pic.seed.axion import Scenario, at, email


def run(sc: Scenario, password: str) -> None:
    from app.pic.services import order, payables, receiving, requisition
    from app.pic.services import supplier as supplier_svc

    with tenant_tx(sc.tenant_id) as s:
        s.add(AppUser(tenant_id=sc.tenant_id, email=email("stores.buyer"), full_name="Ravi Shankar (stores & buying, P200)",
                      password_hash=hash_password(password), roles=["BUYER", "RECEIVER"], attributes={"plants": ["P100", "P200"]}))
        suppliers = {x.code: x.id for x in s.execute(select(Supplier)).scalars()}
        catalogue_id = s.execute(select(CatalogueItem.id)).scalars().first()

    # ------------------------------------------------------------ 4. MPC005 onboarding completes as CONDITIONAL
    with sc.act("supplier.manager", at(date(2027, 1, 18), 10)) as s:
        change = s.execute(select(BankChangeRequest).where(BankChangeRequest.supplier_id == suppliers["MPC005"])).scalar_one()
        supplier_svc.callback_verify(s, change, "Called Madurai Precision Castings accounts head; IFSC and holder confirmed")
        change_id = change.id
    sc.approve_all(change_id, at(date(2027, 1, 18), 15), "Bank letter verified")
    with sc.act("supplier.manager", at(date(2027, 1, 22), 11)) as s:
        q = supplier_svc.start_qualification(s, s.get(Supplier, suppliers["MPC005"]), "ALU-DIECAST")
        supplier_svc.record_assessment(s, q, questionnaire_score=Decimal(76), audit_score=Decimal(77), sample_approval="PPAP_APPROVED")
        supplier_svc.decide_qualification(s, q, "CONDITIONAL", "Capable second-tier caster; environmental certificate pending",
                                          waiver="ISO 14001 audit booked for April 2027; volume capped at 10% share until then")
    sc.note("Case 4: MPC005 bank dual-approved and qualified CONDITIONAL with waiver (ISO 14001 pending)")

    # ------------------------------------------------------------ 2. MRO catalogue purchase (auto-approved, touchless)
    with sc.act("requester", at(date(2027, 1, 25), 10)) as s:
        result = requisition.search(s, "preventive maintenance die casting", "P100")
        pr = requisition.create(s, origin="CATALOGUE", purpose_code="MAINTENANCE", purpose_text="Quarterly PM on HPDC cell 2", plant="P100",
                                lines=[{"item_type": "CATALOGUE", "purchase_type": "SERVICE", "catalogue_item_id": str(catalogue_id), "qty": "1",
                                        "account_assignment_type": "COST_CENTER", "account_assignment_code": "4100", "need_date": "2027-02-05"}])
        requisition.submit(s, pr)
        mro_no, mro_status = pr.number, pr.status
    with sc.act("buyer", at(date(2027, 1, 25), 14)) as s:
        po = order.create_from_requisition(s, requisition=mro_no, lines=[10], supplier_code="HTS004")[0]
        mro_po, mro_touchless = po.number, po.touchless
    with sc.act("hts.service", at(date(2027, 1, 26), 9)) as s:
        order.confirm(s, s.get(PurchaseOrder, po.id), "CONFIRMED")
    with sc.act("hts.service", at(date(2027, 2, 5), 17)) as s:
        ses = receiving.create_ses(s, s.get(PurchaseOrder, po.id), method="UNIT_RATE", period_from=date(2027, 2, 5), period_to=date(2027, 2, 5),
                                   lines=[{"line": 10, "description": "PM visit – HPDC cell 2", "qty": "1", "unit_rate": "18500"}])
        receiving.submit_ses(s, ses)
        ses_id = ses.id
    sc.approve_all(ses_id, at(date(2027, 2, 6), 10), "Visit report signed")
    with sc.act("hts.service", at(date(2027, 2, 6), 15)) as s:
        inv = payables.capture(s, supplier="HTS004", supplier_invoice_no="HTS/1188", invoice_date=date(2027, 2, 6), channel="PORTAL",
                               lines=[{"po": mro_po, "po_line": 10, "qty": "1", "unit_price": "18500", "gst_rate": "18"}])
        mro_inv = inv.id
    with sc.act("ap.clerk", at(date(2027, 2, 8), 10)) as s:
        payables.approve(s, s.get(Invoice, mro_inv))
        payables.post(s, s.get(Invoice, mro_inv), "AXN|1000|HTS004|HTS/1188")
    sc.relay(at(date(2027, 2, 8), 11))
    sc.note(f"Case 2: {mro_no} {mro_status.lower()} by DMN-01 (catalogue < ₹25,000) → {mro_po} touchless={mro_touchless} → SES → HTS/1188 posted")

    # ------------------------------------------------------------ 1. February release with short shipment and price drift
    with sc.act("buyer", at(date(2027, 1, 28), 10)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="BUFFER_BUILD", purpose_text="February OEM schedule increase (SO-88342)",
                                plant="P100", lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "DC-330", "qty": "9000",
                                                      "price_est_minor": 41000, "need_date": "2027-02-15", "storage_location": "0001"}])
        requisition.submit(s, pr)
        feb_req, feb_req_id = pr.number, pr.id
    sc.approve_all(feb_req_id, at(date(2027, 1, 29), 12), "Schedule increase confirmed by sales")
    with sc.act("buyer", at(date(2027, 2, 1), 10)) as s:
        pos = {s.get(Supplier, p.supplier_id).code: (p.id, p.number) for p in order.create_from_requisition(s, requisition=feb_req, lines=[10])}
    sc.relay(at(date(2027, 2, 1), 10, 5))
    for code, who in (("TF001", "tf.sales"), ("KD002", "kd.sales")):
        with sc.act(who, at(date(2027, 2, 1), 15)) as s:
            order.confirm(s, s.get(PurchaseOrder, pos[code][0]), "CONFIRMED")
    shipments = {"TF001": ("tf.sales", "5400", "B-2702-01"), "KD002": ("kd.sales", "3420", "KD-2702-11")}
    asns = {}
    for code, (who, qty, batch) in shipments.items():
        with sc.act(who, at(date(2027, 2, 10), 9)) as s:
            a = receiving.create_asn(s, s.get(PurchaseOrder, pos[code][0]), lines=[{"line": 10, "qty": qty, "batches": [{"batch": batch, "qty": qty}]}],
                                     ship_date=date(2027, 2, 10), expected_date=date(2027, 2, 12), eway_bill_no=f"3310{batch[-5:].replace('-', '')}0000",
                                     vehicle_no="TN45AB1234" if code == "TF001" else "TN38CK4521", distance_km=320 if code == "TF001" else 250,
                                     documents=[f"CoC-{batch}"])
            asns[code] = a.id
    for code, (_, qty, batch) in shipments.items():
        with sc.act("receiver", at(date(2027, 2, 12), 11)) as s:
            gr = receiving.post_gr(s, s.get(PurchaseOrder, pos[code][0]), asn=s.get(Asn, asns[code]), lines=[{"line": 10, "qty": qty, "batch": batch}],
                                   posting_date=date(2027, 2, 12))
            gr_id = gr.id
        with sc.act("quality.inspector", at(date(2027, 2, 12), 16)) as s:
            lot = s.execute(select(InspectionLot).where(InspectionLot.gr_id == gr_id)).scalar_one()
            receiving.usage_decision(s, lot, accepted=Decimal(qty), rejected=Decimal(0))
    sc.relay(at(date(2027, 2, 12), 17))
    with sc.act("tf.sales", at(date(2027, 2, 13), 10)) as s:
        from app.pic.services.payables import expected_irn
        tf_inv = payables.capture(s, supplier="TF001", supplier_invoice_no="INV-TF-9031", invoice_date=date(2027, 2, 13), channel="E_INVOICE",
                                  irn=expected_irn("33AABCT1234K1Z5", "2026-27", "INV", "INV-TF-9031"),
                                  lines=[{"po": pos["TF001"][1], "po_line": 10, "qty": "5400", "unit_price": "398", "gst_rate": "18", "hsn": "87089900"}]).id
    with sc.act("kd.sales", at(date(2027, 2, 13), 11)) as s:
        kd_inv = payables.capture(s, supplier="KD002", supplier_invoice_no="KD/2702-118", invoice_date=date(2027, 2, 13), channel="PORTAL",
                                  lines=[{"po": pos["KD002"][1], "po_line": 10, "qty": "3420", "unit_price": "410", "gst_rate": "18", "hsn": "87089900"}]).id
    with sc.act("ap.clerk", at(date(2027, 2, 15), 10)) as s:
        payables.approve(s, s.get(Invoice, tf_inv))
        payables.post(s, s.get(Invoice, tf_inv), "AXN|1000|TF001|INV-TF-9031")
        exc = s.execute(select(InvoiceException).where(InvoiceException.invoice_id == kd_inv, InvoiceException.status == "OPEN")).scalar_one()
        payables.resolve_exception(s, s.get(Invoice, kd_inv), exc.id, "PRICE_ACCEPTED",
                                   "Kovai alloy surcharge ₹5/pc accepted by buyer lead for February (email 14 Feb); tracked as savings leakage")
        payables.approve(s, s.get(Invoice, kd_inv))
        payables.post(s, s.get(Invoice, kd_inv), "AXN|1000|KD002|KD/2702-118")
    sc.relay(at(date(2027, 2, 15), 11))
    sc.note(f"Case 1: {feb_req} → {pos['TF001'][1]} / {pos['KD002'][1]} touchless; KD short 5% (in tolerance); "
            "INV-TF-9031 first-pass; KD/2702-118 price 410 vs 405 → variance accepted → leakage")

    # ------------------------------------------------------------ 3. duplicate invoice caught and rejected
    with sc.act("kd.sales", at(date(2027, 2, 16), 9)) as s:
        dup = payables.capture(s, supplier="KD002", supplier_invoice_no="KD/2702-118-R", invoice_date=date(2027, 2, 14), channel="PORTAL",
                               lines=[{"po": pos["KD002"][1], "po_line": 10, "qty": "3420", "unit_price": "410", "gst_rate": "18", "hsn": "87089900"}])
        dup_id, dup_status = dup.id, dup.status
    with sc.act("ap.clerk", at(date(2027, 2, 16), 12)) as s:
        payables.reject(s, s.get(Invoice, dup_id), "Duplicate of KD/2702-118 (same amount, dated within 3 days); confirmed with Kovai")
    sc.note(f"Case 3: KD/2702-118-R held as {dup_status.lower()} (fuzzy duplicate) → rejected")

    # ------------------------------------------------------------ 5. unqualified supplier + SoD block on goods receipt
    with sc.act("requester", at(date(2027, 2, 17), 10)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="LINE_SUPPLIES", purpose_text="Fastener kits for P100 assembly", plant="P100",
                                lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "FK-M8-50", "qty": "2000",
                                        "price_est_minor": 1250, "need_date": "2027-02-24", "storage_location": "0001"}])
        requisition.submit(s, pr)
        fk_req, fk_req_id = pr.number, pr.id
    sc.approve_all(fk_req_id, at(date(2027, 2, 17), 14))
    with sc.act("stores.buyer", at(date(2027, 2, 18), 10)) as s:
        fk_po = order.create_from_requisition(s, requisition=fk_req, lines=[10], supplier_code="KD002", unit_price_minor=1250)[0]
        fk_po_id, fk_po_no, fk_risk = fk_po.id, fk_po.number, fk_po.risk_score
    sc.approve_all(fk_po_id, at(date(2027, 2, 18), 15), "One-time buy from Kovai until a fastener source is qualified")
    with sc.act("kd.sales", at(date(2027, 2, 19), 10)) as s:
        order.confirm(s, s.get(PurchaseOrder, fk_po_id), "CONFIRMED")
    blocked = None
    try:
        with sc.act("stores.buyer", at(date(2027, 2, 23), 9)) as s:
            receiving.post_gr(s, s.get(PurchaseOrder, fk_po_id), lines=[{"line": 10, "qty": "2000"}], posting_date=date(2027, 2, 23))
    except Problem as exc:
        blocked = exc.rule_ref
    with sc.act("receiver", at(date(2027, 2, 23), 10)) as s:
        receiving.post_gr(s, s.get(PurchaseOrder, fk_po_id), lines=[{"line": 10, "qty": "2000"}], posting_date=date(2027, 2, 23))
    sc.relay(at(date(2027, 2, 23), 11))
    sc.note(f"Case 5: {fk_po_no} risk {fk_risk} (supplier not qualified for FASTENERS) → approved; stores buyer GR blocked by {blocked}; receiver posted it")

    # ------------------------------------------------------------ 6. sanctions hit at registration
    with sc.act("supplier.manager", at(date(2027, 3, 1), 10)) as s:
        zat = supplier_svc.register(s, code="ZAT006", legal_name="Zenith Alloy Trading FZE", gstin="33AABCZ4321R1Z6", pan="AABCZ4321R",
                                    state_code="33", contact_email="sales@zat006.example", categories=["ALU-DIECAST"], payment_terms="N30")
        screening = supplier_svc.screen(s, zat)
        zat_status = zat.status
    sc.note(f"Case 6: ZAT006 'Zenith Alloy Trading FZE' screened {screening['outcome']} ({', '.join(screening['sanctionsHits'])}) → {zat_status}")

    # ------------------------------------------------------------ 7. source-list PO → change order → re-confirmation
    with sc.act("buyer", at(date(2027, 3, 2), 10)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="BUFFER_BUILD", purpose_text="DC-331 covers for the March OEM schedule",
                                plant="P100", lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "DC-331", "qty": "2000",
                                                      "price_est_minor": 21500, "need_date": "2027-03-22", "storage_location": "0001"}])
        requisition.submit(s, pr)
        cover_req, cover_req_id = pr.number, pr.id
    sc.approve_all(cover_req_id, at(date(2027, 3, 2), 15), "March schedule confirmed")
    with sc.act("buyer", at(date(2027, 3, 3), 10)) as s:
        cover = order.create_from_requisition(s, requisition=cover_req, lines=[10])[0]
        cover_id, cover_no, cover_source = cover.id, cover.number, next(iter(cover.inherited["sourceDetermination"].values()))["method"]
    sc.approve_all(cover_id, at(date(2027, 3, 3), 14), "Source-list supplier at info-record price")
    with sc.act("tf.sales", at(date(2027, 3, 4), 10)) as s:
        order.confirm(s, s.get(PurchaseOrder, cover_id), "CONFIRMED")
    with sc.act("buyer", at(date(2027, 3, 8), 11)) as s:
        changed = order.change_order(s, s.get(PurchaseOrder, cover_id), [{"line": 10, "qty": "2400", "need_date": "2027-03-18"}],
                                     reason="OEM pull-in SO-88415: +400 covers, needed by 18 Mar")
    with sc.act("tf.sales", at(date(2027, 3, 8), 16)) as s:
        order.confirm(s, s.get(PurchaseOrder, cover_id), "CONFIRMED", note="v2 accepted; dispatch 15 Mar")
    sc.relay(at(date(2027, 3, 8), 17))
    sc.note(f"Case 7: {cover_req} → {cover_no} via {cover_source} (TF001 @212) → approved → confirmed → change order v{changed['version']} "
            "(2,400 by 18 Mar) → re-confirmed")

    # ------------------------------------------------------------ case 8: supplier change request after confirmation (PO-03)
    with sc.act("tf.sales", at(date(2027, 3, 9), 10)) as s:
        po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == cover_no)).scalar_one()
        pcr = order.request_change(s, po, [{"line": 10, "need_date": "2027-03-20"}],
                                   "Furnace relining on cell 2 (8-10 Mar); the 2,400 covers ship on 20 Mar instead of 18 Mar")
        pcr_no, po_id = pcr.number, po.id
    sc.approve_all(po_id, at(date(2027, 3, 9), 15), comment="OEM confirmed 20 Mar still meets SO-88415")
    with sc.act("tf.sales", at(date(2027, 3, 9), 17)) as s:
        po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == cover_no)).scalar_one()
        order.confirm(s, po, "CONFIRMED", note="Confirmed for 20 Mar")
        version = po.version
    sc.relay(at(date(2027, 3, 9), 18))
    sc.note(f"Case 8: {pcr_no} Trichy Forge asks to ship {cover_no} on 20 Mar → buyer accepts → v{version} → re-confirmed")

    # ------------------------------------------------------------ month-end payment run
    with sc.act("finance.controller", at(date(2027, 3, 31), 10)) as s:
        paid = payables.payment_run(s, date(2027, 3, 31))
    sc.relay(at(date(2027, 3, 31), 11))
    sc.note(f"Payment run {paid['run']}: paid {', '.join(p['invoice'] for p in paid['paid']) or 'none'}; "
            f"not yet due: INV-TF-9031 (N60 → 14 Apr)")
