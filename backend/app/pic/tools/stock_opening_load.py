"""Load a client's opening stock into the PIC stock ledger: ``python -m app.pic.tools.stock_opening_load --tenant KAC --file opening_stock.csv``.

The production path for the opening position of a tenant that goes live on PIC: the client exports its ERP stock list (SAP MARD / MCHB / MKOL / MSKA
joined with the batch master MCH1 and the material valuation MBEW), maps it to this layout, and this loader posts every balance through the one
posting primitive of the ledger (``stock_ledger.post_movement``) as movement 561 with reference type OPENING_BALANCE, valued at the material's standard
price. The mock opening position of tenant KAC (``data/erp_mock/KAC_INVENTORY/opening_stock.csv``, ILLUSTRATIVE SAMPLE) uses it unchanged.

File (UTF-8 CSV with a header row; column order is free, extra columns are ignored with a warning)

    material           PIC material number (as loaded from the ERP, e.g. 11000001)            required
    plant              plant code                                                              required
    storage_location   storage location code of that plant (e.g. 0001)                          required
    stock_type         UNRESTRICTED | QUALITY | BLOCKED | CONSIGNMENT | SUBCONTRACTOR          required
    batch              batch number; required for a batch-managed material, else may be empty
    qty                quantity in the base unit, not negative, at most 3 decimals              required (0 = nothing to post, listed in the report)
    uom                unit of measure; must equal the material's base unit                    required
    expiry             ISO date (YYYY-MM-DD) of the batch; required for expiry-managed material in live stock, recorded in the batch master
    valuation          value of the line in INR as the ERP stock list shows it (for the reconciliation only; PIC values at its standard price)

The whole file is validated first and refused if any line is wrong (nothing is written; every error names its line); ``--dry-run`` validates and
reports without writing. Idempotent per (material, plant, storage location, stock type, batch): a balance that already has an opening movement is
skipped (so the file can be loaded again, or extended), and a balance that already holds other postings is skipped with a warning (an opening balance
is only ever posted into an empty balance). The report reconciles the file's valuation column with PIC's value at the standard price, per plant.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from sqlalchemy import func, select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import Material, Plant, StockBatch, StockMovement, StorageLocation, Tenant
from app.pic.platform import audit, clock
from app.pic.platform.auth import Principal
from app.pic.services import stock_ledger

log = logging.getLogger("pic.stock_opening_load")

ACTOR = "integration:STOCK_OPENING"
NS = uuid.UUID("5e3a7c1d-2b94-4f60-8d1a-9c4e6b7f2a10")
REQUIRED = ("material", "plant", "storage_location", "stock_type", "qty", "uom")
OPTIONAL = ("batch", "expiry", "valuation")
STOCK_TYPES = stock_ledger.STOCK_TYPES
EXPIRY_TYPES = ("UNRESTRICTED", "QUALITY", "BLOCKED", "CONSIGNMENT")
DIFFERENCE_TOLERANCE_MINOR = 100            # a line whose value differs by more than INR 1.00 is listed in the reconciliation
CHUNK = 1000


class LoadRefused(Exception):
    """The file cannot be loaded: carries the summary (errors with their line numbers)."""

    def __init__(self, summary: dict):
        super().__init__(f"{len(summary.get('errors', []))} error(s) in the opening-stock file")
        self.summary = summary


@dataclass
class IntegrationPrincipal(Principal):
    @property
    def actor(self) -> str:
        return ACTOR


# ---------------------------------------------------------------- parsing
def read_file(path) -> tuple[list[dict], list[dict], list[str], str]:
    """(rows, errors, warnings, sha256) of the file; a file-level problem (unreadable, missing column) is an error with line 0."""
    data = Path(path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], [{"line": 0, "code": "NOT_UTF8", "message": "the file is not UTF-8"}], [], sha
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    errors = [{"line": 0, "code": "MISSING_COLUMN", "message": f"column {c} is missing from the header"} for c in REQUIRED if c not in header]
    warnings = [f"column {c} is not used" for c in header if c and c not in REQUIRED + OPTIONAL]
    rows = []
    if not errors:
        for number, record in enumerate(reader, start=2):
            row = {k.strip().lower(): (v or "").strip() for k, v in record.items() if k}
            if any(row.values()):
                row["_line"] = number
                rows.append(row)
        if not rows:
            errors.append({"line": 0, "code": "EMPTY_FILE", "message": "the file has a header but no lines"})
    return rows, errors, warnings, sha


def _decimal(value: str) -> Optional[Decimal]:
    try:
        number = Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _chunks(items, size=CHUNK):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start:start + size]


# ---------------------------------------------------------------- validation
def validate(session, rows: list[dict]) -> dict:
    """Check every line against the tenant's masters. Returns {"lines": [valid line dicts], "errors": [...], "warnings": [...]}; a valid line carries
    the material row, the quantity, the expiry and the valuation in minor units."""
    numbers = {r["material"] for r in rows if r.get("material")}
    materials = {}
    for part in _chunks(numbers):
        materials.update({m.number: m for m in session.execute(select(Material).where(Material.number.in_(part))).scalars()})
    plants = {p.code: p for p in session.execute(select(Plant)).scalars()}
    locations = {(l.plant, l.code): l for l in session.execute(select(StorageLocation)).scalars()}
    batches = {}
    for part in _chunks({m.id for m in materials.values()}):
        batches.update({(b.material_id, b.batch): b for b in session.execute(select(StockBatch).where(StockBatch.material_id.in_(part))).scalars()})
    errors, warnings, lines, seen, batch_dates = [], [], [], {}, {}

    def bad(row, field, code, message):
        errors.append({"line": row["_line"], "field": field, "code": code, "message": message})

    for row in rows:
        before = len(errors)
        material = materials.get(row.get("material", ""))
        if not row.get("material"):
            bad(row, "material", "MISSING_VALUE", "material is empty")
        elif material is None:
            bad(row, "material", "UNKNOWN_MATERIAL", f"material {row['material']} does not exist in this tenant (load the material master first)")
        elif material.type != "STOCK" or material.status != "ACTIVE":
            bad(row, "material", "NOT_A_STOCK_MATERIAL", f"material {row['material']} is {material.type} / {material.status}: only active stock materials hold stock")
        plant = plants.get(row.get("plant", ""))
        if plant is None:
            bad(row, "plant", "UNKNOWN_PLANT", f"plant {row.get('plant') or '(empty)'} does not exist in this tenant")
        elif not plant.active:
            bad(row, "plant", "PLANT_INACTIVE", f"plant {plant.code} is deactivated in the organisation master")
        location = locations.get((row.get("plant", ""), row.get("storage_location", "")))
        if plant is not None and location is None:
            bad(row, "storage_location", "UNKNOWN_LOCATION", f"storage location {row.get('storage_location') or '(empty)'} does not exist at plant {row['plant']}")
        elif location is not None and not location.active:
            bad(row, "storage_location", "LOCATION_INACTIVE", f"storage location {location.code} of plant {location.plant} is deactivated")
        stock_type = row.get("stock_type", "").upper()
        if stock_type not in STOCK_TYPES:
            bad(row, "stock_type", "BAD_STOCK_TYPE", f"stock type {row.get('stock_type') or '(empty)'} is not one of {', '.join(STOCK_TYPES)}")
        qty = _decimal(row.get("qty", ""))
        if qty is None:
            bad(row, "qty", "BAD_NUMBER", f"quantity {row.get('qty') or '(empty)'} is not a number")
        elif qty < 0:
            bad(row, "qty", "NEGATIVE_QTY", f"quantity {qty} is negative: an opening balance cannot be negative")
        elif qty.quantize(stock_ledger.QTY_PLACES) != qty:
            bad(row, "qty", "TOO_MANY_DECIMALS", f"quantity {qty} has more than three decimals (stock is kept to 0.001)")
        if material is not None and row.get("uom") and row["uom"].upper() != (material.base_uom or "").upper():
            bad(row, "uom", "UOM_MISMATCH", f"unit {row['uom']} differs from the base unit {material.base_uom} of material {material.number}: convert the quantity first")
        elif not row.get("uom"):
            bad(row, "uom", "MISSING_VALUE", "unit of measure is empty")
        if material is not None and plant is not None:
            planned = (material.attributes or {}).get("plants")
            if planned and plant.code not in planned:
                bad(row, "plant", "MATERIAL_NOT_AT_PLANT", f"material {material.number} is not maintained at plant {plant.code} (it is at {', '.join(planned)})")
        batch = row.get("batch", "")
        if len(batch) > 30:
            bad(row, "batch", "BATCH_TOO_LONG", f"batch {batch} is longer than 30 characters")
        expiry = None
        if row.get("expiry"):
            try:
                expiry = date.fromisoformat(row["expiry"])
            except ValueError:
                bad(row, "expiry", "BAD_DATE", f"expiry {row['expiry']} is not an ISO date (YYYY-MM-DD)")
            if expiry is not None and not batch:
                bad(row, "expiry", "EXPIRY_WITHOUT_BATCH", "an expiry date belongs to a batch: give the batch")
        attrs = (material.attributes or {}) if material is not None else {}
        if material is not None and attrs.get("batchManaged") and not batch and qty and qty > 0:
            bad(row, "batch", "BATCH_REQUIRED", f"material {material.number} is batch managed: the line needs a batch")
        if material is not None and attrs.get("expiryManaged") and qty and qty > 0 and stock_type in EXPIRY_TYPES and batch and not row.get("expiry"):
            bad(row, "expiry", "EXPIRY_REQUIRED", f"material {material.number} is expiry managed: batch {batch} needs an expiry date")
        if material is not None and batch and expiry is not None:
            first = batch_dates.setdefault((material.number, batch), (expiry, row["_line"]))
            if first[0] != expiry:
                bad(row, "expiry", "BATCH_EXPIRY_CONFLICT", f"batch {batch} of {material.number} has expiry {first[0].isoformat()} on line {first[1]} and {expiry.isoformat()} here: "
                    "a batch has one expiry date (the batch master is per material, not per plant)")
            known = batches.get((material.id, batch))
            if known is not None and known.expiry_date is not None and known.expiry_date != expiry:
                bad(row, "expiry", "BATCH_EXPIRY_CONFLICT", f"batch {batch} of {material.number} already has expiry {known.expiry_date.isoformat()} in the batch master")
        valuation = None
        if row.get("valuation"):
            amount = _decimal(row["valuation"])
            if amount is None or amount < 0:
                bad(row, "valuation", "BAD_VALUATION", f"valuation {row['valuation']} is not a non-negative amount in INR")
            else:
                valuation = int((amount * 100).to_integral_value())
        key = (row.get("material"), row.get("plant"), row.get("storage_location"), stock_type, batch)
        if len(errors) == before:           # a line that is wrong anyway is not also reported as a duplicate
            if key in seen:
                bad(row, "material", "DUPLICATE_KEY", f"the same balance (material, plant, storage location, stock type, batch) is already on line {seen[key]}")
            else:
                seen[key] = row["_line"]
        if len(errors) == before and material is not None and plant is not None:
            if material.standard_price_minor is None:
                warnings.append(f"line {row['_line']}: material {material.number} has no standard price, the movement is posted without a value")
            lines.append({"line": row["_line"], "material": material, "plant": plant.code, "sloc": row["storage_location"], "stock_type": stock_type,
                          "batch": batch, "qty": qty, "expiry": expiry, "valuation": valuation, "key": key})
    return {"lines": lines, "errors": errors, "warnings": warnings}


def _existing(session, lines: list[dict]) -> tuple[set, set]:
    """(keys with an opening movement, keys with other postings) among the lines' balances."""
    opened, used = set(), set()
    ids = {l["material"].id for l in lines}
    plants = {l["plant"] for l in lines}
    for part in _chunks(ids):
        for m, p, s, t, b, opening, other in session.execute(
                select(StockMovement.material_id, StockMovement.plant, StockMovement.storage_location, StockMovement.stock_type, StockMovement.batch,
                       func.count().filter((StockMovement.movement_type == "561") & (StockMovement.reference_type == "OPENING_BALANCE")),
                       func.count().filter(~((StockMovement.movement_type == "561") & (StockMovement.reference_type == "OPENING_BALANCE"))))
                .where(StockMovement.material_id.in_(part), StockMovement.plant.in_(plants))
                .group_by(StockMovement.material_id, StockMovement.plant, StockMovement.storage_location, StockMovement.stock_type, StockMovement.batch)):
            if opening:
                opened.add((m, p, s, t, b))
            elif other:
                used.add((m, p, s, t, b))
    return opened, used


def _value(material: Material, qty: Decimal) -> Optional[int]:
    return stock_ledger.value_of(material, qty)


def reconcile(lines: list[dict]) -> dict:
    """The file's valuation column against PIC's value of the same quantities at the standard price, in total and per plant."""
    total = {"fileMinor": 0, "picMinor": 0, "lines": 0}
    by_plant: dict = defaultdict(lambda: {"fileMinor": 0, "picMinor": 0, "lines": 0})
    differing = []
    for l in lines:
        pic = _value(l["material"], l["qty"])
        if l["valuation"] is None:
            continue
        for bucket in (total, by_plant[l["plant"]]):
            bucket["fileMinor"] += l["valuation"]
            bucket["picMinor"] += pic or 0
            bucket["lines"] += 1
        if abs((pic or 0) - l["valuation"]) > DIFFERENCE_TOLERANCE_MINOR:
            differing.append({"line": l["line"], "material": l["material"].number, "plant": l["plant"], "batch": l["batch"], "fileMinor": l["valuation"],
                              "picMinor": pic, "differenceMinor": (pic or 0) - l["valuation"]})
    for bucket in [total, *by_plant.values()]:
        bucket["differenceMinor"] = bucket["picMinor"] - bucket["fileMinor"]
    return {**total, "byPlant": {k: dict(v) for k, v in sorted(by_plant.items())}, "differingLines": differing[:50], "differingCount": len(differing),
            "status": "RECONCILED" if not differing else "DIFFERENCES"}


# ---------------------------------------------------------------- the load
def load(tenant_code: str, path, *, dry_run: bool = False, when: Optional[datetime] = None, strict: bool = False) -> dict:
    """Validate and post the opening stock in ``path`` for the tenant. Returns the summary; raises ``LoadRefused`` when the file has errors (nothing is
    written then) or, with ``strict``, when the valuation column does not reconcile."""
    path = Path(path)
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == tenant_code)).scalar_one_or_none()
    if tenant is None:
        raise LoadRefused({"errors": [{"line": 0, "code": "UNKNOWN_TENANT", "message": f"tenant {tenant_code} does not exist"}]})
    rows, errors, warnings, sha = read_file(path)
    summary: dict = {"tenant": tenant_code, "file": path.name, "sha256": sha, "dryRun": dry_run, "rows": len(rows), "errors": errors, "warnings": warnings}
    if errors:
        summary["status"] = "REFUSED"
        raise LoadRefused(summary)
    if when:
        clock.set_pinned(when)
    principal = IntegrationPrincipal(user_id=uuid.UUID(int=0), tenant_id=tenant.id, tenant_code=tenant_code, email="integration.stock_opening",
                                     name="Opening stock load", roles=[], scopes={"inventory:post"}, agent_code=None)
    with tenant_tx(tenant.id, principal.user_id, principal) as session:
        checked = validate(session, rows)
        summary["errors"], summary["warnings"] = checked["errors"], warnings + checked["warnings"]
        if checked["errors"]:
            summary["status"] = "REFUSED"
            raise LoadRefused(summary)
        lines = checked["lines"]
        opened, used = _existing(session, lines)
        todo, zero, loaded, in_use = [], [], [], []
        for l in lines:
            key = (l["material"].id, l["plant"], l["sloc"], l["stock_type"], l["batch"])
            if key in opened:
                loaded.append(l)
            elif key in used:
                in_use.append(l)
                summary["warnings"].append(f"line {l['line']}: {l['material'].number} {l['plant']}/{l['sloc']} {l['stock_type']} batch '{l['batch']}' already holds other "
                                           "postings: skipped (an opening balance is only posted into an empty balance)")
            elif l["qty"] == 0:
                zero.append(l)
            else:
                todo.append(l)
        summary.update({"toPost": len(todo), "alreadyLoaded": len(loaded), "skippedInUse": len(in_use), "zeroQuantity": len(zero),
                        "plants": sorted({l["plant"] for l in lines}), "materials": len({l["material"].id for l in lines}),
                        "reconciliation": reconcile(lines)})
        if strict and summary["reconciliation"]["status"] != "RECONCILED":
            summary["status"] = "REFUSED"
            raise LoadRefused({**summary, "errors": [{"line": 0, "code": "NOT_RECONCILED", "message":
                              f"{summary['reconciliation']['differingCount']} line(s) differ from the file's valuation by more than INR 1.00"}]})
        if dry_run:
            summary.update(status="DRY_RUN", posted=0, postedValueMinor=0, batchesRecorded=0)
            return summary
        load_id = uuid.uuid5(NS, f"{tenant_code}|{sha}")
        posted_value, batches_added, seen_batch = 0, 0, set()
        with session.no_autoflush:
            for l in todo:
                material = l["material"]
                movement = stock_ledger.post_movement(
                    session, material_id=material.id, plant=l["plant"], sloc=l["sloc"], stock_type=l["stock_type"], batch=l["batch"], qty=l["qty"],
                    movement="561", ref_type="OPENING_BALANCE", ref_id=load_id, ref=f"OPEN-{tenant_code}-{material.number}"[:60],
                    posting_ref=f"OPEN-{tenant_code}", reason_code="OPENING")
                posted_value += (movement.value_minor or 0) if movement is not None else 0
                if l["batch"] and l["expiry"] is not None and (material.id, l["batch"]) not in seen_batch:
                    seen_batch.add((material.id, l["batch"]))
                    if session.execute(select(StockBatch.id).where(StockBatch.material_id == material.id, StockBatch.batch == l["batch"])).first() is None:
                        session.add(StockBatch(tenant_id=tenant.id, material_id=material.id, batch=l["batch"], expiry_date=l["expiry"], source="OPENING_BALANCE",
                                               note=f"opening balance {path.name}", created_by=principal.user_id))
                        batches_added += 1
        if todo:
            session.flush()
            audit.record(session, "MIGRATION", load_id, "INITIAL_LOAD", object_ref=f"{tenant_code} opening stock {path.name}", actor=ACTOR,
                         after={"file": path.name, "sha256": sha, "balances": len(todo), "valueMinor": posted_value, "plants": summary["plants"],
                                "alreadyLoaded": len(loaded), "skippedInUse": len(in_use), "zeroQuantity": len(zero), "batchesRecorded": batches_added})
        summary.update(status="LOADED" if todo else "NOTHING_TO_POST", posted=len(todo), postedValueMinor=posted_value, batchesRecorded=batches_added)
        summary["stockOuts"] = [{"material": l["material"].number, "plant": l["plant"]} for l in zero]
    return summary


# ---------------------------------------------------------------- command line
def money(minor: Optional[int]) -> str:
    return f"{(minor or 0) / 100:,.2f}"


def format_report(summary: dict) -> str:
    lines = [f"Opening stock {summary.get('file')} -> tenant {summary.get('tenant')}: {summary.get('status', '?')}"
             + (" (dry run, nothing written)" if summary.get("dryRun") else "")]
    if summary.get("errors"):
        lines.append(f"  {len(summary['errors'])} error(s), nothing was loaded:")
        lines += [f"    line {e['line']}: {e.get('code')} {e['message']}" for e in summary["errors"][:50]]
        if len(summary["errors"]) > 50:
            lines.append(f"    ... and {len(summary['errors']) - 50} more")
        return "\n".join(lines)
    lines.append(f"  lines {summary['rows']}, materials {summary['materials']}, plants {', '.join(summary['plants'])}")
    lines.append(f"  to post {summary['toPost']}, already loaded {summary['alreadyLoaded']}, skipped (balance in use) {summary['skippedInUse']}, "
                 f"zero quantity (stock-out, nothing to post) {summary['zeroQuantity']}")
    r = summary["reconciliation"]
    lines.append(f"  reconciliation vs the file's valuation: file {money(r['fileMinor'])}  PIC at standard price {money(r['picMinor'])}  "
                 f"difference {money(r['differenceMinor'])}  [{r['status']}]")
    for plant, v in r["byPlant"].items():
        lines.append(f"    plant {plant}: file {money(v['fileMinor'])}  PIC {money(v['picMinor'])}  difference {money(v['differenceMinor'])}  ({v['lines']} lines)")
    for d in r["differingLines"][:10]:
        lines.append(f"    line {d['line']}: {d['material']} {d['plant']} file {money(d['fileMinor'])} PIC {money(d['picMinor'])}")
    if not summary.get("dryRun"):
        lines.append(f"  posted {summary.get('posted', 0)} balance(s), value {money(summary.get('postedValueMinor'))}, batch master rows {summary.get('batchesRecorded', 0)}")
    lines += [f"  warning: {w}" for w in summary.get("warnings", [])[:20]]
    return "\n".join(lines)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Load opening stock from a CSV file into the PIC ledger (movement 561).")
    parser.add_argument("--tenant", required=True, help="tenant code, e.g. KAC")
    parser.add_argument("--file", required=True, help="the opening-stock CSV (layout in the module docstring and docs/runbooks/inventory_operations.md)")
    parser.add_argument("--dry-run", action="store_true", help="validate and reconcile, write nothing")
    parser.add_argument("--strict", action="store_true", help="refuse the file when its valuation column does not reconcile (differences above INR 1.00)")
    parser.add_argument("--report", help="also write the summary as JSON to this path")
    args = parser.parse_args(argv)
    import app.pic.services  # noqa: F401  (registers the platform handlers the audit and the ledger rely on)

    try:
        summary = load(args.tenant, args.file, dry_run=args.dry_run, strict=args.strict)
        code = 0
    except LoadRefused as refused:
        summary, code = refused.summary, 2
    finally:
        clock.set_pinned(None)
    print(format_report(summary))
    if args.report:
        Path(args.report).write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
