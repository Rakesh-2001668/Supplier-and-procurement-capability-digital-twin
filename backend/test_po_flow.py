import requests

BASE_URL = "http://127.0.0.1:8080/api/v1/procurement"

def test_full_flow():
    # 1. Create a PO
    create_payload = {
        "supplier_tenant_id": "TENANT_SUPPLIER_001",
        "department": "Propulsion Engineering",
        "buyer_name": "Alex Sharma",
        "priority": "Critical",
        "cost_center": "CC-PROP-201",
        "payment_terms": "Net 30 Days",
        "incoterms": "DDP Spaceport Warehouse Bay 4",
        "target_delivery_date": "2026-11-25",
        "notes": "Cryogenic Fuel Injector Nozzles for Starship Stage 2",
        "items": [
            {
                "sku": "AERO-NOZZLE-901",
                "name": "Inconel 718 Cryogenic Fuel Injector Nozzle",
                "category": "Precision CNC & Milling",
                "unit": "units",
                "quantity": 12,
                "unit_price": 4200.0
            }
        ]
    }
    r = requests.post(f"{BASE_URL}/purchase-orders/create", json=create_payload)
    print("Create PO Status:", r.status_code)
    assert r.status_code == 200
    res = r.json()
    po_number = res["po_number"]
    total = res["total_amount"]
    print(f"Created {po_number} with amount ${total:,.2f}, initial status: {res['initial_status']}")
    assert res["requires_approval"] is True  # 12 * 4200 = 50400 >= 50000

    # 2. Executive Level 2 Approval
    r = requests.post(f"{BASE_URL}/purchase-orders/{po_number}/approve", json={
        "action": "APPROVE",
        "actor_name": "Elena Rostova",
        "actor_role": "VP Finance",
        "notes": "Level 2 financial sign-off approved under CAPEX FY2026."
    })
    print("Approve Status:", r.status_code)
    assert r.status_code == 200
    print(f"New status after approval: {r.json()['new_status']}")

    # 3. Supplier Acknowledgment
    r = requests.post(f"{BASE_URL}/purchase-orders/{po_number}/transition", json={
        "action": "ACKNOWLEDGE",
        "actor_name": "Apex Sales Lead",
        "notes": "Production slots confirmed in CNC 5-Axis Bay 02."
    })
    print("Acknowledge Status:", r.status_code, "->", r.json()["new_status"])

    # 4. Start Production
    r = requests.post(f"{BASE_URL}/purchase-orders/{po_number}/transition", json={
        "action": "START_PRODUCTION",
        "actor_name": "CNC Shopfloor Supervisor",
        "notes": "Raw Inconel billets inspected and 5-axis milling underway."
    })
    print("Start Production Status:", r.status_code, "->", r.json()["new_status"])

    # 5. Advance Ship Notice (ASN)
    r = requests.post(f"{BASE_URL}/purchase-orders/{po_number}/asn", json={
        "carrier": "FedEx Aerospace Freight",
        "tracking_number": "FX-STAR-99218-US",
        "estimated_delivery": "2026-11-20",
        "shipped_quantity": 12,
        "packages_count": 2,
        "coc_number": "COC-APEX-88210"
    })
    print("ASN Status:", r.status_code, "->", r.json().get("new_status"))

    # 6. Buyer Dock Receiving & GRN Generation
    r = requests.post(f"{BASE_URL}/purchase-orders/{po_number}/grn", json={
        "action": "RECORD_GRN",
        "actor_name": "Marcus Vance",
        "actor_role": "Dock Receiving Lead",
        "dock_bay": "Receiving Dock 04-B",
        "received_quantity": 12,
        "batch_lot_number": "LOT-INC-2026-11",
        "cmm_cert_id": "CMM-MET-77821",
        "quality_pass": True,
        "storage_bin": "BIN-AERO-W04"
    })
    print("GRN Status:", r.status_code, "->", r.json()["new_status"])

    # 7. Quality Inspection Sign-off
    r = requests.post(f"{BASE_URL}/purchase-orders/{po_number}/transition", json={
        "action": "INSPECT_QUALITY",
        "actor_name": "Dr. Sarah Jenkins",
        "actor_role": "Quality Metrology Lead",
        "cmm_cert_id": "CMM-MET-77821",
        "notes": "Zero NCR. All 12 nozzles verified to ±0.0001\" tolerance."
    })
    print("Quality Inspect Status:", r.status_code, "->", r.json()["new_status"])

    # 8. 3-Way Match & Invoice Reconciliation
    r = requests.post(f"{BASE_URL}/purchase-orders/{po_number}/transition", json={
        "action": "RECONCILE_3_WAY",
        "actor_name": "ERP Financial Ledger Engine",
        "invoice_number": "INV-APEX-2026-901",
        "notes": "3-Way Match verified: PO $50,400 == GRN 12 units == Tax Invoice $50,400. Variance $0.00."
    })
    print("3-Way Match Reconciled Status:", r.status_code, "->", r.json()["new_status"])

    # 9. Verify full fulfillment dossier
    r = requests.get(f"{BASE_URL}/purchase-orders/fulfillment/{po_number}")
    d = r.json()["fulfillment_dossier"]
    print(f"Final PO {po_number} Status: {d['status']} | Progress: {d['progress_pct']}% | 3-Way Matched: {d['three_way_matched']} | Milestones: {len(d['milestones'])}")
    assert d['status'] == "COMPLETED"
    assert d['three_way_matched'] is True

    print("\n>>> FULL END-TO-END PO LIFECYCLE & FULFILLMENT ENGINE VERIFIED! <<<")

if __name__ == "__main__":
    test_full_flow()
