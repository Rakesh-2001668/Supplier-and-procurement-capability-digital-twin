"""
Verification script for Material Master Governance & Fuzzy Duplicate Shield Studio (MDM-01..04)
Tests:
1. Real-time Fuzzy Duplicate Shield with Principle P03 Hard Block (similarity >= 0.92)
2. Real-time Fuzzy Duplicate Shield on unique items (similarity < 0.70)
3. Agent AGT-MDM-03 Answer Contract and autonomy telemetry
4. Governed Material Request creation: auto-block on duplicate
5. Governed Material Request creation: steward queue initialization
6. 4-View Domain Steward enrichment (Purchasing, Plant, Quality, Accounting)
7. SOD-06 command-time block (Requester u:planner.hosur blocked from self-approving)
8. Independent Domain Steward approval (u:steward.metals) -> Golden Record catalog extension & SAP S/4HANA Outbox Sync
"""

import requests
import sys

BASE_URL = "http://127.0.0.1:8080/api/v1/mdm/studio"

def test_mdm_governance():
    print("==================================================================")
    print("RUNNING MATERIAL MASTER GOVERNANCE & DUPLICATE SHIELD TEST SUITE")
    print("==================================================================")

    # 1. Real-time Fuzzy Duplicate Shield on near-duplicate
    print("\n--- Test 1: Real-time Fuzzy Duplicate Shield on Duplicate Item ---")
    dup_payload = {
        "proposed_description": "DC-330 Die-Cast Aluminium Housing (Anodized Finish)",
        "category": "Castings & Forgings",
        "commodity_code": "25171500",
        "uom": "EA",
        "target_plant": "P100 Hosur"
    }
    r1 = requests.post(f"{BASE_URL}/analyze-duplicate", json=dup_payload)
    assert r1.status_code == 200, f"Expected 200, got {r1.status_code}: {r1.text}"
    data1 = r1.json()
    analysis1 = data1["analysis"]
    print(f"Similarity Score: {analysis1['best_score']} (Threshold: {analysis1['cutoff_threshold']})")
    print(f"Governance Action: {analysis1['governance_action']}")
    print(f"Message: {analysis1['message']}")
    assert analysis1["best_score"] >= 0.90, f"Expected similarity >= 0.90, got {analysis1['best_score']}"
    assert analysis1["governance_action"] == "HARD_BLOCK", f"Expected HARD_BLOCK, got {analysis1['governance_action']}"
    assert analysis1["is_blocked"] is True, "Expected is_blocked to be True"
    assert "agent_contract" in data1, "Expected Agent AGT-MDM-03 contract in response"
    print("Agent Contract ID:", data1["agent_contract"]["agent_id"])
    print("Agent Autonomy Level:", data1["agent_contract"]["autonomy_level"])
    print("PASS: Duplicate item correctly flagged for Principle P03 Hard Block!")

    # 2. Real-time Fuzzy Duplicate Shield on unique item
    print("\n--- Test 2: Real-time Fuzzy Duplicate Shield on Unique Item ---")
    unique_payload = {
        "proposed_description": "Silicon Nitride Ceramic Heat Sink Substrate 50x50mm",
        "category": "Thermal Systems",
        "commodity_code": "25172200",
        "uom": "EA",
        "target_plant": "P100 Hosur"
    }
    r2 = requests.post(f"{BASE_URL}/analyze-duplicate", json=unique_payload)
    assert r2.status_code == 200, f"Expected 200, got {r2.status_code}: {r2.text}"
    data2 = r2.json()
    analysis2 = data2["analysis"]
    print(f"Similarity Score: {analysis2['best_score']}")
    print(f"Governance Action: {analysis2['governance_action']}")
    assert analysis2["best_score"] < 0.70, f"Expected similarity < 0.70, got {analysis2['best_score']}"
    assert analysis2["governance_action"] == "PASS_TO_STEWARD", f"Expected PASS_TO_STEWARD, got {analysis2['governance_action']}"
    assert analysis2["is_blocked"] is False, "Expected is_blocked to be False"
    print("PASS: Unique item correctly identified and cleared for Domain Steward review!")

    # 3. Create governed request with duplicate -> auto blocked
    print("\n--- Test 3: Creation of Duplicate Request (Auto-Block) ---")
    r3 = requests.post(f"{BASE_URL}/requests", json={
        "proposed_description": "DC-330 Die-Cast Aluminium Housing (Anodized Finish)",
        "category": "Castings & Forgings",
        "commodity_code": "25171500",
        "uom": "EA",
        "target_plant": "P100 Hosur",
        "actor": "u:planner.hosur"
    })
    assert r3.status_code == 200, f"Expected 200, got {r3.status_code}: {r3.text}"
    data3 = r3.json()
    assert data3["status"] == "BLOCKED_DUPLICATE", f"Expected BLOCKED_DUPLICATE, got {data3['status']}"
    assert data3["request"]["status"] == "REJECTED_DUPLICATE"
    print(f"Blocked Request ID: {data3['request']['id']} -> Recommendation: Adopt {data3['adopt_material']['material_id']}")
    print("PASS: Duplicate request automatically rejected and prevented from polluting catalog!")

    # 4. Create governed request with unique part -> queued for steward
    print("\n--- Test 4: Creation of Unique Part Request (Queued for Stewards) ---")
    r4 = requests.post(f"{BASE_URL}/requests", json={
        "proposed_description": "Silicon Nitride Ceramic Heat Sink Substrate 50x50mm",
        "category": "Thermal Systems",
        "commodity_code": "25172200",
        "uom": "EA",
        "target_plant": "P100 Hosur",
        "actor": "u:planner.hosur",
        "differentiation_justification": "Required for higher thermal conductivity in gen-4 inverter design."
    })
    assert r4.status_code == 200, f"Expected 200, got {r4.status_code}: {r4.text}"
    data4 = r4.json()
    assert data4["status"] == "PENDING_APPROVAL", f"Expected PENDING_APPROVAL, got {data4['status']}"
    new_req_id = data4["request"]["id"]
    print(f"Created Valid Material Request: {new_req_id}")
    print("PASS: Material request created and queued for 4-view steward enrichment!")

    # 5. Enrich 4 Domain Views (Purchasing, Plant, Quality, Accounting)
    print("\n--- Test 5: 4-View Domain Steward Enrichment ---")
    views = [
        ("purchasing", {"purchasing_group": "P02 Thermal", "order_unit": "EA", "planned_lead_time_days": 21, "default_incoterms": "DDP Hosur"}),
        ("plant", {"plant": "P100 Hosur", "mrp_type": "PD", "lot_sizing_procedure": "EX", "safety_stock": 100, "reorder_point": 250, "storage_location": "SL02 Thermal Stores"}),
        ("quality", {"inspection_setup": "01 Goods Receipt", "certificate_required": "PPAP Level 3", "skip_lot_active": False, "defect_ppm_threshold": 25}),
        ("accounting", {"valuation_class": "3000 Raw Materials", "price_control": "S", "standard_valuation_inr": 1250.00})
    ]
    for view_name, attrs in views:
        rv = requests.put(f"{BASE_URL}/requests/{new_req_id}/views/{view_name}", json={
            "view_name": view_name,
            "actor": f"u:steward.{view_name}",
            "attributes": attrs
        })
        assert rv.status_code == 200, f"Failed enriching {view_name}: {rv.text}"
        print(f"  Enriched {view_name.upper()} view: OK")
    print("PASS: All 4 Domain Steward views successfully enriched!")

    # 6. SOD-06 Command-Time Check: Requester cannot self-approve as steward
    print("\n--- Test 6: SOD-06 Command-Time Enforcement ---")
    r6 = requests.post(f"{BASE_URL}/requests/{new_req_id}/steward-approve", json={
        "actor": "u:planner.hosur", # SAME AS REQUESTER
        "steward_notes": "Attempting self-approval as requester"
    })
    print(f"Response status: {r6.status_code}")
    assert r6.status_code == 403, f"Expected HTTP 403 Forbidden under SOD-06, got {r6.status_code}"
    err_detail = r6.json()["detail"]
    print("SoD Violation Detail:", err_detail)
    assert err_detail["rule_id"] == "SOD-06", f"Expected SOD-06, got {err_detail['rule_id']}"
    print("PASS: SOD-06 correctly blocked requester from self-approving material master!")

    # 7. Independent Domain Steward Approval -> Golden Record Created
    print("\n--- Test 7: Independent Steward Approval & SAP S/4HANA Sync ---")
    assigned_mat_id = f"MAT-SN50-CERAMIC"
    r7 = requests.post(f"{BASE_URL}/requests/{new_req_id}/steward-approve", json={
        "actor": "u:steward.lead.materials", # Independent steward
        "assigned_material_id": assigned_mat_id,
        "steward_notes": "All 4 views audited. Specification adheres to SAE AS9100 standard."
    })
    assert r7.status_code == 200, f"Expected 200, got {r7.status_code}: {r7.text}"
    data7 = r7.json()
    print("Approval message:", data7["message"])
    assert data7["golden_record"]["material_id"] == assigned_mat_id
    assert data7["golden_record"]["status"] == "ACTIVE"
    assert data7["erp_sync"]["status"] == "POSTED"
    print(f"ERP Outbox Sync Ref: {data7['erp_sync']['erpDocument']}")
    print("PASS: Independent steward approved, catalog extended, and synced to SAP S/4HANA!")

    # 8. Check Catalog Retrieval
    print("\n--- Test 8: Golden Catalog Retrieval ---")
    r8 = requests.get(f"{BASE_URL}/catalog")
    assert r8.status_code == 200, f"Expected 200, got {r8.status_code}: {r8.text}"
    catalog_data = r8.json()
    print(f"Active Catalog Size: {catalog_data['total']} materials")
    mat_ids = [m["material_id"] for m in catalog_data["materials"]]
    assert assigned_mat_id in mat_ids, f"Expected {assigned_mat_id} in catalog"
    print(f"Confirmed {assigned_mat_id} is live in standard catalog.")
    print("PASS: Standard Catalog retrieval complete!")

    print("\n==================================================================")
    print("ALL 8 MATERIAL MASTER GOVERNANCE & DUPLICATE SHIELD TESTS PASSED!")
    print("==================================================================")

if __name__ == "__main__":
    test_mdm_governance()
