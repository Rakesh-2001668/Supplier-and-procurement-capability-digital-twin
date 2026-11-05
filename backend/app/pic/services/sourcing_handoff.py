"""M05 hand-off of an award into the source determination data (Technical Document 9.2).

When a contract born of a sourcing event is activated, its prices are published to source determination (services/contract.py) and the quota
arrangement with running counters is created there. This consumer adds the third piece: the source list entry that allows the supplier for the
material and plant over the contract's validity, so a requirement without a contract line (or after the contract is consumed) still finds the
supplier as an allowed source. It is idempotent: an entry that already covers the contract period is left as it is, and a fixed (mandatory) entry of
another supplier is never changed.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.models import Contract, ContractLine, OutboxEvent, SourceList, SourcingEvent
from app.pic.platform import audit, outbox
from app.pic.services.common import principal  # noqa: F401  (kept for symmetry with the other hand-offs)


@outbox.consumer("contract.activated", "sourcing-source-list")
def _source_list(session: Session, event: OutboxEvent) -> None:
    contract = session.get(Contract, event.object_id)
    if contract is None or not contract.source_event_id:
        return
    sourcing = session.get(SourcingEvent, contract.source_event_id)
    added = []
    for line in session.execute(select(ContractLine).where(ContractLine.contract_id == contract.id)).scalars():
        if line.material_id is None:
            continue
        covered = session.execute(select(SourceList.id).where(
            SourceList.supplier_id == contract.supplier_id, SourceList.material_id == line.material_id, SourceList.plant == line.plant,
            SourceList.valid_from <= contract.valid_from, SourceList.valid_to >= contract.valid_to).limit(1)).first()
        if covered:
            continue
        session.add(SourceList(tenant_id=contract.tenant_id, supplier_id=contract.supplier_id, material_id=line.material_id, plant=line.plant, fixed=False,
                               valid_from=contract.valid_from, valid_to=contract.valid_to, created_by=contract.owner_id))
        added.append(f"{line.material_id}/{line.plant}")
    if added and sourcing is not None:
        session.flush()
        audit.record(session, "SOURCING_EVENT", sourcing.id, "SOURCE_LIST_UPDATED", object_ref=sourcing.number,
                     after={"contract": contract.number, "entries": len(added), "validFrom": contract.valid_from.isoformat(), "validTo": contract.valid_to.isoformat()})
