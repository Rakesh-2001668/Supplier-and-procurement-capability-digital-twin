"""M13/M02 inbound ERP batches: planned-order import (AD-05) and master/stock loads.

AD-05 offers two MRP adapters: the in-platform engine (services/planning.py) or importing the planned orders the customer's ERP
calculated. An import is idempotent per (source system, kind, batch reference) through ``integration_batch``: resending the same
batch returns the original result; reusing the reference for different rows is refused. Every row is validated on its own
(material exists, is active and a stock material; plant exists and is in the caller's plants; qty > 0; dates) and accepted rows
become planned orders (source_system, external_ref) on an MRP run per plant with mode ERP_IMPORT, so firming, conversion to a
requisition and the MRP screens work exactly as for platform runs.
"""
import csv
import hashlib
import io
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from email.parser import BytesParser
from email.policy import default as default_policy
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import AuditEvent, IntegrationBatch, Material, MrpRun, Plant, PlannedOrder, Supplier
from app.pic.platform import audit, clock, connectors, outbox, workflow
from app.pic.platform.core import link, next_number
from app.pic.platform.errors import Problem
from app.pic.services import planning, source
from app.pic.services.common import principal

KIND = "PLANNED_ORDERS"
MODE = "ERP_IMPORT"
MAX_ROWS = 5000
CSV_FIELDS = {
    "externalref": "externalRef", "external_ref": "externalRef", "material": "material", "plant": "plant", "qty": "qty",
    "quantity": "qty", "needdate": "needDate", "need_date": "needDate", "releasedate": "releaseDate", "release_date": "releaseDate",
    "supplier": "supplier", "storagelocation": "storageLocation", "storage_location": "storageLocation",
}


def payload_hash(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def _system(system: str) -> str:
    code = (system or "").strip().upper()
    if code not in connectors.REGISTRY:
        raise Problem(422, "UNKNOWN_SOURCE_SYSTEM", f"Unknown source system {system}; use one of {', '.join(connectors.REGISTRY)}")
    return code


def _date(value, field: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD)")


def _plants_allowed(p, plant: str) -> bool:
    allowed = p.attr("plants")
    return p.is_agent or allowed is None or "*" in allowed or plant in allowed


def _validate(session: Session, p, row: dict, seen: set, system: str, materials: dict, plants: dict) -> dict:
    ref = str(row.get("externalRef") or "").strip()
    if not ref:
        raise ValueError("externalRef is required")
    if len(ref) > 60:
        raise ValueError("externalRef is longer than 60 characters")
    if ref in seen:
        raise ValueError(f"externalRef {ref} appears more than once in this batch")
    seen.add(ref)
    duplicate = session.execute(select(PlannedOrder.number).where(PlannedOrder.source_system == system, PlannedOrder.external_ref == ref,
                                                                  PlannedOrder.status != "DELETED").limit(1)).scalar()
    if duplicate:
        raise ValueError(f"externalRef {ref} was already imported as {duplicate}")
    number = str(row.get("material") or "").strip()
    material = materials.get(number)
    if material is None:
        material = session.execute(select(Material).where(Material.number == number)).scalar_one_or_none()
        materials[number] = material
    if material is None:
        raise ValueError(f"material {number or '(empty)'} does not exist")
    if material.status != "ACTIVE":
        raise ValueError(f"material {number} is {material.status}, not ACTIVE")
    if material.type != "STOCK":
        raise ValueError(f"material {number} is a {material.type} material; planned orders are for stock materials")
    plant_code = str(row.get("plant") or "").strip()
    plant = plants.get(plant_code)
    if plant is None:
        plant = session.execute(select(Plant).where(Plant.code == plant_code)).scalar_one_or_none()
        plants[plant_code] = plant
    if plant is None:
        raise ValueError(f"plant {plant_code or '(empty)'} does not exist")
    if not _plants_allowed(p, plant_code):
        raise ValueError(f"you are not assigned to plant {plant_code}")
    try:
        qty = Decimal(str(row.get("qty")).strip())
    except (InvalidOperation, AttributeError):
        raise ValueError("qty must be a number")
    if not qty.is_finite() or qty <= 0:
        raise ValueError("qty must be greater than 0")
    if qty.as_tuple().exponent < -3:
        raise ValueError("qty has more than 3 decimals")
    need = _date(row.get("needDate"), "needDate")
    if row.get("releaseDate") not in (None, ""):
        release = _date(row.get("releaseDate"), "releaseDate")
    else:
        lead = (material.planned_delivery_days or 0) + (material.gr_processing_days or 0)
        release = clock.subtract_working_days(need, lead, list(plant.working_days or [0, 1, 2, 3, 4, 5]), list(plant.holidays or []))
    if release > need:
        raise ValueError("releaseDate is after needDate")
    supplier = None
    if row.get("supplier") not in (None, ""):
        supplier = session.execute(select(Supplier).where(Supplier.code == str(row["supplier"]).strip())).scalar_one_or_none()
        if supplier is None:
            raise ValueError(f"supplier {row['supplier']} does not exist")
        if supplier.status == "BLOCKED":
            raise ValueError(f"supplier {supplier.code} is blocked")
    storage = str(row.get("storageLocation") or "0001").strip()[:10]
    return {"ref": ref, "material": material, "plant": plant_code, "qty": qty, "need": need, "release": release, "supplier": supplier,
            "storage": storage}


def _source(session: Session, v: dict) -> dict:
    determination = source.determine(session, v["material"], v["plant"], v["need"], v["qty"]).as_dict()
    if v["supplier"] is not None:
        determination = {**determination, "erpSupplier": v["supplier"].code}
    return {**determination, "importedFrom": v["system"]}


def _replay(session: Session, batch: IntegrationBatch, digest: str) -> dict:
    stored = session.execute(select(AuditEvent.after).where(AuditEvent.object_type == "INTEGRATION_BATCH", AuditEvent.object_id == batch.id,
                                                            AuditEvent.action == "IMPORTED").limit(1)).scalar()
    if stored and stored.get("payloadSha256") not in (None, digest):
        raise Problem(409, "IDEMPOTENCY_CONFLICT", f"Batch {batch.external_ref} from {batch.source_system} was already imported "
                      f"({batch.number}) with different rows; send corrected rows under a new batchRef")
    return {**view(session, batch), "replayed": True}


def import_planned_orders(session: Session, *, system: str, batch_ref: str, rows: list[dict]) -> dict:
    p = principal(session)
    system = _system(system)
    batch_ref = (batch_ref or "").strip()
    if not batch_ref or len(batch_ref) > 80:
        raise Problem(422, "INVALID_BATCH_REF", "batchRef is required (at most 80 characters)")
    if not rows:
        raise Problem(422, "EMPTY_BATCH", "The batch has no rows")
    if len(rows) > MAX_ROWS:
        raise Problem(413, "BATCH_TOO_LARGE", f"At most {MAX_ROWS} rows per batch; split the import")
    digest = payload_hash(rows)
    session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"erp-import:{current_tenant(session)}:{system}:{batch_ref}"})
    existing = session.execute(select(IntegrationBatch).where(IntegrationBatch.source_system == system, IntegrationBatch.kind == KIND,
                                                              IntegrationBatch.external_ref == batch_ref)).scalar_one_or_none()
    if existing is not None:
        return _replay(session, existing, digest)

    results, accepted, seen, materials, plants = [], [], set(), {}, {}
    for index, raw in enumerate(rows, start=1):
        try:
            v = _validate(session, p, raw, seen, system, materials, plants)
            v["system"] = system
            accepted.append((index, v))
            results.append({"row": index, "externalRef": v["ref"], "status": "ACCEPTED"})
        except ValueError as exc:
            results.append({"row": index, "externalRef": str(raw.get("externalRef") or "") or None, "status": "REJECTED", "error": str(exc)})

    batch = IntegrationBatch(tenant_id=current_tenant(session), number=next_number(session, "INTEGRATION_BATCH"), source_system=system,
                             kind=KIND, external_ref=batch_ref, rows=len(rows), accepted=len(accepted), rejected=len(rows) - len(accepted),
                             results=[], created_by=p.user_id)
    session.add(batch)
    session.flush()

    by_plant: dict[str, list] = defaultdict(list)
    for index, v in accepted:
        by_plant[v["plant"]].append((index, v))
    runs = []
    result_by_row = {r["row"]: r for r in results}
    for plant, items in sorted(by_plant.items()):
        run = MrpRun(tenant_id=current_tenant(session), number=next_number(session, "MRP_RUN"), mode=MODE, plant=plant,
                     scope={"sourceSystem": system, "batchRef": batch_ref, "integrationBatch": batch.number}, run_date=clock.today(),
                     status="RUNNING", started_by=p.user_id, created_by=p.user_id)
        session.add(run)
        session.flush()
        instance = workflow.start(session, planning.PROCESS, "MRP_RUN", run.id, run.number, {"mode": MODE, "sourceSystem": system})
        workflow.step(session, instance, "F1-02", outcome=f"plant {plant}: planned-order import from {system}, batch {batch_ref}")
        workflow.step(session, instance, "F1-03", outcome=f"{len(items)} row(s) received in {batch.number}")
        workflow.step(session, instance, "F1-04", outcome=f"netting and lot sizing performed in {system} (AD-05 ERP adapter)")
        material_numbers = set()
        for index, v in items:
            order = PlannedOrder(
                tenant_id=current_tenant(session), number=next_number(session, "PLANNED_ORDER"), mrp_run_id=run.id,
                material_id=v["material"].id, plant=plant, storage_location=v["storage"], qty=v["qty"], need_date=v["need"],
                release_date=v["release"], status="CREATED", source=_source(session, v),
                exception_codes=["PAST_DUE"] if v["release"] < run.run_date else [], source_system=system, external_ref=v["ref"],
                created_by=p.user_id,
            )
            session.add(order)
            session.flush()
            link(session, "MRP_RUN", run.id, run.number, "PLANNED_ORDER", order.id, order.number, "planned_by")
            result_by_row[index].update({"plannedOrder": order.number, "mrpRun": run.number})
            material_numbers.add(v["material"].number)
        # No platform netting trace: the ERP did the netting. Row results stay on the integration batch.
        run.results = []
        run.materials_planned = len(material_numbers)
        run.planned_orders_created = len(items)
        run.exceptions_raised = 0
        run.status = "COMPLETED"
        run.completed_at = clock.now()
        workflow.step(session, instance, "F1-05", outcome="live import")
        workflow.step(session, instance, "F1-06", outcome=f"{len(items)} planned order(s) imported")
        workflow.wait(session, instance, "F1-07", outcome="review imported orders, firm or convert")
        link(session, "INTEGRATION_BATCH", batch.id, batch.number, "MRP_RUN", run.id, run.number, "imported_as")
        audit.record(session, "MRP_RUN", run.id, "COMPLETED", object_ref=run.number,
                     after={"mode": MODE, "plannedOrders": len(items), "sourceSystem": system, "batch": batch.number})
        outbox.emit(session, "mrp.run.completed", "MRP_RUN", run.id, run.number,
                    {"plant": plant, "mode": MODE, "plannedOrders": len(items), "exceptions": 0, "sourceSystem": system})
        runs.append(run.number)

    batch.results = results
    audit.record(session, "INTEGRATION_BATCH", batch.id, "IMPORTED", object_ref=batch.number,
                 after={"sourceSystem": system, "kind": KIND, "batchRef": batch_ref, "rows": len(rows), "accepted": len(accepted),
                        "rejected": len(rows) - len(accepted), "mrpRuns": runs, "payloadSha256": digest})
    outbox.emit(session, "integration.batch.imported", "INTEGRATION_BATCH", batch.id, batch.number,
                {"sourceSystem": system, "kind": KIND, "batchRef": batch_ref, "accepted": len(accepted), "rejected": len(rows) - len(accepted),
                 "mrpRuns": runs})
    return {**view(session, batch), "replayed": False}


def view(session: Session, batch: IntegrationBatch) -> dict:
    runs = sorted({r.get("mrpRun") for r in batch.results or [] if r.get("mrpRun")})
    return {"id": str(batch.id), "number": batch.number, "sourceSystem": batch.source_system, "kind": batch.kind, "batchRef": batch.external_ref,
            "rows": batch.rows, "accepted": batch.accepted, "rejected": batch.rejected, "mrpRuns": runs, "results": batch.results or [],
            "createdAt": batch.created_at.isoformat(), "createdBy": str(batch.created_by) if batch.created_by else None}


# ---------------------------------------------------------------- CSV
def parse_csv(content: str) -> list[dict]:
    """Header row required: externalRef, material, plant, qty, needDate[, releaseDate, supplier, storageLocation]."""
    text_ = content.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text_[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text_), dialect=dialect)
    if not reader.fieldnames:
        raise Problem(422, "CSV_EMPTY", "The CSV file is empty")
    header = {name: CSV_FIELDS.get((name or "").strip().lower().replace(" ", "")) for name in reader.fieldnames}
    missing = {"externalRef", "material", "plant", "qty", "needDate"} - set(header.values())
    if missing:
        raise Problem(422, "CSV_HEADER", f"The CSV header is missing column(s): {', '.join(sorted(missing))}")
    rows = []
    for record in reader:
        row = {header[k]: (v or "").strip() for k, v in record.items() if k in header and header[k]}
        if any(row.values()):
            rows.append(row)
    return rows


def parse_upload(content_type: str, body: bytes) -> tuple[dict, str]:
    """Accept text/csv or multipart/form-data (field ``file`` plus optional ``system`` / ``batchRef``). Returns (fields, csv text)."""
    ctype = (content_type or "").lower()
    if ctype.startswith("multipart/form-data"):
        message = BytesParser(policy=default_policy).parsebytes(f"Content-Type: {content_type}\r\n\r\n".encode() + body)
        fields, csv_text = {}, None
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            payload = part.get_payload(decode=True) or b""
            if part.get_filename() or name == "file":
                csv_text = payload.decode("utf-8-sig", "replace")
            elif name:
                fields[name] = payload.decode("utf-8", "replace").strip()
        if csv_text is None:
            raise Problem(422, "CSV_MISSING", "Attach the CSV file in the form field 'file'")
        return fields, csv_text
    return {}, body.decode("utf-8-sig", "replace")


def batches(session: Session, kind: Optional[str] = None, system: Optional[str] = None):
    query = select(IntegrationBatch)
    if kind:
        query = query.where(IntegrationBatch.kind == kind.upper())
    if system:
        query = query.where(IntegrationBatch.source_system == system.upper())
    return query
