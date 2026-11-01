"""Consumers for catalogue events that had none (TD §11, wave 1 item 53): in-app notifications, flags on open documents and the
agent/AI governance notices. Every consumer is idempotent (``processed_event`` plus a per-recipient ``dedup_key``) and only reads
the event and the documents it names. Events that stay stream-only (read by the real-time stream and external subscribers) are
listed with the reason in docs/PIC_Event_Catalogue.md.
"""
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import (
    AppUser, Asn, Invoice, Invitee, MaterialRequest, MrpRun, OutboxEvent, PlannedOrder, PurchaseOrder, Requisition, SavingsInitiative,
    ServiceEntry, SourcingEvent, Supplier,
)
from app.pic.platform import audit, outbox
from app.pic.services.notifications import _user, link_for, notify, supplier_users, users_with_role

HEALTHY = ("QUALIFIED", "PREFERRED")
OPEN_PO = ("DRAFT", "IN_APPROVAL", "RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED")
OPEN_SOURCING = ("PUBLISHED", "OPEN", "CLOSED", "UNDER_EVALUATION", "AWARD_PENDING")


def _internal(users: list[AppUser]) -> list[AppUser]:
    return [u for u in users if u.supplier_id is None]


def _role(session: Session, *roles: str, plant: Optional[str] = None) -> list[AppUser]:
    found = [u for role in roles for u in _internal(users_with_role(session, role))]
    if plant is None:
        return found
    return [u for u in found if not (u.attributes or {}).get("plants") or "*" in (u.attributes or {}).get("plants", []) or plant in (u.attributes or {})["plants"]]


def _get(session: Session, model, event: OutboxEvent):
    return session.get(model, event.object_id)


def _inr(minor: Optional[int]) -> str:
    return f"₹{(minor or 0) / 100:,.2f}"


# ---------------------------------------------------------------- suppliers
@outbox.consumer("supplier.status.changed", "supplier-status-flags")
def _supplier_status(session: Session, event: OutboxEvent) -> None:
    """A supplier that is no longer qualified/preferred (blocked, suspended, under review) puts its open purchase orders and
    sourcing events at risk: each is flagged in its audit trail and the buyer or event owner is told. A restored supplier clears it."""
    supplier = _get(session, Supplier, event)
    if supplier is None:
        return
    to, before = event.payload.get("to"), event.payload.get("from")
    adverse = to not in HEALTHY
    if not adverse and before in HEALTHY:
        return
    if not adverse and before is None:
        return
    category = event.payload.get("category")
    reason = event.payload.get("reason") or "not given"
    headline = f"Supplier {supplier.code} {'is now ' + str(to) if adverse else 'is qualified again'}" + (f" for {category}" if category else "")
    for po in session.execute(select(PurchaseOrder).where(PurchaseOrder.supplier_id == supplier.id, PurchaseOrder.status.in_(OPEN_PO))).scalars():
        if adverse:
            audit.record(session, "PURCHASE_ORDER", po.id, "SUPPLIER_STATUS_FLAGGED", object_ref=po.number,
                         after={"supplier": supplier.code, "from": before, "to": to, "category": category}, reason=reason)
        notify(session, _user(session, po.created_by), kind="SUPPLIER_STATUS", dedup_key=f"SUPPLIER_STATUS:{event.id}:{po.id}",
               title=f"{headline}: purchase order {po.number}",
               body=f"{headline} ({reason}). Open purchase order {po.number} ({po.status.replace('_', ' ').lower()}) is affected: "
                    + ("review before it is released, confirmed or received." if adverse else "the flag is cleared."),
               link=link_for("PURCHASE_ORDER", po.number), object_type="PURCHASE_ORDER", object_ref=po.number)
    for sourcing in session.execute(select(SourcingEvent).join(Invitee, Invitee.event_id == SourcingEvent.id).where(
            Invitee.supplier_id == supplier.id, SourcingEvent.status.in_(OPEN_SOURCING))).scalars():
        if adverse:
            audit.record(session, "SOURCING_EVENT", sourcing.id, "SUPPLIER_STATUS_FLAGGED", object_ref=sourcing.number,
                         after={"supplier": supplier.code, "from": before, "to": to, "category": category}, reason=reason)
        notify(session, _user(session, sourcing.owner_id), kind="SUPPLIER_STATUS", dedup_key=f"SUPPLIER_STATUS:{event.id}:{sourcing.id}",
               title=f"{headline}: sourcing event {sourcing.number}",
               body=f"{headline} ({reason}). The supplier is invited to {sourcing.number} ({sourcing.title}); "
                    + ("it cannot be awarded while it is not qualified." if adverse else "it can be awarded again."),
               link=link_for("SOURCING_EVENT", sourcing.number), object_type="SOURCING_EVENT", object_ref=sourcing.number)


@outbox.consumer("supplier.registered", "notify-supplier-registered")
def _supplier_registered(session: Session, event: OutboxEvent) -> None:
    supplier = _get(session, Supplier, event)
    if supplier is None:
        return
    screening = event.payload.get("screening")
    notify(session, _role(session, "SUPPLIER_MANAGER"), kind="SUPPLIER_REGISTERED", dedup_key=f"SUPPLIER_REGISTERED:{supplier.id}",
           title=f"New supplier registered: {supplier.legal_name}",
           body=f"{supplier.legal_name} ({supplier.code}) completed self-registration; sanctions screening: {screening}. Qualification is next.",
           link=link_for("SUPPLIER", supplier.code), object_type="SUPPLIER", object_ref=supplier.code)


# ---------------------------------------------------------------- requisitions and planning
@outbox.consumer("requisition.approved", "notify-requisition-approved")
def _requisition_approved(session: Session, event: OutboxEvent) -> None:
    pr = _get(session, Requisition, event)
    if pr is None:
        return
    link = link_for("REQUISITION", pr.number)
    notify(session, _user(session, pr.requester_id), kind="REQUISITION_APPROVED", dedup_key=f"REQUISITION_APPROVED:{pr.id}:{event.id}",
           title=f"Approved: {pr.number}", body=f"{pr.number} ({_inr(event.payload.get('totalMinor'))}) was approved and went to the buyer.",
           link=link, object_type="REQUISITION", object_ref=pr.number)
    notify(session, _role(session, "BUYER", plant=pr.plant), kind="REQUISITION_APPROVED", dedup_key=f"REQUISITION_APPROVED:{pr.id}:{event.id}:buyer",
           title=f"New approved requisition: {pr.number}",
           body=f"{pr.number} ({_inr(event.payload.get('totalMinor'))}, plant {pr.plant}) is in the buyer workbench.",
           link="/pic/buyer", object_type="REQUISITION", object_ref=pr.number)


@outbox.consumer("requisition.cancelled", "notify-requisition-cancelled")
def _requisition_cancelled(session: Session, event: OutboxEvent) -> None:
    pr = _get(session, Requisition, event)
    if pr is None:
        return
    previous = str(event.payload.get("previousStatus") or "")
    body = f"{pr.number} was cancelled (was {previous.replace('_', ' ').lower() or 'open'}). Reason: {event.payload.get('reason') or 'not given'}."
    notify(session, _user(session, pr.requester_id), kind="REQUISITION_CANCELLED", dedup_key=f"REQUISITION_CANCELLED:{pr.id}",
           title=f"Cancelled: {pr.number}", body=body, link=link_for("REQUISITION", pr.number), object_type="REQUISITION", object_ref=pr.number)
    if previous not in ("DRAFT", "SUBMITTED", "IN_APPROVAL", "REJECTED", ""):  # it had reached the buyer: whoever worked on it must know
        notify(session, _role(session, "BUYER", plant=pr.plant), kind="REQUISITION_CANCELLED", dedup_key=f"REQUISITION_CANCELLED:{pr.id}:buyer",
               title=f"Cancelled before ordering: {pr.number}", body=body + " Remove it from your sourcing and orders.", link="/pic/buyer",
               object_type="REQUISITION", object_ref=pr.number)


@outbox.consumer("mrp.run.completed", "notify-mrp-run")
def _mrp_run(session: Session, event: OutboxEvent) -> None:
    run = _get(session, MrpRun, event)
    plant = event.payload.get("plant")
    exceptions = int(event.payload.get("exceptions") or 0)
    notify(session, _role(session, "MRP_CONTROLLER", plant=plant), kind="MRP_RUN", dedup_key=f"MRP_RUN:{event.object_id}",
           title=f"MRP run {event.object_ref} finished" + (f": {exceptions} exception(s)" if exceptions else ""),
           body=f"Plant {plant}, {str(event.payload.get('mode') or '').replace('_', ' ').lower()}: {event.payload.get('plannedOrders', 0)} planned order(s), "
                f"{exceptions} exception(s). Review the exceptions and firm the orders.",
           link=link_for("MRP_RUN", run.number) if run else "/pic/mrp", object_type="MRP_RUN", object_ref=event.object_ref)


@outbox.consumer("planned_order.firmed", "notify-planned-order-firmed")
def _planned_order_firmed(session: Session, event: OutboxEvent) -> None:
    order = _get(session, PlannedOrder, event)
    if order is None:
        return
    notify(session, _role(session, "BUYER", plant=order.plant), kind="PLANNED_ORDER_FIRMED", dedup_key=f"PLANNED_ORDER_FIRMED:{order.id}",
           title=f"Planned order firmed: {order.number}",
           body=f"{order.number} ({event.payload.get('qty')} needed {event.payload.get('needDate')}, plant {order.plant}) is firmed; a requisition follows.",
           link="/pic/mrp", object_type="PLANNED_ORDER", object_ref=order.number)


# ---------------------------------------------------------------- purchasing, receiving and payables
@outbox.consumer("purchase_order.confirmed", "notify-po-confirmed")
def _po_confirmed(session: Session, event: OutboxEvent) -> None:
    po = _get(session, PurchaseOrder, event)
    if po is None:
        return
    notify(session, _user(session, po.created_by), kind="PO_CONFIRMED", dedup_key=f"PO_CONFIRMED:{po.id}:v{event.payload.get('version')}",
           title=f"Confirmed by the supplier: {po.number}", body=f"The supplier confirmed {po.number} version {event.payload.get('version')} "
           f"after {event.payload.get('hours')} hours.", link=link_for("PURCHASE_ORDER", po.number), object_type="PURCHASE_ORDER", object_ref=po.number)


@outbox.consumer("asn.received", "notify-asn-received")
def _asn_received(session: Session, event: OutboxEvent) -> None:
    asn = _get(session, Asn, event)
    po = session.execute(select(PurchaseOrder).where(PurchaseOrder.number == event.payload.get("po"))).scalar_one_or_none()
    if asn is None or po is None:
        return
    notify(session, _role(session, "RECEIVER"), kind="ASN_RECEIVED", dedup_key=f"ASN_RECEIVED:{asn.id}", title=f"Shipment announced: {asn.number}",
           body=f"{asn.number} against {po.number} is expected on {event.payload.get('expected')}. Plan the goods receipt.",
           link="/pic/receiving", object_type="ASN", object_ref=asn.number)


@outbox.consumer("service_entry.approved", "notify-service-entry-approved")
def _ses_approved(session: Session, event: OutboxEvent) -> None:
    ses = _get(session, ServiceEntry, event)
    if ses is None:
        return
    notify(session, _user(session, ses.created_by) + _role(session, "AP_CLERK"), kind="SES_APPROVED", dedup_key=f"SES_APPROVED:{ses.id}",
           title=f"Service entry approved: {ses.number}",
           body=f"{ses.number} against {event.payload.get('po')} ({_inr(event.payload.get('totalMinor'))}) is approved and accrued; "
                "the supplier's invoice can be matched.", link="/pic/receiving", object_type="SERVICE_ENTRY", object_ref=ses.number)


@outbox.consumer("lot.recalled", "notify-lot-recalled")
def _lot_recalled(session: Session, event: OutboxEvent) -> None:
    batch = event.payload.get("batch")
    stock = ", ".join(f"{q.get('qty')} at {q.get('plant')}/{q.get('storageLocation')}" for q in event.payload.get("quarantined") or []) or "no stock on hand"
    notify(session, _role(session, "QUALITY_INSPECTOR", "BUYER", "RECEIVER"), kind="LOT_RECALLED", dedup_key=f"LOT_RECALLED:{event.id}",
           title=f"Recall: {event.payload.get('material')} batch {batch}",
           body=f"Recall notice {event.payload.get('notice')} for {event.payload.get('material')} batch {batch}. Quarantined: {stock}.",
           link="/pic/receiving", object_type="MATERIAL", object_ref=event.payload.get("material"))


@outbox.consumer("return_delivery.replacement_requested", "notify-replacement-requested")
def _replacement_requested(session: Session, event: OutboxEvent) -> None:
    supplier_id = event.payload.get("supplierId")
    users = supplier_users(session, uuid.UUID(supplier_id)) if supplier_id else []
    notify(session, users, kind="REPLACEMENT_REQUESTED", dedup_key=f"REPLACEMENT_REQUESTED:{event.object_id}",
           title=f"Replacement requested: {event.object_ref}",
           body=f"Please send a replacement of {event.payload.get('qty')} for line {event.payload.get('poLine')} of {event.payload.get('po')} "
                f"(return {event.object_ref}).", link="/pic/portal", object_type="RETURN_DELIVERY", object_ref=event.object_ref)


@outbox.consumer("subcontracting.components_provided", "notify-components-provided")
def _components_provided(session: Session, event: OutboxEvent) -> None:
    supplier = session.execute(select(Supplier).where(Supplier.code == event.payload.get("supplier"))).scalar_one_or_none()
    if supplier is None:
        return
    parts = ", ".join(f"{c.get('qty')} x {c.get('material')}" for c in (event.payload.get("components") or []) if isinstance(c, dict)) or "components"
    notify(session, supplier_users(session, supplier.id), kind="COMPONENTS_PROVIDED", dedup_key=f"COMPONENTS_PROVIDED:{event.id}",
           title=f"Components provided for {event.object_ref}", body=f"Components were provided to you for line {event.payload.get('line')} of "
           f"{event.object_ref}: {parts}.", link="/pic/portal", object_type="PURCHASE_ORDER", object_ref=event.object_ref)


@outbox.consumer("invoice.captured", "notify-invoice-captured")
def _invoice_captured(session: Session, event: OutboxEvent) -> None:
    """Invoices a supplier submitted through the portal wait for accounts payable; internally keyed ones need no notice."""
    invoice = _get(session, Invoice, event)
    if invoice is None:
        return
    creator = session.get(AppUser, invoice.created_by) if invoice.created_by else None
    if creator is None or creator.supplier_id is None:
        return
    notify(session, _role(session, "AP_CLERK"), kind="INVOICE_CAPTURED", dedup_key=f"INVOICE_CAPTURED:{invoice.id}",
           title=f"Supplier invoice received: {invoice.number}",
           body=f"{event.payload.get('supplier')} submitted {invoice.number} ({_inr(event.payload.get('grossMinor'))}) through the portal; matching starts now.",
           link=link_for("INVOICE", invoice.number, invoice.id), object_type="INVOICE", object_ref=invoice.number)


@outbox.consumer("invoice.disputed", "notify-invoice-disputed")
def _invoice_disputed(session: Session, event: OutboxEvent) -> None:
    invoice = _get(session, Invoice, event)
    if invoice is None:
        return
    detail = f"{event.payload.get('exception')} ({event.payload.get('delta')}): {event.payload.get('note')}"
    notify(session, _role(session, "AP_CLERK", "SUPPLIER_MANAGER"), kind="INVOICE_DISPUTED", dedup_key=f"INVOICE_DISPUTED:{event.id}",
           title=f"Invoice disputed: {invoice.number}", body=f"{invoice.number} is disputed with the supplier. {detail}",
           link=link_for("INVOICE", invoice.number, invoice.id), object_type="INVOICE", object_ref=invoice.number)
    notify(session, supplier_users(session, invoice.supplier_id), kind="INVOICE_DISPUTED", dedup_key=f"INVOICE_DISPUTED:{event.id}:supplier",
           title=f"Invoice {invoice.number} is disputed", body=f"Your invoice {invoice.number} is on hold: {detail}. Please send a corrected invoice or a credit note.",
           link="/pic/portal", object_type="INVOICE", object_ref=invoice.number)


@outbox.consumer("payment.completed", "notify-payment-completed")
def _payment_completed(session: Session, event: OutboxEvent) -> None:
    invoice = _get(session, Invoice, event)
    if invoice is None:
        return
    body = (f"Payment {event.payload.get('payment')} of {_inr(event.payload.get('amountMinor'))} for invoice {invoice.number} was cleared "
            f"in the ERP (document {event.payload.get('clearingDocument')}).")
    notify(session, supplier_users(session, invoice.supplier_id), kind="PAYMENT_COMPLETED", dedup_key=f"PAYMENT_COMPLETED:{event.id}:supplier",
           title=f"Payment made: {invoice.number}", body=body, link="/pic/portal", object_type="INVOICE", object_ref=invoice.number)
    notify(session, _user(session, invoice.created_by), kind="PAYMENT_COMPLETED", dedup_key=f"PAYMENT_COMPLETED:{event.id}",
           title=f"Paid: {invoice.number}", body=body, link=link_for("INVOICE", invoice.number, invoice.id), object_type="INVOICE", object_ref=invoice.number)


@outbox.consumer("payment_file.generated", "notify-payment-file")
def _payment_file(session: Session, event: OutboxEvent) -> None:
    notify(session, _role(session, "FINANCE_CONTROLLER"), kind="PAYMENT_FILE", dedup_key=f"PAYMENT_FILE:{event.object_id}",
           title=f"Payment file ready: {event.object_ref}",
           body=f"{event.object_ref} for run {event.payload.get('run')} is generated; upload it to the bank.", link="/pic/invoices",
           object_type="PAYMENT_FILE", object_ref=event.object_ref)


@outbox.consumer("savings.realised", "notify-savings-realised")
def _savings_realised(session: Session, event: OutboxEvent) -> None:
    initiative = _get(session, SavingsInitiative, event)
    if initiative is None:
        return
    notify(session, _user(session, initiative.owner_id), kind="SAVINGS_REALISED", dedup_key=f"SAVINGS_REALISED:{initiative.id}:{event.payload.get('invoice')}",
           title=f"Savings realised: {initiative.number}",
           body=f"{_inr(event.payload.get('amountMinor'))} realised on {initiative.title} from invoice {event.payload.get('invoice')}.",
           link="/pic/savings", object_type="SAVINGS_INITIATIVE", object_ref=initiative.number)


@outbox.consumer("material_request.approved", "notify-material-approved")
def _material_approved(session: Session, event: OutboxEvent) -> None:
    request = _get(session, MaterialRequest, event)
    if request is None:
        return
    notify(session, _user(session, request.requested_by), kind="MATERIAL_APPROVED", dedup_key=f"MATERIAL_APPROVED:{request.id}",
           title=f"Material created: {event.payload.get('material')}",
           body=f"{request.number} was approved; material {event.payload.get('material')} exists and goes to the ERP.",
           link=link_for("MATERIAL_REQUEST", request.number), object_type="MATERIAL_REQUEST", object_ref=request.number)


@outbox.consumer("integration.batch.imported", "notify-batch-imported")
def _batch_imported(session: Session, event: OutboxEvent) -> None:
    rejected = int(event.payload.get("rejected") or 0)
    if not rejected:
        return
    notify(session, _role(session, "MRP_CONTROLLER", "TENANT_ADMIN"), kind="BATCH_REJECTED_ROWS", dedup_key=f"BATCH_REJECTED_ROWS:{event.object_id}",
           title=f"ERP import {event.object_ref}: {rejected} row(s) rejected",
           body=f"{event.payload.get('sourceSystem')} batch {event.payload.get('batchRef')}: {event.payload.get('accepted')} accepted, {rejected} rejected. "
                "Fix the rejected rows in the ERP and resend.", link="/pic/mrp", object_type="INTEGRATION_BATCH", object_ref=event.object_ref)


# ---------------------------------------------------------------- AI governance (agents.py)
@outbox.consumer("agent.suspended", "notify-agent-suspended")
def _agent_suspended(session: Session, event: OutboxEvent) -> None:
    notify(session, _role(session, "CPO", "TENANT_ADMIN"), kind="AGENT_SUSPENDED", dedup_key=f"AGENT_SUSPENDED:{event.id}",
           title=f"AI agent suspended: {event.payload.get('agent')}",
           body=f"{event.payload.get('agent')} was suspended automatically: {event.payload.get('reason')}. Review its recent runs on the agents page "
                "and turn the kill switch off when it is re-validated.", link="/pic/agents", object_type="AGENT", object_ref=event.payload.get("agent"))


@outbox.consumer("ai.switch.changed", "notify-ai-switch")
def _ai_switch(session: Session, event: OutboxEvent) -> None:
    on = bool(event.payload.get("enabled"))
    notify(session, _role(session, "CPO", "TENANT_ADMIN"), kind="AI_SWITCH", dedup_key=f"AI_SWITCH:{event.id}",
           title="AI " + ("switched on" if on else "switched off") + " for the organisation",
           body=("AI agents may act again." if on else "Every AI agent is stopped.") + f" Reason: {event.payload.get('reason')}",
           link="/pic/agents", object_type="TENANT_AI", object_ref="AI_SWITCH")
