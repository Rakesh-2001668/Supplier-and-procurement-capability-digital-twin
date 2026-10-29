"""D3 construction demo tenant CON: WBS C-2207, subcontract SC-118, progress SES, retention, variation.

Deccan Skyline Constructions Pvt Ltd (fictional, Bengaluru, template CONSTRUCTION, BP §23) builds Tower B of a
residential project in Whitefield. Timeline Oct 2026 – Mar 2027, every document through the domain services:

  go-live   ERP budgets (WBS C-2207 hard stop), ERP vendor masters and twelve months of posted spend (Oct 2025 – Sep 2026)
  F8        three suppliers onboarded: rebar & formwork subcontractor, ready-mix concrete supplier, crane hire
            (ISO 45001 mandatory for civil subcontractors through a tenant SUPPLIER-QUAL version)
  F9        service masters for rebar (MT) and formwork (SQM), material master for RMC M40 (CUM)
  F4        subcontract SC-118 (value contract ≥ ₹1 Cr: legal, finance and CPO approval; supplier redlines the payment
            clause: retention released at completion against a performance bank guarantee)
  F2/F5     requisition on WBS C-2207 (hard budget check, four-step DMN-01 route) → subcontract PO with retention 5%
  F6/F7     running-account bills: measurement SES at 35%, 70% and 100% progress, each invoiced (SES match) with 5%
            retention withheld; RMC by goods receipt and 3-way match
  M07       variation order VO-01 (+15 MT podium transfer-girder reinforcement) as a contract amendment, then PO version 2
  F7        payment runs pay net of retention; at completion the retention is released and paid
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import Contract, ContractAmendment, Invoice, Material, PurchaseOrder
from app.pic.seed.axion import at
from app.pic.seed.datasets import _tenant_kit as kit

KEY = "industry-construction"
VERSION = "1"
TITLE = "D3 construction demo tenant CON: WBS C-2207, subcontract SC-118, progress SES, retention, variation"
TENANTS = ('CON',)
CREATES_TENANT = True
READY = True

NAME = "Deccan Skyline Constructions Pvt Ltd"
DOMAIN = "deccanskyline.example"
GSTIN = "29AAKCD4821M1Z7"          # Karnataka (29), PAN AAKCD4821M, check character verified
WBS = "C-2207"
SITE = "S201"
L = 100_000 * 100
NS = uuid.UUID("0c6f3d2e-5b1a-4f7e-9a2d-3e4f5a6b7c8d")
# Fixed-date holidays only (Gandhi Jayanti, Kannada Rajyotsava, Christmas, Republic Day). Festival dates that move with the
# lunar calendar (Deepavali, Ugadi, …) come from the Karnataka government gazette and are not invented here.
HOLIDAYS = [date(2026, 10, 2), date(2026, 11, 1), date(2026, 12, 25), date(2027, 1, 26)]

USERS = [
    ("admin", "Tenant Administrator", ["TENANT_ADMIN"], {}),
    ("site.engineer", "Raghavendra Hegde", ["REQUESTER"], {"cost_objects": [f"WBS:{WBS}", "WBS:C-2208", "COST_CENTER:5100"], "plants": [SITE]}),
    ("project.manager", "Shwetha Kulkarni", ["COST_OBJECT_OWNER"], {"cost_objects": [f"WBS:{WBS}", "WBS:C-2208", "COST_CENTER:5100"], "plants": [SITE]}),
    ("project.director", "Manjunath Gowda", ["DEPT_HEAD"], {"cost_objects": [f"WBS:{WBS}", "WBS:C-2208", "COST_CENTER:5100"], "plants": [SITE]}),
    ("buyer", "Pooja Shetty", ["BUYER"], {"plants": [SITE, "S202"]}),
    ("buyer.lead", "Vinay Rao", ["BUYER"], {"plants": [SITE, "S202"]}),
    ("category.manager", "Nandini Bhat", ["CATEGORY_MANAGER"], {"categories": ["*"]}),
    ("procurement.head", "Ashwin Prabhu", ["PROCUREMENT_HEAD"], {}),
    ("cpo", "Lakshmi Iyengar", ["CPO"], {}),
    ("finance.controller", "Girish Nayak", ["FINANCE_CONTROLLER"], {}),
    ("finance.controller2", "Kavya Murthy", ["FINANCE_CONTROLLER"], {}),
    ("legal", "Roopa Deshpande", ["LEGAL"], {}),
    ("contract.manager", "Sudhir Joshi", ["CONTRACT_MANAGER"], {}),
    ("contract.manager2", "Anitha Reddy", ["CONTRACT_MANAGER"], {}),
    ("supplier.manager", "Prakash Hosmani", ["SUPPLIER_MANAGER"], {"categories": ["*"]}),
    ("mdm.purchasing", "Deepak Kamath", ["MDM_STEWARD"], {"steward_domains": ["PURCHASING"]}),
    ("mdm.quality", "Sowmya Rao", ["MDM_STEWARD"], {"steward_domains": ["QUALITY"]}),
    ("mdm.finance", "Harish Pai", ["MDM_STEWARD"], {"steward_domains": ["FINANCE"]}),
    ("mdm.plant", "Mahesh Patil", ["MDM_STEWARD"], {"steward_domains": ["PLANT"]}),
    ("site.stores", "Basavaraj Angadi", ["RECEIVER"], {"plants": [SITE]}),
    ("quality.inspector", "Chaitra Naik", ["QUALITY_INSPECTOR"], {"plants": [SITE]}),
    ("quantity.surveyor", "Srinivas Murthy", ["SERVICE_OWNER"], {"cost_objects": [f"WBS:{WBS}", "WBS:C-2208"]}),
    ("ap.clerk", "Fathima Khanum", ["AP_CLERK"], {}),
]
ROLE_USER = {
    "COST_OBJECT_OWNER": "project.manager", "DEPT_HEAD": "project.director", "PROCUREMENT_HEAD": "procurement.head",
    "FINANCE_CONTROLLER": ["finance.controller", "finance.controller2"], "CATEGORY_MANAGER": "category.manager", "CPO": "cpo",
    "LEGAL": "legal", "CONTRACT_MANAGER": ["contract.manager", "contract.manager2"], "BUYER": ["buyer.lead", "buyer"],
    "SERVICE_OWNER": "quantity.surveyor", "MDM_STEWARD": ["mdm.purchasing", "mdm.quality", "mdm.finance", "mdm.plant"],
}

SUPPLIERS = [
    kit.SupplierSpec(
        code="SRF001", legal_name="Sahyadri Rebar & Formwork Contractors Pvt Ltd", gstin="29AAMCS7314K1ZS", ifsc="SBIN0040211",
        account="40211876543", terms="N30", categories=["CIVIL-SUBCONTRACT"], user_local="billing", segment="STRATEGIC",
        certificates=[{"type": "ISO45001", "number": "OHS-SRF-45-2291", "issued_on": "2025-02-10", "expires_on": "2028-02-09",
                       "mandatory_for": ["CIVIL-SUBCONTRACT"]},
                      {"type": "ISO9001", "number": "QMS-SRF-9-1182", "issued_on": "2024-08-01", "expires_on": "2027-07-31"}],
        scores=(84, 82), questionnaire={"labourLicence": "CLRA licence verified", "epfEsic": "registrations verified",
                                        "safety": "ISO 45001; site safety plan reviewed", "references": "two towers of 20+ floors"},
        address={"city": "Bengaluru", "state": "Karnataka", "pin": "560037"}),
    kit.SupplierSpec(
        code="TRM002", legal_name="Tungabhadra Ready Mix Concrete Pvt Ltd", gstin="29AAHCT5620N1ZT", ifsc="HDFC0001957",
        account="50200061234571", terms="N30", categories=["CONSTRUCTION-MATERIALS"], user_local="accounts",
        certificates=[{"type": "ISO9001", "number": "QMS-TRM-9-3307", "issued_on": "2025-06-01", "expires_on": "2028-05-31"}],
        scores=(80, 81), questionnaire={"plant": "batching plant at Hoskote, 18 km from site", "mixDesign": "M40 per IS 10262 on file",
                                        "transitMixers": "12"},
        address={"city": "Hoskote", "state": "Karnataka", "pin": "562114"}),
    kit.SupplierSpec(
        code="KEH003", legal_name="Kalyani Equipment Hire Pvt Ltd", gstin="29AAJCK2187P1ZO", ifsc="ICIC0006402",
        account="640205001873", terms="N45", categories=["EQUIPMENT-HIRE"], user_local="accounts",
        certificates=[{"type": "ISO9001", "number": "QMS-KEH-9-0771", "issued_on": "2025-01-15", "expires_on": "2028-01-14"}],
        scores=(78, 79), questionnaire={"fleet": "tower cranes 6, mobile cranes 4", "operators": "certified, third-party load tests"},
        address={"city": "Bengaluru", "state": "Karnataka", "pin": "560058"}),
]

ERP_VENDORS = [
    ("V-310011", "Hoskote Steel Traders Pvt Ltd", "N30", ["CONSTRUCTION-MATERIALS"]),
    ("V-310021", "Whitefield Shuttering Works", "N30", ["CIVIL-SUBCONTRACT"]),
    ("V-310031", "Sarjapur Crane Services", "N45", ["EQUIPMENT-HIRE"]),
]
HISTORY = [f"{y}-{m:02d}" for y, m in [(2025, 10), (2025, 11), (2025, 12), (2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5),
                                        (2026, 6), (2026, 7), (2026, 8), (2026, 9)]]

# BOQ of subcontract SC-118 (rates are the negotiated contract rates of this fictional subcontract).
REBAR = {"description": "Reinforcement steel Fe 550D – supply, cutting, bending and fixing", "uom": "MT", "qty": 120, "rate": 68_500_00}
FORMWORK = {"description": "Formwork for RCC slabs, beams, columns and shear walls – shuttering and de-shuttering", "uom": "SQM",
            "qty": 6_500, "rate": 660_00}
RMC = {"description": "Ready-mix concrete M40 grade, pumped, as per IS 4926", "uom": "CUM", "qty": 180, "rate": 6_150_00}
# Measured progress per running-account bill: (SES period, rebar MT, formwork SQM, cumulative progress)
PROGRESS = [
    ((date(2026, 11, 1), date(2026, 11, 30)), "42", "2275", "35%"),
    ((date(2026, 12, 1), date(2026, 12, 31)), "52.5", "2275", "70%"),
    ((date(2027, 1, 1), date(2027, 2, 25)), "40.5", "1950", "100%"),
]


def apply(tenant_code: str, password: str) -> dict:
    from app.pic.services import amendments, order, payables, receiving, requisition, spend
    from app.pic.services import contract as contract_svc

    sc = kit.setup_tenant(tenant_code, NAME, "CONSTRUCTION", company=("1000", NAME, GSTIN),
                          plants=[(SITE, "Tower B site – Whitefield, Bengaluru", "29"), ("S202", "Central stores – Hoskote", "29")],
                          cost_objects=[("WBS", "C-2206", "Tower A structure (completed Sep 2026)"), ("WBS", WBS, "Tower B structure"), ("WBS", "C-2208", "Tower B MEP and finishes"),
                                        ("COST_CENTER", "5100", "Project site office – Tower B")],
                          holidays=HOLIDAYS, domain=DOMAIN, role_user=ROLE_USER)
    notes, counts = [], {}
    kit.create_users(sc, USERS, password)
    kit.number_range(sc, "CONTRACT", "SC-", 118)
    kit.rule_version(sc, "SUPPLIER-QUAL", "2026.1-CON", date(2026, 10, 1),
                     {"mandatoryCertificates": {"CIVIL-SUBCONTRACT": ["ISO45001"]}, "minQuestionnaireScore": 70, "minAuditScore": 75,
                      "sampleApprovalRequired": [], "bankApprovers": 2, "coolingOffHours": 72},
                     "Construction: ISO 45001 (occupational health & safety) mandatory for civil subcontractors")
    kit.load_budgets(sc, [("WBS", WBS, "HARD", 350 * L), ("WBS", "C-2208", "HARD", 180 * L), ("COST_CENTER", "5100", "SOFT", 40 * L)],
                     at(date(2026, 10, 1), 9))
    vendors = kit.erp_vendors(sc, ERP_VENDORS, at(date(2026, 10, 1), 18))
    history = []
    for i, period in enumerate(HISTORY):
        wave = 1 + (i % 4) * 0.05
        history += [(period, "V-310011", "CONSTRUCTION-MATERIALS", SITE, "WBS:C-2206", int(38 * L * wave), i >= 3,
                     "TMT bars Fe 550D and binding wire – Tower A"),
                    (period, "V-310021", "CIVIL-SUBCONTRACT", SITE, "WBS:C-2206", int(26 * L * wave), True,
                     "Shuttering labour – Tower A slabs"),
                    (period, "V-310031", "EQUIPMENT-HIRE", SITE, "COST_CENTER:5100", int(7 * L * wave), i % 3 != 0,
                     "Tower crane hire with operator – Tower A")]
    counts["erpSpendLines"] = kit.spend_history(sc, history, vendors, at(date(2026, 10, 1), 19), NS, 5_105_300_000)
    notes.append(f"Go-live: budgets WBS {WBS} ₹3.5 Cr (hard), C-2208 ₹1.8 Cr (hard), CC 5100 ₹40 L (soft); "
                 f"{len(ERP_VENDORS)} ERP vendors, {counts['erpSpendLines']} spend lines {HISTORY[0]} – {HISTORY[-1]}")

    # ------------------------------------------------------------ F8 onboarding
    suppliers = {}
    for spec, day in zip(SUPPLIERS, (date(2026, 10, 5), date(2026, 10, 7), date(2026, 10, 9))):
        suppliers[spec.code] = kit.onboard(sc, spec, password, day)
        notes.append(f"F8 {spec.code} {spec.legal_name}: bank dual-approved, {kit.category_status(sc, suppliers[spec.code])}")
    srf, trm = SUPPLIERS[0], SUPPLIERS[1]

    # ------------------------------------------------------------ F9 service and material masters
    masters = {
        "rebar": kit.service_master(sc, "buyer", at(date(2026, 10, 12), 10), description=REBAR["description"], type_="SERVICE",
                                    group="CIVIL-RCC", category="CIVIL-SUBCONTRACT", uom="MT", hsn="995454",
                                    attributes={"grade": "Fe 550D", "standard": "IS 1786", "scope": "supply+cut+bend+fix"}),
        "formwork": kit.service_master(sc, "buyer", at(date(2026, 10, 12), 11), description=FORMWORK["description"], type_="SERVICE",
                                       group="CIVIL-RCC", category="CIVIL-SUBCONTRACT", uom="SQM", hsn="995454",
                                       attributes={"system": "plywood + steel props", "measurement": "contact area"}),
        "rmc": kit.service_master(sc, "buyer", at(date(2026, 10, 12), 12), description=RMC["description"], type_="NON_STOCK",
                                  group="RMC", category="CONSTRUCTION-MATERIALS", uom="CUM", hsn="38245010",
                                  attributes={"grade": "M40", "standard": "IS 4926", "placement": "pumped"}),
    }
    notes.append(f"F9 masters: rebar {masters['rebar']} (MT, SAC 995454), formwork {masters['formwork']} (SQM, SAC 995454), "
                 f"RMC M40 {masters['rmc']} (CUM, HSN 38245010)")
    with tenant_tx(sc.tenant_id) as s:
        mat = {k: s.execute(select(Material).where(Material.number == v)).scalar_one().id for k, v in masters.items()}

    # ------------------------------------------------------------ F4 subcontract SC-118
    with sc.act("contract.manager", at(date(2026, 10, 15), 10)) as s:
        c = contract_svc.create_draft(
            s, type="VALUE_CONTRACT", title="SC-118 Rebar & formwork – Tower B structure (WBS C-2207)", supplier_id=suppliers["SRF001"],
            company_code="1000", valid_from=date(2026, 11, 1), valid_to=date(2027, 6, 30), payment_terms="N30", incoterms=None,
            lines=[{"material_id": mat["rebar"], "description": REBAR["description"], "plant": SITE, "uom": "MT", "target_qty": REBAR["qty"],
                    "unit_price_minor": REBAR["rate"]},
                   {"material_id": mat["formwork"], "description": FORMWORK["description"], "plant": SITE, "uom": "SQM",
                    "target_qty": FORMWORK["qty"], "unit_price_minor": FORMWORK["rate"]}],
            owner_id=s.info["principal"].user_id, tolerances={})
        contract_svc.ai_review(s, c)
        sc118_id, sc118 = c.id, c.number
    with sc.act(kit.supplier_email(srf), at(date(2026, 10, 16), 11)) as s:
        contract_svc.redline(s, s.get(Contract, sc118_id), "PAYMENT",
                             "Payment N30 from receipt of a correct running-account bill and the approved measurement sheet. 5% retention "
                             "is withheld from every bill and released in full on the completion certificate against a performance bank "
                             "guarantee of 5% of the contract value valid for the 12-month defect-liability period.", "FALLBACK")
    with sc.act("contract.manager", at(date(2026, 10, 16), 15)) as s:
        # The supplier's redline waits for the contract manager: retention against a PBG is the playbook fallback position.
        contract_svc.review_redline(s, s.get(Contract, sc118_id), "PAYMENT", "ACCEPT", "FALLBACK",
                                    "Retention released against a 5% PBG is the approved fallback for subcontracts")
        chain = contract_svc.submit(s, s.get(Contract, sc118_id))["chain"]
    sc.approve_all(sc118_id, at(date(2026, 10, 19), 11), "Subcontract terms, retention and PBG approved")
    with sc.act("contract.manager", at(date(2026, 10, 20), 10)) as s:
        contract_svc.sign(s, s.get(Contract, sc118_id), "BUYER", "Sudhir Joshi, Contract Manager")
    with sc.act(kit.supplier_email(srf), at(date(2026, 10, 20), 12)) as s:
        contract_svc.sign(s, s.get(Contract, sc118_id), "SUPPLIER", "Authorised signatory, Sahyadri Rebar & Formwork")
    with sc.act("contract.manager", at(date(2026, 10, 20), 15)) as s:
        contract_svc.activate(s, s.get(Contract, sc118_id))
    kit.relay(sc, at(date(2026, 10, 20), 16))
    notes.append(f"F4 {sc118} {kit.fmt(REBAR['qty'] * REBAR['rate'] + FORMWORK['qty'] * FORMWORK['rate'])}: payment clause redlined "
                 f"(retention against PBG, FALLBACK) → approvals {' → '.join(chain)} → signed → active")

    # ------------------------------------------------------------ F2 requisition on WBS C-2207 → F5 subcontract PO with 5% retention
    with sc.act("site.engineer", at(date(2026, 10, 26), 10)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="PROJECT_EXECUTION", purpose_text="Tower B superstructure – rebar and formwork",
                                plant=SITE, lines=[
                                    {"item_type": "MATERIAL", "purchase_type": "SERVICE", "material": masters["rebar"], "qty": str(REBAR["qty"]),
                                     "price_est_minor": REBAR["rate"], "account_assignment_type": "WBS", "account_assignment_code": WBS,
                                     "need_date": "2027-03-31"},
                                    {"item_type": "MATERIAL", "purchase_type": "SERVICE", "material": masters["formwork"], "qty": str(FORMWORK["qty"]),
                                     "price_est_minor": FORMWORK["rate"], "account_assignment_type": "WBS", "account_assignment_code": WBS,
                                     "need_date": "2027-03-31"}])
        submitted = requisition.submit(s, pr)
        pr_id, pr_no, budget = pr.id, pr.number, pr.budget_result["checks"][0]
    sc.approve_all(pr_id, at(date(2026, 10, 27), 11), f"Within WBS {WBS} budget; subcontract SC-118 rates")
    kit.relay(sc, at(date(2026, 10, 27), 12))
    with sc.act("buyer", at(date(2026, 10, 28), 10)) as s:
        po = order.create_from_requisition(s, requisition=pr_no, lines=[10, 20], contract_ref=sc118, retention_pct=Decimal(5))[0]
        po_id, po_no = po.id, po.number
    sc.approve_all(po_id, at(date(2026, 10, 28), 15), "Subcontract order against SC-118, retention 5%")
    kit.relay(sc, at(date(2026, 10, 28), 16))
    with sc.act(kit.supplier_email(srf), at(date(2026, 10, 29), 11)) as s:
        order.confirm(s, s.get(PurchaseOrder, po_id), "CONFIRMED", note="Mobilisation 1 Nov 2026; bar-bending yard set up at site")
    notes.append(f"F2 {pr_no} on WBS {WBS}: hard budget check {budget['result']} ({kit.fmt(budget['amountMinor'])} of "
                 f"{kit.fmt(budget['availableMinor'])} available), route {' → '.join(submitted['chain'])} → F5 {po_no} subcontract order, "
                 "retention 5%, approved and confirmed")

    # ------------------------------------------------------------ RMC: F5 PO → F6 goods receipt → F7 3-way match
    with sc.act("site.engineer", at(date(2026, 11, 2), 10)) as s:
        rmc_pr = requisition.create(s, origin="MANUAL", purpose_code="PROJECT_EXECUTION", purpose_text="Tower B podium slab pour",
                                    plant=SITE, lines=[{"item_type": "MATERIAL", "purchase_type": "NON_STOCK", "material": masters["rmc"],
                                                        "qty": str(RMC["qty"]), "price_est_minor": RMC["rate"], "account_assignment_type": "WBS",
                                                        "account_assignment_code": WBS, "need_date": "2026-11-20"}])
        requisition.submit(s, rmc_pr)
        rmc_pr_id, rmc_pr_no = rmc_pr.id, rmc_pr.number
    sc.approve_all(rmc_pr_id, at(date(2026, 11, 2), 15), "Podium slab pour as per the pour schedule")
    with sc.act("buyer", at(date(2026, 11, 3), 10)) as s:
        rmc_po = order.create_from_requisition(s, requisition=rmc_pr_no, lines=[10], supplier_code="TRM002", unit_price_minor=RMC["rate"])[0]
        rmc_po_id, rmc_po_no = rmc_po.id, rmc_po.number
    sc.approve_all(rmc_po_id, at(date(2026, 11, 3), 15), "Rate as per TRM quotation Q-TRM-2611-07")
    kit.relay(sc, at(date(2026, 11, 3), 16))
    with sc.act(kit.supplier_email(trm), at(date(2026, 11, 4), 10)) as s:
        order.confirm(s, s.get(PurchaseOrder, rmc_po_id), "CONFIRMED", note="Pour slot 20 Nov 2026, 06:00; two boom pumps")
    with sc.act("site.stores", at(date(2026, 11, 20), 16)) as s:
        gr = receiving.post_gr(s, s.get(PurchaseOrder, rmc_po_id), lines=[{"line": 10, "qty": str(RMC["qty"])}],
                               delivery_note="TRM challans DC-81144 to DC-81173", posting_date=date(2026, 11, 20))
        gr_no = gr.number
    kit.relay(sc, at(date(2026, 11, 20), 17))
    with sc.act(kit.supplier_email(trm), at(date(2026, 11, 21), 11)) as s:
        inv = payables.capture(s, supplier="TRM002", supplier_invoice_no="TRM/2627/0412", invoice_date=date(2026, 11, 21), channel="E_INVOICE",
                               irn=payables.expected_irn(trm.gstin, "2026-27", "INV", "TRM/2627/0412"),
                               lines=[{"po": rmc_po_no, "po_line": 10, "qty": str(RMC["qty"]), "unit_price": str(RMC["rate"] / 100),
                                       "gst_rate": "18", "hsn": "38245010"}])
        rmc_inv_id = inv.id
    _approve_post(sc, payables, rmc_inv_id, at(date(2026, 11, 23), 11))
    notes.append(f"RMC: {rmc_pr_no} → {rmc_po_no} (180 CUM M40 @ ₹6,150) → {gr_no} → TRM/2627/0412 3-way matched and posted")

    # ------------------------------------------------------------ running-account bills with retention, variation order
    bills = []
    for index, ((period_from, period_to), rebar_qty, formwork_qty, progress) in enumerate(PROGRESS, start=1):
        if index == 2:
            _variation(sc, amendments, order, sc118_id, po_id)
        ses_day = date(2026, 12, 5) if index == 1 else date(2027, 1, 5) if index == 2 else date(2027, 2, 25)
        with sc.act(kit.supplier_email(srf), at(ses_day, 17)) as s:
            ses = receiving.create_ses(s, s.get(PurchaseOrder, po_id), method="PROGRESS", period_from=period_from, period_to=period_to,
                                       lines=[{"line": 10, "description": f"RA-{index:02d} rebar measured {rebar_qty} MT (cumulative {progress})",
                                               "qty": rebar_qty, "unit_rate": str(REBAR["rate"] / 100)},
                                              {"line": 20, "description": f"RA-{index:02d} formwork measured {formwork_qty} SQM (cumulative {progress})",
                                               "qty": formwork_qty, "unit_rate": str(FORMWORK["rate"] / 100)}])
            receiving.submit_ses(s, ses)
            ses_id, ses_no = ses.id, ses.number
        sc.approve_all(ses_id, at(ses_day + kit.days(2), 11), f"Joint measurement RA-{index:02d} checked against drawings; {progress} complete")
        kit.relay(sc, at(ses_day + kit.days(2), 12))
        bill_no = f"SRF/RA/2026-27/{index:02d}"
        bill_day = ses_day + kit.days(3)
        with sc.act(kit.supplier_email(srf), at(bill_day, 11)) as s:
            inv = payables.capture(s, supplier="SRF001", supplier_invoice_no=bill_no, invoice_date=bill_day, channel="E_INVOICE",
                                   irn=payables.expected_irn(srf.gstin, "2026-27", "INV", bill_no),
                                   lines=[{"po": po_no, "po_line": 10, "qty": rebar_qty, "unit_price": str(REBAR["rate"] / 100), "gst_rate": "18",
                                           "hsn": "995454", "description": f"RA-{index:02d} rebar {rebar_qty} MT"},
                                          {"po": po_no, "po_line": 20, "qty": formwork_qty, "unit_price": str(FORMWORK["rate"] / 100),
                                           "gst_rate": "18", "hsn": "995454", "description": f"RA-{index:02d} formwork {formwork_qty} SQM"}])
            inv_id = inv.id
        _approve_post(sc, payables, inv_id, at(bill_day + kit.days(1), 11))
        with tenant_tx(sc.tenant_id) as s:
            inv = s.get(Invoice, inv_id)
            bills.append({"bill": bill_no, "ses": ses_no, "progress": progress, "status": inv.status, "netMinor": inv.net_minor,
                          "grossMinor": inv.gross_minor, "retentionMinor": inv.retention_minor})
        notes.append(f"RA-{index:02d}: {ses_no} ({progress}) approved → {bill_no} SES-matched, net {kit.fmt(bills[-1]['netMinor'])}, "
                     f"retention withheld {kit.fmt(bills[-1]['retentionMinor'])}")
        if index == 1:
            _pay(sc, payables, at(date(2027, 1, 12), 10), notes)
        if index == 2:
            _pay(sc, payables, at(date(2027, 2, 10), 10), notes)

    # ------------------------------------------------------------ completion → retention release → payment
    with sc.act("ap.clerk", at(date(2027, 3, 20), 11)) as s:
        po = s.get(PurchaseOrder, po_id)
        before = payables.retention_position(s, po)
        release = payables.release_retention(
            s, po, reference="Completion certificate TB-STR-CC-01 of 15-03-2027; PBG SBIN/PBG/2027/0318 (5%, valid to 14-03-2028)",
            reason="Tower B structure complete; retention released against the performance bank guarantee for the defect-liability period",
            release_date=date(2027, 3, 20))
        release_no, release_minor = release.number, release.gross_minor
    notes.append(f"Completion: {release_no} releases {kit.fmt(release_minor)} retention withheld on RA-01..03 ({before['withheldMinor']} paise)")
    _pay(sc, payables, at(date(2027, 3, 31), 10), notes)

    with sc.act("category.manager", at(date(2027, 3, 31), 15)) as s:
        refreshed = spend.refresh(s, sc.tenant_id)
    kit.relay(sc, at(date(2027, 3, 31), 16))
    counts.update({"suppliers": len(SUPPLIERS), "masters": len(masters), "contracts": 1, "purchaseOrders": 2, "serviceEntries": len(PROGRESS),
                   "invoices": len(bills) + 1, "retentionReleases": 1, "spendRefresh": refreshed})
    return {"notes": notes, "counts": counts, "subcontract": sc118, "po": po_no, "bills": bills, "retentionRelease": release_no}


def _approve_post(sc, payables, invoice_id, when) -> None:
    with sc.act("ap.clerk", when) as s:
        inv = s.get(Invoice, invoice_id)
        if inv.status != "MATCHED":
            raise RuntimeError(f"{inv.number} is {inv.status}, expected MATCHED")
        payables.approve(s, inv)
        payables.post(s, inv, payables.posting_key(s, inv))
    kit.relay(sc, when.replace(minute=30))


def _pay(sc, payables, when, notes) -> None:
    with sc.act("finance.controller", when) as s:
        run = payables.payment_run(s, when.date())
    kit.relay(sc, when.replace(minute=30))
    notes.append(f"Payment run {run['run']} ({when.date().isoformat()}): " + (", ".join(f"{p['invoice']} {kit.fmt(p['amountMinor'])}" for p in run["paid"])
                                                                           or "nothing due") +
                 (f"; skipped {run['skipped']}" if run["skipped"] else ""))


def _variation(sc, amendments, order, contract_id, po_id) -> None:
    """VO-01: structural revision R3 adds podium transfer-girder reinforcement: contract amendment first, then PO version 2."""
    with sc.act("contract.manager", at(date(2026, 12, 15), 10)) as s:
        amendment = amendments.create(s, s.get(Contract, contract_id), kind="VARIATION",
                                      changes={"lines": [{"line": 10, "targetQty": str(REBAR["qty"] + 15)}]},
                                      reason="VO-01: structural consultant revision R3 – additional transfer-girder reinforcement at podium level "
                                             "(+15 MT at the contract rate)", effective_from=date(2026, 12, 15))
        amendment_id = amendment.id
    sc.approve_all(contract_id, at(date(2026, 12, 15), 15), "VO-01 checked against revision R3 bar-bending schedule")
    with tenant_tx(sc.tenant_id) as s:
        if s.get(ContractAmendment, amendment_id).status != "EFFECTIVE":
            raise RuntimeError("VO-01 did not become effective")
    with sc.act("buyer", at(date(2026, 12, 16), 10)) as s:
        po = s.get(PurchaseOrder, po_id)
        number = s.get(ContractAmendment, amendment_id).number
        order.change_order(s, po, [{"line": 10, "qty": str(REBAR["qty"] + 15)}], reason=f"VO-01 ({number}): +15 MT rebar, revision R3")
    kit.relay(sc, at(date(2026, 12, 16), 11))
    with sc.act(kit.supplier_email(SUPPLIERS[0]), at(date(2026, 12, 17), 10)) as s:
        order.confirm(s, s.get(PurchaseOrder, po_id), "CONFIRMED", note="VO-01 accepted at the contract rate")
