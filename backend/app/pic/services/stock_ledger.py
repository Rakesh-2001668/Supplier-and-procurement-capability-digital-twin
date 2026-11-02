"""The stock ledger (BP M09, Technical Document section 5.2): one posting primitive for every change of stock.

``post_movement`` is the only code that changes ``stock.qty`` (besides the ERP stock sync, which overwrites the ERP's own balance and
writes a movement ``ERP``): it locks the balance row, refuses a movement that would make the balance negative, checks the sign of the
movement type and writes the ``stock_movement`` line with its value at the standard price. Receiving, quality, consignment, subcontracting,
cold-chain, expiry write-off and the inventory documents (stock postings, physical inventory, reservations) all post through it.

Also here: the read helpers the inventory module shares (availability, open reservations, first-expiry-first-out allocation, batch expiry,
the ERP message of an inventory document).
"""
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import GoodsReceipt, GrLine, Material, Plant, Stock, StockMovement, StockReservation
from app.pic.platform import audit, integration
from app.pic.platform.errors import Problem
from app.pic.platform.money import D, line_amount
from app.pic.platform.serialize import jsonable
from app.pic.services.common import principal

QTY_PLACES = Decimal("0.001")
OWN_TYPES = ("UNRESTRICTED", "QUALITY", "BLOCKED")          # stock the company owns at its own locations
OPEN_RESERVATION = ("OPEN", "PARTIALLY_ISSUED")

# Movement types: text, and the sign the quantity must have when the type is one-sided. Pairs (transfer, release, block) post a minus and a
# plus line with the same type, so they have no sign rule.
MOVEMENT_TEXT = {
    "101": "Goods receipt", "102": "Goods receipt reversal", "122": "Return delivery to supplier", "201": "Goods issue to cost object",
    "201K": "Consignment withdrawal to cost object", "301": "Transfer posting, plant to plant", "311": "Transfer posting, storage location to storage location",
    "321": "Release from quality inspection", "343": "Unblock (blocked to unrestricted)", "344": "Block (unrestricted to blocked)",
    "350": "Reject to blocked stock (quality)", "411K": "Consignment to own stock", "541": "Components provided to subcontractor",
    "543": "Component consumption at subcontractor", "544": "Component consumption reversal", "551": "Scrapping / write-off",
    "561": "Opening balance", "701": "Inventory difference, gain", "702": "Inventory difference, loss", "344K": "Block of consignment stock",
    "ERP": "Stock level synchronised from the ERP",
}
SIGN = {"101": 1, "102": -1, "122": -1, "201": -1, "201K": -1, "551": -1, "561": 1, "701": 1, "702": -1, "543": -1, "544": 1}
STOCK_TYPES = ("UNRESTRICTED", "QUALITY", "BLOCKED", "CONSIGNMENT", "SUBCONTRACTOR")


def movement_text(code: str) -> str:
    return MOVEMENT_TEXT.get(code, f"Movement {code}")


def value_of(material: Optional[Material], qty) -> Optional[int]:
    """The quantity at the material's standard price (minor units), None when the material has no standard price."""
    if material is None or material.standard_price_minor is None:
        return None
    return line_amount(D(qty), int(material.standard_price_minor))


def post_movement(session: Session, *, material_id, plant: str, sloc: str, stock_type: str, batch: str = "", qty, movement: str,
                  ref_type: str, ref_id, ref: str, posting_ref: Optional[str] = None, reason_code: Optional[str] = None) -> Optional[StockMovement]:
    """Post one signed movement on one stock balance and return the ledger line (None for a zero quantity, which changes nothing).

    The balance row is locked (FOR UPDATE) so concurrent postings serialise; the quantity is at most three decimals (the column's scale) and
    the sign must suit the movement type; a movement that would make the balance negative is refused with 422 NEGATIVE_STOCK."""
    qty = D(qty)
    if not qty.is_finite():
        raise Problem(422, "INVALID_QUANTITY", f"Movement {movement}: the quantity {qty} is not a number", rule_ref="STOCK")
    if qty.quantize(QTY_PLACES) != qty:
        raise Problem(422, "INVALID_QUANTITY", f"Movement {movement}: the quantity {qty} has more than three decimals (stock is kept to 0.001)",
                      rule_ref="STOCK")
    if qty == 0:
        return None
    if stock_type not in STOCK_TYPES:
        raise Problem(422, "INVALID_STOCK_TYPE", f"Movement {movement}: unknown stock type {stock_type}", rule_ref="STOCK")
    sign = SIGN.get(movement)
    if sign is not None and (qty > 0) != (sign > 0):
        raise Problem(500, "MOVEMENT_SIGN", f"Movement {movement} ({movement_text(movement)}) must be {'positive' if sign > 0 else 'negative'}, got {qty}",
                      rule_ref="STOCK")
    tenant_id = current_tenant(session)
    where = (Stock.material_id == material_id, Stock.plant == plant, Stock.storage_location == sloc, Stock.stock_type == stock_type,
             Stock.batch == (batch or ""))
    stock = session.execute(select(Stock).where(*where).with_for_update()).scalar_one_or_none()
    if stock is None:
        if qty < 0:
            raise Problem(422, "NEGATIVE_STOCK", f"Movement {movement} would make {stock_type} stock negative (nothing on hand at {plant}/{sloc}"
                          + (f" batch {batch}" if batch else "") + ")", rule_ref="RCV", availableQty="0")
        # insert-if-absent, then lock: two first postings of the same balance meet on the unique key instead of failing
        session.execute(insert(Stock).values(id=uuid.uuid7(), tenant_id=tenant_id, material_id=material_id, plant=plant, storage_location=sloc,
                                             stock_type=stock_type, batch=batch or "", qty=0, row_version=1,
                                             created_by=principal(session).user_id).on_conflict_do_nothing())
        stock = session.execute(select(Stock).where(*where).with_for_update()).scalar_one()
    if stock.qty + qty < 0:
        raise Problem(422, "NEGATIVE_STOCK", f"Movement {movement} would make {stock_type} stock negative ({stock.qty} on hand at {plant}/{sloc}"
                      + (f" batch {batch}" if batch else "") + f", {-qty} needed)", rule_ref="RCV", availableQty=jsonable(stock.qty))
    stock.qty += qty
    line = StockMovement(tenant_id=tenant_id, material_id=material_id, plant=plant, storage_location=sloc, movement_type=movement,
                         stock_type=stock_type, batch=batch or "", qty=qty, reference_type=ref_type, reference_id=ref_id, reference_ref=ref,
                         value_minor=value_of(session.get(Material, material_id), qty), posting_ref=posting_ref, reason_code=reason_code,
                         created_by=principal(session).user_id)
    session.add(line)
    return line


# ---------------------------------------------------------------- availability and reservations
def on_hand(session: Session, material_id, plant: str, sloc: Optional[str] = None, stock_type: str = "UNRESTRICTED",
            batch: Optional[str] = None) -> Decimal:
    query = select(func.coalesce(func.sum(Stock.qty), 0)).where(Stock.material_id == material_id, Stock.plant == plant, Stock.stock_type == stock_type)
    if sloc is not None:
        query = query.where(Stock.storage_location == sloc)
    if batch is not None:
        query = query.where(Stock.batch == batch)
    return D(session.execute(query).scalar_one())


def reserved_open(session: Session, material_id, plant: str, sloc: Optional[str] = None, exclude_id=None) -> Decimal:
    """Open quantity (reserved, not yet issued) of the live reservations of a material at a plant (and storage location)."""
    query = select(func.coalesce(func.sum(StockReservation.qty - StockReservation.issued_qty), 0)).where(
        StockReservation.material_id == material_id, StockReservation.plant == plant, StockReservation.status.in_(OPEN_RESERVATION))
    if sloc is not None:
        query = query.where(StockReservation.storage_location == sloc)
    if exclude_id is not None:
        query = query.where(StockReservation.id != exclude_id)
    return D(session.execute(query).scalar_one())


def batch_expiry(session: Session, material_id, batches: Optional[list] = None) -> dict:
    """{batch: earliest expiry} from the goods receipts of a material. A reversed receipt never counts: its goods were taken back."""
    query = select(GrLine.batch, func.min(GrLine.expiry)).join(GoodsReceipt, GoodsReceipt.id == GrLine.gr_id).where(
        GrLine.material_id == material_id, GrLine.expiry.is_not(None), GrLine.batch != "", GoodsReceipt.status != "REVERSED")
    if batches is not None:
        query = query.where(GrLine.batch.in_(list(batches) or [""]))
    return {batch: expiry for batch, expiry in session.execute(query.group_by(GrLine.batch)).all()}


def fefo_allocation(session: Session, material_id, plant: str, sloc: str, qty: Decimal, stock_type: str = "UNRESTRICTED",
                    lock: bool = False) -> list[tuple[str, Decimal]]:
    """[(batch, qty)] covering ``qty`` from the batches of a balance, first expiry first out (no expiry last, then the oldest balance).
    Raises 422 INSUFFICIENT_STOCK with the quantity available when the stock does not cover it."""
    query = select(Stock).where(Stock.material_id == material_id, Stock.plant == plant, Stock.storage_location == sloc,
                                Stock.stock_type == stock_type, Stock.qty > 0)
    rows = session.execute(query.with_for_update() if lock else query).scalars().all()
    expiry = batch_expiry(session, material_id, [r.batch for r in rows])
    rows.sort(key=lambda r: (expiry.get(r.batch) or date.max, r.created_at))
    out, remaining = [], D(qty)
    for row in rows:
        take = min(D(row.qty), remaining)
        if take > 0:
            out.append((row.batch, take))
            remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        available = sum((D(r.qty) for r in rows), Decimal(0))
        raise Problem(422, "INSUFFICIENT_STOCK", f"Only {available} {stock_type.lower()} available at {plant}/{sloc}; {qty} needed", rule_ref="STOCK",
                      availableQty=jsonable(available), requiredQty=jsonable(qty))
    return out


def plant_company(session: Session, plant: str) -> str:
    code = session.execute(select(Plant.company_code).where(Plant.code == plant)).scalar_one_or_none()
    if code is None:
        raise Problem(422, "UNKNOWN_PLANT", f"Plant {plant} does not exist", rule_ref="ADM-01")
    return code


# ---------------------------------------------------------------- ERP message of an inventory document
MESSAGE_TYPE = "STOCK_POSTING"


def enqueue_erp(session: Session, *, object_type: str, object_id, ref: str, company_code: str, key: str, payload: dict) -> dict:
    """Post an inventory document to the ERP as a STOCK_POSTING message (exactly once per key) and process it. PIC's ledger is the record:
    when the ERP target does not map the message type the document stays posted and the audit trail says so; when the ERP is unreachable the
    message waits for retry (the document is posted, ``erp_doc_no`` follows)."""
    from app.pic.platform import connectors

    target = integration.target_system(session, company_code)
    if not connectors.maps(target, MESSAGE_TYPE):
        audit.record(session, object_type, object_id, "ERP_NOT_MAPPED", object_ref=ref,
                     after={"system": target, "messageType": MESSAGE_TYPE}, reason="The ERP connector does not map STOCK_POSTING; the posting stands in PIC only")
        return {"status": "NOT_MAPPED", "system": target, "erpDocument": None}
    message = integration.enqueue(session, target_system=target, message_type=MESSAGE_TYPE, idempotency_key=key, object_type=object_type,
                                  object_id=object_id, object_ref=ref, payload={**payload, "companyCode": company_code})
    integration.process(session, message)
    return {"status": message.status, "system": target, "erpDocument": message.erp_doc_no}
