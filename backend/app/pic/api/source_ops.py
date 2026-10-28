"""Contract amendments/termination, clarifications and reverse auction."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.pic.api.deps import idempotency_key, idempotent, uow
from app.pic.models import Contract, SourcingEvent, Supplier
from app.pic.platform import clock
from app.pic.platform.auth import READ, Principal, require, require_any
from app.pic.platform.errors import not_found
from app.pic.services import amendments, auction
from app.pic.services import contract as contract_svc
from app.pic.services.common import by_ref

router = APIRouter(prefix="/v1")


# ---------------------------------------------------------------- M07 contract amendments and termination (F4)
class AmendmentIn(BaseModel):
    kind: str = Field(pattern="^(VARIATION|EXTENSION|TERMS|TERMINATION)$")
    # VARIATION {"lines":[{"line":10,"unitPriceMinor":39500,"targetQty":"700000"}]} · EXTENSION {"validTo":"2028-10-31"}
    # TERMS {"paymentTerms","incoterms","tolerances":{"over_pct",..},"clauses":[{"code","text","title?","position?"}]}
    # TERMINATION {"forCause": false}
    changes: dict = Field(default_factory=dict)
    reason: str = Field(min_length=3, max_length=2000)
    effective_from: Optional[date] = None
    submit: bool = True


class PreviewIn(BaseModel):
    kind: str = Field(pattern="^(VARIATION|EXTENSION|TERMS|TERMINATION)$")
    changes: dict = Field(default_factory=dict)
    effective_from: Optional[date] = None


class WithdrawIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


def _contract(s, ref: str, p: Principal, lock: bool = False) -> Contract:
    contract = by_ref(s, Contract, ref, lock=lock)
    if "SUPPLIER_USER" in p.roles and contract.supplier_id != p.supplier_id:
        raise not_found("Contract", ref)
    return contract


@router.get("/contracts/{ref}/amendments", tags=["F4 Contract"])
def list_amendments(ref: str, p: Principal = Depends(require_any(READ, "supplier:portal"))):
    with uow(p) as s:
        return amendments.listing(s, _contract(s, ref, p), internal="SUPPLIER_USER" not in p.roles)


@router.post("/contracts/{ref}/amendments/preview", tags=["F4 Contract"])
def preview_amendment(ref: str, body: PreviewIn, p: Principal = Depends(require("contract:manage"))):
    """Validate a change set and show its effect, value delta and approval chain without saving it."""
    with uow(p) as s:
        contract = _contract(s, ref, p)
        return amendments.plan(s, contract, body.kind, body.changes, body.effective_from or clock.today())


@router.post("/contracts/{ref}/amendments", status_code=201, tags=["F4 Contract"])
def create_amendment(ref: str, body: AmendmentIn, p: Principal = Depends(require("contract:manage")),
                     key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/contracts/{ref}/amendments", key, body)
        if idem.replay:
            return idem.replay
        contract = _contract(s, ref, p, lock=True)
        amendment = amendments.create(s, contract, kind=body.kind, changes=body.changes, reason=body.reason,
                                      effective_from=body.effective_from or clock.today(), submit_now=body.submit)
        return idem.store(amendments.view(s, amendment), 201)


@router.get("/contracts/{ref}/amendments/{number}", tags=["F4 Contract"])
def get_amendment(ref: str, number: str, p: Principal = Depends(require_any(READ, "supplier:portal"))):
    with uow(p) as s:
        contract = _contract(s, ref, p)
        amendment = amendments.by_number(s, contract, number)
        internal = "SUPPLIER_USER" not in p.roles
        if not internal and amendment.status not in ("APPROVED", "EFFECTIVE"):
            raise not_found("Contract amendment", number)
        return amendments.view(s, amendment, internal)


@router.post("/contracts/{ref}/amendments/{number}/submit", tags=["F4 Contract"])
def submit_amendment(ref: str, number: str, p: Principal = Depends(require("contract:manage"))):
    with uow(p) as s:
        contract = _contract(s, ref, p, lock=True)
        return amendments.view(s, amendments.submit(s, amendments.by_number(s, contract, number, lock=True)))


@router.post("/contracts/{ref}/amendments/{number}/withdraw", tags=["F4 Contract"])
def withdraw_amendment(ref: str, number: str, body: WithdrawIn, p: Principal = Depends(require("contract:manage"))):
    with uow(p) as s:
        contract = _contract(s, ref, p, lock=True)
        return amendments.view(s, amendments.withdraw(s, amendments.by_number(s, contract, number, lock=True), body.reason))


# ---------------------------------------------------------------- F4-07 e-signature provider (PIC_ESIGN_*)
class EnvelopeIn(BaseModel):
    buyer_signer: Optional[str] = None      # e-mail of an internal user with contract:sign; default: the caller
    supplier_signer: Optional[str] = None   # e-mail of a portal user of the contract's supplier; default: the first active one


@router.post("/contracts/{ref}/signature-envelopes", status_code=201, tags=["F4 Contract"])
def create_signature_envelope(ref: str, body: EnvelopeIn, p: Principal = Depends(require("contract:manage")),
                              key: Optional[str] = Depends(idempotency_key)):
    """Send the contract to the configured e-signature provider; 404 ESIGN_NOT_CONFIGURED keeps the internal signature path."""
    contract_svc.require_esign()
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/contracts/{ref}/signature-envelopes", key, body)
        if idem.replay:
            return idem.replay
        contract = _contract(s, ref, p, lock=True)
        return idem.store(contract_svc.create_envelope(s, contract, body.buyer_signer, body.supplier_signer), 201)


@router.post("/esign/webhook", tags=["F4 Contract"])
async def esign_webhook(request: Request):
    """Provider callback (no bearer token): HMAC-SHA256 of the raw body in X-Esign-Signature, tenant from the envelope reference."""
    body = await request.body()
    return contract_svc.handle_webhook(body, request.headers.get(contract_svc.ESIGN_SIGNATURE_HEADER))


# ---------------------------------------------------------------- F3-03 clarification board
class ClarificationIn(BaseModel):
    text: str = Field(min_length=3, max_length=4000)


class AnswerIn(BaseModel):
    answer: str = Field(min_length=2, max_length=4000)


@router.get("/sourcing/events/{ref}/clarifications", tags=["F3 Sourcing"])
def list_clarifications(ref: str, p: Principal = Depends(require_any(READ, "supplier:portal"))):
    with uow(p) as s:
        return auction.clarifications(s, by_ref(s, SourcingEvent, ref))


@router.post("/sourcing/events/{ref}/clarifications", status_code=201, tags=["F3 Sourcing"])
def ask_clarification(ref: str, body: ClarificationIn, p: Principal = Depends(require_any("supplier:portal", "sourcing:manage")),
                      key: Optional[str] = Depends(idempotency_key)):
    """Supplier question while the event is open, or a notice from the event owner / category manager."""
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/sourcing/events/{ref}/clarifications", key, body)
        if idem.replay:
            return idem.replay
        event = by_ref(s, SourcingEvent, ref, lock=True)
        item = auction.ask(s, event, body.text)
        return idem.store(auction.clarification_view(s, item, p.supplier_id, internal="SUPPLIER_USER" not in p.roles), 201)


@router.post("/sourcing/events/{ref}/clarifications/{seq}/answer", tags=["F3 Sourcing"])
def answer_clarification(ref: str, seq: int, body: AnswerIn, p: Principal = Depends(require("sourcing:manage"))):
    with uow(p) as s:
        event = by_ref(s, SourcingEvent, ref, lock=True)
        return auction.clarification_view(s, auction.answer(s, event, seq, body.answer))


@router.post("/sourcing/events/{ref}/clarifications/{seq}/withdraw", tags=["F3 Sourcing"])
def withdraw_clarification(ref: str, seq: int, p: Principal = Depends(require("supplier:portal"))):
    with uow(p) as s:
        event = by_ref(s, SourcingEvent, ref, lock=True)
        return auction.clarification_view(s, auction.withdraw(s, event, seq), p.supplier_id, internal=False)


# ---------------------------------------------------------------- SRC-04 live reverse auction
class AuctionSettingsIn(BaseModel):
    minDecrementPct: Optional[str] = None
    extensionMinutes: Optional[int] = None
    triggerMinutes: Optional[int] = None
    showRank: Optional[bool] = None
    showBestPrice: Optional[bool] = None
    paymentTermsDays: Optional[int] = None
    leadTimeDays: Optional[int] = None


class AuctionBidIn(BaseModel):
    priceMinor: int = Field(gt=0)


@router.put("/sourcing/events/{ref}/auction", tags=["F3 Sourcing"])
def configure_auction(ref: str, body: AuctionSettingsIn, p: Principal = Depends(require("sourcing:manage"))):
    """Override rule AUCTION for one event while it is a draft; the settings are frozen on publish."""
    with uow(p) as s:
        return auction.configure(s, by_ref(s, SourcingEvent, ref, lock=True), body.model_dump(exclude_none=True))


@router.get("/sourcing/events/{ref}/auction", tags=["F3 Sourcing"])
def auction_view(ref: str, p: Principal = Depends(require_any(READ, "supplier:portal"))):
    with uow(p) as s:
        return auction.view(s, by_ref(s, SourcingEvent, ref))


@router.post("/sourcing/events/{ref}/auction/bids", status_code=201, tags=["F3 Sourcing"])
def auction_bid(ref: str, body: AuctionBidIn, p: Principal = Depends(require("bid:submit")), key: Optional[str] = Depends(idempotency_key)):
    with uow(p) as s:
        idem = idempotent(s, f"POST /v1/sourcing/events/{ref}/auction/bids", key, body)
        if idem.replay:
            return idem.replay
        event = by_ref(s, SourcingEvent, ref, lock=True)
        auction.require_visible(s, event)
        auction.place_bid(s, event, s.get(Supplier, p.supplier_id), body.priceMinor)
        return idem.store(auction.view(s, event), 201)
