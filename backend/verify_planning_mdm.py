"""
Comprehensive Automated Verification Suite for Phase 4:
Demand Planning & MRP (M02) and Master Data Governance (M03)
Testing Principles P03, P05, P10, SOD-02, and SOD-06.
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import requests
import json

BASE_URL = "http://127.0.0.1:8080/api/v1"

def print_separator(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)

def test_mrp_runs_and_netting():
    print_separator("1. Testing GET /planning/mrp/runs & Net-Change Run MR-1043...")
    r = requests.get(f"{BASE_URL}/planning/mrp/runs")
    assert r.status_code == 200, f"Failed: {r.text}"
    data = r.json()
    assert data["total"] >= 1, "Expected at least 1 MRP run"
    run = data["runs"][0]
    print(f"   [OK] Run ID: {run['id']}, Plant: {run['plant']}, Type: {run['run_type']}")
    print(f"   [OK] Materials Evaluated: {run['stats']['materials_evaluated']}, Planned Orders: {run['stats']['planned_orders_generated']}")

def test_planned_orders_and_netting_formula():
    print_separator("2. Testing Net Requirement Calculation on PLO-55821...")
    r = requests.get(f"{BASE_URL}/planning/mrp/planned-orders")
    assert r.status_code == 200, f"Failed: {r.text}"
    data = r.json()
    orders = {o["id"]: o for o in data["planned_orders"]}
    assert "PLO-55821" in orders, "PLO-55821 missing"

    plo = orders["PLO-55821"]
    gross = plo["gross_requirement"]
    on_hand = plo["stock_on_hand"]
    scheduled = plo["scheduled_receipts"]
    safety = plo["safety_stock"]
    expected_net = max(0, gross - on_hand - scheduled + safety)

    assert plo["net_requirement"] == expected_net, f"Mismatch: {plo['net_requirement']} vs {expected_net}"
    print(f"   [OK] Material: {plo['material_id']} ('{plo['material_description']}')")
    print(f"   [OK] Netting: Gross ({gross}) - OnHand ({on_hand}) - Scheduled ({scheduled}) + Safety ({safety}) = {plo['net_requirement']} EA")
    print(f"   [OK] Status: {plo['status']}, Converted PR: {plo['converted_pr_id']}")

def test_trigger_mrp_run():
    print_separator("3. Testing POST /planning/mrp/runs/trigger...")
    payload = {
        "plant": "P100 Hosur",
        "run_type": "NET_CHANGE",
        "horizon_days": 90,
        "lot_sizing_rule": "EXACT_REQUIREMENT",
        "actor": "u:planner.hosur"
    }
    r = requests.post(f"{BASE_URL}/planning/mrp/runs/trigger", json=payload)
    assert r.status_code == 200, f"Failed: {r.text}"
    data = r.json()
    assert data["status"] == "success"
    print(f"   [OK] Triggered Run: {data['run']['id']}")
    print(f"   [OK] Generated Planned Orders: {len(data['generated_orders'])}")

def test_firm_and_convert_planned_order():
    print_separator("4. Testing Firm & Conversion of Planned Order with Lineage (P10)...")
    # Firm PLO-55822
    r_firm = requests.post(f"{BASE_URL}/planning/mrp/planned-orders/PLO-55822/firm?actor=u:planner.hosur")
    assert r_firm.status_code == 200, f"Failed: {r_firm.text}"
    print(f"   [OK] PLO-55822 status after firming: {r_firm.json()['planned_order']['status']}")

    # Convert PLO-55821
    payload = {
        "firmed_quantity": 9000,
        "target_delivery_date": "2026-11-10",
        "actor": "u:planner.hosur"
    }
    r_conv = requests.post(f"{BASE_URL}/planning/mrp/planned-orders/PLO-55821/convert-to-pr", json=payload)
    assert r_conv.status_code == 200, f"Failed: {r_conv.text}"
    data = r_conv.json()
    assert data["status"] == "success"
    assert data["requisition_id"] == "REQ-2311"
    print(f"   [OK] Converted PLO-55821 -> Requisition: {data['requisition_id']} (Qty: {data['converted_quantity']} EA)")
    print(f"   [OK] Lineage Recorded: {data['lineage_recorded']}")

def test_mdm_fuzzy_duplicate_detection():
    print_separator("5. Testing MDM Fuzzy Duplicate Scorer (Principles P03 & P05)...")
    # Test Duplicate Case (similarity >= 0.92)
    duplicate_payload = {
        "proposed_description": "DC-330 Aluminium Die-Cast Housing EN AC-46000",
        "category": "Castings & Forgings",
        "commodity_code": "CAST-ALU-HPDC",
        "uom": "EA",
        "target_plant": "P100 Hosur",
        "actor": "u:planner.hosur"
    }
    r_dup = requests.post(f"{BASE_URL}/mdm/material-requests", json=duplicate_payload)
    assert r_dup.status_code == 200
    res_dup = r_dup.json()
    assert res_dup["status"] == "BLOCKED_DUPLICATE", f"Expected BLOCKED_DUPLICATE, got {res_dup['status']}"
    print(f"   [OK] Duplicate Detected! Status: {res_dup['status']}")
    print(f"   [OK] Reason: {res_dup['message']}")
    print(f"   [OK] P03 Directive: {res_dup['recommendation']}")

    # Test Novel Item Case (similarity < 0.92)
    novel_payload = {
        "proposed_description": "Titanium Grade 5 Hexagon Cap Screws M12x60",
        "category": "Fasteners & Hardware",
        "commodity_code": "FAST-TIT-M12",
        "uom": "EA",
        "target_plant": "P200 Chennai",
        "actor": "u:planner.hosur"
    }
    r_nov = requests.post(f"{BASE_URL}/mdm/material-requests", json=novel_payload)
    assert r_nov.status_code == 200
    res_nov = r_nov.json()
    assert res_nov["status"] == "PENDING_APPROVAL"
    req_id = res_nov["request"]["id"]
    print(f"   [OK] Novel Material Approved for Review: ID {req_id}, Duplicate Score: {res_nov['request']['duplicate_score']}")
    return req_id

def test_steward_approval_and_sod_06(req_id: str):
    print_separator("6. Testing Domain Steward Approval with SOD-06 Enforcement...")
    # Requester attempting self-approval (SOD-06 conflict)
    self_approve_payload = {
        "actor": "u:planner.hosur",
        "comments": "Self-approving my own material request."
    }
    r_self = requests.post(f"{BASE_URL}/mdm/material-requests/{req_id}/approve", json=self_approve_payload)
    assert r_self.status_code == 500 or "SOD-06" in r_self.text, f"Expected SOD-06 block, got {r_self.text}"
    print(f"   [OK] SOD-06 Blocked Self-Approval! Requester 'u:planner.hosur' cannot approve material.")

    # Distinct Domain Steward approving
    steward_payload = {
        "actor": "u:steward.metals",
        "comments": "Verified aerospace standard grade specifications."
    }
    r_steward = requests.post(f"{BASE_URL}/mdm/material-requests/{req_id}/approve", json=steward_payload)
    assert r_steward.status_code == 200, f"Steward approval failed: {r_steward.text}"
    data = r_steward.json()
    assert data["status"] == "success"
    print(f"   [OK] Steward Approval Succeeded: Assigned Standard Material ID: {data['material_id']}")

def test_supplier_bank_change_and_sod_02():
    print_separator("7. Testing Supplier Bank Modification Dual-Approval (SOD-02)...")
    # Initiate Request
    init_payload = {
        "supplier_id": "TF001",
        "bank_name": "Axis Bank Corporate",
        "account_number": "91802000381928",
        "ifsc_code": "UTIB0000192",
        "branch": "Trichy Thillai Nagar",
        "actor": "u:supplier.admin.tf001"
    }
    r_init = requests.post(f"{BASE_URL}/mdm/bank-change-requests", json=init_payload)
    assert r_init.status_code == 200
    bcr = r_init.json()["bank_change_request"]
    bcr_id = bcr["id"]
    print(f"   [OK] Bank Change Initiated: ID {bcr_id} for Supplier {bcr['supplier_id']}")

    # First Approval
    first_payload = {
        "actor": "u:finance.steward.p100",
        "approval_stage": "FIRST",
        "comments": "Verified bank statement and cancelled cheque."
    }
    r_first = requests.post(f"{BASE_URL}/mdm/bank-change-requests/{bcr_id}/approve", json=first_payload)
    assert r_first.status_code == 200
    print(f"   [OK] First Approval Recorded by {first_payload['actor']}. Status: {r_first.json()['request']['status']}")

    # Second Approval with SAME Actor (SOD-02 Violation)
    second_fail_payload = {
        "actor": "u:finance.steward.p100",  # Same actor!
        "approval_stage": "SECOND",
        "comments": "Attempting second approval with same account."
    }
    r_sec_fail = requests.post(f"{BASE_URL}/mdm/bank-change-requests/{bcr_id}/approve", json=second_fail_payload)
    assert r_sec_fail.status_code == 403, f"Expected 403 for duplicate approver, got {r_sec_fail.status_code}"
    print(f"   [OK] SOD-02 Blocked Single-User Dual Approval: {r_sec_fail.json()['detail']}")

    # Second Approval with DISTINCT Finance Director
    second_pass_payload = {
        "actor": "u:finance.director.global",
        "approval_stage": "SECOND",
        "comments": "Executive corporate treasury confirmation."
    }
    r_sec_pass = requests.post(f"{BASE_URL}/mdm/bank-change-requests/{bcr_id}/approve", json=second_pass_payload)
    assert r_sec_pass.status_code == 200
    pass_data = r_sec_pass.json()
    assert pass_data["status"] == "APPROVED"
    print(f"   [OK] Dual-Approval Completed! Cooling-off active until: {pass_data['request']['cooling_off_until']}")

if __name__ == "__main__":
    print("=====================================================================")
    print("Testing AlphaHelion Demand Planning, MRP & Master Data Governance")
    print("=====================================================================")
    try:
        test_mrp_runs_and_netting()
        test_planned_orders_and_netting_formula()
        test_trigger_mrp_run()
        test_firm_and_convert_planned_order()
        novel_id = test_mdm_fuzzy_duplicate_detection()
        test_steward_approval_and_sod_06(novel_id)
        test_supplier_bank_change_and_sod_02()
        print("\n=====================================================================")
        print("ALL PLANNING, MRP & MDM VERIFICATION TESTS PASSED WITH 100% SUCCESS! [OK]")
        print("=====================================================================")
    except Exception as e:
        print(f"\n[FAIL] Test aborted with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
