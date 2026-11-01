"""Live inbound ERP sync (Technical Document §12.1): masters (plants, cost objects, vendors, materials), stock levels, open purchase
orders, payment status and planned orders, on a schedule or on demand.

One run = one object kind from one source:

    CONNECTOR  an HTTP pull through the ERP connector (``connectors.get(system).pull``; SAP S/4HANA OData in ``sap_pull.py``)
    FILE_DROP  a directory (``PIC_ERP_SYNC_DROP_DIR``; an SFTP landing folder mounted or fetched with ``PIC_ERP_SYNC_SFTP_*``)
    PAYLOAD    tables / rows posted to the API by an integrator

A run reads the object kind's delta cursor, pulls only what changed since (minus one day of overlap), detects real changes by a content
hash per object (``erp_sync_state``) and applies them through the same loaders and services the cutover uses (``tools/erp_load``,
``erp_import``): vendors and materials through the staged loader (every rule of the migration applies, rejects are reported), plants,
cost objects and stock directly, open purchase orders and payment status as reconciliation findings and invoice clearing, planned
orders through the AD-05 import. Bank and tax-ID differences on existing vendors are never applied: they become MDM-04 change requests
(``route_sensitive``). The run keeps its counts, the reject and exception report and the new cursor; a failed pull is retried with
back-off, and the next scheduled run starts from the unchanged cursor.

The job scheduler (``services/jobs``) registers the plain callables ``sync_masters``, ``sync_stock``, ``sync_open_pos`` and
``sync_payment_status`` (plus ``sync_planned_orders`` and ``retry_failed``); each takes a tenant code or id.
"""
import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant, system_tx, tenant_tx
from app.pic.models import (
    CostObject, ErpSyncCursor, ErpSyncRun, ErpSyncState, Invoice, Material, Plant, PoLine, PurchaseOrder, Stock, StockMovement, StorageLocation,
    Supplier, Tenant,
)
from app.pic.platform import audit, clock, connectors, integration, outbox
from app.pic.platform.auth import Principal
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.integration import ConnectorError
from app.pic.platform.sap_pull import KINDS, PullResult
from app.pic.services import erp_import, master_changes

KIND_LABEL = {"VENDORS": "Vendor masters", "MATERIALS": "Material masters", "COST_OBJECTS": "Cost objects", "PLANTS": "Plants",
              "STOCK": "Stock levels", "OPEN_POS": "Open purchase orders", "PAYMENT_STATUS": "Payment status", "PLANNED_ORDERS": "Planned orders"}
MASTER_KINDS = ("PLANTS", "COST_OBJECTS", "VENDORS", "MATERIALS")      # applied in this order (vendors and materials need plants)
STALE_MINUTES = 30
MAX_REJECTS_STORED = 500


@dataclass
class SyncPrincipal(Principal):
    system: str = "SAP_S4"

    @property
    def actor(self) -> str:
        return f"integration:{self.system}"


def _principal(tenant_id: uuid.UUID, code: str, system: str) -> SyncPrincipal:
    return SyncPrincipal(user_id=uuid.UUID(int=0), tenant_id=tenant_id, tenant_code=code, email=f"integration.{system.lower()}", name=f"{system} inbound sync",
                         roles=[], scopes=set(), agent_code=None, system=system)


def resolve_tenant(tenant) -> tuple[uuid.UUID, str]:
    with system_tx() as s:
        if isinstance(tenant, uuid.UUID):
            row = s.get(Tenant, tenant)
        else:
            row = s.execute(select(Tenant).where(Tenant.code == str(tenant))).scalar_one_or_none()
    if row is None:
        raise Problem(404, "TENANT_NOT_FOUND", f"No tenant {tenant}")
    return row.id, row.code


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


# ---------------------------------------------------------------- sources
def drop_dir() -> Optional[Path]:
    value = os.environ.get("PIC_ERP_SYNC_DROP_DIR", "").strip()
    return Path(value) if value else None


def _read_csv(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    return [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(io.StringIO(text))]


def read_drop(kind: str, directory: Path) -> Optional[PullResult]:
    """A prepared drop for ``kind``: ``<dir>/<KIND>/`` holding SAP-table CSVs (VENDORS: LFA1.csv, ADRC.csv, LFB1.csv, LFBK.csv, T052.csv;
    MATERIALS: MARA, MAKT, MARC, MBEW) or ``<KIND>.json`` / ``<KIND>.csv`` with plain rows. None when nothing is there."""
    folder = directory / kind
    if not folder.is_dir():
        return None
    if kind in ("VENDORS", "MATERIALS"):
        tables = {p.stem.upper(): _read_csv(p) for p in sorted(folder.glob("*.csv"))}
        return PullResult(kind, tables=tables, pulled=len(tables.get("LFA1" if kind == "VENDORS" else "MARA", [])), cursor=clock.today().isoformat()) if tables else None
    data = folder / f"{kind}.json"
    flat = folder / f"{kind}.csv"
    if data.exists():
        rows = json.loads(data.read_text(encoding="utf-8"))
    elif flat.exists():
        rows = _read_csv(flat)
    else:
        return None
    if not isinstance(rows, list):
        raise Problem(422, "DROP_FORMAT", f"{data.name} must hold a JSON list of rows")
    return PullResult(kind, rows=rows, pulled=len(rows), cursor=clock.today().isoformat())


def fetch_sftp(kind: str, target: Path) -> bool:
    """Download ``<sftp dir>/<KIND>/*`` into ``target/<KIND>`` when PIC_ERP_SYNC_SFTP_HOST is set (needs the optional paramiko package)."""
    host = os.environ.get("PIC_ERP_SYNC_SFTP_HOST", "").strip()
    if not host:
        return False
    try:
        import paramiko  # type: ignore
    except ImportError:
        raise Problem(409, "SFTP_UNAVAILABLE", "PIC_ERP_SYNC_SFTP_HOST is set but the paramiko package is not installed on this deployment")
    transport = paramiko.Transport((host, int(os.environ.get("PIC_ERP_SYNC_SFTP_PORT", "22"))))
    try:
        key_file = os.environ.get("PIC_ERP_SYNC_SFTP_KEY_FILE")
        transport.connect(username=os.environ.get("PIC_ERP_SYNC_SFTP_USER"), password=os.environ.get("PIC_ERP_SYNC_SFTP_PASSWORD"),
                          pkey=paramiko.RSAKey.from_private_key_file(key_file) if key_file else None)
        sftp = paramiko.SFTPClient.from_transport(transport)
        remote = f"{os.environ.get('PIC_ERP_SYNC_SFTP_DIR', '.').rstrip('/')}/{kind}"
        try:
            names = sftp.listdir(remote)
        except OSError:
            return False
        (target / kind).mkdir(parents=True, exist_ok=True)
        for name in names:
            sftp.get(f"{remote}/{name}", str(target / kind / name))
        return bool(names)
    finally:
        transport.close()


def _archive_drop(kind: str, directory: Path) -> None:
    """A processed drop moves to ``processed/<KIND>-<timestamp>`` so the next run does not read it again."""
    folder = directory / kind
    if folder.is_dir():
        done = directory / "processed"
        done.mkdir(parents=True, exist_ok=True)
        shutil.move(str(folder), str(done / f"{kind}-{datetime.now():%Y%m%d%H%M%S}"))


# ---------------------------------------------------------------- change detection
def _alpha(value) -> str:
    text = (value or "").strip()
    return (text.lstrip("0") or "0") if text.isdigit() else text


def _vendor_groups(tables: dict) -> dict[str, dict]:
    """Rows of every vendor across LFA1 / LFB1 / LFBK / ADRC, keyed by the (ALPHA-converted) vendor number."""
    adrc = {r.get("ADDRNUMBER"): r for r in tables.get("ADRC", [])}
    groups: dict[str, dict] = {}
    for r in tables.get("LFA1", []):
        key = _alpha(r.get("LIFNR"))
        groups[key] = {"LFA1": [r], "ADRC": [adrc[r["ADRNR"]]] if r.get("ADRNR") in adrc else [], "LFB1": [], "LFBK": []}
    for name in ("LFB1", "LFBK"):
        for r in tables.get(name, []):
            groups.get(_alpha(r.get("LIFNR")), {}).get(name, []).append(r)
    return groups


def _material_groups(tables: dict) -> dict[str, dict]:
    groups: dict[str, dict] = {}
    for r in tables.get("MARA", []):
        groups[_alpha(r.get("MATNR"))] = {"MARA": [r], "MAKT": [], "MARC": [], "MBEW": []}
    for name in ("MAKT", "MARC", "MBEW"):
        for r in tables.get(name, []):
            groups.get(_alpha(r.get("MATNR")), {}).get(name, []).append(r)
    return groups


def _clean(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "_row"} for r in rows]


def _changed_keys(session: Session, system: str, kind: str, groups: dict[str, object]) -> tuple[set[str], dict[str, str]]:
    """Keys whose content hash differs from the stored one (new objects included), and every key's current hash."""
    def digest(group) -> str:      # masters: {table: [rows]}; plain kinds: one row dict
        nested = isinstance(group, dict) and group and all(isinstance(v, list) for v in group.values())
        return _hash({t: _clean(rows) for t, rows in group.items()} if nested else group)

    hashes = {key: digest(group) for key, group in groups.items()}
    known = {s.object_key: s.row_hash for s in session.execute(select(ErpSyncState).where(ErpSyncState.system == system, ErpSyncState.object_kind == kind)).scalars()}
    return {key for key, h in hashes.items() if known.get(key) != h}, hashes


def _store_hashes(session: Session, system: str, kind: str, hashes: dict[str, str], skip: set[str]) -> None:
    tenant_id, now = current_tenant(session), clock.now()
    known = {s.object_key: s for s in session.execute(select(ErpSyncState).where(ErpSyncState.system == system, ErpSyncState.object_kind == kind)).scalars()}
    for key, digest in hashes.items():
        if key in skip:
            continue
        row = known.get(key)
        if row is None:
            session.add(ErpSyncState(tenant_id=tenant_id, system=system, object_kind=kind, object_key=key[:120], row_hash=digest, seen_at=now))
        elif row.row_hash != digest:
            row.row_hash, row.seen_at = digest, now


# ---------------------------------------------------------------- appliers (direct kinds)
def _apply_plants(session: Session, rows: list[dict], system: str, report: "Report") -> None:
    existing = {p.code: p for p in session.execute(select(Plant)).scalars()}
    company = session.execute(select(Plant.company_code).limit(1)).scalar()
    for r in rows:
        code = (r.get("WERKS") or "").strip()
        if not code:
            report.reject("PLANT", "", "KEY_MISSING", "plant number (WERKS) is empty")
            continue
        state = ((r.get("GSTIN") or "")[:2] or r.get("REGIO") or "").strip()
        if state not in master_changes.STATE_CODES:
            report.reject("PLANT", code, "STATE_INVALID", f"no valid GST state code from the business-place GSTIN or region ({state!r})")
            continue
        name = (r.get("NAME1") or code)[:200]
        plant = existing.get(code)
        if plant is None:
            session.add(Plant(tenant_id=current_tenant(session), code=code, name=name, company_code=r.get("BUKRS") or company or "1000", state_code=state,
                              working_days=[0, 1, 2, 3, 4, 5], holidays=[]))
            session.add(StorageLocation(tenant_id=current_tenant(session), plant=code, code="0001", name="Raw material & bought-out parts"))
            report.new += 1
            audit.record(session, "PLANT", uuid.uuid5(uuid.NAMESPACE_URL, f"pic-plant:{code}"), "ERP_DELTA", object_ref=code, actor=f"integration:{system}",
                         after={"name": name, "state": state})
        elif plant.name != name:
            before = plant.name
            plant.name = name
            report.updated += 1
            audit.record(session, "PLANT", plant.id, "ERP_DELTA", object_ref=code, actor=f"integration:{system}", before={"name": before}, after={"name": name})
        else:
            report.unchanged += 1


def _apply_cost_objects(session: Session, rows: list[dict], system: str, report: "Report") -> None:
    existing = {(c.type, c.code): c for c in session.execute(select(CostObject)).scalars()}
    company = session.execute(select(Plant.company_code).limit(1)).scalar() or "1000"
    today = clock.today().isoformat()
    for r in rows:
        kind, code, name = (r.get("type") or "COST_CENTER"), (r.get("code") or "").strip(), (r.get("name") or "").strip()
        if kind not in ("COST_CENTER", "WBS", "ORDER", "ASSET") or not code:
            report.reject("COST_OBJECT", code, "KEY_INVALID", f"type {kind!r} / code {code!r}")
            continue
        if r.get("validTo") and r["validTo"] < today:
            report.skipped += 1
            continue
        obj = existing.get((kind, code))
        if obj is None:
            session.add(CostObject(tenant_id=current_tenant(session), type=kind, code=code[:30], name=(name or code)[:200], company_code=company))
            report.new += 1
            audit.record(session, "COST_OBJECT", uuid.uuid5(uuid.NAMESPACE_URL, f"pic-cost-object:{kind}:{code}"), "ERP_DELTA", object_ref=code,
                         actor=f"integration:{system}", after={"type": kind, "name": name})
        elif name and obj.name != name[:200]:
            before = obj.name
            obj.name = name[:200]
            report.updated += 1
            audit.record(session, "COST_OBJECT", obj.id, "ERP_DELTA", object_ref=code, actor=f"integration:{system}", before={"name": before}, after={"name": obj.name})
        else:
            report.unchanged += 1


def _apply_stock(session: Session, rows: list[dict], run: ErpSyncRun, system: str, report: "Report") -> None:
    materials = {m.number: m for m in session.execute(select(Material)).scalars()}
    plants = {p.code for p in session.execute(select(Plant)).scalars()}
    slocs = {(s.plant, s.code) for s in session.execute(select(StorageLocation)).scalars()}
    stock = {(s.material_id, s.plant, s.storage_location, s.stock_type, s.batch): s for s in session.execute(select(Stock)).scalars()}
    for r in rows:
        number, plant, sloc = _alpha(r.get("material")), (r.get("plant") or "").strip(), (r.get("storageLocation") or "0001").strip()
        key = f"{number}/{plant}/{sloc}"
        material = materials.get(number)
        try:
            qty = Decimal(str(r.get("qty")).strip())
            if not qty.is_finite() or qty < 0:
                raise InvalidOperation
        except (InvalidOperation, AttributeError):
            report.reject("STOCK", key, "QTY_INVALID", f"quantity {r.get('qty')!r}")
            continue
        if material is None:
            report.reject("STOCK", key, "MATERIAL_UNKNOWN", f"material {number} does not exist in PIC")
        elif material.type != "STOCK":
            report.reject("STOCK", key, "MATERIAL_NOT_STOCK", f"material {number} is a {material.type} material")
        elif plant not in plants:
            report.reject("STOCK", key, "PLANT_UNKNOWN", f"plant {plant} does not exist")
        elif (plant, sloc) not in slocs:
            report.reject("STOCK", key, "STORAGE_LOCATION_UNKNOWN", f"storage location {sloc} of plant {plant} does not exist")
        else:
            qty = qty.quantize(Decimal("0.001"))
            row = stock.get((material.id, plant, sloc, "UNRESTRICTED", ""))
            current = Decimal(row.qty) if row is not None else Decimal(0)
            if row is not None and current == qty:
                report.unchanged += 1
                continue
            if row is None:
                row = Stock(tenant_id=current_tenant(session), material_id=material.id, plant=plant, storage_location=sloc, stock_type="UNRESTRICTED",
                            batch="", qty=qty)
                session.add(row)
                report.new += 1
            else:
                row.qty = qty
                report.updated += 1
            session.add(StockMovement(tenant_id=current_tenant(session), material_id=material.id, plant=plant, storage_location=sloc, movement_type="ERP",
                                      stock_type="UNRESTRICTED", batch="", qty=qty - current, reference_type="ERP_SYNC", reference_id=run.id,
                                      reference_ref=run.number))
            audit.record(session, "MATERIAL", material.id, "STOCK_SYNCED", object_ref=number, actor=f"integration:{system}",
                         before={"plant": plant, "storageLocation": sloc, "qty": str(current)}, after={"qty": str(qty), "run": run.number})


def _apply_open_pos(session: Session, rows: list[dict], system: str, report: "Report") -> None:
    """Reconcile the ERP's purchase orders with PIC's: deletion, quantity and price changes made in the ERP, and ERP orders PIC has
    never seen, are exceptions for the buyer (the PO state machine stays PIC's; nothing is rewritten silently)."""
    pos = {p.erp_doc_no: p for p in session.execute(select(PurchaseOrder).where(PurchaseOrder.erp_doc_no.is_not(None))).scalars()}
    for r in rows:
        number = (r.get("po") or "").strip()
        po = pos.get(number)
        if po is None:
            report.exception("OPEN_PO", number, "PO_UNKNOWN_IN_PIC", f"SAP purchase order {number} (supplier {r.get('supplier')}) has no PIC order: "
                             "created directly in the ERP; load it with the cutover loader or close it in SAP")
            continue
        report.unchanged += 1
        lines = {l.line_no: l for l in session.execute(select(PoLine).where(PoLine.po_id == po.id)).scalars()}
        findings = []
        if r.get("deleted") and po.status not in ("CANCELLED", "CLOSED"):
            findings.append(("PO_DELETED_IN_ERP", f"{po.number} ({number}) is marked for deletion in SAP but PIC status is {po.status}"))
        for item in r.get("items", []):
            line = lines.get(int(item["item"]))
            if line is None:
                findings.append(("PO_LINE_UNKNOWN_IN_PIC", f"{po.number} item {item['item']} exists in SAP only"))
                continue
            try:
                qty, price = Decimal(str(item.get("qty") or 0)), Decimal(str(item.get("price") or 0))
            except InvalidOperation:
                findings.append(("PO_LINE_INVALID", f"{po.number} item {item['item']}: unreadable quantity or price"))
                continue
            if qty != Decimal(line.qty):
                findings.append(("PO_QTY_CHANGED_IN_ERP", f"{po.number} item {item['item']}: SAP quantity {qty}, PIC {line.qty}"))
            if int((price * 100).to_integral_value()) != line.unit_price_minor:
                findings.append(("PO_PRICE_CHANGED_IN_ERP", f"{po.number} item {item['item']}: SAP price {price}, PIC {Decimal(line.unit_price_minor) / 100}"))
            if item.get("deleted"):
                findings.append(("PO_LINE_DELETED_IN_ERP", f"{po.number} item {item['item']} is marked for deletion in SAP"))
        for code, detail in findings:
            report.exception("OPEN_PO", po.number, code, detail)
        if findings:
            audit.record(session, "PURCHASE_ORDER", po.id, "ERP_DIFFERENCES_OBSERVED", object_ref=po.number, actor=f"integration:{system}",
                         after={"erpOrder": number, "findings": [c for c, _ in findings]})


def _apply_payment_status(session: Session, rows: list[dict], system: str, report: "Report") -> None:
    """A vendor item cleared in the ERP means the supplier was paid: the matching PIC invoice (by the ERP document number) becomes PAID."""
    invoices = {i.erp_doc_no: i for i in session.execute(select(Invoice).where(Invoice.erp_doc_no.is_not(None))).scalars()}
    suppliers = {s.id: s.code for s in session.execute(select(Supplier)).scalars()}
    for r in rows:
        document = (r.get("document") or "").strip()
        invoice = invoices.get(document)
        if invoice is None:
            report.skipped += 1
            continue
        if suppliers.get(invoice.supplier_id) != _alpha(r.get("supplier")) and r.get("supplier"):
            report.reject("PAYMENT", document, "SUPPLIER_MISMATCH", f"cleared item belongs to vendor {r.get('supplier')}, PIC invoice {invoice.number} to "
                          f"{suppliers.get(invoice.supplier_id)}")
            continue
        if invoice.payment_status == "PAID":
            report.unchanged += 1
            continue
        before = {"paymentStatus": invoice.payment_status, "status": invoice.status}
        invoice.payment_status = "PAID"
        if invoice.status == "POSTED":
            invoice.status = "PAID"
        report.updated += 1
        audit.record(session, "INVOICE", invoice.id, "PAYMENT_STATUS_SYNCED", object_ref=invoice.number, actor=f"integration:{system}", before=before,
                     after={"paymentStatus": "PAID", "clearingDocument": r.get("clearingDocument"), "clearingDate": r.get("clearingDate")})
        outbox.emit(session, "invoice.paid_in_erp", "INVOICE", invoice.id, invoice.number,
                    {"erpDocument": document, "clearingDocument": r.get("clearingDocument"), "clearingDate": r.get("clearingDate")})


def _apply_planned_orders(session: Session, rows: list[dict], system: str, run: ErpSyncRun, report: "Report") -> None:
    if not rows:
        return
    result = erp_import.import_planned_orders(session, system=system, batch_ref=f"LIVE-{_hash(rows)[:24]}", rows=rows)
    for item in result["results"]:
        if item["status"] == "ACCEPTED":
            report.new += 1
        else:
            report.reject("PLANNED_ORDER", item.get("externalRef") or f"row {item['row']}", "ROW_REJECTED", item.get("error", ""))
    if result.get("replayed"):
        report.unchanged += result["accepted"]
        report.new = 0


# ---------------------------------------------------------------- run bookkeeping
class Report:
    def __init__(self):
        self.new = self.updated = self.unchanged = self.skipped = 0
        self.rejects: list[dict] = []
        self.exceptions: list[dict] = []

    def reject(self, obj: str, key: str, reason: str, detail: str) -> None:
        self.rejects.append({"object": obj, "key": key, "reason": reason, "detail": detail[:300]})

    def exception(self, obj: str, key: str, reason: str, detail: str) -> None:
        self.exceptions.append({"object": obj, "key": key, "reason": reason, "detail": detail[:300]})


def view(run: ErpSyncRun) -> dict:
    return {"id": str(run.id), "number": run.number, "system": run.system, "kind": run.object_kind, "label": KIND_LABEL.get(run.object_kind),
            "mode": run.mode, "source": run.source, "status": run.status, "startedAt": run.started_at.isoformat(),
            "finishedAt": run.finished_at.isoformat() if run.finished_at else None, "cursorBefore": run.cursor_before, "cursorAfter": run.cursor_after,
            "attempts": run.attempts, "counts": run.counts, "rejects": run.rejects, "error": run.error, "triggeredBy": run.triggered_by}


def _number(started: datetime) -> str:
    return f"SYN-{started:%y%m%d-%H%M%S}-{uuid.uuid4().hex[:4].upper()}"


def _cursor_row(session: Session, system: str, kind: str) -> ErpSyncCursor:
    row = session.execute(select(ErpSyncCursor).where(ErpSyncCursor.system == system, ErpSyncCursor.object_kind == kind).with_for_update()).scalar_one_or_none()
    if row is None:
        row = ErpSyncCursor(tenant_id=current_tenant(session), system=system, object_kind=kind, consecutive_failures=0)
        session.add(row)
        session.flush()
    return row


def _finish(session: Session, run_id: uuid.UUID, *, status: str, counts: dict, rejects: list, cursor: Optional[str], error: Optional[str], attempts: int) -> ErpSyncRun:
    run = session.get(ErpSyncRun, run_id)
    run.status, run.counts, run.rejects, run.error, run.attempts = status, counts, rejects[:MAX_REJECTS_STORED], (error or None) and error[:1000], attempts
    run.finished_at, run.cursor_after = clock.now(), cursor if status != "FAILED" else run.cursor_before
    row = _cursor_row(session, run.system, run.object_kind)
    row.last_run_id, row.last_status, row.last_run_at = run.id, status, run.finished_at
    if status == "FAILED":
        row.consecutive_failures = (row.consecutive_failures or 0) + 1
    else:
        row.cursor, row.cursor_at, row.consecutive_failures = cursor, run.finished_at, 0
    audit.record(session, "ERP_SYNC", run.id, "ERP_SYNC_FINISHED" if status != "FAILED" else "ERP_SYNC_FAILED", object_ref=run.number,
                 actor=f"integration:{run.system}", after={"kind": run.object_kind, "status": status, "counts": counts, "cursor": cursor, "error": error})
    outbox.emit(session, "erp.sync.finished", "ERP_SYNC", run.id, run.number, {"kind": run.object_kind, "status": status, "counts": counts})
    return run


# ---------------------------------------------------------------- the run
def run(tenant, kind: str, *, system: Optional[str] = None, mode: str = "ON_DEMAND", source: Optional[str] = None, payload: Optional[dict] = None,
        triggered_by: Optional[str] = None, idempotency_key: Optional[str] = None, retries: Optional[int] = None,
        sleep: Callable[[float], None] = time.sleep, directory: Optional[Path] = None) -> dict:
    """Run one sync of ``kind``. ``payload`` = {"tables": {...}} or {"rows": [...]} (source PAYLOAD). Returns the run view; a failed pull
    returns a FAILED run (it does not raise) so a scheduler can go on with the other kinds."""
    kind = (kind or "").upper()
    if kind not in KINDS:
        raise Problem(422, "UNKNOWN_OBJECT_KIND", f"Unknown object kind {kind}; use one of {', '.join(KINDS)}")
    tenant_id, code = resolve_tenant(tenant)
    retries = int(os.environ.get("PIC_ERP_SYNC_RETRIES", "2")) if retries is None else retries

    # phase 1: register the run
    with tenant_tx(tenant_id, uuid.UUID(int=0), _principal(tenant_id, code, "SAP_S4")) as s:
        system = (system or integration.target_system(s)).upper()
        if system not in connectors.REGISTRY:
            raise Problem(422, "UNKNOWN_SOURCE_SYSTEM", f"Unknown source system {system}")
        if idempotency_key:
            earlier = s.execute(select(ErpSyncRun).where(ErpSyncRun.idempotency_key == idempotency_key)).scalar_one_or_none()
            if earlier is not None:
                return {**view(earlier), "replayed": True}
        cursor = _cursor_row(s, system, kind)
        stale = clock.now() - timedelta(minutes=STALE_MINUTES)
        busy = s.execute(select(ErpSyncRun.number).where(ErpSyncRun.system == system, ErpSyncRun.object_kind == kind, ErpSyncRun.status == "RUNNING",
                                                         ErpSyncRun.started_at > stale)).scalar()
        if busy:
            raise Problem(409, "SYNC_RUNNING", f"{busy} is still running for {KIND_LABEL[kind].lower()}; wait for it to finish")
        started = clock.now()
        row = ErpSyncRun(tenant_id=tenant_id, number=_number(started), system=system, object_kind=kind, mode=mode, source=source or "AUTO",
                         status="RUNNING", started_at=started, cursor_before=cursor.cursor, counts={}, rejects=[], triggered_by=triggered_by,
                         idempotency_key=idempotency_key)
        s.add(row)
        s.flush()
        run_id, run_number, since = row.id, row.number, cursor.cursor
        audit.record(s, "ERP_SYNC", run_id, "ERP_SYNC_STARTED", object_ref=run_number, actor=f"integration:{system}",
                     after={"kind": kind, "mode": mode, "since": since, "triggeredBy": triggered_by})

    # phase 2: pull (no transaction open)
    attempts, error, result, used = 0, None, None, source
    connector = connectors.get(system)
    temp_dir: Optional[Path] = None
    try:
        if payload is not None:
            used = "PAYLOAD"
            result = PullResult(kind, tables=payload.get("tables") or {}, rows=payload.get("rows") or [], pulled=0, cursor=clock.today().isoformat())
            result.pulled = len(result.rows) or len(next(iter(result.tables.values()), []))
            attempts = 1
        else:
            for attempt in range(retries + 1):
                attempts = attempt + 1
                try:
                    if (used in (None, "AUTO", "CONNECTOR")) and connector.configured() and not connector.simulator:
                        used = "CONNECTOR"
                        result = connector.pull(kind, since)
                    else:
                        used = "FILE_DROP"
                        base = directory or drop_dir()
                        if base is None and os.environ.get("PIC_ERP_SYNC_SFTP_HOST"):
                            temp_dir = Path(tempfile.mkdtemp(prefix="pic-erp-sync-"))
                            if fetch_sftp(kind, temp_dir):
                                base = temp_dir
                        if base is None:
                            raise ConnectorError(f"no source for {kind}: {system} is not configured for live pulls (PIC_ERP_{system}_URL) and "
                                                 "PIC_ERP_SYNC_DROP_DIR / PIC_ERP_SYNC_SFTP_HOST are not set")
                        result = read_drop(kind, Path(base))
                        if result is None:
                            result = PullResult(kind, cursor=since or clock.today().isoformat(), notes=["nothing in the drop"])
                    error = None
                    break
                except ConnectorError as exc:
                    error = str(exc)
                    if attempt < retries:
                        sleep(min(2 ** attempt, 30))
    finally:
        pass

    if result is None:
        with tenant_tx(tenant_id, uuid.UUID(int=0), _principal(tenant_id, code, system)) as s:
            s.get(ErpSyncRun, run_id).source = used or "AUTO"
            return view(_finish(s, run_id, status="FAILED", counts={"pulled": 0}, rejects=[], cursor=None, error=error, attempts=attempts))

    # phase 3: apply
    report = Report()
    summary: dict = {}
    try:
        if kind in ("VENDORS", "MATERIALS"):
            summary = _apply_master_tables(tenant_id, code, system, kind, result, run_number, report)
        else:
            with tenant_tx(tenant_id, uuid.UUID(int=0), _principal(tenant_id, code, system)) as s:
                row = s.get(ErpSyncRun, run_id)
                _apply_direct(s, kind, result, row, system, report)
        status = "PARTIAL" if report.rejects else "COMPLETED"
        counts = {"pulled": result.pulled, "new": report.new, "updated": report.updated, "unchanged": report.unchanged, "skipped": report.skipped,
                  "rejected": len(report.rejects), "exceptions": len(report.exceptions), **({"sensitive": summary["sensitive"]} if summary.get("sensitive") else {})}
        with tenant_tx(tenant_id, uuid.UUID(int=0), _principal(tenant_id, code, system)) as s:
            s.get(ErpSyncRun, run_id).source = used or "AUTO"
            finished = _finish(s, run_id, status=status, counts=counts, rejects=report.rejects + report.exceptions, cursor=result.cursor, error=None, attempts=attempts)
            out = view(finished)
        if used == "FILE_DROP" and (directory or drop_dir()) is not None and not result.notes:
            _archive_drop(kind, Path(directory or drop_dir()))
        return out
    except Exception as exc:  # noqa: BLE001 - the run record must say what failed
        with tenant_tx(tenant_id, uuid.UUID(int=0), _principal(tenant_id, code, system)) as s:
            s.get(ErpSyncRun, run_id).source = used or "AUTO"
            return view(_finish(s, run_id, status="FAILED", counts={"pulled": result.pulled}, rejects=report.rejects + report.exceptions, cursor=None,
                                error=f"{type(exc).__name__}: {getattr(exc, 'detail', None) or exc}", attempts=attempts))
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _apply_direct(session: Session, kind: str, result: PullResult, run_row: ErpSyncRun, system: str, report: Report) -> None:
    rows = result.rows
    if kind in ("PLANTS", "COST_OBJECTS", "OPEN_POS", "PAYMENT_STATUS"):
        keyed = {_key_of(kind, r, i): r for i, r in enumerate(rows)}
        changed, hashes = _changed_keys(session, system, kind, keyed)
        report.unchanged += len(keyed) - len(changed)
        rows = [r for k, r in keyed.items() if k in changed]
    if kind == "PLANTS":
        _apply_plants(session, rows, system, report)
    elif kind == "COST_OBJECTS":
        _apply_cost_objects(session, rows, system, report)
    elif kind == "STOCK":
        _apply_stock(session, rows, run_row, system, report)
    elif kind == "OPEN_POS":
        _apply_open_pos(session, rows, system, report)
    elif kind == "PAYMENT_STATUS":
        _apply_payment_status(session, rows, system, report)
    elif kind == "PLANNED_ORDERS":
        _apply_planned_orders(session, rows, system, run_row, report)
    if kind in ("PLANTS", "COST_OBJECTS", "OPEN_POS", "PAYMENT_STATUS"):
        bad = {r["key"] for r in report.rejects}
        _store_hashes(session, system, kind, hashes, bad)


def _key_of(kind: str, row: dict, index: int) -> str:
    return str({"PLANTS": row.get("WERKS"), "COST_OBJECTS": f"{row.get('type')}:{row.get('code')}", "OPEN_POS": row.get("po"),
                "PAYMENT_STATUS": f"{row.get('document')}/{row.get('fiscalYear')}"}.get(kind) or index)


def _apply_master_tables(tenant_id: uuid.UUID, code: str, system: str, kind: str, result: PullResult, run_number: str, report: Report) -> dict:
    """Vendors / materials through the staged loader (all migration validations), changed objects only, in transactions of their own."""
    from app.pic.tools import erp_load

    groups = _vendor_groups(result.tables) if kind == "VENDORS" else _material_groups(result.tables)
    with tenant_tx(tenant_id, uuid.UUID(int=0), _principal(tenant_id, code, system)) as s:
        changed, hashes = _changed_keys(s, system, kind, groups)
    report.unchanged += len(groups) - len(changed)
    if not changed:
        return {}
    tables = {name: [] for name in (("LFA1", "ADRC", "LFB1", "LFBK") if kind == "VENDORS" else ("MARA", "MAKT", "MARC", "MBEW"))}
    for key in sorted(changed):
        for name, rows in groups[key].items():
            tables[name].extend(rows)
    for name, rows in result.tables.items():          # context tables travel whole (payment terms, group maps, plants)
        if name not in tables:
            tables.setdefault(name, rows)
    extract = erp_load.table_extract(code, tables, {"extractId": run_number, "sourceSystem": system})
    summary = erp_load.load_extract(code, extract, delta=True, steps=["vendors" if kind == "VENDORS" else "materials"], reference=run_number)
    objects = summary["objects"].get("vendors" if kind == "VENDORS" else "materials", {})
    report.new += objects.get("loaded", 0)
    report.updated += objects.get("updated", 0)
    report.unchanged += max(objects.get("existing", 0) - objects.get("updated", 0), 0)
    rejected_keys = set()
    for r in summary["rejects"]["rows"]:
        reason = r["reason"]
        report.reject(r["object"].upper(), str(r["key"]), reason, r["detail"])
        if reason != "SENSITIVE_CHANGE":
            rejected_keys.add(str(r["key"]))
    routed = summary.get("sensitive") or []
    if routed:
        summary["sensitive"] = len(routed)
        for item in routed:
            report.exception("SUPPLIER", item["supplier"], f"SENSITIVE_CHANGE_{item['status']}",
                             f"{item['kind'].lower()} difference -> {item.get('process', 'MDM-04')} {item.get('request') or item.get('detail', '')}")
    with tenant_tx(tenant_id, uuid.UUID(int=0), _principal(tenant_id, code, system)) as s:
        _store_hashes(s, system, kind, {k: v for k, v in hashes.items() if k in changed}, rejected_keys)
    return {"sensitive": len(routed)} if routed else {}


# ---------------------------------------------------------------- callables for the job scheduler
def _run_kinds(tenant, kinds, mode: str = "SCHEDULED", **kw) -> list[dict]:
    out = []
    for kind in kinds:
        try:
            out.append(run(tenant, kind, mode=mode, **kw))
        except Problem as exc:
            out.append({"kind": kind, "status": "SKIPPED", "error": exc.detail})
    return out


def sync_masters(tenant, **kw) -> list[dict]:
    """Plants, cost objects, vendors, materials (in that order)."""
    return _run_kinds(tenant, MASTER_KINDS, **kw)


def sync_stock(tenant, **kw) -> list[dict]:
    return _run_kinds(tenant, ("STOCK",), **kw)


def sync_open_pos(tenant, **kw) -> list[dict]:
    return _run_kinds(tenant, ("OPEN_POS",), **kw)


def sync_payment_status(tenant, **kw) -> list[dict]:
    return _run_kinds(tenant, ("PAYMENT_STATUS",), **kw)


def sync_planned_orders(tenant, **kw) -> list[dict]:
    return _run_kinds(tenant, ("PLANNED_ORDERS",), **kw)


def retry_failed(tenant, **kw) -> list[dict]:
    """Run again every object kind whose last run failed (the cursor did not move, so nothing is skipped)."""
    tenant_id, code = resolve_tenant(tenant)
    with tenant_tx(tenant_id, uuid.UUID(int=0), _principal(tenant_id, code, "SAP_S4")) as s:
        failed = [(c.system, c.object_kind) for c in s.execute(select(ErpSyncCursor).where(ErpSyncCursor.last_status == "FAILED")).scalars()]
    out = []
    for system, kind in failed:
        try:
            out.append(run(tenant_id, kind, system=system, mode="RETRY", **kw))
        except Problem as exc:
            out.append({"kind": kind, "status": "SKIPPED", "error": exc.detail})
    return out


# ---------------------------------------------------------------- admin views
def overview(session: Session) -> dict:
    cursors = {(c.system, c.object_kind): c for c in session.execute(select(ErpSyncCursor)).scalars()}
    default_system = integration.target_system(session)
    connector = connectors.get(default_system)
    runs = session.execute(select(ErpSyncRun).order_by(ErpSyncRun.started_at.desc()).limit(200)).scalars().all()
    last_by_kind: dict = {}
    for r in runs:
        last_by_kind.setdefault((r.system, r.object_kind), r)
    kinds = []
    for kind in KINDS:
        system_rows = [(k, v) for k, v in cursors.items() if k[1] == kind] or [((default_system, kind), None)]
        for (system, _), cursor in system_rows:
            last = last_by_kind.get((system, kind))
            kinds.append({"kind": kind, "label": KIND_LABEL[kind], "system": system, "cursor": cursor.cursor if cursor else None,
                          "lastStatus": cursor.last_status if cursor else None, "lastRunAt": cursor.last_run_at.isoformat() if cursor and cursor.last_run_at else None,
                          "consecutiveFailures": cursor.consecutive_failures if cursor else 0, "lastRun": view(last) if last else None})
    drop = drop_dir()
    return {"defaultSystem": default_system,
            "sources": {"connector": {"system": connector.system, "configured": connector.configured() and not connector.simulator, "simulator": connector.simulator,
                                      "detail": ("live pulls available" if connector.configured() and not connector.simulator
                                                 else f"{connector.system} is the sandbox simulator or not configured: no live pull")},
                        "fileDrop": {"directory": str(drop) if drop else None, "configured": drop is not None},
                        "sftp": {"configured": bool(os.environ.get("PIC_ERP_SYNC_SFTP_HOST"))}},
            "kinds": kinds, "recentRuns": [view(r) for r in runs[:20]]}


def list_runs(session: Session, kind: Optional[str] = None, limit: int = 50) -> list[dict]:
    query = select(ErpSyncRun).order_by(ErpSyncRun.started_at.desc()).limit(min(max(limit, 1), 200))
    if kind:
        query = query.where(ErpSyncRun.object_kind == kind.upper())
    return [view(r) for r in session.execute(query).scalars()]


def get_run(session: Session, number: str) -> dict:
    row = session.execute(select(ErpSyncRun).where(ErpSyncRun.number == number)).scalar_one_or_none()
    if row is None:
        raise not_found("ERP sync run", number)
    return view(row)
