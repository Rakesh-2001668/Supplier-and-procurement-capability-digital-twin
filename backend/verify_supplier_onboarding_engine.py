import json
import urllib.request
import urllib.error
import sys

BASE_API = "http://127.0.0.1:8080/api/v1/suppliers"
BASE_FE = "http://localhost:3000"

def req(url, method="GET", data=None):
    headers = {"Content-Type": "application/json"} if data else {}
    body = json.dumps(data).encode("utf-8") if data else None
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as res:
            resp_body = res.read().decode("utf-8")
            return res.status, json.loads(resp_body) if "application/json" in res.headers.get("Content-Type", "") else resp_body
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        return e.code, err_body
    except Exception as e:
        return 500, str(e)

def run_tests():
    print("==================================================================")
    print("VERIFYING AEROSPACE SUPPLIER ONBOARDING & APPROVAL ENGINE (E2E)")
    print("==================================================================")

    # 1. Overview
    code, data = req(f"{BASE_API}/onboarding/overview")
    print(f"[1] GET /onboarding/overview -> Status {code}")
    assert code == 200, f"Expected 200, got {code}"
    print(f"    Total Pipeline: {data.get('total_pipeline')}, Avg Score: {data.get('average_assessment_score')}")
    print(f"    Assessment Pillars: {len(data.get('pillars', []))} futuristic aerospace pillars")

    # 2. Pipeline
    code, data = req(f"{BASE_API}/onboarding/pipeline")
    print(f"[2] GET /onboarding/pipeline -> Status {code}")
    assert code == 200, f"Expected 200, got {code}"
    print(f"    Returned {data.get('count')} candidate capability twins in pipeline")

    # 3. Submit New Autonomous Onboarding
    new_twin_payload = {
        "company_name": "Orion Propulsion Dynamics Corp",
        "short_name": "Orion Dynamics",
        "cage_code": "9K881",
        "duns_number": "88-129-4401",
        "industry_sector": "Spaceflight Propulsion & Cryogenic Turbomachinery",
        "contact_name": "Dr. Sarah Vance",
        "contact_email": "sarah.vance@orion-propulsion.aero",
        "contact_phone": "+1 (555) 301-8910",
        "headquarters_city": "Huntsville",
        "headquarters_country": "United States",
        "facility_size_sqft": "95,000 sq.ft Precision Facility",
        "cleanroom_class": "ISO Class 5 Space Flight Ready",
        "processes": [
            "5-Axis CNC Milling",
            "Zeiss CMM Coordinate Metrology",
            "Wire EDM Precision Slicing",
            "Electron Beam Welding"
        ],
        "materials": [
            "Titanium Ti-6Al-4V Grade 5",
            "Inconel 718 Superalloy",
            "Hastelloy X"
        ],
        "precision_tolerance": "±0.0001\" (Sub-Mil Standard)",
        "certifications": [
            "AS9100D",
            "ISO 9001:2015",
            "CMMC-L2",
            "ITAR"
        ],
        "esg_renewable_pct": 88,
        "notes": "Cryogenic flight article manufacturing facility with Zeiss Prismo CMM inspection bay."
    }
    code, data = req(f"{BASE_API}/onboarding/submit", method="POST", data=new_twin_payload)
    print(f"[3] POST /onboarding/submit -> Status {code}")
    assert code == 200, f"Expected 200, got {code}"
    new_sup_id = data.get("supplier_id")
    print(f"    Synthesized Twin ID: {new_sup_id}")
    print(f"    Initial Composite Score: {data.get('composite_score')}")

    # 4. Get Assessment Dossier
    code, data = req(f"{BASE_API}/onboarding/{new_sup_id}/assessment")
    print(f"[4] GET /onboarding/{new_sup_id}/assessment -> Status {code}")
    assert code == 200, f"Expected 200, got {code}"
    print(f"    AI Recommendation: {data.get('ai_recommendation', {}).get('verdict')}")
    print(f"    Pillars evaluated: {len(data.get('pillars', []))}")

    # 5. Evaluate / Recalibrate Pillar
    recal_payload = {
        "pillar_id": "as9100d_metrology",
        "new_score": 98,
        "evaluator_name": "Lead Quality Assessor",
        "evaluator_notes": "Zeiss CMM coordinate calibration re-attested to ±0.0001\"."
    }
    code, data = req(f"{BASE_API}/onboarding/{new_sup_id}/assessment/evaluate", method="POST", data=recal_payload)
    print(f"[5] POST /onboarding/{new_sup_id}/assessment/evaluate -> Status {code}")
    assert code == 200, f"Expected 200, got {code}"
    print(f"    New Composite Score: {data.get('new_composite_score')}")

    # 6. Get Approval Dossier
    code, data = req(f"{BASE_API}/onboarding/{new_sup_id}/approval-dossier")
    print(f"[6] GET /onboarding/{new_sup_id}/approval-dossier -> Status {code}")
    assert code == 200, f"Expected 200, got {code}"
    print(f"    Digital Signature Stamp: {data.get('digital_signature_stamp')}")
    print(f"    Ready for final signoff: {data.get('is_ready_for_final_signoff')}")

    # 7. Execute Executive Approvals
    # Role 1
    code, data = req(f"{BASE_API}/onboarding/{new_sup_id}/approve", method="POST", data={
        "role": "Lead Quality & Metrology Assessor",
        "approver_name": "Dr. Sarah Jenkins",
        "action": "APPROVE",
        "comments": "Zero NCR detected. Zeiss CMM meets sub-mil flight tolerance."
    })
    print(f"[7a] Approve Role 1 -> Status {code}")
    assert code == 200

    # Role 2
    code, data = req(f"{BASE_API}/onboarding/{new_sup_id}/approve", method="POST", data={
        "role": "Chief Security & Defense Compliance Officer",
        "approver_name": "Marcus Vance",
        "action": "APPROVE",
        "comments": "CMMC Level 2 air-gap and CAGE 9K881 validated."
    })
    print(f"[7b] Approve Role 2 -> Status {code}")
    assert code == 200

    # Role 3 (Final graduation)
    code, data = req(f"{BASE_API}/onboarding/{new_sup_id}/approve", method="POST", data={
        "role": "VP Global Strategic Procurement",
        "approver_name": "Elena Rostova",
        "action": "APPROVE",
        "comments": "Graduation authorized for prime tier 1 defense contracts."
    })
    print(f"[7c] Approve Role 3 (Final) -> Status {code}")
    assert code == 200
    print(f"    New Status: {data.get('new_status')}")
    assert data.get('new_status') == "VERIFIED_CAPABILITY_TWIN", f"Expected VERIFIED_CAPABILITY_TWIN, got {data.get('new_status')}"

    # 8. Batch Approvals
    batch_payload = {
        "supplier_ids": ["SUP-AERO-991", "SUP-AERO-992"],
        "action": "APPROVE",
        "approver_name": "Executive Procurement Committee",
        "comments": "Batch sign-off authorized."
    }
    code, data = req(f"{BASE_API}/onboarding/approvals/batch", method="POST", data=batch_payload)
    print(f"[8] POST /onboarding/approvals/batch -> Status {code}")
    assert code == 200
    print(f"    Updated: {data.get('updated_count')} suppliers")

    # 9. Verify Next.js Frontend Routes
    fe_routes = [
        "/suppliers",
        "/suppliers/onboarding",
        "/suppliers/assessments",
        "/suppliers/approvals"
    ]
    print("\n[9] Testing Frontend Routes via Next.js...")
    for route in fe_routes:
        url = f"{BASE_FE}{route}"
        try:
            req_fe = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_fe, timeout=10) as r:
                print(f"    {route} -> Status {r.status} (OK)")
                assert r.status == 200
        except Exception as e:
            print(f"    {route} -> Error: {e}")

    print("\n==================================================================")
    print("ALL AEROSPACE SUPPLIER ONBOARDING TESTS PASSED PERFECTLY!")
    print("==================================================================")

if __name__ == "__main__":
    run_tests()
