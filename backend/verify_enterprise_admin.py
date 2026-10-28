"""
Automated Verification Suite for Module M13: Enterprise Administration, SoD Matrix & Governance (ADM-01..04)
Testing Principles P09, P10, and P13.
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

def test_sod_matrix():
    print_separator("1. Testing SoD Conflict Matrix (ADM-01)...")
    r = requests.get(f"{BASE_URL}/admin/governance/sod-matrix")
    assert r.status_code == 200, f"Failed: {r.text}"
    data = r.json()
    assert data["status"] == "success"
    assert data["total_rules"] == 7, f"Expected 7 SoD rules, got {data['total_rules']}"
    print(f"   [OK] Loaded {data['total_rules']} Segregation of Duties Rules (SOD-01 to SOD-07)")
    for rule in data["rules"][:3]:
        print(f"        &bull; {rule['id']} ({rule['risk']}): {rule['title']}")

def test_sod_violations_log():
    print_separator("2. Testing SoD Real-Time Violation Audit Log (ADM-01)...")
    r = requests.get(f"{BASE_URL}/admin/governance/sod-violations")
    assert r.status_code == 200, f"Failed: {r.text}"
    data = r.json()
    assert data["status"] == "success"
    assert data["total_violations_blocked"] >= 3
    print(f"   [OK] Total Blocked Violations Logged: {data['total_violations_blocked']}")
    for v in data["violations"]:
        print(f"        &bull; [{v['rule_id']}] {v['actor']} -> {v['attempted_action']} on {v['target_object_id']}: {v['decision']}")

def test_dmn_rules_configuration():
    print_separator("3. Testing DMN Parameter Calibration & Plant Config (ADM-02)...")
    # Get initial config
    r_get = requests.get(f"{BASE_URL}/admin/governance/config/dmn-rules")
    assert r_get.status_code == 200, f"Failed: {r_get.text}"
    cfg = r_get.json()["config"]
    print(f"   [OK] Touchless PO Max Risk Score: {cfg['touchless_po_max_risk_score']}")
    print(f"   [OK] Metal Indexation Deadband: +/- {cfg['metal_indexation_deadband_pct']}%")
    print(f"   [OK] MDM Duplicate Block Similarity: {cfg['mdm_duplicate_similarity_block_pct']}%")

    # Update config
    update_payload = {
        "touchless_po_max_risk_score": 22,
        "metal_indexation_deadband_pct": 3.5,
        "actor": "u:platform.admin"
    }
    r_put = requests.put(f"{BASE_URL}/admin/governance/config/dmn-rules", json=update_payload)
    assert r_put.status_code == 200, f"Update failed: {r_put.text}"
    updated = r_put.json()["config"]
    assert updated["touchless_po_max_risk_score"] == 22
    assert updated["metal_indexation_deadband_pct"] == 3.5
    print(f"   [OK] DMN Rule parameters successfully calibrated: Risk {updated['touchless_po_max_risk_score']}, Deadband {updated['metal_indexation_deadband_pct']}%")

def test_outbox_telemetry_and_retry():
    print_separator("4. Testing Transactional Outbox & Idempotency Monitor (ADM-03 / Principle P13)...")
    r_outbox = requests.get(f"{BASE_URL}/admin/governance/outbox")
    assert r_outbox.status_code == 200, f"Failed: {r_outbox.text}"
    data = r_outbox.json()
    assert data["status"] == "success"
    assert data["total_messages"] >= 1
    msg = data["messages"][0]
    print(f"   [OK] Outbox Messages Tracked: {data['total_messages']}")
    print(f"   [OK] Connector: {data['connector_target']}")
    print(f"   [OK] Message ID: {msg['msg_id']}, ERP Doc: {msg['erp_doc_no']}, Idempotency Key: {msg['idempotency_key']}")

    # Test retry endpoint
    r_retry = requests.post(f"{BASE_URL}/admin/governance/outbox/{msg['msg_id']}/retry")
    assert r_retry.status_code == 200
    assert r_retry.json()["outbox_record"]["retries"] >= 1
    print(f"   [OK] Outbox Retry Endpoint: {r_retry.json()['message']}")

def test_lineage_graph_inspection():
    print_separator("5. Testing Lineage Graph Visualizer Engine (ADM-04 / Principle P10)...")
    r_lin = requests.get(f"{BASE_URL}/admin/governance/lineage/INV-TF-8812")
    assert r_lin.status_code == 200, f"Failed: {r_lin.text}"
    data = r_lin.json()
    assert data["status"] == "success"
    print(f"   [OK] Lineage Query for 'INV-TF-8812': Found {data['lineage_depth']} connected nodes in transaction graph.")
    print(f"   [OK] Nodes: {[n['id'] for n in data['lineage_graph']['nodes']]}")

if __name__ == "__main__":
    print("=====================================================================")
    print("Testing AlphaHelion Enterprise Administration & Governance (ADM-01..04)")
    print("=====================================================================")
    try:
        test_sod_matrix()
        test_sod_violations_log()
        test_dmn_rules_configuration()
        test_outbox_telemetry_and_retry()
        test_lineage_graph_inspection()
        print("\n=====================================================================")
        print("ALL ENTERPRISE ADMINISTRATION & GOVERNANCE TESTS PASSED! [OK]")
        print("=====================================================================")
    except Exception as e:
        print(f"\n[FAIL] Test aborted with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
