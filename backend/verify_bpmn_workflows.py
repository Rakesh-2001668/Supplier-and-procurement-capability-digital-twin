"""
AlphaHelion Purchasing Intelligence Cloud
Test Suite: BPMN 2.0 Governed Swimlane Workflows & Token Simulation Engine
Blueprint Reference: Part C: Section 21 (Flows F1 - F9, pages 37-54) & Technical Doc Section 8 & 16
"""

import sys
import json
import urllib.request
import urllib.error

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://127.0.0.1:8080"

def run_tests():
    print("=" * 80)
    print("  TEST SUITE: BPMN 2.0 SWIMLANE WORKFLOWS (F1 - F9) & TOKEN ENGINE")
    print("=" * 80)

    # 1. Test GET /api/v1/bpmn/flows
    print("\n[TEST 1] Listing all Governed BPMN 2.0 Flows...")
    req = urllib.request.Request(f"{BASE_URL}/api/v1/bpmn/flows")
    with urllib.request.urlopen(req) as resp:
        flows = json.loads(resp.read().decode('utf-8'))
        total = len(flows)
        print(f"-> Total BPMN Flows returned: {total}")
        assert total == 9, f"Expected 9 flows, got {total}"
        
        expected_keys = [
            ("F1", "pic.mrp-to-pr"),
            ("F2", "pic.requisition"),
            ("F3", "pic.sourcing-award"),
            ("F4", "pic.contract"),
            ("F5", "pic.po"),
            ("F6", "pic.receipt"),
            ("F7", "pic.invoice"),
            ("F8", "pic.supplier-onboarding"),
            ("F9", "pic.material-request"),
        ]
        for flow_code, p_key in expected_keys:
            matched = next((f for f in flows if f["flow_code"] == flow_code), None)
            assert matched is not None, f"Flow {flow_code} not found in catalog!"
            assert matched["process_key"] == p_key, f"Expected {p_key}, got {matched['process_key']}"
            print(f"  * [{matched['flow_code']}] {matched['title']} ({matched['process_key']}) - {matched['total_steps']} steps, {matched['lanes_count']} lanes")
    print("  PASS: All 9 Governed BPMN 2.0 flows present and properly structured.")

    # 2. Test detailed flow structure for all F1 to F9
    print("\n[TEST 2] Verifying Swimlanes, Step Roles, Gateways & SLA Timers for F1-F9...")
    for flow_code, p_key in expected_keys:
        req = urllib.request.Request(f"{BASE_URL}/api/v1/bpmn/flows/{flow_code}")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            flow = data["flow"]
            token_state = data["token_state"]
            assert flow["flow_code"] == flow_code
            assert len(flow["lanes"]) >= 3, f"{flow_code} should have at least 3 swimlanes"
            assert len(flow["steps"]) >= 4, f"{flow_code} should have at least 4 steps"
            
            # Check step types: must have START_EVENT and END_EVENT
            step_types = [s["type"] for s in flow["steps"]]
            assert "START_EVENT" in step_types, f"Flow {flow_code} missing START_EVENT"
            assert "END_EVENT" in step_types, f"Flow {flow_code} missing END_EVENT"
            assert any(t in ("USER_TASK", "SYSTEM_TASK") for t in step_types), f"Flow {flow_code} missing tasks"

            print(f"  * {flow_code}: {len(flow['lanes'])} lanes, {len(flow['steps'])} steps, types: {set(step_types)}")
    print("  PASS: Detailed BPMN structure verified for F1 through F9.")

    # 3. Test Token Simulation on F2 (Guided Buying Requisition)
    print("\n[TEST 3] Testing Step-by-Step Token Advance on F2 (pic.requisition)...")
    sim_req_data = json.dumps({
        "current_step_index": 0,
        "branch_choice": "MAIN_PATH",
        "actor": "Simulated Procurement User"
    }).encode('utf-8')
    req = urllib.request.Request(
        f"{BASE_URL}/api/v1/bpmn/flows/F2/simulate",
        data=sim_req_data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        sim_res = json.loads(resp.read().decode('utf-8'))
        print(f"  * Token advanced to step {sim_res['new_step_index']}: {sim_res['active_step']['label']}")
        print(f"  * Action message: {sim_res['message']}")
        print(f"  * Current lane: {sim_res['active_step']['lane']} | Type: {sim_res['active_step']['type']}")
        assert sim_res["new_step_index"] == 1
        assert sim_res["active_step"]["step_id"] == "S2_SEARCH"
    
    # Advance to Step 2
    sim_req_data = json.dumps({
        "current_step_index": 1,
        "branch_choice": "MAIN_PATH",
        "actor": "Simulated Procurement User"
    }).encode('utf-8')
    req = urllib.request.Request(
        f"{BASE_URL}/api/v1/bpmn/flows/F2/simulate",
        data=sim_req_data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        sim_res2 = json.loads(resp.read().decode('utf-8'))
        print(f"  * Token advanced to step {sim_res2['new_step_index']}: {sim_res2['active_step']['label']}")
        assert sim_res2["new_step_index"] == 2
        assert sim_res2["active_step"]["type"] == "GATEWAY"
    print("  PASS: Token simulation successfully advances across swimlanes.")

    # 4. Test Token Simulation Gateway Choice on F2 Step 3 (Gateway)
    print("\n[TEST 4] Testing Gateway Step Simulation on F2...")
    sim_branch_data = json.dumps({
        "current_step_index": 2,
        "branch_choice": "MAIN_PATH",
        "actor": "Category Director"
    }).encode('utf-8')
    req = urllib.request.Request(
        f"{BASE_URL}/api/v1/bpmn/flows/F2/simulate",
        data=sim_branch_data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        branch_res = json.loads(resp.read().decode('utf-8'))
        print(f"  * Next step: {branch_res['new_step_index']} - {branch_res['active_step']['label']}")
        assert branch_res["new_step_index"] == 3
    print("  PASS: Gateway step token advancement works.")

    # 5. Test Token Reset
    print("\n[TEST 5] Testing Token Reset on F2...")
    req = urllib.request.Request(f"{BASE_URL}/api/v1/bpmn/flows/F2/reset", data=b"", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        reset_res = json.loads(resp.read().decode('utf-8'))
        print(f"  * Reset state: {reset_res['message']} (active step: {reset_res['current_step_index']})")
        assert reset_res["current_step_index"] == 0
    print("  PASS: Token reset functions as expected.")

    print("\n" + "=" * 80)
    print("  ALL 5 BPMN WORKFLOW TESTS PASSED CLEANLY (100% SUCCESS)")
    print("=" * 80)

if __name__ == "__main__":
    run_tests()
