"""D4 IT services demo tenant ITS: SOW-4410 T&M, rate card RC-22, timesheet SES, licence renewal.

Indrayani Digital Services Pvt Ltd (fictional, Pune, template IT_SERVICES, BP §23) moves its data-centre workloads to
the cloud with a time-and-material partner and renews its observability-platform subscription. Timeline Oct 2026 –
Mar 2027, every document through the domain services:

  go-live   ERP budgets (cost centres 6100 cloud platform, 6200 enterprise applications), ERP vendor masters and twelve
            months of posted spend (Oct 2025 – Sep 2026)
  F8        three suppliers onboarded; ISO 27001 mandatory for IT services through a tenant SUPPLIER-QUAL version
            (InfoSec and data-privacy assessment in the questionnaire)
  F9        rate-card roles as service masters (day and hour rates, SAC 998313) and the subscription (SAC 997331)
  F4        licence contract LIC-2601 (term to 31 Mar 2027) and SOW-4410 cloud migration T&M whose lines are rate card
            RC-22 (five roles × day/hour rate); supplier redlines the RATES clause to reference RC-22
  F2/F5/F6  licence requisition → contract-priced PO → licence entitlement receipt → 3-way invoice
            SOW requisition → PO against SOW-4410 → November timesheet SES of 320 hours → invoice matched to the SES
  F4        renewal alert 90 days before expiry (IT template renewalNoticeDays) → renewal decision → extension amendment
            to 31 Mar 2028, approved by the second contract manager
  F7        payment runs
"""
import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import Contract, ContractAmendment, Invoice, Material, PurchaseOrder, Supplier, Task
from app.pic.platform import workflow
from app.pic.seed.axion import at
from app.pic.seed.datasets import _tenant_kit as kit

KEY = "industry-it-services"
VERSION = "1"
TITLE = "D4 IT services demo tenant ITS: SOW-4410 T&M, rate card RC-22, timesheet SES, licence renewal"
TENANTS = ('ITS',)
CREATES_TENANT = True
READY = True

NAME = "Indrayani Digital Services Pvt Ltd"
DOMAIN = "indrayanidigital.example"
GSTIN = "27AAGCI6152H1ZH"          # Maharashtra (27), PAN AAGCI6152H, check character verified
CAMPUS = "P10"
L = 100_000 * 100
NS = uuid.UUID("3b8e1f40-7c2d-4a5e-8f6b-9d0c1e2f3a4b")
# Fixed-date holidays only (Gandhi Jayanti, Christmas, Republic Day); lunar-calendar festivals come from the Maharashtra
# government holiday notification and are not invented here.
HOLIDAYS = [date(2026, 10, 2), date(2026, 12, 25), date(2027, 1, 26)]

USERS = [
    ("admin", "Tenant Administrator", ["TENANT_ADMIN"], {}),
    ("delivery.lead", "Aditya Kulkarni", ["REQUESTER"], {"cost_objects": ["COST_CENTER:6100", "COST_CENTER:6200"], "plants": [CAMPUS]}),
    ("it.head", "Smita Deshmukh", ["COST_OBJECT_OWNER"], {"cost_objects": ["COST_CENTER:6100", "COST_CENTER:6200"], "plants": [CAMPUS]}),
    ("cto", "Rajesh Joshi", ["DEPT_HEAD"], {"cost_objects": ["COST_CENTER:6100", "COST_CENTER:6200"], "plants": [CAMPUS]}),
    ("buyer", "Neha Patwardhan", ["BUYER"], {"plants": [CAMPUS, "P20"]}),
    ("buyer.lead", "Omkar Gokhale", ["BUYER"], {"plants": [CAMPUS, "P20"]}),
    ("category.manager", "Priyanka Sathe", ["CATEGORY_MANAGER"], {"categories": ["*"]}),
    ("procurement.head", "Sameer Bhide", ["PROCUREMENT_HEAD"], {}),
    ("cpo", "Madhavi Ranade", ["CPO"], {}),
    ("finance.controller", "Vikram Apte", ["FINANCE_CONTROLLER"], {}),
    ("finance.controller2", "Swati Karve", ["FINANCE_CONTROLLER"], {}),
    ("legal", "Gauri Phadke", ["LEGAL"], {}),
    ("contract.manager", "Nikhil Chitale", ["CONTRACT_MANAGER"], {}),
    ("contract.manager2", "Rutuja Pawar", ["CONTRACT_MANAGER"], {}),
    ("supplier.manager", "Amol Shinde", ["SUPPLIER_MANAGER"], {"categories": ["*"]}),
    ("mdm.purchasing", "Ketan Mehta", ["MDM_STEWARD"], {"steward_domains": ["PURCHASING"]}),
    ("mdm.quality", "Pallavi Jadhav", ["MDM_STEWARD"], {"steward_domains": ["QUALITY"]}),
    ("mdm.finance", "Sachin Mane", ["MDM_STEWARD"], {"steward_domains": ["FINANCE"]}),
    ("mdm.plant", "Tejas More", ["MDM_STEWARD"], {"steward_domains": ["PLANT"]}),
    ("it.asset.desk", "Yogesh Kale", ["RECEIVER"], {"plants": [CAMPUS]}),
    ("engagement.manager", "Shruti Limaye", ["SERVICE_OWNER"], {"cost_objects": ["COST_CENTER:6100"]}),
    ("ap.clerk", "Sana Shaikh", ["AP_CLERK"], {}),
]
ROLE_USER = {
    "COST_OBJECT_OWNER": "it.head", "DEPT_HEAD": "cto", "PROCUREMENT_HEAD": "procurement.head",
    "FINANCE_CONTROLLER": ["finance.controller", "finance.controller2"], "CATEGORY_MANAGER": "category.manager", "CPO": "cpo",
    "LEGAL": "legal", "CONTRACT_MANAGER": ["contract.manager", "contract.manager2"], "BUYER": ["buyer.lead", "buyer"],
    "SERVICE_OWNER": "engagement.manager", "MDM_STEWARD": ["mdm.purchasing", "mdm.quality", "mdm.finance", "mdm.plant"],
}
INFOSEC = {"infosec": "ISO 27001 statement of applicability reviewed; VAPT report Aug 2026 without open high findings",
           "dataPrivacy": "DPDP Act 2023 data-processing addendum signed; data stays in Indian cloud regions",
           "ipClause": "work product and scripts assigned to Indrayani on payment"}
SUPPLIERS = [
    kit.SupplierSpec(
        code="PCC001", legal_name="Pavana Cloud Consulting Pvt Ltd", gstin="27AAKCP3948D1Z8", ifsc="UTIB0000562",
        account="917020045127730", terms="N30", categories=["IT-SERVICES"], user_local="billing", segment="STRATEGIC",
        certificates=[{"type": "ISO27001", "number": "ISMS-PCC-27-4410", "issued_on": "2025-05-20", "expires_on": "2028-05-19",
                       "mandatory_for": ["IT-SERVICES"]},
                      {"type": "ISO9001", "number": "QMS-PCC-9-2210", "issued_on": "2024-11-01", "expires_on": "2027-10-31"}],
        scores=(88, 86), questionnaire=INFOSEC, address={"city": "Pune", "state": "Maharashtra", "pin": "411057"}),
    kit.SupplierSpec(
        code="MSD002", legal_name="Mula Software Distribution Pvt Ltd", gstin="27AAHCM8261Q1ZN", ifsc="KKBK0001766",
        account="7612450093", terms="N30", categories=["SOFTWARE-LICENCES"], user_local="accounts",
        certificates=[{"type": "ISO9001", "number": "QMS-MSD-9-0915", "issued_on": "2025-09-01", "expires_on": "2028-08-31"}],
        scores=(81, 80), questionnaire={"authorisation": "authorised reseller letter for the platform on file",
                                        "licenceAudit": "named-user true-up yearly"},
        address={"city": "Mumbai", "state": "Maharashtra", "pin": "400051"}),
    kit.SupplierSpec(
        code="TDO003", legal_name="Tamhini DataOps Pvt Ltd", gstin="27AAJCT4093B1ZB", ifsc="HDFC0004473",
        account="50200077341289", terms="N45", categories=["IT-SERVICES"], user_local="accounts",
        certificates=[{"type": "ISO27001", "number": "ISMS-TDO-27-1307", "issued_on": "2026-01-12", "expires_on": "2029-01-11",
                       "mandatory_for": ["IT-SERVICES"]}],
        scores=(79, 80), questionnaire=INFOSEC, address={"city": "Pune", "state": "Maharashtra", "pin": "411045"}),
]
ERP_VENDORS = [
    ("V-410011", "Aundh Systems Integrators Pvt Ltd", "N30", ["IT-SERVICES"]),
    ("V-410021", "Baner Software Resellers Pvt Ltd", "N30", ["SOFTWARE-LICENCES"]),
    ("V-410031", "Kothrud Telecom Services", "N30", ["TELECOM"]),
]
HISTORY = [f"{y}-{m:02d}" for y, m in [(2025, 10), (2025, 11), (2025, 12), (2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5),
                                        (2026, 6), (2026, 7), (2026, 8), (2026, 9)]]

# Rate card RC-22 (negotiated rates of this fictional SOW): key, role, UoM, target quantity, rate in paise
RC22 = [
    ("architect", "Cloud solution architect – rate card RC-22 day rate", "DAY", 40, 28_000_00),
    ("senior", "Senior cloud engineer – rate card RC-22 hour rate", "H", 960, 2_400_00),
    ("devops", "DevOps engineer – rate card RC-22 hour rate", "H", 800, 1_900_00),
    ("dba", "Database migration specialist – rate card RC-22 hour rate", "H", 400, 2_200_00),
    ("pm", "Project manager – rate card RC-22 day rate", "DAY", 30, 22_000_00),
]
TIMESHEET = [("senior", 160), ("devops", 120), ("dba", 40)]   # November 2026: 320 hours
LICENCE = {"description": "Observability platform subscription – named user, term licence", "uom": "EA", "qty": 150, "rate": 9_250_00}


def apply(tenant_code: str, password: str) -> dict:
    from app.pic.services import amendments, order, payables, receiving, requisition, spend
    from app.pic.services import contract as contract_svc

    sc = kit.setup_tenant(tenant_code, NAME, "IT_SERVICES", company=("1000", NAME, GSTIN),
                          plants=[(CAMPUS, "Pune – Hinjewadi campus", "27"), ("P20", "Mumbai – BKC office", "27")],
                          cost_objects=[("COST_CENTER", "6100", "Cloud platform engineering"),
                                        ("COST_CENTER", "6200", "Enterprise applications and tooling")],
                          holidays=HOLIDAYS, domain=DOMAIN, role_user=ROLE_USER)
    notes, counts = [], {}
    kit.create_users(sc, USERS, password)
    kit.rule_version(sc, "SUPPLIER-QUAL", "2026.1-ITS", date(2026, 10, 1),
                     {"mandatoryCertificates": {"IT-SERVICES": ["ISO27001"]}, "minQuestionnaireScore": 70, "minAuditScore": 75,
                      "sampleApprovalRequired": [], "bankApprovers": 2, "coolingOffHours": 72},
                     "IT services: ISO 27001 mandatory (InfoSec and data-privacy assessment, BP §23)")
    kit.load_budgets(sc, [("COST_CENTER", "6100", "SOFT", 120 * L), ("COST_CENTER", "6200", "SOFT", 60 * L)], at(date(2026, 10, 1), 9))
    vendors = kit.erp_vendors(sc, ERP_VENDORS, at(date(2026, 10, 1), 18))
    history = []
    for i, period in enumerate(HISTORY):
        wave = 1 + (i % 3) * 0.04
        history += [(period, "V-410011", "IT-SERVICES", CAMPUS, "COST_CENTER:6100", int(9 * L * wave), i >= 2,
                     "Data-centre operations and managed services"),
                    (period, "V-410021", "SOFTWARE-LICENCES", CAMPUS, "COST_CENTER:6200", int(4 * L * wave), True,
                     "Software subscriptions and support renewals"),
                    (period, "V-410031", "TELECOM", CAMPUS, "COST_CENTER:6100", int(2 * L * wave), True, "MPLS and internet leased lines")]
    counts["erpSpendLines"] = kit.spend_history(sc, history, vendors, at(date(2026, 10, 1), 19), NS, 5_105_400_000)
    notes.append(f"Go-live: budgets CC 6100 ₹1.2 Cr, CC 6200 ₹60 L (soft); {len(ERP_VENDORS)} ERP vendors, "
                 f"{counts['erpSpendLines']} spend lines {HISTORY[0]} – {HISTORY[-1]}")

    # ------------------------------------------------------------ F8 onboarding
    suppliers = {}
    for spec, day in zip(SUPPLIERS, (date(2026, 10, 2), date(2026, 10, 3), date(2026, 10, 6))):
        suppliers[spec.code] = kit.onboard(sc, spec, password, day)
        notes.append(f"F8 {spec.code} {spec.legal_name}: bank dual-approved, {kit.category_status(sc, suppliers[spec.code])}")
    pcc, msd = SUPPLIERS[0], SUPPLIERS[1]

    # ------------------------------------------------------------ F9 rate-card roles and subscription
    masters = {}
    for index, (key, role, uom, _, _) in enumerate(RC22):
        masters[key] = kit.service_master(sc, "buyer", at(date(2026, 10, 7), 9 + index), description=role, type_="SERVICE", group="IT-TM",
                                          category="IT-SERVICES", uom=uom, hsn="998313",
                                          attributes={"rateCard": "RC-22", "billing": "day" if uom == "DAY" else "hour"})
    masters["licence"] = kit.service_master(sc, "buyer", at(date(2026, 10, 7), 15), description=LICENCE["description"], type_="NON_STOCK",
                                            group="SW-SUBSCRIPTION", category="SOFTWARE-LICENCES", uom="EA", hsn="997331",
                                            attributes={"metric": "named user", "term": "co-terminus with FY"})
    with tenant_tx(sc.tenant_id) as s:
        mat = {k: s.execute(select(Material).where(Material.number == v)).scalar_one().id for k, v in masters.items()}
    notes.append(f"F9 masters: {len(RC22)} RC-22 roles (SAC 998313) and the subscription {masters['licence']} (SAC 997331)")

    # ------------------------------------------------------------ F4 licence contract LIC-2601 (renewal case)
    kit.number_range(sc, "CONTRACT", "LIC-", 2601)
    lic_id, lic_no = _contract(sc, contract_svc, msd, at(date(2026, 10, 8), 10), title="LIC-2601 Observability platform – 150 named users",
                               valid=(date(2026, 10, 15), date(2027, 3, 31)),
                               lines=[{"material_id": mat["licence"], "description": LICENCE["description"], "plant": CAMPUS, "uom": "EA",
                                       "target_qty": LICENCE["qty"], "unit_price_minor": LICENCE["rate"]}])
    notes.append(f"F4 {lic_no}: subscription term 15 Oct 2026 – 31 Mar 2027 (co-terminus with the financial year), active")

    with sc.act("delivery.lead", at(date(2026, 10, 13), 10)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="SOFTWARE_SUBSCRIPTION", purpose_text="Observability platform for cloud workloads",
                                plant=CAMPUS, lines=[{"item_type": "MATERIAL", "purchase_type": "EXPENSE", "material": masters["licence"],
                                                      "qty": str(LICENCE["qty"]), "price_est_minor": LICENCE["rate"],
                                                      "account_assignment_type": "COST_CENTER", "account_assignment_code": "6200",
                                                      "need_date": "2026-10-15"}])
        requisition.submit(s, pr)
        lic_pr_id, lic_pr_no = pr.id, pr.number
    sc.approve_all(lic_pr_id, at(date(2026, 10, 13), 15), "Subscription within the CC 6200 budget")
    kit.relay(sc, at(date(2026, 10, 13), 16))
    with sc.act("buyer", at(date(2026, 10, 14), 10)) as s:
        lic_po = order.create_from_requisition(s, requisition=lic_pr_no, lines=[10], contract_ref=lic_no)[0]
        lic_po_id, lic_po_no, touchless = lic_po.id, lic_po.number, lic_po.touchless
    sc.approve_all(lic_po_id, at(date(2026, 10, 14), 12), "Contract price LIC-2601")
    kit.relay(sc, at(date(2026, 10, 14), 13))
    with sc.act(kit.supplier_email(msd), at(date(2026, 10, 14), 16)) as s:
        order.confirm(s, s.get(PurchaseOrder, lic_po_id), "CONFIRMED", note="Tenant provisioned; licence keys issued 15 Oct 2026")
    with sc.act("it.asset.desk", at(date(2026, 10, 15), 12)) as s:
        gr = receiving.post_gr(s, s.get(PurchaseOrder, lic_po_id), lines=[{"line": 10, "qty": str(LICENCE["qty"])}],
                               delivery_note="Entitlement ENT-MSD-26-0415", posting_date=date(2026, 10, 15))
        lic_gr = gr.number
    kit.relay(sc, at(date(2026, 10, 15), 13))
    with sc.act(kit.supplier_email(msd), at(date(2026, 10, 16), 11)) as s:
        inv = payables.capture(s, supplier="MSD002", supplier_invoice_no="MSD/26-27/1187", invoice_date=date(2026, 10, 16), channel="E_INVOICE",
                               irn=payables.expected_irn(msd.gstin, "2026-27", "INV", "MSD/26-27/1187"),
                               lines=[{"po": lic_po_no, "po_line": 10, "qty": str(LICENCE["qty"]), "unit_price": str(LICENCE["rate"] / 100),
                                       "gst_rate": "18", "hsn": "997331"}])
        lic_inv_id = inv.id
    _approve_post(sc, payables, lic_inv_id, at(date(2026, 10, 19), 11))
    notes.append(f"Licence: {lic_pr_no} → {lic_po_no} ({'touchless' if touchless else 'approved'}) → entitlement receipt {lic_gr} → "
                 "MSD/26-27/1187 3-way matched and posted")
    _pay(sc, payables, at(date(2026, 11, 16), 10), notes)

    # ------------------------------------------------------------ F4 SOW-4410 with rate card RC-22
    kit.number_range(sc, "CONTRACT", "SOW-", 4410)
    sow_id, sow_no = _contract(
        sc, contract_svc, pcc, at(date(2026, 10, 20), 10), title="SOW-4410 Cloud migration – time & material, rate card RC-22",
        valid=(date(2026, 11, 1), date(2027, 4, 30)),
        lines=[{"material_id": mat[key], "description": role, "plant": CAMPUS, "uom": uom, "target_qty": qty, "unit_price_minor": rate}
               for key, role, uom, qty, rate in RC22],
        redline=("RATES", "Services are charged at rate card RC-22 (Schedule B): day rates for the solution architect and the project "
                          "manager, hourly rates for engineers. Timesheets are approved monthly by the engagement manager; rates are fixed "
                          "for the SOW term."))
    sow_value = sum(qty * rate for _, _, _, qty, rate in RC22)
    notes.append(f"F4 {sow_no} {kit.fmt(sow_value)}: rate card RC-22 as {len(RC22)} contract lines; RATES clause redlined → approved → active")

    with sc.act("delivery.lead", at(date(2026, 10, 28), 10)) as s:
        pr = requisition.create(s, origin="MANUAL", purpose_code="PROJECT_RESOURCING", purpose_text="Data-centre exit: cloud migration wave 1-3",
                                plant=CAMPUS, lines=[{"item_type": "MATERIAL", "purchase_type": "SERVICE", "material": masters[key], "qty": str(qty),
                                                      "price_est_minor": rate, "account_assignment_type": "COST_CENTER",
                                                      "account_assignment_code": "6100", "need_date": "2027-04-30"}
                                                     for key, _, _, qty, rate in RC22])
        submitted = requisition.submit(s, pr)
        sow_pr_id, sow_pr_no = pr.id, pr.number
    sc.approve_all(sow_pr_id, at(date(2026, 10, 29), 11), "Programme approved by the IT steering committee")
    kit.relay(sc, at(date(2026, 10, 29), 12))
    with sc.act("buyer", at(date(2026, 10, 30), 10)) as s:
        sow_po = order.create_from_requisition(s, requisition=sow_pr_no, lines=[10 * (i + 1) for i in range(len(RC22))], contract_ref=sow_no)[0]
        sow_po_id, sow_po_no = sow_po.id, sow_po.number
    sc.approve_all(sow_po_id, at(date(2026, 10, 30), 15), "Call-off against SOW-4410 at RC-22 rates")
    kit.relay(sc, at(date(2026, 10, 30), 16))
    with sc.act(kit.supplier_email(pcc), at(date(2026, 10, 31), 11)) as s:
        order.confirm(s, s.get(PurchaseOrder, sow_po_id), "CONFIRMED", note="Team onboarded from 2 Nov 2026")
    notes.append(f"F2 {sow_pr_no} route {' → '.join(submitted['chain'])} → F5 {sow_po_no} against {sow_no}, approved and confirmed")

    # ------------------------------------------------------------ F6 timesheet SES (320 h) → F7 invoice matched to the SES
    line_of = {key: 10 * (i + 1) for i, (key, *_rest) in enumerate(RC22)}
    rate_of = {key: rate for key, _, _, _, rate in RC22}
    with sc.act(kit.supplier_email(pcc), at(date(2026, 12, 1), 10)) as s:
        ses = receiving.create_ses(s, s.get(PurchaseOrder, sow_po_id), method="TIME_MATERIAL", period_from=date(2026, 11, 1),
                                   period_to=date(2026, 11, 30),
                                   lines=[{"line": line_of[key], "description": f"Timesheet Nov 2026 – {hours} h", "qty": str(hours),
                                           "unit_rate": str(rate_of[key] / 100)} for key, hours in TIMESHEET])
        receiving.submit_ses(s, ses)
        ses_id, ses_no = ses.id, ses.number
    sc.approve_all(ses_id, at(date(2026, 12, 2), 11), "Timesheets reconciled with the sprint board and access logs")
    kit.relay(sc, at(date(2026, 12, 2), 12))
    with sc.act(kit.supplier_email(pcc), at(date(2026, 12, 3), 11)) as s:
        inv = payables.capture(s, supplier="PCC001", supplier_invoice_no="PCC/INV/2026-27/0098", invoice_date=date(2026, 12, 3),
                               channel="E_INVOICE", irn=payables.expected_irn(pcc.gstin, "2026-27", "INV", "PCC/INV/2026-27/0098"),
                               lines=[{"po": sow_po_no, "po_line": line_of[key], "qty": str(hours), "unit_price": str(rate_of[key] / 100),
                                       "gst_rate": "18", "hsn": "998313", "description": f"{key} – Nov 2026 timesheet {hours} h"}
                                      for key, hours in TIMESHEET])
        sow_inv_id = inv.id
    _approve_post(sc, payables, sow_inv_id, at(date(2026, 12, 4), 11))
    with tenant_tx(sc.tenant_id) as s:
        sow_inv = s.get(Invoice, sow_inv_id)
        sow_invoice = {"invoice": sow_inv.number, "matchType": sow_inv.match_type, "status": sow_inv.status, "netMinor": sow_inv.net_minor}
    notes.append(f"F6/F7 {ses_no}: {sum(h for _, h in TIMESHEET)} h timesheet approved → {sow_invoice['invoice']} "
                 f"{sow_invoice['matchType']}-matched {kit.fmt(sow_invoice['netMinor'])} and posted")

    # ------------------------------------------------------------ F4 renewal alert → decision → extension amendment
    fired = kit.fire(sc, "contract.manager", "CONTRACT_RENEWAL", lic_id, at(date(2026, 12, 31), 10))
    kit.relay(sc, at(date(2026, 12, 31), 10, 5))
    _pay(sc, payables, at(date(2027, 1, 5), 10), notes)
    with sc.act("contract.manager", at(date(2027, 1, 5), 11)) as s:
        task = s.execute(select(Task).where(Task.kind == "CONTRACT_RENEWAL", Task.object_id == lic_id, Task.status == "OPEN")).scalar_one()
        workflow.complete(s, task.id, "APPROVE", "Renew for FY 2027-28: 142 of 150 named users active in December; keep 150")
    # The extension draft is effective from the decision day; it is submitted the same day (a draft submitted on a later day
    # is rejected as back-dated, see the report).
    with sc.act("contract.manager", at(date(2027, 1, 5), 15)) as s:
        draft = s.execute(select(ContractAmendment).where(ContractAmendment.contract_id == lic_id, ContractAmendment.kind == "EXTENSION")
                          ).scalar_one()
        amendments.submit(s, draft)
        extension_no = draft.number
    sc.approve_all(lic_id, at(date(2027, 1, 6), 11), "Renewal on the same per-user price")
    kit.relay(sc, at(date(2027, 1, 6), 12))
    with tenant_tx(sc.tenant_id) as s:
        lic = s.get(Contract, lic_id)
        renewal = {"contract": lic.number, "status": lic.status, "validTo": lic.valid_to.isoformat(), "extension": extension_no,
                   "alertFired": fired}
    notes.append(f"F4 renewal: alert on 31 Dec 2026 (90 days before 31 Mar 2027) → renewal approved → {extension_no} extension to "
                 f"{renewal['validTo']} approved → {lic_no} {renewal['status']}")

    with sc.act("category.manager", at(date(2027, 3, 31), 15)) as s:
        refreshed = spend.refresh(s, sc.tenant_id)
    kit.relay(sc, at(date(2027, 3, 31), 16))
    counts.update({"suppliers": len(SUPPLIERS), "masters": len(masters), "contracts": 2, "purchaseOrders": 2, "serviceEntries": 1,
                   "invoices": 2, "amendments": 1, "spendRefresh": refreshed})
    return {"notes": notes, "counts": counts, "sow": sow_no, "licence": lic_no, "sowInvoice": sow_invoice, "renewal": renewal}


def _contract(sc, contract_svc, spec, when, *, title, valid, lines, redline=None):
    """Value contract drafted from the playbook → AI review → optional supplier redline → approval → both signatures → active."""
    with sc.act("contract.manager", when) as s:
        supplier = s.execute(select(Supplier).where(Supplier.code == spec.code)).scalar_one()
        c = contract_svc.create_draft(s, type="VALUE_CONTRACT", title=title, supplier_id=supplier.id, company_code="1000", valid_from=valid[0],
                                      valid_to=valid[1], payment_terms=spec.terms, incoterms=None, lines=lines,
                                      owner_id=s.info["principal"].user_id, tolerances={})
        contract_svc.ai_review(s, c)
        contract_id, number = c.id, c.number
    if redline:
        with sc.act(kit.supplier_email(spec), when + timedelta(days=1)) as s:
            contract_svc.redline(s, s.get(Contract, contract_id), redline[0], redline[1], "STANDARD")
    with sc.act("contract.manager", when + timedelta(days=1, hours=4)) as s:
        contract_svc.submit(s, s.get(Contract, contract_id))
    sc.approve_all(contract_id, when + timedelta(days=2), "Commercials and clauses approved")
    with sc.act("contract.manager", when + timedelta(days=3)) as s:
        contract_svc.sign(s, s.get(Contract, contract_id), "BUYER", "Nikhil Chitale, Contract Manager")
    with sc.act(kit.supplier_email(spec), when + timedelta(days=3, hours=2)) as s:
        contract_svc.sign(s, s.get(Contract, contract_id), "SUPPLIER", f"Authorised signatory, {spec.legal_name}")
    with sc.act("contract.manager", when + timedelta(days=3, hours=4)) as s:
        contract_svc.activate(s, s.get(Contract, contract_id))
    kit.relay(sc, when + timedelta(days=3, hours=5))
    return contract_id, number


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
