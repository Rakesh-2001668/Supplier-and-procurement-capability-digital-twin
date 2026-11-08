"""Load hosted catalogue items into a tenant from a CSV file (M04 CATALOGUE channel, flow fixes A11).

    python -m app.pic.tools.load_catalogue --tenant KAC --file catalogue.csv [--dry-run] [--reason "Q3 price list"]
    python -m app.pic.tools.load_catalogue --sample catalogue_sample.csv        (writes the format, one example row)

Columns (header row, UTF-8; ``price_minor`` in paise, or ``price`` in rupees):
    supplier, supplier_part_no, description, material_group, uom, price_minor | price          required
    category, currency, gst_rate, hsn_code, material, contract, valid_from, valid_to, lead_time_days   optional

Every row goes through the same validation as ``POST /v1/catalogue-items`` (services/catalogue.py): supplier not blocked, positive price,
GST slab, HSN format, validity order, active material, live contract of the same supplier, one active price per part and period. A row
whose supplier part already has an active item with the same ``valid_from`` changes that item (audited before / after); any other row
creates an item. The load is all or nothing: one invalid row and nothing is written; ``--dry-run`` validates and rolls back.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import Tenant
from app.pic.platform.auth import Principal
from app.pic.platform.errors import Problem

ACTOR = "integration:CATALOGUE_LOAD"
REQUIRED = ("supplier", "supplier_part_no", "description", "material_group", "uom")
OPTIONAL = ("price_minor", "price", "category", "currency", "gst_rate", "hsn_code", "material", "contract", "valid_from", "valid_to",
            "lead_time_days")
SAMPLE = [{"supplier": "SUP-1001", "supplier_part_no": "HTS-PM-STD", "description": "Preventive maintenance kit, standard", "material_group": "MRO",
           "category": "MRO", "uom": "EA", "price_minor": "125000", "currency": "INR", "gst_rate": "18", "hsn_code": "84849000", "material": "",
           "contract": "", "valid_from": "2026-04-01", "valid_to": "2027-03-31", "lead_time_days": "5"}]


@dataclass
class IntegrationPrincipal(Principal):
    @property
    def actor(self) -> str:
        return ACTOR


class _Rollback(Exception):
    pass


def read_rows(text: str) -> tuple[list[dict], list[dict]]:
    reader = csv.DictReader(io.StringIO(text))
    header = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
    errors = [{"line": 0, "message": f"column {c} is missing"} for c in REQUIRED if c not in header]
    if "price_minor" not in header and "price" not in header:
        errors.append({"line": 0, "message": "column price_minor (paise) or price (rupees) is missing"})
    rows = []
    for number, raw in enumerate(reader, start=2):
        data = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        if not any(data.values()):
            continue
        if not data.get("price_minor") and data.get("price"):
            try:
                data["price_minor"] = str(int((Decimal(data["price"]) * 100).to_integral_value()))
            except InvalidOperation:
                errors.append({"line": number, "message": f"price '{data['price']}' is not a number"})
                continue
        data.pop("price", None)
        row = {k: v for k, v in data.items() if k in REQUIRED + OPTIONAL and v != ""}
        rows.append({"line": number, "data": row})
    return rows, errors


def load(tenant_code: str, text: str, *, reason: str = "catalogue load", dry_run: bool = False) -> dict:
    from app.pic.services import catalogue

    rows, errors = read_rows(text)
    summary = {"tenant": tenant_code, "rows": len(rows), "created": 0, "changed": 0, "unchanged": 0, "errors": errors, "dryRun": dry_run}
    if errors:
        summary["status"] = "REFUSED"
        return summary
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == tenant_code)).scalar_one_or_none()
    if tenant_id is None:
        raise SystemExit(f"Tenant {tenant_code} does not exist")
    principal = IntegrationPrincipal(user_id=uuid.UUID(int=0), tenant_id=tenant_id, tenant_code=tenant_code, email="integration.catalogue",
                                     name="Catalogue load", roles=[], scopes={"sourcing:manage"}, agent_code=None)
    try:
        with tenant_tx(tenant_id, principal.user_id, principal) as session:
            for entry in rows:
                try:
                    with session.begin_nested():
                        outcome, _ = catalogue.upsert(session, dict(entry["data"]), reason)
                    summary[outcome.lower()] += 1
                except Problem as exc:
                    summary["errors"].append({"line": entry["line"], "code": exc.code, "message": exc.detail})
            if summary["errors"] or dry_run:
                raise _Rollback()
    except _Rollback:
        pass
    summary["status"] = "REFUSED" if summary["errors"] else ("VALIDATED" if dry_run else "LOADED")
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Load hosted catalogue items from a CSV file")
    parser.add_argument("--tenant")
    parser.add_argument("--file")
    parser.add_argument("--reason", default="catalogue load")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sample", help="write a sample file in the expected format and exit")
    args = parser.parse_args(argv)
    if args.sample:
        with open(args.sample, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(SAMPLE[0]))
            writer.writeheader()
            writer.writerows(SAMPLE)
        print(f"sample written to {args.sample}")
        return 0
    if not args.tenant or not args.file:
        parser.error("--tenant and --file are required")
    summary = load(args.tenant, Path(args.file).read_bytes().decode("utf-8-sig"), reason=args.reason, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary["status"] != "REFUSED" else 2


if __name__ == "__main__":
    sys.exit(main())
