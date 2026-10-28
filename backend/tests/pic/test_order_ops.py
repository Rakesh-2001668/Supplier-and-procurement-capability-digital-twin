"""M08/M09/M10 operations: delivery schedules, PO transmission (EDIFACT / e-mail), inbound EDI, e-way bill, 4-way match,
bank payment files, GST e-invoice verification and document capture.

The tests share one new PO (DC-330 from Trichy Forge, 1,000 EA, manual price) and run in file order. Anything that would
change the signature-case KPIs checked by later test files (invoices, first-pass match, savings) runs in a rolled-back
transaction.
"""
import base64
import hashlib
import json
import os
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, AuditEvent, InspectionLot, OutboxEvent, PaymentFile, Payment, PoTransmission, PurchaseOrder, Supplier, SupplierBankAccount, Tenant,
)
from app.pic.platform import clock, crypto
from app.pic.platform.auth import Principal, scopes_for
from app.pic.services import bank_files, einvoice, order, payables, receiving, requisition, transmission

IST = clock.IST
EDI_ID = "TF001EDI"
NS = {"p": "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"}
EDI = {"content-type": "application/EDIFACT"}


class _Rollback(Exception):
    pass


def _axn():
    with system_tx() as s:
        return s.execute(select(Tenant.id).where(Tenant.code == "AXN")).scalar_one()


def _as(session, email: str) -> None:
    user = session.execute(select(AppUser).where(AppUser.email == email)).scalar_one()
    session.info["principal"] = Principal(user.id, user.tenant_id, "AXN", user.email, user.full_name, list(user.roles), scopes_for(list(user.roles)),
                                          user.attributes or {}, user.supplier_id)
    session.info["user_id"] = user.id


def _interchange(message_type: str, reference: str, body: list[str], sender: str = EDI_ID, receiver: str = "AXN") -> str:
    now = datetime.now(IST)
    segments = [f"UNH+1+{message_type}:D:96A:UN", *body]
    segments.append(f"UNT+{len(segments) + 1}+1")
    return ("UNA:+.? '" + f"UNB+UNOC:3+{sender}:ZZZ+{receiver}:ZZZ+{now:%y%m%d}:{now:%H%M}+{reference}'"
            + "".join(s + "'" for s in segments) + f"UNZ+1+{reference}'")


def _d(value: date) -> str:
    return value.strftime("%Y%m%d")


@pytest.fixture(scope="module")
def ops(database):
    """A PO released over portal + EDI + e-mail (TF001 order_channel), with no EDI gateway and no SMTP configured."""
    from app.pic.seed.axion import Scenario
    saved_env = {k: os.environ.pop(k) for k in ("PIC_EDI_GATEWAY_URL", "PIC_SMTP_HOST", "PIC_OCR_URL", "PIC_IRP_URL") if k in os.environ}
    tenant_id = _axn()
    with tenant_tx(tenant_id) as s:
        tf = s.execute(select(Supplier).where(Supplier.code == "TF001")).scalar_one()
        previous_channel = dict(tf.order_channel or {})
        tf.order_channel = {"channels": ["PORTAL", "EDI", "EMAIL"], "ediId": EDI_ID, "email": "orders@trichyforge.example"}
    now = datetime.now(IST).replace(microsecond=0)
    need = (now + timedelta(days=30)).date()
    sc = Scenario(tenant_id)
    try:
        with sc.act("buyer", now) as s:
            pr = requisition.create(s, origin="MANUAL", purpose_code="BUFFER_BUILD", purpose_text="Delivery schedule and EDI test", plant="P100",
                                    lines=[{"item_type": "MATERIAL", "purchase_type": "STOCK", "material": "DC-330", "qty": "1000",
                                            "price_est_minor": 40500, "need_date": need.isoformat(), "storage_location": "0001"}])
            requisition.submit(s, pr)
            pr_id, pr_no = pr.id, pr.number
        sc.approve_all(pr_id, now)
        with sc.act("buyer", now) as s:
            po = order.create_from_requisition(s, requisition=pr_no, lines=[10], supplier_code="TF001", unit_price_minor=40500)[0]
            po_id, number = po.id, po.number
        sc.approve_all(po_id, now, "Manual price as per quotation")
    finally:
        clock.set_pinned(None)
    with tenant_tx(tenant_id) as s:
        assert s.get(PurchaseOrder, po_id).status == "TRANSMITTED"
    yield {"tenant": tenant_id, "po": number, "po_id": po_id, "need": need, "state": {}}
    with tenant_tx(tenant_id) as s:
        s.execute(select(Supplier).where(Supplier.code == "TF001")).scalar_one().order_channel = previous_channel
    os.environ.update(saved_env)


# ---------------------------------------------------------------- 1. schedule lines
def test_default_schedule_line_is_created_with_the_po(client, login, ops):
    rows = client.get(f"/v1/purchase-orders/{ops['po']}/schedule", headers=login("buyer")).json()
    assert [(r["line"], r["seq"], r["qty"], r["deliveryDate"], r["openQty"]) for r in rows] == [(10, 1, "1000", ops["need"].isoformat(), "1000")]
    assert client.get(f"/v1/purchase-orders/{ops['po']}/schedule", headers=login("tf.sales")).status_code == 200
    assert client.get(f"/v1/purchase-orders/{ops['po']}/schedule", headers=login("kd.sales")).status_code == 404


# ---------------------------------------------------------------- 2. transmission records, EDIFACT ORDERS, e-mail
def test_transmission_per_channel_and_delivery_without_gateway_or_smtp(client, login, ops):
    from app.pic.worker import tick
    rows = client.get(f"/v1/purchase-orders/{ops['po']}/transmissions", headers=login("buyer")).json()
    by_channel = {r["channel"]: r for r in rows}
    assert set(by_channel) == {"PORTAL", "EDI", "EMAIL"} and {r["version"] for r in rows} == {1}
    assert by_channel["PORTAL"]["status"] == "SENT"
    assert by_channel["EDI"]["format"] == "EDIFACT_ORDERS" and by_channel["EDI"]["recipient"] == EDI_ID
    assert by_channel["EMAIL"]["format"] == "HTML_EMAIL" and by_channel["EMAIL"]["recipient"] == "orders@trichyforge.example"
    with tenant_tx(ops["tenant"]) as s:
        event = s.execute(select(OutboxEvent).where(OutboxEvent.topic == "purchase_order.transmitted",
                                                    OutboxEvent.object_id == ops["po_id"])).scalars().one()
        assert event.payload["channels"] == ["PORTAL", "EDI", "EMAIL"] and event.payload["version"] == 1
    tick()  # outbox relay runs the delivery consumer
    after = {r["channel"]: r for r in client.get(f"/v1/purchase-orders/{ops['po']}/transmissions", headers=login("buyer")).json()}
    assert after["EDI"]["status"] == "QUEUED" and after["EDI"]["error"] == "EDI gateway not configured"
    assert after["EMAIL"]["status"] == "QUEUED" and "DISABLED" in after["EMAIL"]["error"]  # mailer.send() answered DISABLED
    # Re-sending stays queued (and never fails the PO) while nothing is configured.
    r = client.post(f"/v1/purchase-orders/{ops['po']}/transmissions/{after['EDI']['id']}/resend", headers=login("buyer"))
    assert r.status_code == 200 and r.json()["status"] == "QUEUED"
    ops["state"]["edi_v1"] = after["EDI"]["id"]
    ops["state"]["email_v1"] = after["EMAIL"]["id"]


def test_edifact_orders_message(client, login, ops):
    r = client.get(f"/v1/purchase-orders/{ops['po']}/transmissions/{ops['state']['edi_v1']}", headers=login("buyer")).json()
    document = r["document"]
    assert document.startswith("UNA:+.? 'UNB+UNOC:3+AXN:ZZZ+TF001EDI:ZZZ+")
    assert r["sha256"] == hashlib.sha256(document.encode()).hexdigest()
    interchange = transmission.parse(document)  # also checks UNT and UNZ counts
    assert (interchange.sender, interchange.receiver, len(interchange.messages)) == ("AXN", EDI_ID, 1)
    message = interchange.messages[0]
    tags = [s.tag for s in message.segments]
    assert tags == ["UNH", "BGM", "DTM", "NAD", "NAD", "CUX", "LIN", "PIA", "IMD", "QTY", "DTM", "PRI", "UNS", "CNT", "UNT"]
    seg = {(s.tag, s.el(0)): s for s in message.segments}
    assert message.type == "ORDERS" and seg[("UNH", "1")].elements[1] == ["ORDERS", "D", "96A", "UN"]
    assert seg[("BGM", "220")].el(1) == ops["po"] and seg[("BGM", "220")].el(2) == "9"
    assert seg[("NAD", "BY")].el(1) == "1000" and seg[("NAD", "SU")].el(1) == "TF001"
    assert seg[("CUX", "2")].elements[0] == ["2", "INR", "9"]
    assert seg[("LIN", "10")].elements[2] == ["DC-330", "IN"] and seg[("PIA", "1")].elements[1] == ["87089900", "HS"]
    assert seg[("QTY", "21")].elements[0] == ["21", "1000", "EA"]
    assert seg[("DTM", "2")].elements[0] == ["2", _d(ops["need"]), "102"]
    assert seg[("PRI", "AAA")].elements[0] == ["AAA", "405.00"]
    assert seg[("CNT", "2")].elements[0] == ["2", "1"]
    assert int(seg[("UNT", str(len(message.segments)))].el(0)) == len(message.segments) == r["segments"]["declared"]
    download = client.get(f"/v1/purchase-orders/{ops['po']}/transmissions/{ops['state']['edi_v1']}/document", headers=login("tf.sales"))
    assert download.status_code == 200 and download.text == document and download.headers["content-type"].startswith("application/EDIFACT")
    mail = client.get(f"/v1/purchase-orders/{ops['po']}/transmissions/{ops['state']['email_v1']}", headers=login("buyer")).json()["document"]
    assert f"Purchase order {ops['po']} (version 1)" in mail and "1000 EA" in mail and "Trichy Forge" in mail


def test_edifact_escaping_round_trip():
    assert transmission._esc("A+B:C'D?E") == "A?+B?:C?'D??E"
    raw = _interchange("ORDRSP", "X1", ["BGM+231+R?+1?'A+29", "RFF+ON:PO?:1", "UNS+S"])
    message = transmission.parse(raw).messages[0]
    assert message.segments[1].el(1) == "R+1'A" and message.segments[2].el(0, 1) == "PO:1"
    with pytest.raises(Exception) as exc:
        transmission.parse(raw.replace("UNT+5+1", "UNT+4+1"))
    assert getattr(exc.value, "code", "") == "EDI_SYNTAX"


# ---------------------------------------------------------------- 3. schedule edits before confirmation
def test_schedule_edit_validation_and_in_place_edit(client, login, ops):
    path, need, h = f"/v1/purchase-orders/{ops['po']}/lines/10/schedule", ops["need"], login("buyer")
    r = client.put(path, json={"lines": [{"qty": "600", "deliveryDate": need.isoformat()}, {"qty": "300", "deliveryDate": (need + timedelta(days=14)).isoformat()}]}, headers=h)
    assert r.status_code == 422 and r.json()["code"] == "SCHEDULE_QTY_MISMATCH" and r.json()["scheduledQty"] == "900"
    r = client.put(path, json={"lines": [{"qty": "1000", "deliveryDate": "2020-01-01"}]}, headers=h)
    assert r.status_code == 422 and r.json()["ruleRef"] == "PO-SCHEDULE"
    assert client.put(path, json={"lines": [{"qty": "1000", "deliveryDate": need.isoformat()}]}, headers=login("tf.sales")).status_code == 403
    assert client.put(f"/v1/purchase-orders/{ops['po']}/lines/20/schedule", json={"lines": [{"qty": "1", "deliveryDate": need.isoformat()}]},
                      headers=h).status_code == 404
    body = {"lines": [{"qty": "600", "deliveryDate": need.isoformat()}, {"qty": "400", "deliveryDate": (need + timedelta(days=14)).isoformat()}],
            "reason": "Split delivery agreed with stores"}
    r = client.put(path, json=body, headers=h)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["mode"] == "IN_PLACE" and result["version"] == 1 and result["status"] == "TRANSMITTED"
    assert [(x["seq"], x["qty"]) for x in result["schedule"]] == [(1, "600"), (2, "400")]
    trail = client.get(f"/v1/audit/PURCHASE_ORDER/{ops['po']}", headers=h).json()
    changed = [e for e in trail if e["action"] == "SCHEDULE_CHANGED"]
    assert changed and changed[-1]["before"]["schedule"][0]["qty"] == "1000" and changed[-1]["reason"] == "Split delivery agreed with stores"


def test_later_confirmed_date_is_a_change_request(ops):
    """Service level, rolled back: a schedule-line date later than requested goes back to the buyer."""
    with pytest.raises(_Rollback):
        with tenant_tx(ops["tenant"]) as s:
            _as(s, "tf.sales@axion.example")
            po = s.get(PurchaseOrder, ops["po_id"])
            sl = order.schedule_lines(s, po)[0]
            result = order.confirm(s, po, "CONFIRMED", [{"line": 10, "scheduleConfirmations": [
                {"seq": sl.seq, "confirmedDate": (sl.delivery_date + timedelta(days=5)).isoformat()}]}])
            assert result["confirmation"] == "CHANGE_REQUESTED" and "later date" in result["outsideTolerance"][0]
            raise _Rollback


# ---------------------------------------------------------------- 4. inbound ORDRSP
def test_inbound_ordrsp_confirms_the_po_and_acknowledges_edi(client, login, ops):
    need = ops["need"]
    reference = f"R{uuid.uuid4().hex[:10].upper()}"
    raw = _interchange("ORDRSP", reference, [
        "BGM+231+RSP-77+29", f"DTM+137:{_d(date.today())}:102", f"RFF+ON:{ops['po']}", "LIN+10+5",
        "SCC+1", f"DTM+2:{_d(need)}:102", "SCC+1", f"DTM+2:{_d(need + timedelta(days=12))}:102", "UNS+S", "CNT+2:1"])
    assert client.post("/v1/edi/inbound", content=raw, headers={**login("buyer"), **EDI}).status_code == 403
    unknown = _interchange("ORDRSP", "R0000000001", ["BGM+231+RSP-1+29", f"RFF+ON:{ops['po']}"], sender="NOBODY")
    r = client.post("/v1/edi/inbound", content=unknown, headers={**login("admin"), **EDI})
    assert r.status_code == 403 and r.json()["code"] == "EDI_PARTNER_UNKNOWN"
    r = client.post("/v1/edi/inbound", content=raw, headers={**login("admin"), **EDI})
    assert r.status_code == 200, r.text
    message = r.json()["messages"][0]
    assert message["type"] == "ORDRSP" and message["result"]["confirmation"] == "CONFIRMED" and message["result"]["status"] == "CONFIRMED"
    again = client.post("/v1/edi/inbound", content=raw, headers={**login("admin"), **EDI}).json()
    assert again["replayed"] is True  # same sender + control reference replays, nothing is confirmed twice
    edi = client.get(f"/v1/purchase-orders/{ops['po']}/transmissions/{ops['state']['edi_v1']}", headers=login("buyer")).json()
    assert edi["status"] == "ACKNOWLEDGED" and edi["ackAt"]
    schedule = client.get(f"/v1/purchase-orders/{ops['po']}/schedule", headers=login("buyer")).json()
    assert [s["confirmedDate"] for s in schedule] == [need.isoformat(), (need + timedelta(days=12)).isoformat()]
    trail = client.get(f"/v1/audit/PURCHASE_ORDER/{ops['po']}", headers=login("buyer")).json()
    confirm = [e for e in trail if e["action"] == "CONFIRM"][-1]
    assert confirm["actor"].startswith("u:edi.tf001@")  # acted as the supplier through the EDI channel


# ---------------------------------------------------------------- 5. schedule change after confirmation → version 2 + ORDCHG
def test_schedule_change_after_confirmation_creates_a_version_and_ordchg(client, login, ops):
    need = ops["need"]
    body = {"lines": [{"qty": "500", "deliveryDate": need.isoformat()}, {"qty": "500", "deliveryDate": (need + timedelta(days=21)).isoformat()}]}
    r = client.put(f"/v1/purchase-orders/{ops['po']}/lines/10/schedule", json=body, headers=login("buyer"))
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["mode"] == "NEW_VERSION" and result["version"] == 2 and result["status"] == "TRANSMITTED"
    assert all(s["confirmedDate"] is None for s in result["schedule"])  # re-confirmation required
    rows = client.get(f"/v1/purchase-orders/{ops['po']}/transmissions", headers=login("buyer")).json()
    v2 = {t["channel"]: t for t in rows if t["version"] == 2}
    assert set(v2) == {"PORTAL", "EDI", "EMAIL"} and v2["EDI"]["format"] == "EDIFACT_ORDCHG"
    document = client.get(f"/v1/purchase-orders/{ops['po']}/transmissions/{v2['EDI']['id']}", headers=login("buyer")).json()["document"]
    message = transmission.parse(document).messages[0]
    seg = {s.tag: s for s in message.segments}
    assert message.type == "ORDCHG" and seg["BGM"].elements[:3] == [["230"], [ops["po"]], ["4"]]
    assert seg["LIN"].el(1) == "3"  # line 10 changed
    assert [s.tag for s in message.segments].count("SCC") == 2  # delivered on two dates
    versions = client.get("/v1/po-confirmations", headers=login("buyer")).json()["versions"]
    assert any(v["po"] == ops["po"] and v["version"] == 1 for v in versions)
    r = client.post(f"/v1/purchase-orders/{ops['po']}/confirmations", headers=login("tf.sales"),
                    json={"status": "CONFIRMED", "lines": [{"line": 10, "scheduleConfirmations": [{"seq": 1, "confirmedDate": need.isoformat()}]}]})
    assert r.status_code == 200 and r.json()["confirmation"] == "CONFIRMED"
    portal = {t["channel"]: t for t in client.get(f"/v1/purchase-orders/{ops['po']}/transmissions", headers=login("buyer")).json()
              if t["version"] == 2}["PORTAL"]
    assert portal["status"] == "ACKNOWLEDGED"


# ---------------------------------------------------------------- 6. e-way bill on ASN
def test_eway_bill_required_format_and_validity(client, login, ops):
    today = clock.today()
    h = login("tf.sales")
    base = {"po": ops["po"], "ship_date": today.isoformat(), "expected_date": (today + timedelta(days=2)).isoformat(),
            "lines": [{"line": 10, "qty": "200"}]}  # 200 × ₹405 + 18% GST = ₹95,580 ≥ ₹50,000
    r = client.post("/v1/asns", json=base, headers=h)
    assert r.status_code == 422 and r.json()["code"] == "EWAY_BILL_REQUIRED" and set(r.json()["missing"]) >= {"eway_bill_no", "vehicle_no"}
    r = client.post("/v1/asns", json={**base, "eway_bill_no": "3310098765", "vehicle_no": "TN45AB1234", "distance_km": 320}, headers=h)
    assert r.status_code == 422 and r.json()["ruleRef"].startswith("EWAY-BILL") and "format" in r.json()["detail"]
    r = client.post("/v1/asns", json={**base, "eway_bill_no": "331009876501", "vehicle_no": "TN45AB1234",
                                      "eway_bill_valid_until": f"{today.isoformat()}T23:00:00+05:30"}, headers=h)
    assert r.status_code == 422 and "after the ship date" in r.json()["detail"]
    r = client.post("/v1/asns", json={**base, "eway_bill_no": "331009876501", "vehicle_no": "XYZ", "distance_km": 320}, headers=h)
    assert r.status_code == 422 and "Vehicle" in r.json()["detail"]
    small = client.post("/v1/asns", json={**base, "lines": [{"line": 10, "qty": "1"}]}, headers=h)  # ₹477.90: below the threshold
    assert small.status_code == 201 and small.json()["eway_bill_no"] is None
    r = client.post("/v1/asns", json={**base, "eway_bill_no": "331009876501", "vehicle_no": "tn 45 ab 1234", "distance_km": 320}, headers=h)
    assert r.status_code == 201, r.text
    asn = r.json()
    assert asn["vehicle_no"] == "TN45AB1234" and asn["eway_bill_no"] == "331009876501"
    # 320 km at 200 km/day → 2 days, valid until midnight of the second day after the ship date
    assert datetime.fromisoformat(asn["eway_bill_valid_until"]) == datetime.combine(today + timedelta(days=2), time(23, 59, 59), tzinfo=IST)


# ---------------------------------------------------------------- 7. inbound DESADV → ASN (with an expired e-way bill)
def test_inbound_desadv_creates_an_asn(client, login, ops):
    today = date.today()
    raw = _interchange("DESADV", f"D{uuid.uuid4().hex[:10].upper()}", [
        "BGM+351+DES-4410+9", f"DTM+137:{_d(today)}:102", f"DTM+11:{_d(today - timedelta(days=3))}:102", f"DTM+132:{_d(today)}:102",
        f"RFF+ON:{ops['po']}", "RFF+ZEW:331012345678", f"DTM+36:{_d(today - timedelta(days=2))}2359:203", "TDT+12++30+++++TN45AB9876",
        "CPS+1", "LIN+10", "QTY+12:700:EA", "GIN+BX+B-OPS-01", "CNT+2:1"])
    r = client.post("/v1/edi/inbound", content=raw, headers={**login("admin"), **EDI})
    assert r.status_code == 200, r.text
    message = r.json()["messages"][0]
    asn = message["result"]
    assert message["type"] == "DESADV" and asn["po_id"] == str(ops["po_id"]) and asn["status"] == "IN_TRANSIT"
    assert asn["eway_bill_no"] == "331012345678" and asn["vehicle_no"] == "TN45AB9876"
    assert asn["lines"][0]["qty"] == "700" and asn["lines"][0]["batches"] == [{"batch": "B-OPS-01", "qty": "700"}]
    assert asn["documents"] == ["DESADV DES-4410"]
    ops["state"]["desadv_asn"] = message["asn"]


# ---------------------------------------------------------------- 8. goods receipt: schedule allocation + expired e-way warning
def test_gr_allocates_to_earliest_schedule_line_and_warns_on_expired_eway(client, login, ops):
    r = client.post("/v1/goods-receipts", headers=login("receiver"),
                    json={"po": ops["po"], "asn": ops["state"]["desadv_asn"], "lines": [{"line": 10, "qty": "700", "batch": "B-OPS-01"}]})
    assert r.status_code == 201, r.text
    gr = r.json()
    assert gr["status"] == "QUALITY_HOLD" and gr["warnings"][0]["code"] == "EWAY_BILL_EXPIRED"
    trail = client.get(f"/v1/audit/GOODS_RECEIPT/{gr['number']}", headers=login("receiver")).json()
    assert any(e["action"] == "EWAY_BILL_EXPIRED_WARNING" for e in trail)
    schedule = client.get(f"/v1/purchase-orders/{ops['po']}/schedule", headers=login("buyer")).json()
    assert [(s["seq"], s["receivedQty"], s["openQty"], s["status"]) for s in schedule] == [
        (1, "500", "0", "DELIVERED"), (2, "200", "300", "PARTIALLY_RECEIVED")]
    expediting = [x for x in client.get("/v1/expediting", headers=login("buyer")).json() if x["po"] == ops["po"]]
    assert [(x["scheduleSeq"], Decimal(x["openQty"])) for x in expediting] == [(2, Decimal(300))]
    ops["state"]["gr"] = gr["number"]


# ---------------------------------------------------------------- 9. 4-way match
def test_signature_invoice_is_four_way_with_unchanged_numbers(client, login):
    inv = client.get("/v1/invoices/INV-TF-8812", headers=login("ap.clerk")).json()
    assert inv["match_type"] == "4WAY"  # DC-330 is quality-managed: PO + GR + inspection + invoice
    quantity = [e for e in inv["exceptions"] if e["type"] == "QUANTITY"][0]
    assert quantity["delta"] == {"qty": "20"} and "vs accepted" in quantity["detail"] and "20" in quantity["detail"]


def test_four_way_match_waits_for_inspection(ops):
    """Rolled back so the first-pass KPI of the seeded invoices stays as it is."""
    with pytest.raises(_Rollback):
        with tenant_tx(ops["tenant"]) as s:
            _as(s, "ap.clerk@axion.example")
            invoice = payables.capture(s, supplier="TF001", supplier_invoice_no=f"TF-OPS-{uuid.uuid4().hex[:6]}", invoice_date=clock.today(),
                                       channel="PORTAL", lines=[{"po": ops["po"], "po_line": 10, "qty": "700", "unit_price": "405",
                                                                 "gst_rate": "18", "hsn": "87089900"}])
            assert invoice.match_type == "4WAY" and invoice.status == "EXCEPTION"
            line = payables._lines(s, invoice)[0]
            assert line.match_detail["matchBasis"] == "INSPECTION_ACCEPTED" and Decimal(line.match_detail["inInspectionQty"]) == 700
            exc = [e for e in s.execute(select(payables.InvoiceException).where(payables.InvoiceException.invoice_id == invoice.id)).scalars()][0]
            assert exc.type == "QUANTITY" and "still in quality inspection" in exc.detail
            _as(s, "quality.inspector@axion.example")
            from app.pic.models import GoodsReceipt
            gr = s.execute(select(GoodsReceipt).where(GoodsReceipt.number == ops["state"]["gr"])).scalar_one()
            lot = s.execute(select(InspectionLot).where(InspectionLot.gr_id == gr.id)).scalar_one()
            receiving.usage_decision(s, lot, accepted=Decimal(700), rejected=Decimal(0))
            _as(s, "ap.clerk@axion.example")
            result = payables.match(s, invoice)
            assert result["status"] == "MATCHED" and result["matchType"] == "4WAY"
            raise _Rollback


# ---------------------------------------------------------------- 10. bank payment files
def test_payment_file_pain001(client, login):
    fin, run = login("finance.controller"), "PRUN-2611"
    runs = {r["run"]: r for r in client.get("/v1/payments/runs", headers=login("buyer")).json()}
    assert runs[run]["payments"] >= 1
    assert client.post(f"/v1/payments/runs/{run}/file", json={"format": "ISO20022_PAIN001"}, headers=login("buyer")).status_code == 403
    r = client.post(f"/v1/payments/runs/{run}/file", json={"format": "ISO20022_PAIN001"}, headers=fin)
    assert r.status_code == 409 and r.json()["code"] == "PAYMENT_FILE_NOT_CONFIGURED" and set(r.json()["missing"]) == {
        "debtorName", "debtorAccountRef", "debtorIfsc"}
    rule = client.post("/v1/admin/rules", headers=login("admin"), json={
        "key": "PAYMENT-FILE", "version": "2026.1-CC1000", "effective_from": "2026-04-01", "company_code": "1000",
        "body": {"format": "ISO20022_PAIN001", "debtorName": "Axion Mobility Systems Pvt Ltd", "debtorAccountRef": "917020012345678",
                 "debtorIfsc": "UTIB0000123"}, "description": "Axion current account, Axis Bank Hosur"})
    assert rule.status_code == 201, rule.text
    r = client.post(f"/v1/payments/runs/{run}/file", json={"format": "ISO20022_PAIN001"}, headers={**fin, "Idempotency-Key": "pf-test-1"})
    assert r.status_code == 201, r.text
    pf = r.json()
    assert pf["status"] == "GENERATED" and pf["fileName"] == f"{pf['number']}_{run}_pain001.xml" and pf["number"].startswith("PF-")
    again = client.post(f"/v1/payments/runs/{run}/file", json={"format": "ISO20022_PAIN001"}, headers={**fin, "Idempotency-Key": "pf-test-1"})
    assert again.json()["replayed"] is True and again.json()["number"] == pf["number"]
    dup = client.post(f"/v1/payments/runs/{run}/file", json={"format": "NEFT_CSV"}, headers=fin)
    assert dup.status_code == 409 and dup.json()["code"] == "PAYMENT_FILE_EXISTS"

    listing = client.get("/v1/payment-files", headers=login("buyer")).json()
    assert any(f["number"] == pf["number"] for f in listing["items"]) and "content" not in listing["items"][0]
    assert listing["bankConnector"]["configured"] is False
    for who in ("ap.clerk", "buyer", "tf.sales"):
        assert client.get(f"/v1/payment-files/{pf['number']}/content", headers=login(who)).status_code == 403
    content = client.get(f"/v1/payment-files/{pf['number']}/content", headers=fin)
    assert content.status_code == 200 and content.headers["content-type"].startswith("application/xml")
    assert hashlib.sha256(content.content).hexdigest() == pf["sha256"] == content.headers["x-content-sha256"]

    with tenant_tx(_axn()) as s:
        payments = s.execute(select(Payment).where(Payment.run_ref == run, Payment.status == "COMPLETED")).scalars().all()
        accounts = {}
        for p in payments:
            account = s.get(SupplierBankAccount, p.bank_account_id)
            accounts[p.number] = (crypto.decrypt(account.tenant_id, "bank", account.account_enc), account.ifsc, p.amount_minor)
        stored = s.execute(select(PaymentFile).where(PaymentFile.number == pf["number"])).scalar_one()
        audit_text = json.dumps([e.after for e in s.execute(select(AuditEvent).where(AuditEvent.object_type == "PAYMENT_FILE")).scalars()])
        event_text = json.dumps([e.payload for e in s.execute(select(OutboxEvent).where(OutboxEvent.topic.like("payment_file.%"))).scalars()])
    root = ET.fromstring(content.content)
    assert root.tag == "{%s}Document" % NS["p"]
    header = root.find("p:CstmrCdtTrfInitn/p:GrpHdr", NS)
    assert header.findtext("p:MsgId", namespaces=NS) == pf["number"]
    assert int(header.findtext("p:NbOfTxs", namespaces=NS)) == len(payments) == pf["payments"]
    assert Decimal(header.findtext("p:CtrlSum", namespaces=NS)) == Decimal(sum(a[2] for a in accounts.values())) / 100 == Decimal(pf["totalMinor"]) / 100
    info = root.find("p:CstmrCdtTrfInitn/p:PmtInf", NS)
    assert info.findtext("p:PmtMtd", namespaces=NS) == "TRF"
    assert info.findtext("p:Dbtr/p:Nm", namespaces=NS) == "Axion Mobility Systems Pvt Ltd"
    assert info.findtext("p:DbtrAcct/p:Id/p:Othr/p:Id", namespaces=NS) == "917020012345678"
    assert info.findtext("p:DbtrAgt/p:FinInstnId/p:ClrSysMmbId/p:MmbId", namespaces=NS) == "UTIB0000123"
    txs = info.findall("p:CdtTrfTxInf", NS)
    assert len(txs) == len(payments)
    for tx in txs:
        e2e = tx.findtext("p:PmtId/p:EndToEndId", namespaces=NS)
        account, ifsc, amount = accounts[e2e]  # end-to-end id = payment number
        assert tx.findtext("p:CdtrAcct/p:Id/p:Othr/p:Id", namespaces=NS) == account
        assert tx.findtext("p:CdtrAgt/p:FinInstnId/p:ClrSysMmbId/p:ClrSysId/p:Cd", namespaces=NS) == "INFSC"
        assert tx.findtext("p:CdtrAgt/p:FinInstnId/p:ClrSysMmbId/p:MmbId", namespaces=NS) == ifsc
        assert Decimal(tx.find("p:Amt/p:InstdAmt", NS).text) == Decimal(amount) / 100 and tx.find("p:Amt/p:InstdAmt", NS).get("Ccy") == "INR"
        assert tx.findtext("p:Cdtr/p:Nm", namespaces=NS)
        # account numbers never leave the file: not stored in clear, not in audit, not in events
        assert account not in stored.content and account not in audit_text and account not in event_text

    status = f"/v1/payment-files/{pf['number']}/status"
    assert client.post(status, json={"status": "ACKNOWLEDGED", "bankRef": "X"}, headers=fin).status_code == 409
    assert client.post(status, json={"status": "SENT"}, headers=login("ap.clerk")).status_code == 403
    assert client.post(status, json={"status": "SENT"}, headers=fin).json()["status"] == "SENT"
    r = client.post(status, json={"status": "ACKNOWLEDGED"}, headers=fin)
    assert r.status_code == 422 and r.json()["code"] == "BANK_REF_REQUIRED"
    done = client.post(status, json={"status": "ACKNOWLEDGED", "bankRef": "AXIS-H2H-88231"}, headers=fin).json()
    assert done["status"] == "ACKNOWLEDGED" and done["bankRef"] == "AXIS-H2H-88231"
    r = client.post(f"/v1/payment-files/{pf['number']}/transmit", headers=fin)
    assert r.status_code == 503 and r.json()["code"] == "BANK_CONNECTOR_NOT_CONFIGURED"


def test_neft_csv_layout():
    tx = {"creditor": "Trichy Forge Pvt Ltd", "account": "30112345678", "ifsc": "SBIN0001234", "amountMinor": 2_536_840_00,
          "currency": "INR", "valueDate": date(2027, 1, 13), "payment": "PAY-880001", "supplierInvoiceNo": "INV-TF-8812"}
    lines = bank_files.neft_csv([({"debtorAccountRef": "917020012345678", "debtorIfsc": "UTIB0000123"}, [tx])]).splitlines()
    assert lines[0].split(",") == bank_files.NEFT_HEADER
    assert lines[1] == "NEFT,917020012345678,UTIB0000123,Trichy Forge Pvt Ltd,30112345678,SBIN0001234,2536840.00,INR,13-01-2027,PAY-880001,INV-TF-8812"


# ---------------------------------------------------------------- 11. GST e-invoice
def _qr(data: dict, alg: str = "RS256") -> str:
    enc = lambda obj: base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")  # noqa: E731
    return f"{enc({'alg': alg, 'typ': 'JWT'})}.{enc({'iss': 'NIC', 'data': json.dumps(data)})}.c2lnbmF0dXJl"


def test_irn_local_verification(client, login):
    seeded = client.get("/v1/invoices/INV-TF-8812/e-invoice", headers=login("ap.clerk")).json()
    assert seeded["level"] == "LOCAL" and seeded["valid"] is True and seeded["irnValid"] is True
    assert {c["code"] for c in seeded["checks"]} == {"IRN_FORMAT", "IRN_HASH"} and all(c["ok"] for c in seeded["checks"])
    assert client.get("/v1/invoices/INV-TF-8812/e-invoice", headers=login("kd.sales")).status_code == 404
    with tenant_tx(_axn()) as s:
        _as(s, "ap.clerk@axion.example")
        tf = s.execute(select(Supplier).where(Supplier.code == "TF001")).scalar_one()
        irn = payables.expected_irn("33AABCT1234K1Z5", "2026-27", "INV", "TF-QR-1")
        data = {"SellerGstin": "33AABCT1234K1Z5", "BuyerGstin": "33AAACA4321F1Z9", "DocNo": "TF-QR-1", "DocTyp": "INV", "DocDt": "14/11/2026",
                "TotInvVal": 1180.0, "ItemCnt": 1, "MainHsnCode": "87089900", "Irn": irn}
        common = dict(supplier=tf, company_code="1000", supplier_invoice_no="TF-QR-1", invoice_date=date(2026, 11, 14), gross_minor=118000)
        ok = einvoice.verify(s, irn=irn, signed_qr=_qr(data), **common)
        assert ok["level"] == "LOCAL" and ok["valid"] is True and ok["qrSignatureVerified"] is False
        assert {"IRN_HASH", "QR_STRUCTURE", "QR_IRN", "QR_SELLER_GSTIN", "QR_BUYER_GSTIN", "QR_DOC_NO", "QR_DOC_DATE", "QR_TOTAL"} <= {c["code"] for c in ok["checks"]}
        tampered = einvoice.verify(s, irn=irn, signed_qr=_qr({**data, "TotInvVal": 11800.0}), **common)
        assert tampered["valid"] is False and [c["code"] for c in tampered["checks"] if not c["ok"]] == ["QR_TOTAL"]
        wrong_irn = einvoice.verify(s, irn="ab" * 32, **common)
        assert wrong_irn["valid"] is False and [c["code"] for c in wrong_irn["checks"] if not c["ok"]] == ["IRN_HASH"]
        broken = einvoice.verify(s, irn=irn, signed_qr="not-a-jwt", **common)
        assert broken["valid"] is False and [c["code"] for c in broken["checks"] if not c["ok"]] == ["QR_STRUCTURE"]


# ---------------------------------------------------------------- 12. document capture
def test_document_capture_needs_an_ocr_engine(client, login):
    files = {"file": ("invoice.pdf", b"%PDF-1.4 test", "application/pdf")}
    r = client.post("/v1/invoices/documents", files=files, headers=login("ap.clerk"))
    assert r.status_code == 503 and r.json()["code"] == "OCR_NOT_CONFIGURED"
    assert client.post("/v1/invoices/documents", files=files, headers=login("buyer")).status_code == 403
