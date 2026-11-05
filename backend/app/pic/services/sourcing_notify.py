"""M05 notifications of the sourcing second pass: regret letters to bidders that were not awarded, and the notice to a disqualified bidder.

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
