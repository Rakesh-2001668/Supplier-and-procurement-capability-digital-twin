"""M05 notifications of the sourcing second pass: regret letters to bidders that were not awarded, and the notice to a disqualified bidder;
since the flow fixes also the invitation of every invited supplier when the event is published (F3-02), a new negotiation round and a
deadline extension (the clarification answers, award and cancellation notices live in services/notifications.py).

A regret letter tells a supplier what happened to its own bid (not selected and its own rank, disqualified with the reason, not evaluable);
it never names a competitor or shows a price or score of another bid. Withdrawn bids get none. The letter is a SOURCING_NOT_AWARDED notification with the
same dedup key as the generic "awarded elsewhere" notice of services/notifications.py: it is relayed first (the regret events precede the award event), so
a bidder gets this letter and the generic notice is skipped; invited suppliers that never bid still get the generic notice.
"""
import uuid

from sqlalchemy.orm import Session

from app.pic.models import OutboxEvent, SourcingEvent
from app.pic.platform import outbox
from app.pic.services.notifications import _object, notify, supplier_users


@outbox.consumer("sourcing.award.regret", "notify-award-regret")
def _regret(session: Session, event: OutboxEvent) -> None:
    sourcing = _object(session, event, SourcingEvent, "SOURCING_EVENT", "eventId")
    if sourcing is None:
        return
    supplier_id = event.payload.get("supplierId")
    if not supplier_id:
        return
    detail = event.payload.get("detail") or "your bid was not selected"
    notify(session, supplier_users(session, uuid.UUID(supplier_id)), kind="SOURCING_NOT_AWARDED", dedup_key=f"SOURCING_NOT_AWARDED:{sourcing.id}:{supplier_id}",
           title=f"Outcome of {sourcing.number}: not awarded to you",
           body=f"Thank you for bidding in {sourcing.number} ({sourcing.title}). The event has been awarded to other suppliers; {detail}. "
                "We value your participation and will invite you to future events in this category.",
           link="/pic/portal", object_type="SOURCING_EVENT", object_ref=sourcing.number)


@outbox.consumer("sourcing.bid.disqualified", "notify-bid-disqualified")
def _disqualified(session: Session, event: OutboxEvent) -> None:
    sourcing = _object(session, event, SourcingEvent, "SOURCING_EVENT", "eventId")
    if sourcing is None:
        return
    supplier_id = event.payload.get("supplierId")
    if not supplier_id:
        return
    notify(session, supplier_users(session, uuid.UUID(supplier_id)), kind="SOURCING_DISQUALIFIED",
           dedup_key=f"SOURCING_DISQUALIFIED:{sourcing.id}:{supplier_id}", title=f"Your bid in {sourcing.number} was disqualified",
           body=f"Your bid in {sourcing.number} ({sourcing.title}) was disqualified from the evaluation. Reason: {event.payload.get('reason') or 'not given'}. "
                "Contact the buyer if you believe this is wrong.", link="/pic/portal", object_type="SOURCING_EVENT", object_ref=sourcing.number)


def _invitee_users(session: Session, event: OutboxEvent, sourcing: SourcingEvent) -> list:
    from sqlalchemy import select

    from app.pic.models import Invitee
    ids = event.payload.get("inviteeSupplierIds")
    if ids is None:  # events emitted before the payload carried the invitees
        ids = [str(i) for i in session.execute(select(Invitee.supplier_id).where(Invitee.event_id == sourcing.id)).scalars()]
    return [u for sid in ids for u in supplier_users(session, uuid.UUID(str(sid)))]


def _ist(value) -> str:
    from datetime import datetime

    from app.pic.platform import clock
    try:
        return datetime.fromisoformat(str(value)).astimezone(clock.IST).strftime("%d %b %Y %H:%M IST")
    except (TypeError, ValueError):
        return str(value)


@outbox.consumer("sourcing.event.published", "notify-sourcing-invited")
def _invited(session: Session, event: OutboxEvent) -> None:
    """F3-02: every invited supplier hears that the event is published, what it is about and until when bids are accepted."""
    sourcing = _object(session, event, SourcingEvent, "SOURCING_EVENT", "eventId")
    if sourcing is None:
        return
    kind = {"RFI": "request for information", "RFP": "request for proposal", "REVERSE_AUCTION": "reverse auction"}.get(sourcing.type, "request for quotation")
    opens = f" Bidding opens {_ist(event.payload['openAt'])}." if event.payload.get("openAt") else ""
    notify(session, _invitee_users(session, event, sourcing), kind="SOURCING_INVITED", dedup_key=f"SOURCING_INVITED:{sourcing.id}",
           title=f"Invitation to bid: {sourcing.number}",
           body=f"You are invited to the {kind} {sourcing.number} ({sourcing.title}), category {sourcing.category}.{opens} "
                f"Bids close {_ist(event.payload.get('closeAt') or sourcing.close_at.isoformat())}. Open the event in the supplier portal to read "
                "the requirement, ask questions and submit your sealed bid.",
           link="/pic/portal", object_type="SOURCING_EVENT", object_ref=sourcing.number)


@outbox.consumer("sourcing.round.opened", "notify-sourcing-round")
def _round_opened(session: Session, event: OutboxEvent) -> None:
    sourcing = _object(session, event, SourcingEvent, "SOURCING_EVENT", "eventId")
    if sourcing is None:
        return
    round_no = event.payload.get("round")
    notify(session, _invitee_users(session, event, sourcing), kind="SOURCING_ROUND", dedup_key=f"SOURCING_ROUND:{sourcing.id}:{round_no}",
           title=f"{sourcing.number}: negotiation round {round_no} is open",
           body=f"The buyer opened negotiation round {round_no} of {sourcing.number} ({sourcing.title})"
                + (f": {event.payload['note']}" if event.payload.get("note") else "")
                + f". Submit your revised sealed bid before {_ist(event.payload.get('closeAt'))}.",
           link="/pic/portal", object_type="SOURCING_EVENT", object_ref=sourcing.number)


@outbox.consumer("sourcing.deadline.extended", "notify-sourcing-extended")
def _deadline_extended(session: Session, event: OutboxEvent) -> None:
    sourcing = _object(session, event, SourcingEvent, "SOURCING_EVENT", "eventId")
    if sourcing is None:
        return
    notify(session, _invitee_users(session, event, sourcing), kind="SOURCING_DEADLINE_EXTENDED",
           dedup_key=f"SOURCING_DEADLINE_EXTENDED:{sourcing.id}:{event.payload.get('closeAt')}",
           title=f"{sourcing.number}: bid deadline extended",
           body=f"The bid deadline of {sourcing.number} ({sourcing.title}) moved from {_ist(event.payload.get('previousCloseAt'))} to "
                f"{_ist(event.payload.get('closeAt'))}. Reason: {event.payload.get('reason') or 'not given'}. A bid you already submitted stays valid; "
                "you may replace it until the new deadline.",
           link="/pic/portal", object_type="SOURCING_EVENT", object_ref=sourcing.number)
