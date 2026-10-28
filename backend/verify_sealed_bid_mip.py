"""
Verification script for Sealed Bid Envelope & MIP Award Optimization Solver Workbench (SRC-03..05)
Workflow: BPMN Flow F3 (pic.sourcing-award)
Principles: P06 (Multi-attribute scoring / MIP), P07 (Sealed bid escrow), P09 (SOD-05), P10 (Lineage), P11 (AI Explainability), P12 (Negotiated Savings)
"""

import requests
import sys

# Ensure UTF-8 output on Windows terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://127.0.0.1:8080/api/v1/sourcing/mip-studio"

def test_sealed_bid_mip_workbench():
    print("==================================================================")
    print("RUNNING SEALED BID ENVELOPE & MIP AWARD OPTIMIZATION TEST SUITE")
    print("==================================================================")

    # 1. List Sourcing Events
    print("\n--- Test 1: Sourcing Events Listing ---")
    r1 = requests.get(f"{BASE_URL}/events")
    assert r1.status_code == 200, f"Expected 200, got {r1.status_code}: {r1.text}"
    events = r1.json()["events"]
    print(f"Total Sourcing Events: {len(events)}")
    rfq2231 = next((e for e in events if e["id"] == "RFQ-2231"), None)
    assert rfq2231 is not None, "Expected RFQ-2231 in events"
    print(f"Event: {rfq2231['id']} - {rfq2231['title']}")
    print(f"Annual Volume: {rfq2231['target_annual_volume']:,} | Monthly: {rfq2231['monthly_run_rate']:,}")
    print(f"Should-Cost: ₹{rfq2231['should_cost_inr']} | Baseline: ₹{rfq2231['baseline_price_inr']}")
    print(f"Sealed Status: {rfq2231['is_sealed']} | Envelopes: {rfq2231['envelope_count']}")
    assert rfq2231["is_sealed"] is True, "Expected bids to be sealed initially"
    print("PASS: Event listed with sealed envelope status!")

    # 2. Cryptographic Masking Prior to Unsealing (Principle P07)
    print("\n--- Test 2: Cryptographic Masking Prior to Unsealing ---")
    r2 = requests.get(f"{BASE_URL}/events/RFQ-2231")
    assert r2.status_code == 200, f"Expected 200, got {r2.status_code}"
    data2 = r2.json()
    envelopes2 = data2["envelopes"]
    assert len(envelopes2) == 3, f"Expected 3 envelopes, got {len(envelopes2)}"
    for env in envelopes2:
        print(f"Envelope {env['envelope_id']} ({env['supplier_name']}): Status = {env['status']}, Hash = {env['cryptographic_hash'][:16]}...")
        assert env["status"] == "SEALED_IN_ESCROW", "Expected SEALED_IN_ESCROW"
        assert "unit_price_inr" not in env, "Commercial prices must NOT be visible before ceremony!"
    print("PASS: Commercial bids are cryptographically masked in escrow!")

    # 3. Premature MIP Execution Block
    print("\n--- Test 3: Premature MIP Execution Block ---")
    r3 = requests.post(f"{BASE_URL}/events/RFQ-2231/solve-mip", json={
        "event_id": "RFQ-2231",
        "actor": "u:category.mgr.castings"
    })
    print(f"Response status: {r3.status_code}")
    assert r3.status_code == 400, f"Expected HTTP 400 when solving while sealed, got {r3.status_code}"
    print(f"Blocked Message: {r3.json()['detail']}")
    print("PASS: MIP solver correctly refuses to run while bids are sealed!")

    # 4. Authorized Sealed Bid Opening Ceremony
    print("\n--- Test 4: Authorized Sealed Bid Opening Ceremony ---")
    r4 = requests.post(f"{BASE_URL}/events/RFQ-2231/unseal-ceremony", json={
        "actor": "u:category.mgr.castings",
        "ceremony_token": "CEREMONY-AUTH-7721"
    })
    assert r4.status_code == 200, f"Expected 200, got {r4.status_code}: {r4.text}"
    data4 = r4.json()
    print("Ceremony Message:", data4["message"])
    unsealed = data4["unsealed_bids"]
    assert len(unsealed) == 3
    for b in unsealed:
        print(f"  Supplier {b['supplier_name']}: Base Price = ₹{b['unit_price_inr']}, Landed TCO = ₹{b['computed_tco_inr']}, Verified Cap = {b['verified_monthly_capacity']:,}/mo")
        assert b["computed_tco_inr"] >= b["unit_price_inr"], "TCO must include freight, packaging & COPQ"
    print("PASS: Sealed envelopes cryptographically opened and Landed TCO calculated!")

    # 5. Mixed-Integer Programming (MIP) Award Solver Execution
    print("\n--- Test 5: Mixed-Integer Programming (MIP) Award Optimizer Execution ---")
    r5 = requests.post(f"{BASE_URL}/events/RFQ-2231/solve-mip", json={
        "event_id": "RFQ-2231",
        "max_single_supplier_share_pct": 70.0,
        "actor": "u:category.mgr.castings"
    })
    assert r5.status_code == 200, f"Expected 200, got {r5.status_code}: {r5.text}"
    data5 = r5.json()
    solver_res = data5["solver_results"]
    scenarios = solver_res["scenarios"]
    print(f"Generated {len(scenarios)} Optimization Scenarios:")
    
    # Check Scenario A (Unconstrained) -> Must be Infeasible
    scen_a = next(s for s in scenarios if s["scenario_id"] == "UNCONSTRAINED_LOWEST")
    print(f"\n* {scen_a['title']}:")
    print(f"  Feasibility: {scen_a['feasibility']} (is_feasible: {scen_a['is_feasible']})")
    print(f"  Capacity Check: {scen_a['allocations'][0]['capacity_utilization_pct']}% utilization")
    assert scen_a["is_feasible"] is False, "Unconstrained single-source must violate capacity limits!"

    # Check Scenario B (Dual-Source Optimal) -> Recommended
    scen_b = next(s for s in scenarios if s["scenario_id"] == "DUAL_SOURCE_OPTIMAL")
    print(f"\n* {scen_b['title']}:")
    print(f"  Feasibility: {scen_b['feasibility']} (is_feasible: {scen_b['is_feasible']})")
    print(f"  Weighted Average Price: ₹{scen_b['weighted_average_price_inr']}")
    print(f"  Annual Spend: ₹{scen_b['annual_contract_spend_inr']:,}")
    print(f"  Negotiated Savings: ₹{scen_b['negotiated_annual_savings_inr']:,}")
    assert scen_b["is_feasible"] is True
    assert scen_b.get("is_recommended") is True
    assert scen_b["weighted_average_price_inr"] == 400.80
    assert scen_b["negotiated_annual_savings_inr"] == 9936000.0 # ₹99.36 Lakhs

    # Verify Agent AGT-MIP-06 Answer Contract
    assert "agent_contract" in data5
    ac = data5["agent_contract"]
    print(f"\nAgent: {ac['agent_id']} ({ac['agent_name']}) • Autonomy: {ac['autonomy_level']} • Confidence: {ac['confidence_score']}")
    print(f"Agent Recommendation: {ac['recommendation']}")
    print("PASS: MIP solver evaluated capacity constraints and recommended dual-source 60/40 split!")

    # 6. Select Scenario B
    print("\n--- Test 6: Select Winning MIP Scenario ---")
    r6 = requests.post(f"{BASE_URL}/events/RFQ-2231/select-scenario", json={
        "scenario_id": "DUAL_SOURCE_OPTIMAL",
        "actor": "u:category.mgr.castings",
        "rationale": "MIP proved 60/40 allocation satisfies 100% capacity with ₹99.36L savings."
    })
    assert r6.status_code == 200, f"Expected 200, got {r6.status_code}: {r6.text}"
    print("PASS: Scenario B selected for Board Review!")

    # 7. SOD-05 Enforcement: Sourcing Creator Blocked from Self-Approving Award
    print("\n--- Test 7: SOD-05 Command-Time Enforcement ---")
    r7 = requests.post(f"{BASE_URL}/events/RFQ-2231/board-signoff", json={
        "actor": "u:category.mgr.castings", # EVENT CREATOR
        "board_role": "CATEGORY_MGR",
        "signoff_notes": "Attempting creator sign-off"
    })
    print(f"Response status: {r7.status_code}")
    assert r7.status_code == 403, f"Expected HTTP 403 Forbidden under SOD-05, got {r7.status_code}"
    sod_err = r7.json()["detail"]
    print("SoD Violation:", sod_err)
    assert sod_err["rule_id"] == "SOD-05", f"Expected SOD-05, got {sod_err['rule_id']}"
    print("PASS: SOD-05 command-time sentinel blocked sourcing creator from self-approving award!")

    # 8. Independent Board Sign-off (Finance Controller) -> Awarded & Contract Drafted
    print("\n--- Test 8: Independent Board Sign-off & CLM Handoff ---")
    r8 = requests.post(f"{BASE_URL}/events/RFQ-2231/board-signoff", json={
        "actor": "u:finance.controller.p100", # INDEPENDENT BOARD APPROVER
        "board_role": "FINANCE_CONTROLLER",
        "signoff_notes": "Finance audited MIP scenario B. ₹99.36 Lakhs negotiated savings recognized."
    })
    assert r8.status_code == 200, f"Expected 200, got {r8.status_code}: {r8.text}"
    data8 = r8.json()
    print("Approval Message:", data8["message"])
    print("Draft Contract ID:", data8["contract_draft_id"])
    print("Negotiated Savings Initiative ID:", data8["savings_initiative_id"])
    print(f"Allocations: {data8['award_summary']['allocations']}")
    assert data8["contract_draft_id"] == "SA-5520"
    assert data8["savings_initiative_id"] == "SV-0412"
    print("PASS: Board approved award, SA-5520 contract drafted, and SV-0412 savings logged!")

    print("\n==================================================================")
    print("ALL 8 SEALED BID ENVELOPE & MIP OPTIMIZATION TESTS PASSED!")
    print("==================================================================")

if __name__ == "__main__":
    test_sealed_bid_mip_workbench()
