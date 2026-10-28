"""Operating cases seeded after the signature case (seed/operations.py)."""


def test_price_drift_shows_as_savings_leakage(client, login):
    waterfall = client.get("/v1/savings/SV-0412/waterfall", headers=login("finance.controller")).json()
    drift = [l for l in waterfall["leakage"] if l["kind"] == "PRICE_DRIFT"]
    assert drift and drift[0]["amountMinor"] == 5 * 100 * 3420   # ₹5/pc above the 405 contract on 3,420 pcs


def test_catalogue_buy_auto_approved_and_touchless(client, login):
    pr = client.get("/v1/requisitions/REQ-2314", headers=login("requester")).json()
    assert pr["origin"] == "CATALOGUE" and pr["approval_chain"] == []
    po = client.get("/v1/purchase-orders/PO-77413", headers=login("buyer")).json()
    assert po["touchless"] is True and po["lines"][0]["price_source"] == "CATALOGUE"


def test_duplicate_invoice_rejected(client, login):
    items = client.get("/v1/invoices?status=REJECTED", headers=login("ap.clerk")).json()["items"]
    assert [i["supplier_invoice_no"] for i in items] == ["KD/2702-118-R"]


def test_short_shipment_inside_tolerance_completes_receipt(client, login):
    po = client.get("/v1/purchase-orders/PO-77415", headers=login("buyer")).json()
    assert po["supplier"]["code"] == "KD002" and po["lines"][0]["received_qty"] == "3420"
    assert po["status"] in ("RECEIVED", "INVOICED")


def test_conditional_supplier_and_sod_block_recorded(client, login):
    mpc = client.get("/v1/suppliers/MPC005", headers=login("supplier.manager")).json()
    assert mpc["categories"][0]["status"] == "CONDITIONAL" and "ISO 14001" in mpc["categories"][0]["waiver_reason"]
    sod = client.get("/v1/admin/sod", headers=login("admin")).json()
    assert any(v["rule_code"] == "SOD-03" for v in sod["violations"])
