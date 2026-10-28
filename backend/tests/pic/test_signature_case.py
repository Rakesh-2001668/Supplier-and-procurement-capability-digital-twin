"""E2E-01: the Axion Mobility signature case (blueprint §20) produced by the services."""
from decimal import Decimal


def test_mrp_netting_mr1043(client, login):
    run = client.get("/v1/mrp/runs/MR-1043", headers=login("mrp.controller")).json()
    result = run["results"][0]
    # 12,000 − (1,400 + 1,200 + 600 + 0) + 200 = 9,000
    assert (result["gross"], result["on_hand"], result["open_po"], result["in_transit"], result["safety_stock"], result["net"]) == \
        ("12000.000", "1400.000", "1200.000", "600.000", "200.000", "9000.000")
    assert run["plannedOrders"][0]["number"] == "PLO-55821"
    assert run["plannedOrders"][0]["status"] == "CONVERTED"


def test_requisition_from_mrp_followed_dmn01(client, login):
    pr = client.get("/v1/requisitions/REQ-2311", headers=login("buyer")).json()
    assert pr["origin"] == "MRP" and pr["origin_ref"] == "PLO-55821"
    assert pr["approval_chain"] == ["COST_OBJECT_OWNER", "DEPT_HEAD", "PROCUREMENT_HEAD", "FINANCE_CONTROLLER"]
    assert pr["status"] == "ORDERED"


def test_award_is_capacity_constrained_dual_source(client, login):
    event = client.get("/v1/sourcing/events/RFQ-2231", headers=login("category.manager")).json()
    assert event["status"] == "AWARDED"
    assert event["should_cost"]["unitCost"] == "391.00"
    scenarios = {s["kind"]: s for s in event["scenarios"]}
    assert scenarios["LOWEST_COST"]["feasible"] is False  # Trichy capacity 60k < 90k/month
    chosen = scenarios["CAPACITY_CONSTRAINED"]
    assert chosen["weighted_price_minor"] == 40080
    assert {a["supplier"]: a["share"] for a in chosen["allocations"]} == {"TF001": "0.6000", "KD002": "0.4000"}


def test_po_77410_inherits_contract_and_is_touchless(client, login):
    po = client.get("/v1/purchase-orders/PO-77410", headers=login("buyer")).json()
    assert po["supplier"]["code"] == "TF001"
    assert po["lines"][0]["qty"] == "5400" and po["lines"][0]["unit_price_minor"] == 39800
    assert po["payment_terms"] == "N60" and po["incoterms"] == "FCA Trichy"
    assert po["tolerance"]["over_pct"] == "2" and po["tolerance"]["under_pct"] == "5"
    assert po["risk_score"] == 18 and po["touchless"] is True
    assert po["released_by"] == "agent:TOUCHLESS_PO"
    assert po["lineageChain"] == ["PLO-55821", "REQ-2311", "RFQ-2231", "SA-5520"]


def test_receipt_quality_and_invoice_exception(client, login):
    gr = client.get("/v1/goods-receipts/GR-90231", headers=login("receiver")).json()
    assert gr["lines"][0]["accepted_qty"] == "5380" and gr["lines"][0]["rejected_qty"] == "20"
    assert gr["inspectionLots"][0]["number"] == "QL-2210"
    inv = client.get("/v1/invoices/INV-TF-8812", headers=login("ap.clerk")).json()
    quantity = [e for e in inv["exceptions"] if e["type"] == "QUANTITY"][0]
    assert quantity["delta"] == {"qty": "20"} and quantity["status"] == "RESOLVED"
    assert inv["creditNotes"][0]["number"] == "CN-TF-221"
    assert inv["erp_doc_no"] == "5100004421" and inv["status"] == "PAID"
    assert inv["irn_valid"] is True and inv["first_pass_matched"] is False


def test_savings_three_kinds(client, login):
    register = client.get("/v1/savings", headers=login("finance.controller")).json()[0]
    assert register["number"] == "SV-0412" and register["stage"] == "VALIDATED"
    assert register["negotiatedCr"] == "0.99"
    assert Decimal(register["avoidanceCr"]) == Decimal("0.32")
    # Realised only from posted invoices: (410 − 398) × 5,380 (INV-TF-8812, net of the credit note)
    # + (410 − 398) × 5,400 (INV-TF-9031) + (410 − 410) × 3,420 (Kovai's accepted price drift realises nothing).
    assert register["realisedMinor"] == 12 * 100 * 5380 + 12 * 100 * 5400


def test_process_paths(client, login):
    paths = client.get("/v1/documents/INVOICE/INV-TF-8812/process", headers=login("ap.clerk")).json()
    steps = [p["step"] for p in paths[0]["path"]]
    for expected in ["F7-01", "F7-02", "F7-03", "F7-04", "F7-05", "F7-03", "F7-06", "F7-08", "F7-07", "F7-09"]:
        assert expected in steps
    assert paths[0]["status"] == "COMPLETED"
    po_path = client.get("/v1/documents/PURCHASE_ORDER/PO-77410/process", headers=login("buyer")).json()[0]
    f505 = [p for p in po_path["path"] if p["step"] == "F5-05"][0]
    assert f505["status"] == "SKIPPED"  # touchless: no human approval step
