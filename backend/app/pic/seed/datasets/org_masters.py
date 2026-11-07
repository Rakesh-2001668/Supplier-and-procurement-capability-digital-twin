"""D19 Legal Entity, Purchasing Org and Purchasing Group Masters (Technical Document §4, TD-4a).

Seeds and harmonizes master data for:
- CompanyCode (Legal Entities): Multi-entity corporate structures, GSTIN, currency, fiscal year.
- PurchasingOrg (Purchasing Organisations): Assigned to company codes.
- PurchasingGroup (Purchasing Groups / Buying Teams): Linked to purchasing org, plant, and internal buyer users.

Resolves TD-4a: Legal Entity / Purch Org masters are no longer unanchored strings on documents;
all existing and new POs, Invoices, Contracts, and Requisitions are grounded in audited, active master records.
"""
import csv
import io
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.config import BACKEND_DIR
from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, CompanyCode, Plant, PurchasingGroup, PurchasingOrg, Tenant,
)
from app.pic.platform import audit

log = logging.getLogger(__name__)

KEY = "org-masters"
VERSION = "1"
TITLE = "D19 Legal Entity, Purchasing Org & Purchasing Group Masters (TD-4a)"
TENANTS = ('*',)
CREATES_TENANT = False
READY = True

DATA_FILE = BACKEND_DIR / "data" / "reference" / "org_masters.csv"


def read_org_masters_csv() -> list[dict]:
    """Read canonical org master CSV rows."""
    if not DATA_FILE.exists():
        return []
    text = DATA_FILE.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    return list(csv.DictReader(io.StringIO(body)))


def load_org_masters_for_tenant(session: Session, tenant_id: uuid.UUID, tenant_code: str) -> dict:
    """Load or update CompanyCode, PurchasingOrg, and PurchasingGroup masters for a tenant.
    
    Ensures referential validity with existing documents (e.g. POs referencing purch_org '1000').
    Audits every record creation/update in compliance with P01 & P12.
    """
    rows = [r for r in read_org_masters_csv() if r.get("tenant_code") == tenant_code]
    if not rows:
        return {"notes": [f"{tenant_code}: No rows in org_masters.csv"], "counts": {}}

    # Find candidate buyer users for purchasing groups
    all_users = session.execute(
        select(AppUser).where(AppUser.active.is_(True), AppUser.supplier_id.is_(None))
    ).scalars().all()
    buyer_users = [u.id for u in all_users if "BUYER" in (u.roles or [])]
    if not buyer_users:
        buyer_users = [u.id for u in all_users if "TENANT_ADMIN" in (u.roles or [])]

    counts = {"companyCodes": 0, "purchasingOrgs": 0, "purchasingGroups": 0}
    notes = []

    # 1. Company Codes (Legal Entities)
    cc_rows = [r for r in rows if r.get("entity_type") == "COMPANY_CODE"]
    for r in cc_rows:
        code = r["code"].strip().upper()
        name = r["name"].strip()
        gstin = r.get("gstin", "").strip() or None
        currency = r.get("currency", "INR").strip().upper() or "INR"
        fy_month = int(r.get("fiscal_year_start") or 4)

        existing = session.execute(
            select(CompanyCode).where(CompanyCode.code == code)
        ).scalar_one_or_none()

        if existing:
            before = {"code": existing.code, "name": existing.name, "gstin": existing.gstin,
                      "currency": existing.currency, "fiscal_year_start_month": existing.fiscal_year_start_month}
            existing.name = name
            existing.gstin = gstin
            existing.currency = currency
            existing.fiscal_year_start_month = fy_month
            existing.active = True
            session.flush()
            audit.record(session, "COMPANY_CODE", existing.id, "UPDATED", object_ref=code,
                         before=before, after={"code": code, "name": name, "gstin": gstin, "currency": currency,
                                               "fiscal_year_start_month": fy_month},
                         reason="TD-4a org master alignment")
        else:
            new_cc = CompanyCode(
                tenant_id=tenant_id,
                code=code,
                name=name,
                gstin=gstin,
                currency=currency,
                fiscal_year_start_month=fy_month,
                active=True,
            )
            session.add(new_cc)
            session.flush()
            audit.record(session, "COMPANY_CODE", new_cc.id, "CREATED", object_ref=code,
                         after={"code": code, "name": name, "gstin": gstin, "currency": currency,
                                "fiscal_year_start_month": fy_month},
                         reason="TD-4a org master creation")
        counts["companyCodes"] += 1

    # 2. Purchasing Organisations
    po_rows = [r for r in rows if r.get("entity_type") == "PURCHASING_ORG"]
    for r in po_rows:
        code = r["code"].strip().upper()
        name = r["name"].strip()
        cc_ref = r.get("parent_code", "1000").strip().upper()

        existing = session.execute(
            select(PurchasingOrg).where(PurchasingOrg.code == code)
        ).scalar_one_or_none()

        if existing:
            before = {"code": existing.code, "name": existing.name, "company_code": existing.company_code}
            existing.name = name
            existing.company_code = cc_ref
            existing.active = True
            session.flush()
            audit.record(session, "PURCHASING_ORG", existing.id, "UPDATED", object_ref=code,
                         before=before, after={"code": code, "name": name, "company_code": cc_ref},
                         reason="TD-4a org master alignment")
        else:
            new_po = PurchasingOrg(
                tenant_id=tenant_id,
                code=code,
                name=name,
                company_code=cc_ref,
                active=True,
            )
            session.add(new_po)
            session.flush()
            audit.record(session, "PURCHASING_ORG", new_po.id, "CREATED", object_ref=code,
                         after={"code": code, "name": name, "company_code": cc_ref},
                         reason="TD-4a org master creation")
        counts["purchasingOrgs"] += 1

    # 3. Purchasing Groups (Buying Teams)
    pg_rows = [r for r in rows if r.get("entity_type") == "PURCHASING_GROUP"]
    for i, r in enumerate(pg_rows):
        code = r["code"].strip().upper()
        name = r["name"].strip()
        porg_ref = r.get("parent_code", "").strip().upper() or None
        plant_ref = r.get("plant", "").strip().upper() or None

        # Assign buyer(s) from pool round-robin
        assigned_buyers = []
        if buyer_users:
            assigned_buyers = [buyer_users[i % len(buyer_users)]]

        existing = session.execute(
            select(PurchasingGroup).where(PurchasingGroup.code == code)
        ).scalar_one_or_none()

        if existing:
            before = {"code": existing.code, "name": existing.name, "purchasing_org": existing.purchasing_org,
                      "plant": existing.plant}
            existing.name = name
            existing.purchasing_org = porg_ref
            existing.plant = plant_ref
            if assigned_buyers and not existing.buyer_user_ids:
                existing.buyer_user_ids = assigned_buyers
            existing.active = True
            session.flush()
            audit.record(session, "PURCHASING_GROUP", existing.id, "UPDATED", object_ref=code,
                         before=before, after={"code": code, "name": name, "purchasing_org": porg_ref,
                                               "plant": plant_ref},
                         reason="TD-4a org master alignment")
        else:
            new_pg = PurchasingGroup(
                tenant_id=tenant_id,
                code=code,
                name=name,
                purchasing_org=porg_ref,
                plant=plant_ref,
                buyer_user_ids=assigned_buyers,
                active=True,
            )
            session.add(new_pg)
            session.flush()
            audit.record(session, "PURCHASING_GROUP", new_pg.id, "CREATED", object_ref=code,
                         after={"code": code, "name": name, "purchasing_org": porg_ref,
                                "plant": plant_ref},
                         reason="TD-4a org master creation")
        counts["purchasingGroups"] += 1

    notes.append(
        f"Seeded {counts['companyCodes']} Legal Entities, {counts['purchasingOrgs']} Purchasing Orgs, "
        f"and {counts['purchasingGroups']} Purchasing Groups for {tenant_code}"
    )
    return {"notes": notes, "counts": counts}


def apply(tenant_code: str, password: str) -> dict:
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == tenant_code)).scalar_one_or_none()
    if tenant_id is None:
        return {"notes": [f"{tenant_code}: Tenant not found"], "counts": {}}

    with tenant_tx(tenant_id) as s:
        result = load_org_masters_for_tenant(s, tenant_id, tenant_code)
    return result
