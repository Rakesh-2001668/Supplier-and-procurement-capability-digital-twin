"""M05 sourcing clarification board and live reverse auction.

Clarifications (F3-03): invited suppliers ask while the event is open; the
event owner or the category manager answers, and the answer is published to
every invitee without the asker's identity. Buyers may also publish notices.

Reverse auction (SRC-04): settings come from rule AUCTION, overridable per event
and frozen on publish. Bids are an append-only ledger (pic_app cannot UPDATE or
DELETE auction_bid). Each new bid must beat the supplier's own last bid by the
minimum decrement; a bid inside the trigger window extends the end (soft
close). At close each supplier's last price becomes a sealed Bid in the existing
structure, so evaluation, award scenarios and award work unchanged.
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.models import AuctionBid, Bid, EventLine, Invitee, SourcingClarification, SourcingEvent, Supplier
from app.pic.platform import audit, clock, crypto, outbox, rules, workflow
from app.pic.platform.errors import Problem, illegal_transition, not_found, rule_violation
from app.pic.platform.money import D, fmt_inr
from app.pic.services import supplier as supplier_svc
from app.pic.services.common import category_status, days_from_terms, principal

ELIGIBLE = ("QUALIFIED", "PREFERRED")
CLOSED_FOR_NOTICES = ("DRAFT", "CANCELLED", "AWARDED")
SETTING_TYPES = {"minDecrementPct": "pct", "extensionMinutes": "minutes", "triggerMinutes": "minutes", "showRank": "bool",
                 "showBestPrice": "bool", "paymentTermsDays": "days", "leadTimeDays": "days"}
PUBLIC_SETTINGS = ("minDecrementPct", "extensionMinutes", "triggerMinutes", "showRank", "showBestPrice", "paymentTermsDays", "leadTimeDays")


def is_supplier(p) -> bool:
    return "SUPPLIER_USER" in p.roles


def ends_at(event: SourcingEvent) -> datetime:
    """When bidding stops: the live auction end for reverse auctions (soft close), the close time otherwise."""
    if event.type == "REVERSE_AUCTION" and event.auction_ends_at is not None:
        return event.auction_ends_at
    return event.close_at


def _invitee(session: Session, event: SourcingEvent, supplier_id: Optional[uuid.UUID]) -> Optional[Invitee]:
    if supplier_id is None:
        return None
    return session.execute(select(Invitee).where(Invitee.event_id == event.id, Invitee.supplier_id == supplier_id)).scalar_one_or_none()


def require_visible(session: Session, event: SourcingEvent) -> Optional[Invitee]:
    """Supplier users only see published events they are invited to (404 otherwise, like GET /sourcing/events/{ref})."""
    p = principal(session)
    if not is_supplier(p):
        return None
    invitee = _invitee(session, event, p.supplier_id)
    if event.status == "DRAFT" or invitee is None:
        raise not_found("Sourcing event", event.number)
    return invitee


def _require_manager(session: Session, event: SourcingEvent) -> None:
    """The event owner or a category manager of the event's category."""
    p = principal(session)
    if p.user_id == event.owner_id:
        return
    categories = p.attr("categories") or []
    if "CATEGORY_MANAGER" in p.roles and ("*" in categories or event.category in categories):
        return
    raise Problem(403, "NOT_EVENT_MANAGER", f"Only the owner of {event.number} or a {event.category} category manager can do this",
                  rule_ref="ABAC")


def _supplier_brief(session: Session, supplier_id: Optional[uuid.UUID]) -> Optional[dict]:
    if supplier_id is None:
        return None
    s = session.get(Supplier, supplier_id)
    return {"id": str(s.id), "code": s.code, "name": s.legal_name}


# ---------------------------------------------------------------- clarification board (F3-03)
def _clarification(session: Session, event: SourcingEvent, seq: int, lock: bool = False) -> SourcingClarification:
    query = select(SourcingClarification).where(SourcingClarification.event_id == event.id, SourcingClarification.seq == seq)
    if lock:
        query = query.with_for_update()
    item = session.execute(query).scalar_one_or_none()
    if item is None:
        raise not_found("Clarification", f"{event.number}/{seq}")
    return item


def _invitee_ids(session: Session, event: SourcingEvent) -> list[str]:
    return [str(i.supplier_id) for i in session.execute(select(Invitee).where(Invitee.event_id == event.id)).scalars()]


def _published(session: Session, event: SourcingEvent, item: SourcingClarification) -> None:
    outbox.emit(session, "sourcing.clarification.answered", "SOURCING_EVENT", event.id, event.number,
                {"seq": item.seq, "kind": "NOTICE" if item.asked_by_supplier_id is None else "QUESTION", "question": item.question,
                 "answer": item.answer, "ownerId": str(event.owner_id), "inviteeSupplierIds": _invitee_ids(session, event),
                 # Internal only: lets the asker be told their question was answered. Never shown to other suppliers.
                 "askedBySupplierId": str(item.asked_by_supplier_id) if item.asked_by_supplier_id else None})


def ask(session: Session, event: SourcingEvent, text: str) -> SourcingClarification:
    """Supplier question while the event is open, or a buyer notice published straight to all invitees. Caller locks the event."""
    p = principal(session)
    text = (text or "").strip()
    if len(text) < 3:
        raise Problem(422, "TEXT_REQUIRED", "Write the question or notice")
    now = clock.now()
    if is_supplier(p):
        require_visible(session, event)
        if event.status != "OPEN" or now >= ends_at(event):
            raise Problem(409, "CLARIFICATION_WINDOW_CLOSED", f"Questions on {event.number} closed at {ends_at(event).isoformat()}",
                          rule_ref="F3-03")
    else:
        _require_manager(session, event)
        if event.status in CLOSED_FOR_NOTICES:
            raise illegal_transition("Sourcing event", event.number, event.status, "notice")
    seq = (session.execute(select(func.max(SourcingClarification.seq)).where(SourcingClarification.event_id == event.id)).scalar() or 0) + 1
    notice = not is_supplier(p)
    item = SourcingClarification(
        tenant_id=event.tenant_id, event_id=event.id, seq=seq, asked_by_supplier_id=p.supplier_id if not notice else None,
        question=text, status="ANSWERED" if notice else "OPEN", answered_by=p.user_id if notice else None,
        answered_at=now if notice else None, created_by=p.user_id,
    )
    session.add(item)
    session.flush()
    supplier = _supplier_brief(session, item.asked_by_supplier_id)
    audit.record(session, "SOURCING_EVENT", event.id, "NOTICE_PUBLISHED" if notice else "CLARIFICATION_ASKED", object_ref=event.number,
                 after={"seq": seq, "supplier": supplier["code"] if supplier else None, "text": text})
    if notice:
        _published(session, event, item)
    return item


def answer(session: Session, event: SourcingEvent, seq: int, text: str) -> SourcingClarification:
    _require_manager(session, event)
    text = (text or "").strip()
    if len(text) < 2:
        raise Problem(422, "TEXT_REQUIRED", "Write the answer")
    if event.status in ("CANCELLED", "AWARDED"):
        raise illegal_transition("Sourcing event", event.number, event.status, "answer")
    item = _clarification(session, event, seq, lock=True)
    if item.status != "OPEN":
        raise illegal_transition("Clarification", f"{event.number}/{seq}", item.status, "answer")
    item.answer = text
    item.status = "ANSWERED"
    item.answered_by = principal(session).user_id
    item.answered_at = clock.now()
    audit.record(session, "SOURCING_EVENT", event.id, "CLARIFICATION_ANSWERED", object_ref=event.number,
                 before={"seq": seq, "status": "OPEN"}, after={"seq": seq, "status": "ANSWERED", "answer": text})
    _published(session, event, item)
    return item


def withdraw(session: Session, event: SourcingEvent, seq: int) -> SourcingClarification:
    p = principal(session)
    require_visible(session, event)
    item = _clarification(session, event, seq, lock=True)
    if not is_supplier(p) or item.asked_by_supplier_id != p.supplier_id:
        raise Problem(403, "FORBIDDEN", "Only the asking supplier can withdraw a question", rule_ref="SUPPLIER_SCOPE")
    if item.status != "OPEN":
        raise illegal_transition("Clarification", f"{event.number}/{seq}", item.status, "withdraw")
    item.status = "WITHDRAWN"
    audit.record(session, "SOURCING_EVENT", event.id, "CLARIFICATION_WITHDRAWN", object_ref=event.number,
                 before={"seq": seq, "status": "OPEN"}, after={"seq": seq, "status": "WITHDRAWN"})
    return item


def clarification_view(session: Session, item: SourcingClarification, supplier_id: Optional[uuid.UUID] = None,
                       internal: bool = True) -> dict:
    out = {"seq": item.seq, "kind": "NOTICE" if item.asked_by_supplier_id is None else "QUESTION", "question": item.question,
           "answer": item.answer, "status": item.status, "askedAt": item.created_at.isoformat(),
           "answeredAt": item.answered_at.isoformat() if item.answered_at else None}
    if internal:
        out["askedBy"] = _supplier_brief(session, item.asked_by_supplier_id)
    else:
        out["mine"] = item.asked_by_supplier_id is not None and item.asked_by_supplier_id == supplier_id
    return out


def clarifications(session: Session, event: SourcingEvent) -> dict:
    p = principal(session)
    require_visible(session, event)
    items = session.execute(select(SourcingClarification).where(SourcingClarification.event_id == event.id)
                            .order_by(SourcingClarification.seq)).scalars().all()
    now = clock.now()
    window = {"event": event.number, "status": event.status, "questionsCloseAt": ends_at(event).isoformat(),
              "open": event.status == "OPEN" and now < ends_at(event)}
    if is_supplier(p):
        # Suppliers see every published answer and their own questions; the asker of any item is never disclosed.
        visible = [i for i in items if i.status == "ANSWERED" or i.asked_by_supplier_id == p.supplier_id]
        return {**window, "items": [clarification_view(session, i, p.supplier_id, internal=False) for i in visible]}
    return {**window, "openQuestions": sum(1 for i in items if i.status == "OPEN"),
            "items": [clarification_view(session, i) for i in items]}


# ---------------------------------------------------------------- reverse auction settings
def _validated(overrides: dict) -> dict:
    clean = {}
    for key, value in (overrides or {}).items():
        kind = SETTING_TYPES.get(key)
        if kind is None:
            raise Problem(422, "INVALID_SETTING", f"Unknown auction setting {key}; use {', '.join(SETTING_TYPES)}")
        if value is None:
            continue
        if kind == "pct":
            pct = D(value)
            if pct < 0 or pct >= 50:
                raise Problem(422, "INVALID_SETTING", "minDecrementPct must be between 0 and 50")
            clean[key] = str(pct)
        elif kind == "bool":
            if not isinstance(value, bool):
                raise Problem(422, "INVALID_SETTING", f"{key} must be true or false")
            clean[key] = value
        else:
            number = int(value)
            if number < 0 or (kind == "minutes" and number > 240) or (kind == "days" and number > 365):
                raise Problem(422, "INVALID_SETTING", f"{key} is out of range")
            clean[key] = number
    return clean


def effective_settings(session: Session, event: SourcingEvent) -> dict:
    """Rule AUCTION overlaid with the event's overrides (frozen into the event on publish)."""
    rule = rules.resolve(session, "AUCTION", category=event.category)
    overrides = {k: v for k, v in (event.auction or {}).items() if k in SETTING_TYPES}
    return {**{k: v for k, v in rule.body.items() if k in SETTING_TYPES}, **overrides, "ruleSet": (event.auction or {}).get("ruleSet", rule.ref)}


def configure(session: Session, event: SourcingEvent, overrides: dict) -> dict:
    if event.type != "REVERSE_AUCTION":
        raise Problem(409, "NOT_AN_AUCTION", f"{event.number} is an {event.type}, not a reverse auction")
    if event.status != "DRAFT":
        raise illegal_transition("Sourcing event", event.number, event.status, "configure auction")
    _require_manager(session, event)
    clean = _validated(overrides)
    before = dict(event.auction or {})
    event.auction = {**before, **clean}
    audit.record(session, "SOURCING_EVENT", event.id, "AUCTION_CONFIGURED", object_ref=event.number, before=before, after=event.auction)
    return effective_settings(session, event)


def on_publish(session: Session, event: SourcingEvent) -> None:
    """Freeze the settings and start the live clock. Called by sourcing.publish before the event opens."""
    lines = session.execute(select(EventLine).where(EventLine.event_id == event.id)).scalars().all()
    if len(lines) != 1:
        raise rule_violation("A reverse auction is run per item: give exactly one event line", "SRC-AUCTION")
    settings = effective_settings(session, event)
    event.auction = settings
    event.auction_ends_at = event.close_at


def on_new_round(event: SourcingEvent) -> None:
    if event.type == "REVERSE_AUCTION":
        event.auction_ends_at = event.close_at


# ---------------------------------------------------------------- live bidding
def _bids(session: Session, event: SourcingEvent) -> list[AuctionBid]:
    return session.execute(select(AuctionBid).where(AuctionBid.event_id == event.id)
                           .order_by(AuctionBid.submitted_at, AuctionBid.id)).scalars().all()


def _ladder(bids: list[AuctionBid]) -> list[AuctionBid]:
    """Each supplier's latest bid, best first (ties go to the earlier bid)."""
    latest: dict[uuid.UUID, AuctionBid] = {}
    for b in bids:
        latest[b.supplier_id] = b
    return sorted(latest.values(), key=lambda b: (b.price_minor, b.submitted_at, b.id))


def max_next_price(settings: dict, last_price_minor: Optional[int]) -> Optional[int]:
    if last_price_minor is None:
        return None
    pct = D(settings.get("minDecrementPct", 0))
    return int((Decimal(last_price_minor) * (1 - pct / 100)).quantize(Decimal("1"), ROUND_FLOOR))


def place_bid(session: Session, event: SourcingEvent, supplier: Supplier, price_minor: int) -> AuctionBid:
    """One live bid. The caller holds a row lock on the event, so rank and soft close are computed serially."""
    p = principal(session)
    if event.type != "REVERSE_AUCTION":
        raise Problem(409, "NOT_AN_AUCTION", f"{event.number} is an {event.type}; submit a sealed bid instead")
    if event.status != "OPEN":
        raise illegal_transition("Sourcing event", event.number, event.status, "auction bid")
    now = clock.now()
    end = ends_at(event)
    if now >= end:
        raise Problem(409, "AUCTION_CLOSED", f"The auction for {event.number} ended at {end.isoformat()}")
    invitee = _invitee(session, event, supplier.id)
    if invitee is None:
        raise Problem(403, "NOT_INVITED", f"{supplier.code} is not invited to {event.number}")
    status = category_status(session, supplier.id, event.category)
    if status not in ELIGIBLE and not (status == "CONDITIONAL" and invitee.waiver_reason):
        raise rule_violation(f"{supplier.code} is {status} for {event.category} and cannot bid", "P06/SRC-INVITE")
    if price_minor <= 0:
        raise Problem(422, "INVALID_PRICE", "priceMinor must be positive")
    settings = event.auction or effective_settings(session, event)
    bids = _bids(session, event)
    own = [b for b in bids if b.supplier_id == supplier.id]
    limit = max_next_price(settings, own[-1].price_minor if own else None)
    if limit is not None and price_minor > limit:
        raise rule_violation(f"Each bid must be at least {settings.get('minDecrementPct')}% below your last bid "
                             f"({fmt_inr(own[-1].price_minor)}): bid {fmt_inr(limit)} or less", "AUCTION-DECREMENT",
                             maxAllowedMinor=limit, lastBidMinor=own[-1].price_minor)
    ladder = [b for b in _ladder(bids) if b.supplier_id != supplier.id]
    rank = 1 + sum(1 for b in ladder if b.price_minor <= price_minor)
    extended = False
    trigger = timedelta(minutes=int(settings.get("triggerMinutes", 0)))
    extension = timedelta(minutes=int(settings.get("extensionMinutes", 0)))
    if extension and end - now <= trigger:
        event.auction_ends_at = end + extension
        extended = True
        workflow.create_timer(session, "SOURCING_CLOSE", "SOURCING_EVENT", event.id, event.auction_ends_at,
                              {"round": event.round, "softClose": True})
    bid = AuctionBid(tenant_id=event.tenant_id, event_id=event.id, supplier_id=supplier.id, price_minor=int(price_minor),
                     rank_at_submit=rank, submitted_at=now, extended_close=extended, created_by=p.user_id)
    session.add(bid)
    session.flush()
    audit.record(session, "SOURCING_EVENT", event.id, "AUCTION_BID", object_ref=event.number,
                 after={"supplier": supplier.code, "priceMinor": int(price_minor), "rank": rank, "extendedClose": extended,
                        "endsAt": ends_at(event).isoformat()}, rule_set_version=settings.get("ruleSet"))
    if extended:
        audit.record(session, "SOURCING_EVENT", event.id, "AUCTION_EXTENDED", object_ref=event.number,
                     before={"endsAt": end.isoformat()}, after={"endsAt": event.auction_ends_at.isoformat()},
                     reason=f"bid within {settings.get('triggerMinutes')} min of the end (soft close)", rule_set_version=settings.get("ruleSet"))
    return bid


def _bid_row(b: AuctionBid, codes: dict, with_supplier: bool) -> dict:
    out = {"id": str(b.id), "priceMinor": b.price_minor, "rankAtSubmit": b.rank_at_submit, "submittedAt": b.submitted_at.isoformat(),
           "extendedClose": b.extended_close}
    if with_supplier:
        out["supplier"] = codes.get(b.supplier_id)
    return out


def view(session: Session, event: SourcingEvent) -> dict:
    p = principal(session)
    require_visible(session, event)
    if event.type != "REVERSE_AUCTION":
        raise Problem(409, "NOT_AN_AUCTION", f"{event.number} is an {event.type}, not a reverse auction")
    settings = event.auction if event.status != "DRAFT" else effective_settings(session, event)
    now = clock.now()
    end = ends_at(event)
    live = event.status == "OPEN" and now < end
    bids = _bids(session, event)
    ladder = _ladder(bids)
    base = {"event": event.number, "title": event.title, "status": event.status, "round": event.round, "live": live,
            "serverTime": now.isoformat(), "startsAt": event.published_at.isoformat() if event.published_at else None,
            "scheduledCloseAt": event.close_at.isoformat() if event.close_at else None, "endsAt": end.isoformat() if end else None,
            "secondsLeft": max(0, int((end - now).total_seconds())) if live else 0,
            "extensions": sum(1 for b in bids if b.extended_close), "bidders": len(ladder),
            "settings": {k: settings.get(k) for k in PUBLIC_SETTINGS}, "ruleSet": settings.get("ruleSet")}
    if is_supplier(p):
        own = [b for b in bids if b.supplier_id == p.supplier_id]
        rank = next((i for i, b in enumerate(ladder, start=1) if b.supplier_id == p.supplier_id), None)
        return {**base, "myBids": [_bid_row(b, {}, False) for b in reversed(own)],
                "myLastPriceMinor": own[-1].price_minor if own else None,
                "myRank": rank if settings.get("showRank") else None,
                "nextMaxPriceMinor": max_next_price(settings, own[-1].price_minor if own else None),
                "bestPriceMinor": ladder[0].price_minor if ladder and settings.get("showBestPrice") else None}
    codes = {s.id: s.code for s in session.execute(select(Supplier).where(Supplier.id.in_({b.supplier_id for b in bids}))).scalars()} if bids else {}
    names = {s.id: s.legal_name for s in session.execute(select(Supplier).where(Supplier.id.in_(list(codes)))).scalars()} if codes else {}
    counts: dict = {}
    for b in bids:
        counts[b.supplier_id] = counts.get(b.supplier_id, 0) + 1
    best = ladder[0].price_minor if ladder else None
    baseline = event.baseline_price_minor
    return {**base, "baselineMinor": baseline, "bestPriceMinor": best,
            "savingsVsBaselinePct": str(((Decimal(baseline) - best) / baseline * 100).quantize(Decimal("0.01"))) if best and baseline else None,
            "ladder": [{"rank": i, "supplier": codes[b.supplier_id], "name": names.get(b.supplier_id), "priceMinor": b.price_minor,
                        "submittedAt": b.submitted_at.isoformat(), "bids": counts[b.supplier_id]} for i, b in enumerate(ladder, start=1)],
            "bids": [_bid_row(b, codes, True) for b in reversed(bids)],
            "invited": len(_invitee_ids(session, event))}


# ---------------------------------------------------------------- close: auction → sealed bids
def to_sealed_bids(session: Session, event: SourcingEvent) -> int:
    """Turn each supplier's last auction price into a sealed Bid for this round; the normal unseal then evaluates it."""
    end = ends_at(event)
    settings = event.auction or {}
    line = session.execute(select(EventLine).where(EventLine.event_id == event.id).order_by(EventLine.line_no)).scalars().first()
    converted = []
    for last in _ladder([b for b in _bids(session, event) if b.submitted_at <= end]):
        supplier = session.get(Supplier, last.supplier_id)
        twin = supplier_svc.twin(session, supplier.id, event.category)
        terms = settings.get("paymentTermsDays")
        lead = settings.get("leadTimeDays")
        payload_lines = [{
            "line": line.line_no, "unit_price": str((Decimal(last.price_minor) / 100).quantize(Decimal("0.01"))),
            "freight": "0", "duty": "0", "packaging": "0",
            "payment_terms_days": int(terms) if terms is not None else days_from_terms(supplier.payment_terms),
            "lead_time_days": int(lead) if lead is not None else int(twin.lead_time_days or 0) if twin else 0,
            "capacity_per_month": None,
        }]
        payload = json.dumps({"lines": payload_lines}, sort_keys=True, default=str)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        sealed = crypto.encrypt(event.tenant_id, f"bid:{event.id}", payload)
        bid = session.execute(select(Bid).where(Bid.event_id == event.id, Bid.supplier_id == supplier.id,
                                                Bid.round == event.round)).scalar_one_or_none()
        if bid is None:
            bid = Bid(tenant_id=event.tenant_id, event_id=event.id, supplier_id=supplier.id, round=event.round, status="SEALED",
                      sealed_payload=sealed, payload_hash=digest, submitted_at=last.submitted_at,
                      submitted_by=last.created_by or principal(session).user_id, created_by=last.created_by)
            session.add(bid)
        else:
            bid.sealed_payload, bid.payload_hash, bid.submitted_at, bid.status = sealed, digest, last.submitted_at, "SEALED"
        converted.append({"supplier": supplier.code, "priceMinor": last.price_minor, "hash": digest})
    session.flush()
    audit.record(session, "SOURCING_EVENT", event.id, "AUCTION_CLOSED", object_ref=event.number,
                 after={"round": event.round, "endedAt": end.isoformat(), "finalBids": converted}, rule_set_version=settings.get("ruleSet"))
    return len(converted)
