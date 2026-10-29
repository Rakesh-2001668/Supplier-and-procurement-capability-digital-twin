"""Axion Mobility Systems: the blueprint signature case (§20) run end to end through the services.

Nothing here writes business documents directly except the §12.4 data-migration loads
(masters, opening stock, demand, one migrated open PO). Every other row — requisitions,
events, bids, contracts, POs, receipts, invoices, payments, savings, audit, lineage and
process history — is produced by the same service calls the API uses.

Timeline (IST): onboarding Sep 2026 → MRP 6 Oct → sourcing 8–21 Oct → contracts 22–26 Oct
→ PO 2 Nov → receipt 12–13 Nov → invoice 14 Nov → index reset 28 Dec → payment 13 Jan 2027.
"""
import logging
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import (
    AppUser, Budget, CatalogueItem, Contract, DemandElement, GoodsReceipt, InfoRecord, InspectionLot, Invoice, InvoiceException,
    Material, MaterialRequest, PlannedOrder, PoLine, PurchaseOrder, Qualification, Requisition, SavingsInitiative, ServiceEntry,
    SourceList, SourcingEvent, Stock, Supplier, Task, TwinSnapshot,
)
from app.pic.platform import audit, clock, crypto, workflow
from app.pic.platform.auth import Principal, hash_password, scopes_for
from app.pic.seed import reference
from app.pic.worker import tick

log = logging.getLogger("pic.seed")

TENANT = ("AXN", "Axion Mobility Systems Pvt Ltd")
DOMAIN = "axion.example"
CATEGORY = "ALU-DIECAST"

INTERNAL_USERS = [
    # email local part, name, roles, attributes
    ("admin", "Tenant Administrator", ["TENANT_ADMIN"], {}),
    ("mrp.controller", "Meena Raghavan", ["MRP_CONTROLLER"], {"plants": ["P100"]}),
    ("requester", "Arun Prakash", ["REQUESTER"], {"cost_objects": ["COST_CENTER:4100"], "plants": ["P100"]}),
    ("plant.controller", "Karthik Subramanian", ["COST_OBJECT_OWNER"], {"plants": ["P100"], "cost_objects": ["COST_CENTER:4100"]}),
    ("ops.head", "Lakshmi Narayanan", ["DEPT_HEAD"], {"plants": ["P100"], "cost_objects": ["COST_CENTER:4100"]}),
    ("buyer", "Divya Krishnan", ["BUYER"], {"plants": ["P100", "P200"]}),
    ("buyer.lead", "Rahul Menon", ["BUYER"], {"plants": ["P100", "P200"]}),
    ("category.manager", "Sanjay Iyer", ["CATEGORY_MANAGER"], {"categories": [CATEGORY]}),
    ("category.head", "Priya Venkatesh", ["CATEGORY_MANAGER"], {"categories": ["*"]}),
    ("quality.engineer", "Vignesh Kumar", ["QUALITY_INSPECTOR"], {"plants": ["P100"]}),
    ("procurement.head", "Ramesh Chandran", ["PROCUREMENT_HEAD"], {}),
    ("cpo", "Anitha Rao", ["CPO"], {}),
    ("finance.controller", "Suresh Babu", ["FINANCE_CONTROLLER"], {}),
    ("finance.controller2", "Deepa Ramesh", ["FINANCE_CONTROLLER"], {}),
    ("legal", "Harini Srinivasan", ["LEGAL"], {}),
    ("contract.manager", "Ganesh Murthy", ["CONTRACT_MANAGER"], {}),
    ("contract.manager2", "Meena Raghavan", ["CONTRACT_MANAGER"], {}),  # second contract manager: four-eyes on small amendments
    ("supplier.manager", "Kavitha Sundaram", ["SUPPLIER_MANAGER"], {"categories": ["*"]}),
    ("mdm.purchasing", "Naveen Joseph", ["MDM_STEWARD"], {"steward_domains": ["PURCHASING"]}),
    ("mdm.quality", "Revathi Mohan", ["MDM_STEWARD"], {"steward_domains": ["QUALITY"]}),
    ("mdm.finance", "Ashok Pillai", ["MDM_STEWARD"], {"steward_domains": ["FINANCE"]}),
    ("mdm.plant", "Selvi Arumugam", ["MDM_STEWARD"], {"steward_domains": ["PLANT"]}),
    ("receiver", "Murugan Pandian", ["RECEIVER"], {"plants": ["P100"]}),
    ("quality.inspector", "Bhavani Shankar", ["QUALITY_INSPECTOR"], {"plants": ["P100"]}),
    ("service.owner", "Prakash Rajan", ["SERVICE_OWNER"], {"cost_objects": ["COST_CENTER:4100"]}),
    ("ap.clerk", "Fathima Begum", ["AP_CLERK"], {}),
]

SUPPLIERS = [
    # code, legal name, GSTIN, IFSC, account, terms, incoterms, categories, twin (free capacity/month, trust, late prob, ppm, lead days)
    ("TF001", "Trichy Forge Pvt Ltd", "33AABCT1234K1ZM", "SBIN0001234", "30112345678", "N60", "FCA Trichy", [CATEGORY],
     (60000, "0.860", "0.220", 1200, 12), "tf.sales"),
    ("KD002", "Kovai Diecast Pvt Ltd", "33AABCK5678L1Z5", "HDFC0002345", "50100234567", "N45", "FCA Coimbatore", [CATEGORY],
     (45000, "0.810", "0.120", 800, 10), "kd.sales"),
    ("SLA003", "Salem Light Alloys Pvt Ltd", "33AABCS9012M1ZB", "ICIC0003456", "000405123456", "N30", "FCA Salem", [CATEGORY],
     (70000, "0.740", "0.180", 2500, 14), "sla.sales"),
    ("HTS004", "Hosur Tooling Services", "33AABCH3456N1ZG", "CNRB0004567", "1234101009876", "N30", None, ["TOOLING-SERVICES"],
     (400, "0.900", "0.100", 0, 2), "hts.service"),
]

# Who works which approval role in the scenario.
ROLE_USER = {
    "COST_OBJECT_OWNER": "plant.controller", "DEPT_HEAD": "ops.head", "PROCUREMENT_HEAD": "procurement.head",
    "FINANCE_CONTROLLER": ["finance.controller", "finance.controller2"], "CATEGORY_MANAGER": "category.head", "CPO": "cpo",
    "LEGAL": "legal", "CONTRACT_MANAGER": "contract.manager", "BUYER": "buyer.lead", "SERVICE_OWNER": "service.owner",
    "MDM_STEWARD": ["mdm.purchasing", "mdm.quality", "mdm.finance", "mdm.plant"],
}


def email(local: str) -> str:
    return f"{local}@{DOMAIN}"


def at(day: date, hour: int = 10, minute: int = 0) -> datetime:
    return clock.at_ist(day, hour, minute)


class Scenario:
    def __init__(self, tenant_id: uuid.UUID, tenant_code: str = TENANT[0], domain: str = DOMAIN, role_user: dict | None = None):
        self.tenant_id = tenant_id
        self.tenant_code = tenant_code
        self.domain = domain
        self.role_user = role_user or ROLE_USER
        self.log: list[str] = []

    def email(self, who: str) -> str:
        return who if "@" in who else f"{who}@{self.domain}"

    @contextmanager
    def act(self, who: str, when: datetime):
        """Run one transaction as a named user at a business date-time."""
        clock.set_pinned(when)
        with tenant_tx(self.tenant_id) as s:
            user = s.execute(select(AppUser).where(AppUser.email == self.email(who))).scalar_one()
            p = Principal(user_id=user.id, tenant_id=self.tenant_id, tenant_code=self.tenant_code, email=user.email, name=user.full_name,
                          roles=list(user.roles), scopes=scopes_for(list(user.roles)), attributes=user.attributes or {},
                          supplier_id=user.supplier_id)
            s.info["principal"], s.info["user_id"] = p, user.id
            yield s

    def relay(self, when: datetime) -> dict:
        clock.set_pinned(when)
        return tick()

    def note(self, text: str) -> None:
        self.log.append(text)
        log.info(text)

    def approve_all(self, object_id: uuid.UUID, when: datetime, comment: str = "Approved") -> int:
        done = 0
        for _ in range(12):
            clock.set_pinned(when)
            with tenant_tx(self.tenant_id) as s:
                tasks = s.execute(select(Task).where(Task.object_id == object_id, Task.status == "OPEN").order_by(Task.sequence)).scalars().all()
                pending = [(t.id, t.candidate_role, t.candidate_scope, list(t.excluded_user_ids or [])) for t in tasks]
            if not pending:
                return done
            for task_id, role, scope, excluded in pending:
                candidates = self.role_user[role] if isinstance(self.role_user[role], list) else [self.role_user[role]]
                for who in candidates:
                    with self.act(who, when) as s:
                        p = s.info["principal"]
                        task = s.get(Task, task_id)
                        if task.status != "OPEN" or workflow.can_work(p, task):
                            continue
                        workflow.complete(s, task_id, "APPROVE", comment)
                        done += 1
                        break
        return done


def _create_users(sc: Scenario, password: str) -> None:
    with tenant_tx(sc.tenant_id) as s:
        if s.execute(select(AppUser.id)).first():
            raise RuntimeError("Tenant AXN already has users; the scenario seeds an empty tenant only")
        hashed = hash_password(password)
        for local, name, roles, attrs in INTERNAL_USERS:
            s.add(AppUser(tenant_id=sc.tenant_id, email=email(local), full_name=name, password_hash=hashed, roles=roles,
                          attributes=attrs, mfa_enrolled=any(r in roles for r in ("FINANCE_CONTROLLER", "TENANT_ADMIN", "CPO"))))


def _load_masters(sc: Scenario) -> None:
    """§12.4 initial loads: materials, catalogue, budgets."""
    clock.set_pinned(at(date(2026, 9, 1), 9))
    with tenant_tx(sc.tenant_id) as s:
        materials = [
            Material(tenant_id=sc.tenant_id, number="DC-330", description="Aluminium die-cast housing DC-330", type="STOCK",
                     material_group=CATEGORY, category=CATEGORY, base_uom="EA", valuation_class="3000", hsn_code="87089900",
                     gst_rate=Decimal(18), mpn="AXN-DC-330", attributes={"alloy": "ADC12", "weight_kg": "1.2", "process": "HPDC"},
                     mrp_type="PD", lot_size_policy="EXACT", safety_stock=Decimal(200), planned_delivery_days=10, gr_processing_days=1,
                     quality_managed=True, standard_price_minor=41000, annual_demand=Decimal(1080000), status="ACTIVE", erp_synced=True),
            Material(tenant_id=sc.tenant_id, number="DC-331", description="Aluminium die-cast cover DC-331", type="STOCK",
                     material_group=CATEGORY, category=CATEGORY, base_uom="EA", valuation_class="3000", hsn_code="87089900",
                     gst_rate=Decimal(18), mpn="AXN-DC-331", attributes={"alloy": "ADC12", "weight_kg": "0.6", "process": "HPDC"},
                     mrp_type="PD", lot_size_policy="FIXED", lot_size_qty=Decimal(2000), safety_stock=Decimal(100),
                     planned_delivery_days=10, gr_processing_days=1, quality_managed=True, standard_price_minor=21500, status="ACTIVE",
                     erp_synced=True),
            Material(tenant_id=sc.tenant_id, number="FK-M8-50", description="Fastener kit M8 x 50 zinc flake", type="STOCK",
                     material_group="FASTENERS", category="FASTENERS", base_uom="EA", valuation_class="3100", hsn_code="73181500",
                     gst_rate=Decimal(18), mrp_type="ND", standard_price_minor=1250, status="ACTIVE", erp_synced=True),
        ]
        s.add_all(materials)
        s.flush()
        for budget in [("COST_CENTER", "4100", "SOFT", 50), ("COST_CENTER", "4200", "SOFT", 30), ("WBS", "C-2207", "HARD", 200)]:
            s.add(Budget(tenant_id=sc.tenant_id, cost_object_type=budget[0], cost_object_code=budget[1], fiscal_year="2026-27",
                         control=budget[2], amount_minor=budget[3] * reference.L, committed_minor=0, consumed_minor=0))
        audit.record(s, "MIGRATION", uuid.uuid5(uuid.NAMESPACE_URL, "axn-masters"), "INITIAL_LOAD", object_ref="materials+budgets",
                     after={"materials": [m.number for m in materials], "budgets": 3}, actor="migration")
    sc.note("Masters loaded: DC-330, DC-331, FK-M8-50; budgets CC 4100, CC 4200, WBS C-2207")


def _onboard_suppliers(sc: Scenario, password: str) -> dict:
    from app.pic.services import supplier as svc

    codes = {}
    day = date(2026, 9, 2)
    for code, name, gstin, ifsc, account, terms, inco, categories, twin, user_local in SUPPLIERS:
        with sc.act("supplier.manager", at(day, 10)) as s:
            sup = svc.register(s, code=code, legal_name=name, gstin=gstin, pan=gstin[2:12], state_code=gstin[:2],
                               contact_email=email(user_local).replace(DOMAIN, f"{code.lower()}.example"), categories=categories,
                               payment_terms=terms, incoterms=inco, segment="STRATEGIC" if CATEGORY in categories else "ROUTINE")
            supplier_id = sup.id
            capacity, trust, late, ppm, lead = twin
            for category in categories:
                s.add(TwinSnapshot(tenant_id=sc.tenant_id, supplier_id=sup.id, category=category,
                                   capability={"process": "HPDC" if category == CATEGORY else "die maintenance", "evidence": "audit+ERP"},
                                   evidence_level="E3", free_capacity_per_month=Decimal(capacity), trust_score=Decimal(trust),
                                   late_delivery_prob=Decimal(late), model_version="eta-v3", ppm=Decimal(ppm), lead_time_days=lead,
                                   as_of=day))
            s.add(AppUser(tenant_id=sc.tenant_id, email=email(user_local), full_name=f"{name} – sales", password_hash=hash_password(password),
                          roles=["SUPPLIER_USER"], attributes={}, supplier_id=sup.id, mfa_enrolled=True))
        mandatory = [CATEGORY] if CATEGORY in categories else []
        certs = ([{"type": "IATF16949", "number": f"IATF-{code}-0451", "issued_on": "2025-01-10", "expires_on": "2028-01-09", "mandatory_for": mandatory},
                  {"type": "ISO14001", "number": f"EMS-{code}-2207", "issued_on": "2024-06-01", "expires_on": "2027-05-31", "mandatory_for": mandatory}]
                 if mandatory else [{"type": "ISO9001", "number": f"QMS-{code}-1180", "issued_on": "2025-03-01", "expires_on": "2028-02-28"}])
        with sc.act(user_local, at(day, 15)) as s:
            result = svc.submit_profile(s, s.get(Supplier, supplier_id), bank_account=account, ifsc=ifsc, holder_name=name, certificates=certs)
            change_no = result["bankChange"]
        with sc.act("supplier.manager", at(day + _days(1), 11)) as s:
            from app.pic.models import BankChangeRequest
            change = s.execute(select(BankChangeRequest).where(BankChangeRequest.number == change_no)).scalar_one()
            svc.callback_verify(s, change, f"Called {name} on registered landline; account holder and IFSC confirmed")
            change_id = change.id
        sc.approve_all(change_id, at(day + _days(1), 15), "Bank letter and cancelled cheque verified")
        with sc.act("supplier.manager", at(day + _days(3), 10)) as s:
            # F8-04: the certificates are verified explicitly (issuer register), no longer as a side effect of the bank approval.
            svc.verify_certificates(s, s.get(Supplier, supplier_id), "Checked against the certification body's public register")
            for category in categories:
                q = svc.start_qualification(s, s.get(Supplier, supplier_id), category)
                score = {"TF001": (86, 88), "KD002": (84, 85), "SLA003": (74, 78), "HTS004": (82, 80)}[code]
                svc.record_assessment(s, q, questionnaire={"capacity": "verified", "ppap": "level 3"}, questionnaire_score=Decimal(score[0]),
                                      audit_score=Decimal(score[1]), sample_approval="PPAP_APPROVED" if category == CATEGORY else None)
                svc.decide_qualification(s, q, "QUALIFIED", f"Audit {score[1]}/100; certificates verified")
        codes[code] = supplier_id
        day = day + _days(1)
        sc.note(f"F8 onboarded {code} {name}: bank dual-approved, qualified for {', '.join(categories)}")
    # A supplier still in onboarding: profile submitted, waiting for the bank call-back.
    with sc.act("supplier.manager", at(date(2026, 10, 20), 10)) as s:
        mpc = svc.register(s, code="MPC005", legal_name="Madurai Precision Castings", gstin="33AABCM7890P1ZT", pan="AABCM7890P", state_code="33",
                           contact_email="sales@mpc005.example", categories=[CATEGORY], payment_terms="N45", incoterms="FCA Madurai")
        s.add(AppUser(tenant_id=sc.tenant_id, email=email("mpc.sales"), full_name="Madurai Precision Castings – sales",
                      password_hash=hash_password(password), roles=["SUPPLIER_USER"], attributes={}, supplier_id=mpc.id, mfa_enrolled=True))
        mpc_id = mpc.id
    with sc.act("mpc.sales", at(date(2026, 10, 21), 11)) as s:
        svc.submit_profile(s, s.get(Supplier, mpc_id), bank_account="6011223344", ifsc="IOBA0005678", holder_name="Madurai Precision Castings",
                           certificates=[{"type": "IATF16949", "number": "IATF-MPC-7781", "issued_on": "2026-02-01", "expires_on": "2029-01-31",
                                          "mandatory_for": [CATEGORY]}])
    sc.note("F8 MPC005 registered; profile submitted; waiting for bank call-back")
    return codes


def _days(n: int):
    from datetime import timedelta
    return timedelta(days=n)


def _migrate_open_supply(sc: Scenario, suppliers: dict) -> None:
    """§12.4: opening stock, demand and one open ERP PO (loaded with its ERP number as external reference)."""
    clock.set_pinned(at(date(2026, 9, 15), 9))
    with tenant_tx(sc.tenant_id) as s:
        dc330 = s.execute(select(Material).where(Material.number == "DC-330")).scalar_one()
        kd = suppliers["KD002"]
        s.add(Stock(tenant_id=sc.tenant_id, material_id=dc330.id, plant="P100", storage_location="0001", stock_type="UNRESTRICTED",
                    batch="", qty=Decimal(1400)))
        s.add(InfoRecord(tenant_id=sc.tenant_id, supplier_id=kd, material_id=dc330.id, plant="P100", last_price_minor=41000,
                         lead_time_days=10))
        # ERP source list for the cover: Trichy Forge fixed, Kovai Diecast as alternate (DC-330 is sourced by contract quota).
        dc331 = s.execute(select(Material).where(Material.number == "DC-331")).scalar_one()
        for supplier_code, fixed in (("TF001", True), ("KD002", False)):
            s.add(SourceList(tenant_id=sc.tenant_id, supplier_id=suppliers[supplier_code], material_id=dc331.id, plant="P100", fixed=fixed,
                             valid_from=date(2026, 4, 1), valid_to=date(2027, 3, 31)))
        s.add(InfoRecord(tenant_id=sc.tenant_id, supplier_id=suppliers["TF001"], material_id=dc331.id, plant="P100", last_price_minor=21200,
                         lead_time_days=12))
        changed = clock.now()
        s.add(DemandElement(tenant_id=sc.tenant_id, material_id=dc330.id, plant="P100", type="FORECAST", reference="FC-2026-11",
                            req_date=date(2026, 11, 12), qty=Decimal(9000), changed_at=changed))
        s.add(DemandElement(tenant_id=sc.tenant_id, material_id=dc330.id, plant="P100", type="SALES_ORDER", reference="SO-88120",
                            req_date=date(2026, 11, 12), qty=Decimal(3000), changed_at=changed))
        po = PurchaseOrder(tenant_id=sc.tenant_id, number="PO-77395", version=1, company_code="1000", purch_org="1000", plant="P100",
                           supplier_id=kd, status="CONFIRMED", purpose_code="MRP_REPLENISHMENT", currency="INR", total_minor=1800 * 41000,
                           payment_terms="N45", incoterms="FCA Coimbatore", tolerance={"over_pct": "0", "under_pct": "0", "price_pct": "0"},
                           rule_set_version="MIGRATION", erp_doc_no="4500017001", inherited={"migratedFrom": "SAP_S4"}, touchless=False)
        s.add(po)
        s.flush()
        s.add(PoLine(tenant_id=sc.tenant_id, po_id=po.id, line_no=10, item_type="MATERIAL", purchase_type="STOCK", material_id=dc330.id,
                     description=dc330.description, material_group=CATEGORY, qty=Decimal(1800), uom="EA", unit_price_minor=41000,
                     net_minor=1800 * 41000, gst_rate=Decimal(18), hsn_code="87089900", need_date=date(2026, 10, 28), plant="P100",
                     storage_location="0001", gr_required=True, ir_required=True, quality_managed=True, price_source="INFO_RECORD"))
        audit.record(s, "PURCHASE_ORDER", po.id, "MIGRATED", object_ref=po.number, after={"erpDocument": "4500017001", "qty": "1800"},
                     actor="migration")
        po_id = po.id
    from app.pic.services import receiving
    with sc.act("kd.sales", at(date(2026, 10, 5), 14)) as s:
        receiving.create_asn(s, s.get(PurchaseOrder, po_id), lines=[{"line": 10, "qty": "600", "batches": [{"batch": "KD-2610-07", "qty": "600"}]}],
                             ship_date=date(2026, 10, 5), expected_date=date(2026, 10, 9), eway_bill_no="331008765432",
                             vehicle_no="TN38CK4521", distance_km=250, documents=["CoC-KD-2610-07"])
    sc.note("Migrated: stock 1,400; demand 12,000 (FC-2026-11 + SO-88120); PO-77395 1,800 open, ASN-61207 600 in transit")


def run(password: str) -> list[str]:
    from app.pic.services import contract as contract_svc
    from app.pic.services import mdm, order, payables, planning, receiving, requisition, savings, sourcing

    reference.deploy_process_definitions()
    tenant_id = reference.create_tenant(*TENANT)
    reference.bootstrap(tenant_id, company=("1000", TENANT[1], "33AAACA4321F1ZF"),
                        plants=[("P100", "Hosur", "33"), ("P200", "Chennai", "33")],
                        cost_objects=[("COST_CENTER", "4100", "Production engineering – Hosur"), ("COST_CENTER", "4200", "IT services"),
                                      ("WBS", "C-2207", "Tower B structure")],
                        holidays=[date(2026, 10, 20), date(2026, 11, 8), date(2027, 1, 15)])
    sc = Scenario(tenant_id)
    _create_users(sc, password)
    _load_masters(sc)
    suppliers = _onboard_suppliers(sc, password)
    with tenant_tx(tenant_id) as s:
        s.add(CatalogueItem(tenant_id=tenant_id, supplier_id=suppliers["HTS004"], supplier_part_no="HTS-PM-STD",
                            description="Preventive maintenance visit – die casting cell", material_group="SVC-TOOLING",
                            category="TOOLING-SERVICES", uom="EA", price_minor=1_850_000, gst_rate=Decimal(18), hsn_code="998717"))
    _migrate_open_supply(sc, suppliers)
    from app.pic.seed import intelligence
    intelligence.load_erp_history(sc)

    # ---------------------------------------------------------------- F1 MRP → planned order → PR
    with sc.act("mrp.controller", at(date(2026, 10, 6), 9)) as s:
        mrp = planning.run(s, plant="P100", mode="NET_CHANGE", run_date=date(2026, 10, 6))
        run_number, net = mrp.number, mrp.results[0]["net"]
    with sc.act("mrp.controller", at(date(2026, 10, 6), 10)) as s:
        plo = s.execute(select(PlannedOrder).where(PlannedOrder.status == "CREATED")).scalar_one()
        planning.firm(s, plo)
        pr = planning.convert(s, plo)
        req_id, req_no, plo_no = pr.id, pr.number, plo.number
    sc.approve_all(req_id, at(date(2026, 10, 7), 11), "Within plan; sourcing required")
    sc.relay(at(date(2026, 10, 7), 12))
    sc.note(f"F1 {run_number}: net {net} → {plo_no} firmed → {req_no} approved (4-step DMN-01 chain)")

    # ---------------------------------------------------------------- F2 guided buying + F9 material governance
    with sc.act("requester", at(date(2026, 10, 10), 10)) as s:
        requisition.search(s, "custom fixture DC-330", "P100")
        fixture = requisition.create(s, origin="MANUAL", purpose_code="TOOLING_UPGRADE", purpose_text="Line 3 changeover fixture",
                                     plant="P100", lines=[{"item_type": "FREE_TEXT", "purchase_type": "NON_STOCK",
                                                           "description": "Custom fixture for DC-330 line 3", "material_group": "41-FIXTURE",
                                                           "category": "TOOLING", "qty": "2", "uom": "EA", "price_est_minor": 9_250_000,
                                                           "account_assignment_type": "COST_CENTER", "account_assignment_code": "4100",
                                                           "need_date": "2026-12-01", "reusable": True,
                                                           "quotes": [{"supplier": "HTS004", "reference": "HTS/Q/26-27/0412",
                                                                       "date": "2026-10-08"}],
                                                           "attributes": {"line": "DC-330 L3", "type": "fixture"}}])
        requisition.submit(s, fixture)
        fixture_id, fixture_no = fixture.id, fixture.number
        mrq = s.execute(select(MaterialRequest).where(MaterialRequest.source_pr_id == fixture.id)).scalar_one()
        mrq_id, mrq_no = mrq.id, mrq.number
    sc.approve_all(fixture_id, at(date(2026, 10, 10), 15), "Approved against CC 4100 tooling budget")
    sc.approve_all(mrq_id, at(date(2026, 10, 12), 11), "Domain data complete")
    with sc.act("buyer", at(date(2026, 10, 12), 14)) as s:
        dup = mdm.create_request(s, description="Aluminium die-cast housing DC-330", type="STOCK", material_group=CATEGORY,
                                 category=CATEGORY, base_uom="EA", mpn="AXN-DC-330",
                                 attributes={"alloy": "ADC12", "weight_kg": "1.2", "process": "HPDC"})
        dup_no = dup.number
        mdm.merge_into_existing(s, dup, s.execute(select(Material).where(Material.number == "DC-330")).scalar_one())
    sc.relay(at(date(2026, 10, 12), 15))
    sc.note(f"F2 {fixture_no} free-text fixture approved; F9 {mrq_no} → new material via 4 stewards; {dup_no} blocked as duplicate → merged into DC-330")

    # ---------------------------------------------------------------- F3 sourcing → award
    criteria = [{"code": "PRICE_TCO", "name": "Price / TCO", "weight": 50}, {"code": "QUALITY", "name": "Quality", "weight": 20},
                {"code": "DELIVERY", "name": "Delivery", "weight": 15}, {"code": "TECHNICAL", "name": "Technical", "weight": 10},
                {"code": "ESG", "name": "ESG", "weight": 5}]
    with sc.act("category.manager", at(date(2026, 10, 8), 10)) as s:
        event = sourcing.create_event(
            s, type="RFQ", title="DC-330 aluminium die-cast housing – annual requirement", category=CATEGORY,
            lines=[{"requisition": req_no, "line": 10, "annual_qty": "1080000", "monthly_qty": "90000"}], criteria=criteria,
            invitees=[{"supplier": "TF001"}, {"supplier": "KD002"}, {"supplier": "SLA003"}], close_at=at(date(2026, 10, 15), 17),
            should_cost_params={"net_weight_kg": "1.2", "alloy_rate_per_kg": "215", "cycle_time_min": "3.5", "machine_rate_per_min": "18",
                                "tooling_amortisation": "12", "packaging": "7", "overhead_margin_pct": "15"},
            constraints={"max_suppliers": 2, "max_share": "0.60", "min_share": "0.20"}, savings_target_pct=Decimal("2.0"))
        sourcing.publish(s, event)
        event_id, event_no = event.id, event.number
    sc.relay(at(date(2026, 10, 8), 11))
    bids = {"tf.sales": ("398", "3.00", 60, 12, "60000"), "kd.sales": ("412", "2.00", 45, 10, "45000"),
            "sla.sales": ("405", "4.50", 30, 14, "70000")}
    for i, (who, (price, freight, terms, lead, cap)) in enumerate(bids.items()):
        with sc.act(who, at(date(2026, 10, 12 + i), 16)) as s:
            sourcing.submit_bid(s, s.get(SourcingEvent, event_id), s.get(Supplier, s.info["principal"].supplier_id),
                                [{"line": 10, "unit_price": price, "freight": freight, "packaging": "1.00", "payment_terms_days": terms,
                                  "lead_time_days": lead, "capacity_per_month": cap}])
    sc.relay(at(date(2026, 10, 15), 17, 5))  # close timer unseals the bids
    with sc.act("category.manager", at(date(2026, 10, 16), 10)) as s:
        sourcing.new_round(s, s.get(SourcingEvent, event_id), at(date(2026, 10, 19), 17), "negotiation round: Kovai invited to improve 412")
    with sc.act("kd.sales", at(date(2026, 10, 17), 12)) as s:
        sourcing.submit_bid(s, s.get(SourcingEvent, event_id), s.get(Supplier, suppliers["KD002"]),
                            [{"line": 10, "unit_price": "405", "freight": "2.00", "packaging": "1.00", "payment_terms_days": 45,
                              "lead_time_days": 10, "capacity_per_month": "45000"}])
    sc.relay(at(date(2026, 10, 19), 17, 5))
    scores = {"category.manager": [("TF001", "QUALITY", 82), ("KD002", "QUALITY", 88), ("SLA003", "QUALITY", 70),
                                   ("TF001", "DELIVERY", 78), ("KD002", "DELIVERY", 90), ("SLA003", "DELIVERY", 80),
                                   ("TF001", "ESG", 80), ("KD002", "ESG", 75), ("SLA003", "ESG", 70)],
              "quality.engineer": [("TF001", "QUALITY", 84), ("KD002", "QUALITY", 86), ("SLA003", "QUALITY", 68),
                                   ("TF001", "TECHNICAL", 85), ("KD002", "TECHNICAL", 82), ("SLA003", "TECHNICAL", 74)]}
    for who, entries in scores.items():
        with sc.act(who, at(date(2026, 10, 20), 11)) as s:
            sourcing.score(s, s.get(SourcingEvent, event_id), [{"supplier": a, "criterion": b, "score": c} for a, b, c in entries])
    with sc.act("category.manager", at(date(2026, 10, 20), 15)) as s:
        options = sourcing.build_scenarios(s, s.get(SourcingEvent, event_id))
        chosen = next(o for o in options if o["kind"] == "CAPACITY_CONSTRAINED")
        sourcing.propose_award(s, s.get(SourcingEvent, event_id), uuid.UUID(chosen["id"]),
                               "Trichy Forge verified free capacity is 60k/month (digital twin), so single sourcing is infeasible; "
                               "dual source 60/40 with Kovai Diecast, negotiated from 412 to 405.",
                               "No personal or financial interest in any bidder.")
    sc.approve_all(event_id, at(date(2026, 10, 21), 12), "Capacity-constrained award approved")
    sc.relay(at(date(2026, 10, 21), 13))
    sc.note(f"F3 {event_no}: TF 398 · KD 412→405 · SLA 405; award 60/40 weighted {chosen['weightedPriceMinor']/100:.2f}")

    # ---------------------------------------------------------------- F4 contracts
    with tenant_tx(tenant_id) as s:
        contracts = [(c.id, c.number, c.supplier_id) for c in s.execute(select(Contract).order_by(Contract.number)).scalars()]
    signer = {suppliers["TF001"]: "tf.sales", suppliers["KD002"]: "kd.sales"}
    for contract_id, number, supplier_id in contracts:
        with sc.act("contract.manager", at(date(2026, 10, 22), 10)) as s:
            contract_svc.ai_review(s, s.get(Contract, contract_id))
            contract_svc.submit(s, s.get(Contract, contract_id))
        sc.approve_all(contract_id, at(date(2026, 10, 23), 11), "Standard clauses; value approved")
        with sc.act("contract.manager", at(date(2026, 10, 26), 10)) as s:
            contract_svc.sign(s, s.get(Contract, contract_id), "BUYER", "Ganesh Murthy, Contract Manager")
        with sc.act(signer[supplier_id], at(date(2026, 10, 26), 12)) as s:
            contract_svc.sign(s, s.get(Contract, contract_id), "SUPPLIER", "Authorised signatory")
        with sc.act("contract.manager", at(date(2026, 10, 26), 15)) as s:
            contract_svc.activate(s, s.get(Contract, contract_id))
    sc.relay(at(date(2026, 10, 26), 16))
    sc.note(f"F4 {', '.join(n for _, n, _ in contracts)} approved, signed and active; prices and 60/40 quota published")

    # ---------------------------------------------------------------- F5 PO (touchless) → confirmation
    with sc.act("buyer", at(date(2026, 11, 2), 10)) as s:
        pos = order.create_from_requisition(s, requisition=req_no, lines=[10])
        po_ids = {s.get(Supplier, po.supplier_id).code: (po.id, po.number) for po in pos}
    sc.relay(at(date(2026, 11, 2), 10, 5))
    with sc.act("tf.sales", at(date(2026, 11, 2), 16)) as s:
        order.confirm(s, s.get(PurchaseOrder, po_ids["TF001"][0]), "CONFIRMED", note="Confirmed as ordered; dispatch 10 Nov")
    with sc.act("kd.sales", at(date(2026, 11, 3), 11)) as s:
        order.confirm(s, s.get(PurchaseOrder, po_ids["KD002"][0]), "CONFIRMED")
    sc.note(f"F5 {po_ids['TF001'][1]} (TF 5,400 @398) and {po_ids['KD002'][1]} (KD 3,600 @405) released touchless and confirmed")

    # ---------------------------------------------------------------- F6 ASN → GR → quality
    with sc.act("tf.sales", at(date(2026, 11, 10), 9)) as s:
        asn = receiving.create_asn(s, s.get(PurchaseOrder, po_ids["TF001"][0]),
                                   lines=[{"line": 10, "qty": "5400", "batches": [{"batch": "B-2611-01", "qty": "2700"},
                                                                                {"batch": "B-2611-02", "qty": "2700"}]}],
                                   ship_date=date(2026, 11, 10), expected_date=date(2026, 11, 12), eway_bill_no="331009876543",
                                   vehicle_no="TN45AB1234", distance_km=320, documents=["CoC-TF-2611", "PackingList-TF-2611"])
        asn_id, asn_no = asn.id, asn.number
    with sc.act("kd.sales", at(date(2026, 11, 18), 9)) as s:
        receiving.create_asn(s, s.get(PurchaseOrder, po_ids["KD002"][0]), lines=[{"line": 10, "qty": "3600", "batches": [{"batch": "KD-2611-18", "qty": "3600"}]}],
                             ship_date=date(2026, 11, 18), expected_date=date(2026, 11, 21), eway_bill_no="331009912345", vehicle_no="TN38CK4521",
                             distance_km=250, documents=["CoC-KD-2611-18"])
    with sc.act("receiver", at(date(2026, 11, 12), 11)) as s:
        from app.pic.models import Asn
        gr = receiving.post_gr(s, s.get(PurchaseOrder, po_ids["TF001"][0]), asn=s.get(Asn, asn_id), delivery_note="DN-TF-77410",
                               lines=[{"line": 10, "qty": "5400", "batch": "B-2611"}], posting_date=date(2026, 11, 12))
        gr_id, gr_no = gr.id, gr.number
    with sc.act("quality.inspector", at(date(2026, 11, 13), 15)) as s:
        lot = s.execute(select(InspectionLot).where(InspectionLot.gr_id == gr_id)).scalar_one()
        decision = receiving.usage_decision(s, lot, accepted=Decimal(5380), rejected=Decimal(20), defect_code="POROSITY",
                                            reason="Gas porosity found on X-ray in 20 housings")
    sc.relay(at(date(2026, 11, 13), 16))
    sc.note(f"F6 {asn_no} → {gr_no}: 5,400 received; {decision['lot']} 5,380 accepted, 20 rejected → {decision['returnDelivery']}")

    # ---------------------------------------------------------------- F7 invoice → exception → credit note → post
    tf = suppliers["TF001"]
    with sc.act("tf.sales", at(date(2026, 11, 14), 10)) as s:
        irn = payables.expected_irn("33AABCT1234K1ZM", "2026-27", "INV", "INV-TF-8812")
        invoice = payables.capture(s, supplier="TF001", supplier_invoice_no="INV-TF-8812", invoice_date=date(2026, 11, 14), channel="E_INVOICE",
                                   irn=irn, lines=[{"po": po_ids["TF001"][1], "po_line": 10, "qty": "5400", "unit_price": "398",
                                                    "gst_rate": "18", "hsn": "87089900"}])
        inv_id = invoice.id
    with sc.act("tf.sales", at(date(2026, 11, 14), 14)) as s:
        payables.submit_credit_note(s, s.get(Invoice, inv_id), supplier_credit_note_no="CN-TF-221", note_date=date(2026, 11, 14),
                                    reason="Credit for 20 housings rejected for porosity (RD-4410)", lines=[{"invoice_line": 10, "qty": "20"}])
    with sc.act("ap.clerk", at(date(2026, 11, 14), 16)) as s:
        inv = s.get(Invoice, inv_id)
        exc = s.execute(select(InvoiceException).where(InvoiceException.invoice_id == inv_id, InvoiceException.status == "OPEN")).scalar_one()
        payables.resolve_exception(s, inv, exc.id, "CREDIT_NOTE_RECEIVED", "Credit note CN-TF-221 for 20 rejected pcs", "CN-TF-221")
        payables.approve(s, inv)
        posted = payables.post(s, inv, f"{TENANT[0]}|1000|TF001|INV-TF-8812")
    sc.relay(at(date(2026, 11, 14), 17))
    sc.note(f"F7 INV-TF-8812: QTY +20 → CN-TF-221 → matched → posted as ERP {posted['erpDocument']}")

    # ---------------------------------------------------------------- F6 service branch + F7 SES match
    with sc.act("requester", at(date(2026, 11, 3), 10)) as s:
        amc = requisition.create(s, origin="MANUAL", purpose_code="MAINTENANCE", purpose_text="Die maintenance for HPDC cell 2", plant="P100",
                                 lines=[{"item_type": "FREE_TEXT", "purchase_type": "SERVICE", "description": "Die maintenance AMC – November 2026 (T&M)",
                                         "material_group": "SVC-TOOLING", "category": "TOOLING-SERVICES", "qty": "40", "uom": "H",
                                         "price_est_minor": 300_000, "account_assignment_type": "COST_CENTER", "account_assignment_code": "4100",
                                         "need_date": "2026-11-30",
                                         "quotes": [{"supplier": "HTS004", "reference": "HTS/Q/26-27/0438", "date": "2026-10-30"}]}])
        requisition.submit(s, amc)
        amc_id, amc_no = amc.id, amc.number
    sc.approve_all(amc_id, at(date(2026, 11, 3), 14))
    with sc.act("buyer", at(date(2026, 11, 4), 10)) as s:
        svc_po = order.create_from_requisition(s, requisition=amc_no, lines=[10], supplier_code="HTS004", unit_price_minor=300_000)[0]
        svc_po_id, svc_po_no = svc_po.id, svc_po.number
    sc.approve_all(svc_po_id, at(date(2026, 11, 4), 15), "Rate as per quote HTS-Q-1031")
    with sc.act("hts.service", at(date(2026, 11, 5), 10)) as s:
        order.confirm(s, s.get(PurchaseOrder, svc_po_id), "CONFIRMED")
    with sc.act("hts.service", at(date(2026, 11, 28), 17)) as s:
        ses = receiving.create_ses(s, s.get(PurchaseOrder, svc_po_id), method="TIME_MATERIAL", period_from=date(2026, 11, 1),
                                   period_to=date(2026, 11, 30), lines=[{"line": 10, "description": "Die maintenance – 40 h timesheet", "qty": "40",
                                                                         "unit_rate": "3000"}])
        receiving.submit_ses(s, ses)
        ses_id, ses_no = ses.id, ses.number
    sc.approve_all(ses_id, at(date(2026, 11, 30), 10), "Timesheet verified against log book")
    with sc.act("hts.service", at(date(2026, 11, 30), 15)) as s:
        hts_inv = payables.capture(s, supplier="HTS004", supplier_invoice_no="HTS/1107", invoice_date=date(2026, 11, 30), channel="PORTAL",
                                   lines=[{"po": svc_po_no, "po_line": 10, "qty": "40", "unit_price": "3000", "gst_rate": "18"}])
        hts_id = hts_inv.id
    with sc.act("ap.clerk", at(date(2026, 12, 1), 11)) as s:
        payables.approve(s, s.get(Invoice, hts_id))
        payables.post(s, s.get(Invoice, hts_id), f"{TENANT[0]}|1000|HTS004|HTS/1107")
    sc.relay(at(date(2026, 12, 1), 12))
    sc.note(f"F6/F7 service: {amc_no} → {svc_po_no} (approved, not touchless) → {ses_no} approved → HTS/1107 matched first pass and posted")

    # ---------------------------------------------------------------- F4 indexation → cost avoidance
    for contract_id, number, _ in contracts:
        with sc.act("contract.manager", at(date(2026, 12, 28), 11)) as s:
            contract_svc.index_reset(s, s.get(Contract, contract_id), Decimal("100.74"), date(2027, 1, 1))
    sc.note("F4 Q1-2027 LME reset +0.74% absorbed inside the ±3% band → new validity periods + cost avoidance")

    # ---------------------------------------------------------------- F7 payment run → savings validation
    with sc.act("finance.controller", at(date(2027, 1, 13), 10)) as s:
        paid = payables.payment_run(s, date(2027, 1, 13))
    sc.relay(at(date(2027, 1, 13), 11))
    with sc.act("finance.controller", at(date(2027, 1, 14), 10)) as s:
        initiative = s.execute(select(SavingsInitiative)).scalars().first()
        savings.validate(s, initiative)
        register = savings.register(s)
    sc.relay(at(date(2027, 1, 14), 11))
    from app.pic.seed import operations
    sc.note(f"F7 payment run {paid['run']}: {', '.join(p['invoice'] for p in paid['paid'])} paid; "
            f"savings {register[0]['number']}: negotiated {register[0]['negotiatedCr']} Cr, avoidance {register[0]['avoidanceCr']} Cr, "
            f"realised {register[0]['realisedCr']} Cr (validated)")
    operations.run(sc, password)
    intelligence.run(sc)
    clock.set_pinned(None)
    _record_signature(tenant_id)
    return sc.log


# Bump when the signature case changes in a way the AXN dataset packs depend on (users, documents, identifiers). The
# packs REQUIRE this marker, so they are skipped, not half-applied, on a database seeded by an older release.
SIGNATURE_KEY, SIGNATURE_VERSION = "axn-signature-case", "2026.10.29"


def _record_signature(tenant_id: uuid.UUID) -> None:
    from app.pic.models import DatasetLoad
    with tenant_tx(tenant_id) as s:
        s.add(DatasetLoad(tenant_id=tenant_id, key=SIGNATURE_KEY, version=SIGNATURE_VERSION, loaded_at=clock.now(),
                          summary={"notes": ["Axion signature case (seed/axion.py, operations.py, intelligence.py)"]}))
