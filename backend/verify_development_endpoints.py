import requests
import json
import sys

BASE = "http://127.0.0.1:8080/api/v1/development"

def run_tests():
    print("Testing Supplier Development & 8D CAPA API Endpoints...")

    # 1. Overview
    print("\n1. Testing GET /overview...")
    r = requests.get(f"{BASE}/overview")
    assert r.status_code == 200, f"Overview failed: {r.status_code} {r.text}"
    overview = r.json()
    assert "kpis" in overview, "No kpis in overview response"
    print(f"   [OK] Active Plans: {overview['kpis']['active_development_plans']}, Open CAPAs: {overview['kpis']['open_capa_cases']}")

    # 2. List Plans
    print("\n2. Testing GET /plans...")
    r = requests.get(f"{BASE}/plans")
    assert r.status_code == 200, f"List plans failed: {r.status_code}"
    plans = r.json()["plans"]
    print(f"   [OK] Total Plans loaded: {len(plans)}")

    # 3. Get Plan Details
    print("\n3. Testing GET /plans/DEV-PLAN-001...")
    r = requests.get(f"{BASE}/plans/DEV-PLAN-001")
    assert r.status_code == 200, f"Get plan failed: {r.status_code}"
    plan = r.json()["plan"]
    print(f"   [OK] Plan: '{plan['title']}' for {plan['supplier_name']} - Progress: {plan['progress_pct']}%")

    # 4. Create Plan
    print("\n4. Testing POST /plans...")
    new_plan_payload = {
        "title": "Cryogenic Heat Treatment Quality Enhancement",
        "supplier_id": "TWIN-AERO-999",
        "supplier_name": "Titanium Forgings Global",
        "focus_area": "Metallurgy & Heat Treat",
        "strategic_priority": "HIGH",
        "baseline_metric": "Grain size ASTM 4.5, quench uniformity ±8°C",
        "target_metric": "Grain size ASTM 7.5, vacuum quench uniformity ±2°C",
        "investment_budget_usd": 220000,
        "target_date": "2026-06-30",
        "description": "Deployment of automated vacuum quench system with digital thermal logging."
    }
    r = requests.post(f"{BASE}/plans", json=new_plan_payload)
    assert r.status_code == 200, f"Create plan failed: {r.status_code} {r.text}"
    created_plan = r.json()["plan"]
    plan_id = created_plan["id"]
    print(f"   [OK] Created Plan ID: {plan_id}")

    # 5. Verify Milestone
    print(f"\n5. Testing POST /plans/{plan_id}/milestones/MS-001/verify...")
    r = requests.post(f"{BASE}/plans/{plan_id}/milestones/MS-001/verify", json={
        "verification_proof": "Charter Approval Signoff Document #CAD-2025-99",
        "verifier_name": "Dr. Sarah Lin (Chief Metallurgist)",
        "notes": "Kickoff scope reviewed and signed off."
    })
    assert r.status_code == 200, f"Verify milestone failed: {r.status_code} {r.text}"
    print(f"   [OK] Milestone verified. New progress: {r.json()['plan_progress_pct']}%")

    # 6. List CAPA Cases
    print("\n6. Testing GET /capa...")
    r = requests.get(f"{BASE}/capa")
    assert r.status_code == 200, f"List CAPAs failed: {r.status_code}"
    capas = r.json()["capas"]
    print(f"   [OK] Total 8D CAPAs loaded: {len(capas)}")

    # 7. Get CAPA Details (D1-D8)
    print("\n7. Testing GET /capa/CAPA-2025-001...")
    r = requests.get(f"{BASE}/capa/CAPA-2025-001")
    assert r.status_code == 200, f"Get CAPA failed: {r.status_code}"
    capa = r.json()["capa"]
    print(f"   [OK] CAPA {capa['id']} ('{capa['title']}') - Stage: {capa['current_stage']}, Status: {capa['status']}")
    assert "eight_d" in capa, "Missing 8D structure"
    print(f"   [OK] 8D Structure present: D1 team ({len(capa['eight_d']['d1_team'])} members), D4 5-Whys ({len(capa['eight_d']['d4_root_cause_analysis'].get('five_whys', []))} whys)")

    # 8. Create 8D CAPA Case
    print("\n8. Testing POST /capa...")
    new_capa_payload = {
        "title": "B-Nut Coupling Micro-Fissures on High Pressure Fuel Manifold",
        "supplier_id": "TWIN-HYDRA-004",
        "supplier_name": "Vortex Flow Systems",
        "part_number": "VFS-BNUT-4482-Ti",
        "part_name": "Titanium Fuel Coupling B-Nut",
        "severity": "CRITICAL",
        "source": "INCOMING_RECEIVING_INSPECTION",
        "champion_name": "Elena Rostova (Lead Propulsion Auditor)",
        "supplier_rep": "Marco Rossi (Quality VP)",
        "risk_impact": "Fuel leak under 3,000 PSI test condition; flight hazard",
        "what": "12 of 85 couplings exhibited fluorescent penetrant indications (fissures > 25μm)",
        "where": "Receiving Inspection Bay 4, Dock C",
        "magnitude": "14.1% lot defect rate (Lot #VFS-2025-Q1-98)"
    }
    r = requests.post(f"{BASE}/capa", json=new_capa_payload)
    assert r.status_code == 200, f"Create CAPA failed: {r.status_code} {r.text}"
    new_capa_id = r.json()["capa"]["id"]
    print(f"   [OK] Created 8D CAPA: {new_capa_id}")

    # 9. Transition 8D Stage
    print(f"\n9. Testing POST /capa/{new_capa_id}/transition to D3 Containment...")
    r = requests.post(f"{BASE}/capa/{new_capa_id}/transition", json={
        "target_stage": "D3_CONTAINMENT",
        "actor": "Elena Rostova",
        "containment_actions": [
            "Lot #VFS-2025-Q1-98 placed under red tag physical quarantine",
            "Stop-ship notice issued to Vortex Flow facility",
            "100% Eddy Current non-destructive inspection initiated on all in-stock assemblies"
        ]
    })
    assert r.status_code == 200, f"Stage transition failed: {r.status_code} {r.text}"
    print(f"   [OK] CAPA transitioned to: {r.json()['capa']['current_stage']}, Status: {r.json()['capa']['status']}")

    # 10. Add CAPA Action
    print(f"\n10. Testing POST /capa/{new_capa_id}/action...")
    r = requests.post(f"{BASE}/capa/{new_capa_id}/action", json={
        "action_type": "INTERIM_CONTAINMENT",
        "action_description": "Supplier certified replacement batch dispatched via air priority with NADCAP NDT cert",
        "actor": "Marco Rossi"
    })
    assert r.status_code == 200, f"Add action failed: {r.status_code} {r.text}"
    print(f"   [OK] Action successfully appended to 8D report.")

    # 11. Training Modules
    print("\n11. Testing GET /training...")
    r = requests.get(f"{BASE}/training")
    assert r.status_code == 200, f"Get training failed: {r.status_code}"
    modules = r.json()["modules"]
    print(f"   [OK] Total Training Modules: {len(modules)}")

    # 12. Enroll in Training
    print(f"\n12. Testing POST /training/{modules[0]['id']}/enroll...")
    r = requests.post(f"{BASE}/training/{modules[0]['id']}/enroll?supplier_id=TWIN-APEX-001&supplier_name=Apex Precision Machining Ltd")
    assert r.status_code == 200, f"Enroll failed: {r.status_code} {r.text}"
    print(f"   [OK] Supplier enrolled! New count: {r.json()['module']['enrolled_suppliers']}")

    print("\nALL 12 SUPPLIER DEVELOPMENT & 8D CAPA TESTS PASSED SUCCESSFULLY! [100% OK]")

if __name__ == "__main__":
    try:
        run_tests()
    except Exception as e:
        print(f"\n[FAIL] Test encountered error: {e}")
        sys.exit(1)
