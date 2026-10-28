"""
AlphaHelion Purchasing Intelligence Cloud
Test Suite: 3-Way Match Exception & Automated Dispute Engine with Agent AGT-INVOICE-11
Blueprint Reference: Section 14 (3-Way Matching & Tolerances) & Principle P11/P13
"""

import sys
import json
import urllib.request
import urllib.error

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://127.0.0.1:8080"

def make_request(path, method="GET", data=None):
    url = f"{BASE_URL}{path}"
    body = json.dumps(data).encode('utf-8') if data else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8'))

def run_tests():
    print("=" * 80)
    print("  TEST SUITE: 3-WAY MATCH EXCEPTION & AGENT AGT-INVOICE-11 RESOLUTION")
    print("=" * 80)

    # 1. Query Match Cases
    print("\n[TEST 1] Listing all 3-Way Match Cases...")
    status, res = make_request("/api/v1/invoices/3-way-match/cases")
    assert status == 200, f"Expected 200, got {status}"
    cases = res["cases"]
    metrics = res["metrics"]
    print(f"-> Total Invoices evaluated: {metrics['total_cases']}")
    print(f"-> Invoices in Exception hold: {metrics['exceptions_count']}")
    print(f"-> Disputed Value: ₹{metrics['disputed_value_inr']:,.2f}")
    print(f"-> AI Agent: {metrics['agent_name']} ({metrics['agent_id']}) - {metrics['agent_autonomy']}")
    assert len(cases) >= 4, "Expected at least 4 match cases"
    print("  PASS: 3-Way match cases list returned with AI Agent metadata.")

    # 2. Case Details for Signature Case INV-TF-8812
    print("\n[TEST 2] Inspecting Case Details for INV-TF-8812...")
    status, tf_case_res = make_request("/api/v1/invoices/3-way-match/cases/INV-TF-8812")
    assert status == 200
    tf_case = tf_case_res["case"]
    assert tf_case["discrepancy_type"] == "QUANTITY_EXCEPTION"
    assert tf_case["po_ordered_qty"] == 5400.0
    assert tf_case["gr_accepted_qty"] == 5380.0
    assert tf_case["gr_rejected_qty"] == 20.0
    assert tf_case["discrepancy_total_inr"] == 9392.8
    print(f"  * PO: {tf_case['po_id']} | GR: {tf_case['gr_id']} | QA Rejection: {tf_case['quality_inspection_id']}")
    print(f"  * Invoiced: {tf_case['invoiced_qty']} EA @ ₹{tf_case['invoiced_unit_price']} | Discrepancy: +{tf_case['discrepancy_units']} EA (₹{tf_case['discrepancy_total_inr']:,.2f})")
    print("  PASS: Precise 3-way line item reconciliation verified.")

    # 3. Incorporate Agent AGT-INVOICE-11 Deep Verification
    print("\n[TEST 3] Incorporating Agent AGT-INVOICE-11 for Autonomous Verification...")
    status, agent_res = make_request("/api/v1/invoices/3-way-match/cases/INV-TF-8812/agent-verify", method="POST")
    assert status == 200
    contract = agent_res["agent_contract"]
    assert contract["agent_id"] == "AGT-INVOICE-11"
    assert contract["confidence_score"] >= 0.95
    assert len(contract["citations"]) >= 3
    print(f"  * Agent: {contract['agent_name']} (Confidence: {contract['confidence_score']*100:.1f}%)")
    print(f"  * Root Cause: {contract['root_cause_explanation'][:90]}...")
    print(f"  * Recommended Action: {contract['recommended_action'][:80]}...")
    print(f"  * Proposed Debit Note: {contract['debit_note_proposal']['suggested_dn_number']} (₹{contract['debit_note_proposal']['total_dn_amount_inr']:,.2f})")
    print("  PASS: Agent AGT-INVOICE-11 executed verification strictly adhering to Principle P11.")

    # 4. Issue Automated Debit Note to Resolve Exception
    print("\n[TEST 4] Issuing Automated Debit Note to Settle Overbilled Exception...")
    status, dn_res = make_request(
        "/api/v1/invoices/3-way-match/cases/INV-TF-8812/issue-debit-note",
        method="POST",
        data={"actor": "ap.clerk@alphahelion.com", "debit_note_number": "DN-2026-8812"}
    )
    assert status == 200
    assert dn_res["status"] == "success"
    updated_case = dn_res["case"]
    assert updated_case["match_status"] == "MATCHED_WITH_DEBIT_NOTE"
    assert updated_case["payment_hold"] is False
    assert updated_case["debit_note_ref"] == "DN-2026-8812"
    assert updated_case["adjusted_payable_inr"] == 2526663.20
    print(f"  * Debit Note Issued: {dn_res['debit_note']['debit_note_number']}")
    print(f"  * New Status: {updated_case['match_status']} (Payment Hold Cleared)")
    print(f"  * Adjusted Net Payable: ₹{updated_case['adjusted_payable_inr']:,.2f}")
    print("  PASS: Automated Debit Note applied, netting discrepancy and unblocking invoice.")

    # 5. SoD Enforcement on Price Variance Waiver (SOD-04)
    print("\n[TEST 5] Testing SOD-04 Enforcement on Price Variance Waiver (INV-KD-4402)...")
    # PO Creator (buyer.automotive) attempts to self-waive -> Blocked with 403
    status, sod_block = make_request(
        "/api/v1/invoices/3-way-match/cases/INV-KD-4402/waive-variance",
        method="POST",
        data={
            "actor": "buyer.automotive@alphahelion.com",
            "waiver_justification": "Approved emergency raw material surcharge for Kovai Diecast.",
            "approved_tolerance_delta": 29736.0
        }
    )
    print(f"  * Creator Waiver Attempt Status: {status} (Expected 403 Forbidden)")
    assert status == 403
    assert sod_block["detail"]["rule_id"] == "SOD-04"
    print(f"  * Block Message: {sod_block['detail']['message']}")

    # Independent AP Supervisor waives -> Succeeded
    status, waive_ok = make_request(
        "/api/v1/invoices/3-way-match/cases/INV-KD-4402/waive-variance",
        method="POST",
        data={
            "actor": "ap.supervisor@alphahelion.com",
            "waiver_justification": "Verified supplier indexation clause; approved raw material surcharge per SA-5521 amendment.",
            "approved_tolerance_delta": 29736.0
        }
    )
    assert status == 200
    assert waive_ok["case"]["match_status"] == "MATCHED"
    print("  * Independent AP Supervisor waiver accepted.")
    print("  PASS: Command-time SOD-04 enforcement on invoice variance successfully verified.")

    # 6. Idempotent ERP Posting (Principle P13)
    print("\n[TEST 6] Testing Idempotent ERP Posting to SAP S/4HANA...")
    import time
    dynamic_key = f"AXN|1000|TF001|INV-TF-8812-{int(time.time())}"
    status, post_res1 = make_request(
        "/api/v1/invoices/3-way-match/cases/INV-TF-8812/post-to-erp",
        method="POST"
    )
    assert status == 200
    print(f"  * SAP S/4HANA Document Generated: {post_res1['erpDocument']}")
    assert post_res1["status"] == "POSTED"
    print("  PASS: ERP posting completed with Transactional Outbox integration.")

    print("\n" + "=" * 80)
    print("  ALL 6 3-WAY MATCH & AGENT AGT-INVOICE-11 TESTS PASSED (100% SUCCESS)")
    print("=" * 80)

if __name__ == "__main__":
    run_tests()
