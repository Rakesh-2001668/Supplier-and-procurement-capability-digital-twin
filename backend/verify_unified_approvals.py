"""
AlphaHelion Purchasing Intelligence Cloud
Test Suite: Unified Multi-Tier Approval Inbox & Segregation of Duties (SoD) Sentinel
Blueprint Reference: Section 24 (Multi-Tier Approval Matrix) & Table 4 (SoD Rules SOD-01..07)
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
    print("  TEST SUITE: UNIFIED MULTI-TIER APPROVAL INBOX & SOD SENTINEL")
    print("=" * 80)

    # 1. Query Inbox
    print("\n[TEST 1] Listing Unified Approval Inbox...")
    status, res = make_request("/api/v1/approvals/inbox")
    assert status == 200, f"Expected 200, got {status}"
    items = res["items"]
    metrics = res["metrics"]
    print(f"-> Total Items in Inbox: {len(items)}")
    print(f"-> Pending RFQ Awards: {metrics['total_rfq_pending_count']}")
    print(f"-> Pending Value: ₹{metrics['total_pending_value_inr']:,.2f}")
    assert len(items) >= 5, "Expected at least 5 pending approval items"
    assert any(i["document_type"] == "RFQ_SOURCING_AWARD" for i in items)
    print("  PASS: Inbox returned with multi-tier metrics.")

    # 2. Filter Inbox by RFQ_SOURCING_AWARD
    print("\n[TEST 2] Filtering Inbox for RFQ Sourcing Awards...")
    status, rfq_res = make_request("/api/v1/approvals/inbox?document_type=RFQ_SOURCING_AWARD")
    assert status == 200
    for rfq in rfq_res["items"]:
        assert rfq["document_type"] == "RFQ_SOURCING_AWARD"
        print(f"  * [{rfq['id']}] {rfq['title']} | Tier: {rfq['tier']} | Amount: {rfq['amount_display']}")
    print("  PASS: Filter by RFQ_SOURCING_AWARD verified.")

    # 3. SoD Precheck on RFQ-701
    print("\n[TEST 3] Testing SoD Precheck for Creator vs Independent Approver...")
    # Precheck for creator (amit.verma) -> Should flag conflict
    status, pre_creator = make_request("/api/v1/approvals/inbox/APP-RFQ-701?actor=amit.verma@alphahelion.com")
    assert status == 200
    assert pre_creator["sod_precheck"]["can_approve"] is False
    assert pre_creator["sod_precheck"]["rule_id"] == "SOD-05"
    print(f"  * Creator Pre-check: can_approve={pre_creator['sod_precheck']['can_approve']} (Rule: {pre_creator['sod_precheck']['rule_id']})")

    # Precheck for CPO -> Should pass cleanly
    status, pre_cpo = make_request("/api/v1/approvals/inbox/APP-RFQ-701?actor=cpo@alphahelion.com")
    assert status == 200
    assert pre_cpo["sod_precheck"]["can_approve"] is True
    print(f"  * CPO Pre-check: can_approve={pre_cpo['sod_precheck']['can_approve']}")
    print("  PASS: SoD pre-check properly identifies conflicts prior to execution.")

    # 4. Command-Time SoD Block (SOD-05 on RFQ Award)
    print("\n[TEST 4] Enforcing Command-Time Block: Creator attempting to self-approve RFQ Award...")
    status, block_res = make_request(
        "/api/v1/approvals/inbox/APP-RFQ-701/action",
        method="POST",
        data={"action": "APPROVE", "actor": "amit.verma@alphahelion.com"}
    )
    print(f"  * Response Status: {status} (Expected 403 Forbidden)")
    assert status == 403, f"Expected 403 Forbidden, got {status}"
    err_detail = block_res["detail"]
    assert err_detail["error"] == "SEGREGATION_OF_DUTIES_VIOLATION"
    assert err_detail["rule_id"] == "SOD-05"
    print(f"  * Block Message: {err_detail['message']}")
    print("  PASS: Command-time SOD-05 enforcement successfully blocked unauthorized self-approval.")

    # 5. Command-Time SoD Block (SOD-01 on Requisition)
    print("\n[TEST 5] Enforcing Command-Time Block: Requester attempting to self-approve PR #REQ-2311...")
    status, pr_block = make_request(
        "/api/v1/approvals/inbox/APP-REQ-2311/action",
        method="POST",
        data={"action": "APPROVE", "actor": "priya.sharma@alphahelion.com"}
    )
    assert status == 403, f"Expected 403, got {status}"
    assert pr_block["detail"]["rule_id"] == "SOD-01"
    print(f"  * Block Message: {pr_block['detail']['message']}")
    print("  PASS: Command-time SOD-01 enforcement successfully blocked self-approval.")

    # 6. Valid Approval by Independent Authority (CPO on RFQ-701)
    print("\n[TEST 6] Valid Multi-Tier Sign-off: CPO approving RFQ-701...")
    status, approve_res = make_request(
        "/api/v1/approvals/inbox/APP-RFQ-701/action",
        method="POST",
        data={"action": "APPROVE", "actor": "cpo@alphahelion.com"}
    )
    assert status == 200, f"Expected 200, got {status}"
    assert approve_res["status"] == "success"
    print(f"  * Result: {approve_res['message']}")
    print("  PASS: Independent authorized sign-off executed successfully.")

    # 7. Rejection with Mandatory Written Rationale
    print("\n[TEST 7] Testing Rejection Validation (Mandatory Rationale >= 15 chars)...")
    # Missing/short rationale should fail with 400
    status, rej_fail = make_request(
        "/api/v1/approvals/inbox/APP-RFQ-704/action",
        method="POST",
        data={"action": "REJECT", "actor": "category.lead@alphahelion.com", "rationale": "too short"}
    )
    assert status == 400, f"Expected 400 for short rationale, got {status}"
    print("  * Short rationale properly rejected with 400.")

    # Valid rationale should succeed
    status, rej_ok = make_request(
        "/api/v1/approvals/inbox/APP-RFQ-704/action",
        method="POST",
        data={
            "action": "REJECT",
            "actor": "category.lead@alphahelion.com",
            "rationale": "Lead time of 6 weeks exceeds our Q4 plant production requirement; renegotiate to 3 weeks."
        }
    )
    assert status == 200, f"Expected 200, got {status}"
    assert rej_ok["approval_status"] == "REJECTED"
    print("  * Rejection recorded with detailed audit rationale.")
    print("  PASS: Rejection validation and status update verified.")

    # 8. Query SoD Matrix & Violation Sentinel Log
    print("\n[TEST 8] Inspecting SoD Matrix & Live Violation Sentinel Log...")
    status, matrix_res = make_request("/api/v1/approvals/sod/matrix")
    assert status == 200
    print(f"  * Cataloged SoD Rules: {matrix_res['total_rules']}")
    print(f"  * Role Conflict Grid Pairs: {len(matrix_res['conflict_grid'])}")

    status, viol_res = make_request("/api/v1/approvals/sod/violations")
    assert status == 200
    print(f"  * Total Blocked SoD Violations in Sentinel Log: {viol_res['total_violations']}")
    assert viol_res["total_violations"] >= 2
    latest = viol_res["violations"][0]
    print(f"  * Latest Blocked Attempt: [{latest['rule_id']}] {latest['actor']} -> {latest['attempted_action']}")
    print("  PASS: SoD Matrix & Sentinel audit ledger fully operational.")

    # 9. Out-of-Office Delegation Registry
    print("\n[TEST 9] Creating and Querying Out-of-Office Delegation Rule...")
    status, del_list = make_request("/api/v1/approvals/delegations")
    assert status == 200
    initial_count = len(del_list["delegations"])
    
    new_del = {
        "delegator": "category.lead@alphahelion.com",
        "delegatee": "senior.buyer@alphahelion.com",
        "scope": "RFQ_ONLY",
        "valid_from": "2026-10-24T00:00:00Z",
        "valid_until": "2026-10-31T23:59:59Z",
        "reason": "Annual Sourcing Negotiations Offsite"
    }
    status, create_del = make_request("/api/v1/approvals/delegations", method="POST", data=new_del)
    assert status == 200
    assert create_del["delegation"]["delegator"] == new_del["delegator"]
    print(f"  * Created delegation rule {create_del['delegation']['id']} for '{new_del['delegator']}'")
    print("  PASS: Out-of-office delegation registry verified.")

    print("\n" + "=" * 80)
    print("  ALL 9 UNIFIED APPROVAL & SOD SENTINEL TESTS PASSED (100% SUCCESS)")
    print("=" * 80)

if __name__ == "__main__":
    run_tests()
