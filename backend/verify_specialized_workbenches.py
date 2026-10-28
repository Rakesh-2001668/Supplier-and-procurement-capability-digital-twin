"""
Verification Suite: AlphaHelion Specialized High-Impact Workbenches
Blueprint Reference: Section 30 Screen Catalogue (SPD-07, PO-04, RCV-03, CLM-02)

Tests the 4 High-Impact Specialist Workbenches:
1. SPD-07: Category Strategy Workbench (Kraljic Portfolio Matrix)
2. PO-04: Predictive Expediting Cockpit (ML Late Risk & Escalation)
3. RCV-03: Service Entry Sheet (SES) Console (SOD-03 & Progress)
4. CLM-02: AI Clause Review & Redline Studio (Playbook Fallbacks)
"""

import requests
import json
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://127.0.0.1:8080/api/v1/workbenches"

def test_specialized_workbenches():
    print("="*70)
    print("Testing AlphaHelion Specialized Workbenches (Blueprint Section 30)")
    print("="*70)

    # 1. Test Kraljic Matrix (SPD-07)
    print("\n1. Testing GET /workbenches/kraljic (Category Strategy Workbench)...")
    r = requests.get(f"{BASE_URL}/kraljic")
    assert r.status_code == 200, f"Failed getting Kraljic data: {r.status_code} {r.text}"
    data = r.json()
    summary = data["portfolio_summary"]
    quads = data["quadrants"]
    assert "STRATEGIC" in quads and "LEVERAGE" in quads and "BOTTLENECK" in quads and "ROUTINE" in quads
    assert summary["total_spend_under_management_cr"] > 100.0
    print(f"   [OK] Total Spend Under Management: INR {summary['total_spend_under_management_cr']} Cr")
    print(f"   [OK] Target Savings Tracked: INR {summary['total_target_savings_cr']} Cr across {summary['total_categories_tracked']} categories")
    print(f"   [OK] Strategic Quadrant: {[c['name'] for c in quads['STRATEGIC']]}")
    print(f"   [OK] Leverage Quadrant: {[c['name'] for c in quads['LEVERAGE']]}")
    print(f"   [OK] Bottleneck Quadrant: {[c['name'] for c in quads['BOTTLENECK']]}")
    print(f"   [OK] Routine Quadrant: {[c['name'] for c in quads['ROUTINE']]}")

    # 2. Test Predictive Expediting Cockpit (PO-04)
    print("\n2. Testing GET /workbenches/expediting (Predictive Expediting Cockpit)...")
    r = requests.get(f"{BASE_URL}/expediting")
    assert r.status_code == 200, f"Failed getting expediting data: {r.status_code}"
    exp_data = r.json()
    items = exp_data["expediting_items"]
    assert len(items) >= 3
    critical_item = next((i for i in items if i["risk_level"] == "CRITICAL_LATE"), None)
    assert critical_item is not None
    print(f"   [OK] Monitored PO Lines: {exp_data['summary']['monitored_pos']}, High-Risk Delayed: {exp_data['summary']['high_risk_delayed']}")
    print(f"   [OK] Critical Late PO: {critical_item['po_number']} for {critical_item['item_description']} (Late Prob: {critical_item['late_delivery_prob']*100}%, Delay: {critical_item['delay_hours']}h)")

    # 3. Test PO Escalation Action
    print("\n3. Testing POST /workbenches/expediting/{po_id}/escalate...")
    esc_payload = {
        "escalation_tier": "TIER_2_EXECUTIVE",
        "contact_email": "supply-chain@raremagnets.com",
        "message": "Urgent expedite required for Chennai Air Customs hold on Neodymium Rings.",
        "requested_revised_eta": "2026-10-27",
        "actor": "u:buyer.hosur"
    }
    r = requests.post(f"{BASE_URL}/expediting/PO-77395/escalate", json=esc_payload)
    assert r.status_code == 200, f"Escalation failed: {r.status_code} {r.text}"
    esc_res = r.json()
    assert esc_res["current_status"] == "ESCALATED_TIER_2_EXECUTIVE"
    assert esc_res["promised_date_updated"] == "2026-10-27"
    print(f"   [OK] Escalation Dispatched: {esc_res['message']}")
    print(f"   [OK] Revised Promised Date Committed: {esc_res['promised_date_updated']}")

    # 4. Test Service Entry Sheets (RCV-03)
    print("\n4. Testing GET /workbenches/service-entries (Service Entry Sheets)...")
    r = requests.get(f"{BASE_URL}/service-entries")
    assert r.status_code == 200
    ses_data = r.json()
    sheets = ses_data["service_entries"]
    assert len(sheets) >= 2
    pending_ses = next((s for s in sheets if s["status"] == "PENDING_APPROVAL"), None)
    assert pending_ses is not None
    print(f"   [OK] Total Service Entry Sheets: {ses_data['total_sheets']}")
    print(f"   [OK] Pending Construction SES: {pending_ses['ses_id']} for {pending_ses['service_title']}")
    print(f"   [OK] Subcontract SC-118: Gross ₹{pending_ses['total_amount_inr']}, 5% Retention: ₹{pending_ses['retention_amount_inr']}, Net Certified: ₹{pending_ses['net_payable_inr']}")

    # 5. Test SES Approval SOD-03 Enforcement
    print("\n5. Testing POST /workbenches/service-entries/{ses_id}/approve with SOD-03 Enforcement...")
    # Attempt approval by the PO Creator -> Must be BLOCKED
    invalid_approval = {
        "decision": "APPROVE",
        "actor": pending_ses["po_creator"], # conflicting PO creator!
        "comments": "Self-approving my own created PO service entry",
        "measured_work_quality": "SATISFACTORY"
    }
    r_bad = requests.post(f"{BASE_URL}/service-entries/{pending_ses['ses_id']}/approve", json=invalid_approval)
    assert r_bad.status_code == 403, f"Expected 403 SOD-03 violation, got {r_bad.status_code}"
    print(f"   [OK] SOD-03 Correctly Blocked PO Creator! Reason: {r_bad.json()['detail']}")

    # Valid approval by independent Site Project Manager
    valid_approval = {
        "decision": "APPROVE",
        "actor": pending_ses["candidate_approver"],
        "comments": "Inspected formwork and RCC rebar at Tower B; 35% milestone certified with 5% retention withheld.",
        "measured_work_quality": "SATISFACTORY"
    }
    r_ok = requests.post(f"{BASE_URL}/service-entries/{pending_ses['ses_id']}/approve", json=valid_approval)
    assert r_ok.status_code == 200
    print(f"   [OK] Independent Approver Succeeded: {r_ok.json()['message']}")

    # 6. Test AI Clause Redline Studio (CLM-02)
    print("\n6. Testing GET /workbenches/clause-redline/SA-5520 (AI Clause Review & Redline)...")
    r = requests.get(f"{BASE_URL}/clause-redline/SA-5520")
    assert r.status_code == 200
    redline_data = r.json()["redline_workspace"]
    clauses = redline_data["clauses"]
    assert len(clauses) >= 3
    indemnity_clause = next((c for c in clauses if "INDEMNITY" in c["clause_id"]), None)
    assert indemnity_clause is not None
    assert indemnity_clause["risk_rating"] == "HIGH"
    print(f"   [OK] Contract: {redline_data['contract_title']} (Playbook: {redline_data['playbook_version']})")
    print(f"   [OK] High-Risk Clause: {indemnity_clause['title']}")
    print(f"   [OK] Playbook: {indemnity_clause['playbook_position'][:80]}...")
    print(f"   [OK] Supplier Proposed: {indemnity_clause['supplier_proposed'][:80]}...")
    print(f"   [OK] Recommended Fallback: {indemnity_clause['fallback_suggestion'][:80]}...")

    # 7. Test Clause Redline Decision
    print("\n7. Testing POST /workbenches/clause-redline/SA-5520/decision...")
    decision_payload = {
        "clause_id": indemnity_clause["clause_id"],
        "decision": "APPLY_FALLBACK",
        "actor": "u:legal.counsel.corporate",
        "justification": "Applied Compromise Position B with 3x annual commitment cap and strict carveout for serial porosity defects."
    }
    r_dec = requests.post(f"{BASE_URL}/clause-redline/SA-5520/decision", json=decision_payload)
    assert r_dec.status_code == 200
    dec_res = r_dec.json()
    assert dec_res["new_status"] == "APPLY_FALLBACK"
    print(f"   [OK] Redline Decision Recorded: {dec_res['message']}")

    print("\n" + "="*70)
    print("ALL 7 SPECIALIZED HIGH-IMPACT WORKBENCH TESTS PASSED 100%! [OK]")
    print("="*70)

if __name__ == "__main__":
    try:
        test_specialized_workbenches()
    except Exception as e:
        print(f"\n[FAIL] Test encountered error: {e}")
        sys.exit(1)
