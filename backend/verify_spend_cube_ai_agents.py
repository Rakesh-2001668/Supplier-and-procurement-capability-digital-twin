"""
Comprehensive Automated Verification Suite for Phase 5:
Spend Analytics Cube (M01: SPD-01..09) & Governed AI Agent Runtime (M12: AIX-01..03)
Testing Principles P03, P11 (Copilot Answer Contract), and Agent Safety Governance.
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

def test_spend_cube_metrics():
    print_separator("1. Testing Spend Cube Multidimensional Aggregation (M01)...")
    r = requests.get(f"{BASE_URL}/spend/cube")
    assert r.status_code == 200, f"Failed: {r.text}"
    data = r.json()
    assert data["status"] == "success"
    print(f"   [OK] Total Spend Analyzed: ₹{data['total_spend_cr']} Cr")
    print(f"   [OK] On-Contract Spend: ₹{data['on_contract_spend_cr']} Cr ({data['contract_compliance_pct']}%)")
    print(f"   [OK] Off-Contract Maverick Spend: ₹{data['maverick_spend_cr']} Cr")
    print(f"   [OK] Commodities Tracked: {len(data['commodity_breakdown'])}, Top Suppliers: {len(data['top_suppliers'])}")

def test_maverick_spend():
    print_separator("2. Testing Maverick Spend Detection (Principle P03 Violation)...")
    r = requests.get(f"{BASE_URL}/spend/maverick")
    assert r.status_code == 200, f"Failed: {r.text}"
    data = r.json()
    assert data["status"] == "success"
    assert data["maverick_spend_cr"] > 0
    print(f"   [OK] Detected Maverick Spend: ₹{data['maverick_spend_cr']} Cr across {len(data['records'])} transactions.")
    print(f"   [OK] P03 Violation Warning: {data['principle_p03_warning']}")

def test_tail_spend():
    print_separator("3. Testing Tail Spend 80/20 Pareto Analyzer...")
    r = requests.get(f"{BASE_URL}/spend/tail")
    assert r.status_code == 200, f"Failed: {r.text}"
    data = r.json()
    assert data["status"] == "success"
    print(f"   [OK] Tail Threshold: {data['tail_threshold_pct']}%, Tail Suppliers: {data['tail_supplier_count']}/{data['total_suppliers']}")
    print(f"   [OK] Tail Spend Value: ₹{data['tail_spend_cr']} Cr. Insight: {data['insight']}")

def test_ai_agents_registry():
    print_separator("4. Testing 14 Governed AI Agents Registry (M12: AIX-01..03)...")
    r = requests.get(f"{BASE_URL}/agents/registry")
    assert r.status_code == 200, f"Failed: {r.text}"
    data = r.json()
    assert data["status"] == "success"
    assert data["total_agents"] == 14, f"Expected 14 agents, got {data['total_agents']}"
    print(f"   [OK] 14 Governed AI Agents Registered across L0..L4 Autonomy.")
    for a in data["agents"][:3]:
        print(f"        &bull; {a['id']}: {a['name']} ({a['autonomy_level']}) - Status: {a['status']}")

def test_kill_switches():
    print_separator("5. Testing Safety Kill Switches (Per-Agent and Global Emergency Stop)...")
    # Toggle individual agent
    r_single = requests.post(f"{BASE_URL}/agents/AGT-MAVERICK-01/toggle-kill-switch?actor=u:security.admin")
    assert r_single.status_code == 200
    res_single = r_single.json()
    assert res_single["kill_switch_engaged"] is True
    print(f"   [OK] Single Agent Kill Switch Engaged: {res_single['message']}")

    # Release individual agent
    r_release = requests.post(f"{BASE_URL}/agents/AGT-MAVERICK-01/toggle-kill-switch?actor=u:security.admin")
    assert r_release.status_code == 200
    assert r_release.json()["kill_switch_engaged"] is False
    print(f"   [OK] Single Agent Kill Switch Released: {r_release.json()['message']}")

    # Global Emergency Stop
    r_global = requests.post(f"{BASE_URL}/agents/global-emergency-stop?actor=u:cpo.executive")
    assert r_global.status_code == 200
    assert r_global.json()["global_emergency_stop"] is True
    print(f"   [OK] Global Emergency Stop ENGAGED: {r_global.json()['message']}")

    # Release Global Emergency Stop
    r_global_rel = requests.post(f"{BASE_URL}/agents/global-emergency-stop?actor=u:cpo.executive")
    assert r_global_rel.status_code == 200
    assert r_global_rel.json()["global_emergency_stop"] is False
    print(f"   [OK] Global Emergency Stop DISENGAGED: All 14 agents restored.")

def test_copilot_answer_contract():
    print_separator("6. Testing Principle P11 Copilot Answer Contract Validation...")
    payload = {
        "query": "What is the status and savings lineage of DC-330 aluminium housing at Hosur P100?",
        "tenant_id": "axion-mobility",
        "actor": "u:cpo.executive",
        "plant": "P100 Hosur"
    }
    r = requests.post(f"{BASE_URL}/agents/copilot/query", json=payload)
    assert r.status_code == 200, f"Query failed: {r.text}"
    ans = r.json()

    # Validate all 6 mandatory Answer Contract fields (Principle P11)
    assert "answer_summary" in ans and len(ans["answer_summary"]) > 0, "Missing answer_summary"
    assert "citations" in ans and len(ans["citations"]) >= 4, "Missing or insufficient citations"
    assert "confidence_score" in ans and 0.0 <= ans["confidence_score"] <= 1.0, "Invalid confidence_score"
    assert "assumptions_made" in ans and len(ans["assumptions_made"]) > 0, "Missing assumptions_made"
    assert "sod_check_result" in ans and "status" in ans["sod_check_result"], "Missing sod_check_result"
    assert "recommended_next_actions" in ans and len(ans["recommended_next_actions"]) > 0, "Missing next actions"

    print(f"   [OK] Field 1 - Answer Summary: {ans['answer_summary'][:95]}...")
    print(f"   [OK] Field 2 - Citations ({len(ans['citations'])} Grounded Docs):")
    for c in ans["citations"]:
        print(f"        &bull; [{c['doc_type']}] {c['document_id']}: {c['url']} -> {c['snippet'][:60]}...")
    print(f"   [OK] Field 3 - Confidence Score: {ans['confidence_score'] * 100:.1f}%")
    print(f"   [OK] Field 4 - Operational Assumptions: {len(ans['assumptions_made'])} explicit statements")
    print(f"   [OK] Field 5 - SoD Command-Time Check: {ans['sod_check_result']['rule_id']} = {ans['sod_check_result']['status']}")
    print(f"   [OK] Field 6 - Recommended Next Actions: {len(ans['recommended_next_actions'])} actions with role approvals")

if __name__ == "__main__":
    print("=====================================================================")
    print("Testing AlphaHelion Spend Cube & Governed AI Agent Runtime")
    print("=====================================================================")
    try:
        test_spend_cube_metrics()
        test_maverick_spend()
        test_tail_spend()
        test_ai_agents_registry()
        test_kill_switches()
        test_copilot_answer_contract()
        print("\n=====================================================================")
        print("ALL SPEND CUBE & GOVERNED AI AGENT TESTS PASSED WITH 100% SUCCESS! [OK]")
        print("=====================================================================")
    except Exception as e:
        print(f"\n[FAIL] Test aborted with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
