"""
Verification Suite: AlphaHelion Industry Template Packs
Blueprint Reference: Section 23, Tables 22 & 23, Delivery Roadmap Phase 4

Tests the 6 Industry Configuration Packs:
1. Manufacturing & Industrial
2. Construction & Projects (BOQ / WBS / 5% Retention)
3. IT & Professional Services (SOW / Rate Card / Timesheet SES)
4. Logistics & Transportation (Lane Rate / Diesel Fuel Index / e-POD)
5. Healthcare & Life Sciences (Consignment / Cold-Chain / Recall Traceability)
6. General Enterprise (Indirect Punch-Out / P-Card / 2-Way Match)
"""

import requests
import json
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://127.0.0.1:8080/api/v1/industry-templates"

def test_industry_templates():
    print("="*70)
    print("Testing AlphaHelion Industry Template Packs (Blueprint Section 23)")
    print("="*70)

    # 1. Test List Templates
    print("\n1. Testing GET /industry-templates (Listing All 6 Industry Packs)...")
    r = requests.get(BASE_URL)
    assert r.status_code == 200, f"Failed listing templates: {r.status_code} {r.text}"
    templates = r.json()
    assert len(templates) == 6, f"Expected 6 industry templates, got {len(templates)}"
    
    expected_ids = ["MANUFACTURING", "CONSTRUCTION", "IT_SERVICES", "LOGISTICS", "HEALTHCARE", "GENERAL_ENTERPRISE"]
    found_ids = [t["id"] for t in templates]
    for exp in expected_ids:
        assert exp in found_ids, f"Missing expected template {exp}"
    print(f"   [OK] Loaded {len(templates)} Industry Templates: {[t['name'] for t in templates]}")

    # 2. Test Active Template
    print("\n2. Testing GET /industry-templates/active...")
    r = requests.get(f"{BASE_URL}/active")
    assert r.status_code == 200, f"Failed getting active template: {r.status_code}"
    active_data = r.json()
    assert active_data["status"] == "success"
    print(f"   [OK] Current Active Template: {active_data['active_template']['name']} ({active_data['active_template']['tenant_name']})")

    # 3. Test Detail Inspection for Construction (BOQ, WBS, 5% Retention)
    print("\n3. Testing GET /industry-templates/CONSTRUCTION (WBS / BOQ / 5% Retention)...")
    r = requests.get(f"{BASE_URL}/CONSTRUCTION")
    assert r.status_code == 200, f"Failed getting construction detail: {r.status_code}"
    const_data = r.json()["template"]
    assert "WBS" in const_data["nuance_description"]
    assert "5% retention" in const_data["match_rule"]
    assert const_data["sample_document"]["retention_pct"] == 5.0
    print(f"   [OK] Construction Nuance: {const_data['nuance_description']}")
    print(f"   [OK] Sample Document: {const_data['sample_document']['doc_id']} for {const_data['sample_document']['trade']}")
    print(f"   [OK] Special Controls: {const_data['special_controls']}")

    # 4. Test Detail Inspection for IT Services (SOW, Rate Card RC-22, Timesheet SES)
    print("\n4. Testing GET /industry-templates/IT_SERVICES (SOW / Rate Card / Auto-Renewal)...")
    r = requests.get(f"{BASE_URL}/IT_SERVICES")
    assert r.status_code == 200
    it_data = r.json()["template"]
    assert "RC-22" in it_data["sample_document"]["rate_card_ref"]
    assert it_data["sample_document"]["approved_hours"] == 320
    print(f"   [OK] IT Services Engagement: {it_data['sample_document']['engagement']}")
    print(f"   [OK] Blended Rate: ₹{it_data['sample_document']['blended_hourly_rate']}/hr, Hours: {it_data['sample_document']['approved_hours']}")

    # 5. Test Detail Inspection for Logistics (Lane CHE->PNQ, Diesel Fuel Surcharge, e-POD)
    print("\n5. Testing GET /industry-templates/LOGISTICS (Lane CHE->PNQ / Fuel Index / e-POD)...")
    r = requests.get(f"{BASE_URL}/LOGISTICS")
    assert r.status_code == 200
    log_data = r.json()["template"]
    assert log_data["sample_document"]["distance_km"] == 1150
    assert log_data["sample_document"]["base_rate_per_km"] == 54.0
    print(f"   [OK] Logistics Lane: {log_data['sample_document']['origin']} -> {log_data['sample_document']['destination']} ({log_data['sample_document']['distance_km']} km)")
    print(f"   [OK] Match Rule: {log_data['match_rule']}")

    # 6. Test Detail Inspection for Healthcare (Cold-chain 2-8°C, KN-77 Consignment, CDSCO)
    print("\n6. Testing GET /industry-templates/HEALTHCARE (Consignment KN-77 / Cold-chain / Recall)...")
    r = requests.get(f"{BASE_URL}/HEALTHCARE")
    assert r.status_code == 200
    health_data = r.json()["template"]
    assert health_data["sample_document"]["temp_range_celsius"] == "2°C - 8°C"
    assert health_data["sample_document"]["billing_trigger"] == "PATIENT_IMPLANTATION"
    print(f"   [OK] Healthcare Device: {health_data['sample_document']['device']}")
    print(f"   [OK] Cold-Chain Range: {health_data['sample_document']['temp_range_celsius']}, Trigger: {health_data['sample_document']['billing_trigger']}")

    # 7. Test Detail Inspection for General Enterprise (cXML Punch-Out, P-Card, 2-Way Match)
    print("\n7. Testing GET /industry-templates/GENERAL_ENTERPRISE (cXML Punchout / 2-Way Match)...")
    r = requests.get(f"{BASE_URL}/GENERAL_ENTERPRISE")
    assert r.status_code == 200
    gen_data = r.json()["template"]
    assert "cXML" in gen_data["sample_document"]["punchout_protocol"]
    assert gen_data["sample_document"]["match_tolerance"] == "2-WAY_AUTO_CLEAR"
    print(f"   [OK] Enterprise Item: {gen_data['sample_document']['item_description']} (₹{gen_data['sample_document']['negotiated_price']})")

    # 8. Test Template Switch to CONSTRUCTION
    print("\n8. Testing POST /industry-templates/switch to 'CONSTRUCTION'...")
    switch_payload = {
        "template_id": "CONSTRUCTION",
        "actor": "Chief Procurement Officer",
        "notes": "Activating Construction & Projects Template for Kempegowda Terminal 3 Project"
    }
    r = requests.post(f"{BASE_URL}/switch", json=switch_payload)
    assert r.status_code == 200, f"Switch failed: {r.status_code} {r.text}"
    switch_res = r.json()
    assert switch_res["active_template_id"] == "CONSTRUCTION"
    assert "Apex Infra" in switch_res["tenant_name"]
    print(f"   [OK] Activated: {switch_res['tenant_name']} (Tenant ID: {switch_res['tenant_id']})")
    print(f"   [OK] Reconfigured Modules: {switch_res['reconfigured_modules']}")

    # Verify active endpoint reflects the switch
    r_check = requests.get(f"{BASE_URL}/active")
    assert r_check.json()["active_template"]["id"] == "CONSTRUCTION"
    print("   [OK] Active endpoint verified as CONSTRUCTION.")

    # 9. Test Switch Back to MANUFACTURING (Axion Baseline)
    print("\n9. Testing POST /industry-templates/switch back to 'MANUFACTURING' (Axion Baseline)...")
    r_restore = requests.post(f"{BASE_URL}/switch", json={"template_id": "MANUFACTURING", "actor": "Chief Procurement Officer"})
    assert r_restore.status_code == 200
    assert r_restore.json()["active_template_id"] == "MANUFACTURING"
    print("   [OK] Restored active template to Manufacturing & Industrial (Axion Mobility Systems).")

    print("\n" + "="*70)
    print("ALL 9 INDUSTRY TEMPLATE PACK TESTS PASSED WITH 100% SUCCESS! [OK]")
    print("="*70)

if __name__ == "__main__":
    try:
        test_industry_templates()
    except Exception as e:
        print(f"\n[FAIL] Test encountered error: {e}")
        sys.exit(1)
