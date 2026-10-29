"""Shared building blocks for the industry demo tenants (D3 construction, D4 IT services).

Everything business-related still goes through the domain services; this module only wraps the repetitive parts
(tenant bootstrap, users, F8 onboarding, F9 material creation) and the configuration a demo tenant needs on top of
reference.bootstrap (number ranges per document type, template rule versions, the ERP opening budgets and spend history).

Relaying is scoped to the demo tenant: outbox events and ERP messages of that tenant only, and timers are fired one by
one for the tenant's own objects, so no other tenant's timers or tasks are touched.
"""
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import (
    AppUser, BankChangeRequest, Budget, MaterialRequest, NumberRange, RuleSet, SpendLine, Supplier, SupplierCategoryStatus, Timer,
)
from app.pic.platform import audit, clock, integration, outbox, workflow
from app.pic.platform.auth import hash_password
from app.pic.platform.money import fmt_inr as fmt  # noqa: F401  (re-exported for the packs)
from app.pic.seed import reference
from app.pic.seed.axion import Scenario, at


GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def days(n: int) -> timedelta:
    return timedelta(days=n)


def gstin_valid(gstin: str) -> bool:
    """GSTIN check character (mod-36 weighted sum of the first 14 characters)."""
    if len(gstin) != 15 or any(ch not in GSTIN_CHARS for ch in gstin):
        return False
    total = 0
    for i, ch in enumerate(gstin[:14]):
        v = GSTIN_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += v // 36 + v % 36
    return GSTIN_CHARS[(36 - total % 36) % 36] == gstin[14]


# ---------------------------------------------------------------- tenant, users, configuration
def setup_tenant(code: str, name: str, template: str, *, company: tuple[str, str, str], plants: list[tuple[str, str, str]],
                 cost_objects: list[tuple[str, str, str]], holidays: list[date], domain: str, role_user: dict) -> Scenario:
    if not gstin_valid(company[2]):
        raise ValueError(f"GSTIN {company[2]} has a wrong check character")
    reference.deploy_process_definitions()
    tenant_id = reference.create_tenant(code, name, template)
    reference.bootstrap(tenant_id, company=company, plants=plants, cost_objects=cost_objects, holidays=holidays)
    reference.ensure_extensions(tenant_id)
    return Scenario(tenant_id, tenant_code=code, domain=domain, role_user=role_user)


def create_users(sc: Scenario, users: list[tuple[str, str, list[str], dict]], password: str) -> int:
    """Internal users (check-then-insert by e-mail)."""
    added = 0
    with tenant_tx(sc.tenant_id) as s:
        have = set(s.execute(select(AppUser.email)).scalars())
        hashed = hash_password(password)
        for local, name, roles, attrs in users:
            if sc.email(local) in have:
                continue
            s.add(AppUser(tenant_id=sc.tenant_id, email=sc.email(local), full_name=name, password_hash=hashed, roles=roles,
                          attributes=attrs, mfa_enrolled=any(r in roles for r in ("FINANCE_CONTROLLER", "TENANT_ADMIN", "CPO"))))
            added += 1
    return added


def number_range(sc: Scenario, object_type: str, prefix: str, next_value: int, padding: int = 0) -> None:
    """Document-type number range (e.g. subcontracts SC-118, statements of work SOW-4410). Contracts of different types
    share the CONTRACT range in the platform, so the range is switched before each contract type is created."""
    with tenant_tx(sc.tenant_id) as s:
        nr = s.execute(select(NumberRange).where(NumberRange.object_type == object_type)).scalar_one()
        before = {"prefix": nr.prefix, "next": nr.next_value}
        nr.prefix, nr.next_value, nr.padding = prefix, next_value, padding
        audit.record(s, "NUMBER_RANGE", nr.id, "CONFIGURED", object_ref=object_type, before=before,
                     after={"prefix": prefix, "next": next_value}, actor="configuration")


def rule_version(sc: Scenario, key: str, version: str, effective_from: date, patch: dict, description: str) -> None:
    """New effective-dated version of a tenant rule: the current body with `patch` merged in (P14, never edit a version)."""
    with tenant_tx(sc.tenant_id) as s:
        if s.execute(select(RuleSet.id).where(RuleSet.key == key, RuleSet.version == version)).first():
            return
        current = s.execute(select(RuleSet).where(RuleSet.key == key, RuleSet.company_code.is_(None), RuleSet.plant.is_(None),
                                                  RuleSet.category.is_(None), RuleSet.purchase_type.is_(None))
                            .order_by(RuleSet.effective_from.desc())).scalars().first()
        body = {**(current.body if current else {}), **patch}
        rs = RuleSet(tenant_id=sc.tenant_id, key=key, version=version, effective_from=effective_from, body=body, description=description)
        s.add(rs)
        s.flush()
        audit.record(s, "RULE_SET", rs.id, "VERSION_ADDED", object_ref=f"{key}@{version}", after={"patch": patch},
                     actor="configuration")


# Axion's approved FY 2027-28 controlling budgets (company code 1000), loaded by whichever AXN pack runs first so the
# amounts never depend on pack order: (cost object type, code, control, amount in lakh).
AXN_BUDGETS_2027_28 = (("COST_CENTER", "4100", "SOFT", 60), ("COST_CENTER", "4200", "SOFT", 30), ("WBS", "C-2207", "HARD", 200))


def load_budgets(sc: Scenario, budgets: list[tuple[str, str, str, int]], when: datetime) -> None:
    """§12.4 initial load of the approved FY budgets from the ERP (cost object type, code, control, amount in paise)."""
    clock.set_pinned(when)
    with tenant_tx(sc.tenant_id) as s:
        have = {(b.cost_object_type, b.cost_object_code) for b in s.execute(select(Budget)).scalars()}
        for type_, code, control, amount in budgets:
            if (type_, code) in have:
                continue
            s.add(Budget(tenant_id=sc.tenant_id, cost_object_type=type_, cost_object_code=code, fiscal_year="2026-27", control=control,
                         amount_minor=amount, committed_minor=0, consumed_minor=0))
        audit.record(s, "MIGRATION", uuid.uuid5(uuid.NAMESPACE_URL, f"{sc.tenant_code}-budgets"), "INITIAL_LOAD", object_ref="budgets",
                     after={"budgets": [f"{t}:{c}" for t, c, _, _ in budgets]}, actor="migration")


# ---------------------------------------------------------------- relay and timers (tenant-scoped)
def relay(sc: Scenario, when: datetime) -> None:
    from app.pic.worker import system_principal
    clock.set_pinned(when)
    outbox.relay_tenant(sc.tenant_id)
    integration.run_pending(sc.tenant_id, system_principal(sc.tenant_id))
    outbox.relay_tenant(sc.tenant_id)


def fire(sc: Scenario, who: str, kind: str, object_id: uuid.UUID, when: datetime) -> int:
    """Fire this object's due timers of one kind (as tests/pic/test_source_ops.py::_fire does)."""
    fired = 0
    with sc.act(who, when) as s:
        for timer in s.execute(select(Timer).where(Timer.kind == kind, Timer.object_id == object_id, Timer.fired_at.is_(None),
                                                   Timer.due_at <= clock.now())).scalars().all():
            timer.fired_at = clock.now()
            workflow._timer_handlers[kind](s, timer)
            fired += 1
    return fired


# ---------------------------------------------------------------- F8 onboarding
@dataclass
class SupplierSpec:
    code: str
    legal_name: str
    gstin: str
    ifsc: str
    account: str
    terms: str
    categories: list[str]
    user_local: str
    certificates: list[dict]
    scores: tuple[int, int]                 # questionnaire, audit
    questionnaire: dict = field(default_factory=dict)
    segment: str = "ROUTINE"
    incoterms: Optional[str] = None
    address: dict = field(default_factory=dict)


def supplier_email(spec: SupplierSpec) -> str:
    return f"{spec.user_local}@{spec.code.lower()}.example"


def onboard(sc: Scenario, spec: SupplierSpec, password: str, day: date, *, manager: str = "supplier.manager") -> uuid.UUID:
    """F8: registration → supplier profile with bank and certificates → call-back → dual finance approval → qualification."""
    from app.pic.services import supplier as svc

    if not gstin_valid(spec.gstin):
        raise ValueError(f"GSTIN {spec.gstin} of {spec.code} has a wrong check character")
    with sc.act(manager, at(day, 10)) as s:
        existing = s.execute(select(Supplier).where(Supplier.code == spec.code)).scalar_one_or_none()
        if existing is not None:
            return existing.id
        sup = svc.register(s, code=spec.code, legal_name=spec.legal_name, gstin=spec.gstin, pan=spec.gstin[2:12], state_code=spec.gstin[:2],
                           contact_email=supplier_email(spec), categories=spec.categories, payment_terms=spec.terms, incoterms=spec.incoterms,
                           segment=spec.segment, address=spec.address)
        supplier_id = sup.id
        s.add(AppUser(tenant_id=sc.tenant_id, email=supplier_email(spec), full_name=f"{spec.legal_name} – accounts", password_hash=hash_password(password),
                      roles=["SUPPLIER_USER"], attributes={}, supplier_id=sup.id, mfa_enrolled=True))
    with sc.act(supplier_email(spec), at(day, 15)) as s:
        change_no = svc.submit_profile(s, s.get(Supplier, supplier_id), bank_account=spec.account, ifsc=spec.ifsc, holder_name=spec.legal_name,
                                       certificates=spec.certificates)["bankChange"]
    with sc.act(manager, at(day + days(1), 11)) as s:
        change = s.execute(select(BankChangeRequest).where(BankChangeRequest.number == change_no)).scalar_one()
        svc.callback_verify(s, change, f"Called {spec.legal_name} on the landline in the cancelled cheque; holder name and IFSC confirmed")
        change_id = change.id
    sc.approve_all(change_id, at(day + days(1), 15), "Cancelled cheque and bank letter verified")
    with sc.act(manager, at(day + days(2), 10)) as s:
        svc.verify_certificates(s, s.get(Supplier, supplier_id), "Certificates checked against the issuing bodies' registers")
        for category in spec.categories:
            q = svc.start_qualification(s, s.get(Supplier, supplier_id), category)
            svc.record_assessment(s, q, questionnaire=spec.questionnaire or {"capacity": "verified"},
                                  questionnaire_score=Decimal(spec.scores[0]), audit_score=Decimal(spec.scores[1]))
            svc.decide_qualification(s, q, "QUALIFIED", f"Questionnaire {spec.scores[0]}/100, audit {spec.scores[1]}/100; certificates verified")
    return supplier_id


def category_status(sc: Scenario, supplier_id: uuid.UUID) -> dict[str, str]:
    with tenant_tx(sc.tenant_id) as s:
        return {r.category: r.status for r in s.execute(select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == supplier_id)).scalars()}


# ---------------------------------------------------------------- F9 material / service masters
def service_master(sc: Scenario, requester: str, when: datetime, *, description: str, type_: str, group: str, category: str, uom: str,
                   hsn: str, attributes: dict) -> str:
    """F9: material request → duplicate check → four steward domains → golden record → ERP material master."""
    from app.pic.services import mdm

    with sc.act(requester, when) as s:
        request = mdm.create_request(s, description=description, type=type_, material_group=group, category=category, base_uom=uom,
                                     hsn_code=hsn, attributes=attributes)
        request_id, status = request.id, request.status
    if status == "DUPLICATE_BLOCKED":
        raise RuntimeError(f"{description}: blocked as duplicate")
    sc.approve_all(request_id, when + timedelta(hours=3), "Domain data complete and correct")
    relay(sc, when + timedelta(hours=3, minutes=5))
    with tenant_tx(sc.tenant_id) as s:
        from app.pic.models import Material
        request = s.get(MaterialRequest, request_id)
        return s.get(Material, request.material_id).number


# ---------------------------------------------------------------- ERP history (go-live load)
def erp_vendors(sc: Scenario, vendors: list[tuple[str, str, str, list[str]]], when: datetime) -> dict[str, uuid.UUID]:
    """ERP vendor masters loaded at go-live (§12.4): code, legal name, terms, qualified categories."""
    clock.set_pinned(when)
    with sc.act("admin", when) as s:
        ids = {x.code: x.id for x in s.execute(select(Supplier)).scalars()}
        admin_id = s.info["principal"].user_id
        for code, name, terms, categories in vendors:
            if code in ids:
                continue
            supplier = Supplier(tenant_id=sc.tenant_id, code=code, legal_name=name, status="ACTIVE", country="IN", payment_terms=terms,
                                risk_tier="LOW", screening={"outcome": "NOT_SCREENED", "source": "ERP_INITIAL_LOAD", "erpVendor": code},
                                created_by=admin_id)
            s.add(supplier)
            s.flush()
            ids[code] = supplier.id
            for category in categories:
                s.add(SupplierCategoryStatus(tenant_id=sc.tenant_id, supplier_id=supplier.id, category=category, status="QUALIFIED",
                                             qualified_on=date(2025, 4, 1), created_by=admin_id))
            audit.record(s, "SUPPLIER", supplier.id, "MIGRATED", object_ref=code, after={"source": "ERP vendor master", "legalName": name},
                         actor="migration")
    return ids


def spend_history(sc: Scenario, rows: list[tuple[str, str, str, str, str, int, bool]], ids: dict[str, uuid.UUID], when: datetime,
                  ns: uuid.UUID, first_doc: int) -> int:
    """Posted ERP invoices of the last twelve months (period, vendor, category, plant, cost object, amount, contracted)."""
    clock.set_pinned(when)
    with sc.act("ap.clerk", when) as s:
        if s.execute(select(SpendLine.id).where(SpendLine.source == "ERP_HISTORY")).first():
            return 0
        user = s.info["principal"].user_id
        doc = first_doc
        for period, vendor, category, plant, cost_object, amount, contracted, *text in rows:
            doc += 1
            ref = f"ERP-{doc}"
            s.add(SpendLine(tenant_id=sc.tenant_id, invoice_line_id=uuid.uuid5(ns, ref), invoice_ref=ref, po_ref=f"45{doc % 100000000:08d}",
                            supplier_id=ids[vendor], category=category, material_group=category, plant=plant, company_code="1000",
                            cost_object=cost_object, period=period, amount_minor=amount, currency="INR", contracted=contracted, addressable=True,
                            maverick_flags=[], classification_confidence=Decimal("1.000"), description=(text[0] if text else category)[:300],
                            price_variance_minor=0, source="ERP_HISTORY", created_by=user))
        s.flush()
        audit.record(s, "SPEND_LINE", uuid.uuid5(ns, "erp-history"), "MIGRATED", object_ref="ERP spend history",
                     after={"lines": len(rows), "periods": [rows[0][0], rows[-1][0]] if rows else []}, actor="migration")
    return len(rows)
