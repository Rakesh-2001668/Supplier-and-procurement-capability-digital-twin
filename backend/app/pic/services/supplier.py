"""F8 Supplier onboarding & qualification, bank changes (MDM-04), status and performance (M06)."""
import difflib
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    BankChangeRequest, Certificate, GoodsReceipt, GrLine, Invoice, PoLine, PurchaseOrder, Qualification,
    SanctionEntry, Scorecard, Supplier, SupplierBankAccount, SupplierCategoryStatus, Task, TwinFeedback, TwinSnapshot,
)
from app.pic.platform import audit, clock, crypto, integration, outbox, rules, sod, workflow
from app.pic.platform.core import next_number
from app.pic.platform.errors import Problem, illegal_transition, not_found, rule_violation
from app.pic.services.common import principal, require_supplier_user, supplier_ref

PROCESS = "pic.supplier-onboarding"
ACTIVE_CATEGORY_STATUSES = ("QUALIFIED", "PREFERRED")


def _instance(session: Session, supplier: Supplier):
    return workflow.find(session, "SUPPLIER", supplier.id, PROCESS)


def _set_category_status(session: Session, supplier: Supplier, category: str, status: str, reason: str,
                         waiver: Optional[str] = None) -> SupplierCategoryStatus:
    row = session.execute(select(SupplierCategoryStatus).where(
        SupplierCategoryStatus.supplier_id == supplier.id, SupplierCategoryStatus.category == category)).scalar_one_or_none()
    before = row.status if row else None
    if row is None:
        row = SupplierCategoryStatus(tenant_id=current_tenant(session), supplier_id=supplier.id, category=category,
                                     status=status, created_by=principal(session).user_id)
        session.add(row)
    row.status = status
    if waiver is not None:
        row.waiver_reason = waiver
    if status in ACTIVE_CATEGORY_STATUSES:
        row.qualified_on = clock.today()
    session.flush()
    if before != status:
        audit.record(session, "SUPPLIER", supplier.id, "CATEGORY_STATUS_CHANGED", object_ref=supplier.code,
                     before={"category": category, "status": before}, after={"category": category, "status": status},
                     reason=reason)
        outbox.emit(session, "supplier.status.changed", "SUPPLIER", supplier.id, supplier.code,
                    {"supplierCode": supplier.code, "category": category, "from": before, "to": status, "reason": reason})
    return row


# ---------------------------------------------------------------- F8-01/02 registration and profile
def register(session: Session, *, code: Optional[str], legal_name: str, gstin: str, pan: str, state_code: str,
             contact_email: str, categories: list[str], payment_terms: str = "N60", incoterms: Optional[str] = None,
             segment: Optional[str] = None, address: Optional[dict] = None, channel: str = "SUPPLIER_MANAGER") -> Supplier:
    p = principal(session)
    tenant_id = current_tenant(session)
    supplier = Supplier(
        tenant_id=tenant_id, code=code or next_number(session, "SUPPLIER"), legal_name=legal_name, status="REGISTERED",
        gstin_enc=crypto.encrypt(tenant_id, "gstin", gstin), gstin_masked=crypto.mask(gstin), gstin_hash=crypto.blind_index(tenant_id, gstin),
        pan_hash=crypto.blind_index(tenant_id, pan), state_code=state_code, contact_email=contact_email,
        payment_terms=payment_terms, incoterms=incoterms, segment=segment, address=address or {}, created_by=p.user_id,
    )
    session.add(supplier)
    session.flush()
    for category in categories:
        _set_category_status(session, supplier, category, "REGISTERED", "invited for category")
    # SOD-01: whoever creates the supplier master may not create POs for it.
    sod.record(session, "SUPPLIER_CREATE", {"supplier_id": supplier.id})
    audit.record(session, "SUPPLIER", supplier.id, "REGISTERED", object_ref=supplier.code,
                 after={"legalName": legal_name, "gstin": supplier.gstin_masked, "categories": categories, "channel": channel})
    instance = workflow.start(session, PROCESS, "SUPPLIER", supplier.id, supplier.code)
    workflow.wait(session, instance, "F8-02", outcome="awaiting profile, tax IDs, bank and certificates")
    return supplier


def submit_profile(session: Session, supplier: Supplier, *, bank_account: str, ifsc: str, holder_name: str,
                   certificates: list[dict]) -> dict:
    require_supplier_user(session, supplier.id)
    tenant_id = current_tenant(session)
    p = principal(session)
    for cert in certificates:
        session.add(Certificate(
            tenant_id=tenant_id, supplier_id=supplier.id, type=cert["type"], number=cert["number"],
            issued_on=date.fromisoformat(str(cert["issued_on"])), expires_on=date.fromisoformat(str(cert["expires_on"])),
            mandatory_for=cert.get("mandatory_for", []), verified=False, status="VALID", created_by=p.user_id,
        ))
    change = request_bank_change(session, supplier, bank_account=bank_account, ifsc=ifsc, holder_name=holder_name,
                                 in_onboarding=True)
    instance = _instance(session, supplier)
    workflow.step(session, instance, "F8-02", outcome=f"profile submitted with {len(certificates)} certificates")
    screening = screen(session, supplier)
    return {"screening": screening, "bankChange": change.number}


# ---------------------------------------------------------------- F8-03 licensed sanctions / watch-list feed
SANCTIONS_MATCH_RATIO = 0.88


class SanctionsUnavailable(Exception):
    """The provider list download failed."""


class SanctionsNoDownload(SanctionsUnavailable):
    """The provider offers search only, no list download."""


class SanctionsProvider:
    """HTTP adapter for a licensed sanctions / watch-list provider, configured by environment:

    PIC_SANCTIONS_PROVIDER  name of the provider; used as ``source`` of hits and of synced entries (e.g. OPENSANCTIONS)
    PIC_SANCTIONS_URL       base URL. Screening calls ``GET {url}/search?name=&country=``; list sync calls ``GET {url}/list``
    PIC_SANCTIONS_API_KEY   sent as ``Authorization: Bearer <key>`` and ``X-API-Key``

    Responses are JSON: a list, or an object with ``results`` / ``matches`` / ``hits`` (search) or ``entries`` / ``results``
    (list). Each item has ``name`` (or ``caption``) and optionally ``score`` (0..1), ``list``/``dataset`` and ``id``.
    Items without a score are fuzzy-matched like the local list.
    """

    def __init__(self, name: str, url: str, api_key: Optional[str]):
        self.name = name[:60]
        self.url = url.rstrip("/")
        self.api_key = api_key

    @classmethod
    def from_env(cls) -> Optional["SanctionsProvider"]:
        name, url = os.environ.get("PIC_SANCTIONS_PROVIDER"), os.environ.get("PIC_SANCTIONS_URL")
        return cls(name.strip().upper(), url.strip(), os.environ.get("PIC_SANCTIONS_API_KEY")) if name and url else None

    def _get(self, path: str, params: Optional[dict] = None):
        import httpx
        headers = {"accept": "application/json", "user-agent": "AlphaHelion PIC screening"}
        if self.api_key:
            headers.update({"authorization": f"Bearer {self.api_key}", "x-api-key": self.api_key})
        response = httpx.get(f"{self.url}{path}", params=params, headers=headers, timeout=10)
        return response

    @staticmethod
    def _items(data, keys: tuple[str, ...]) -> list:
        if isinstance(data, list):
            return data
        for key in keys:
            if isinstance(data, dict) and isinstance(data.get(key), list):
                return data[key]
        return []

    def search(self, legal_name: str, country: Optional[str]) -> list[dict]:
        response = self._get("/search", {"name": legal_name, "country": country or "IN"})
        response.raise_for_status()
        hits = []
        for item in self._items(response.json(), ("results", "matches", "hits")):
            name = str(item.get("name") or item.get("caption") or "") if isinstance(item, dict) else str(item)
            if not name:
                continue
            score = item.get("score") if isinstance(item, dict) else None
            score = float(score) if score is not None else difflib.SequenceMatcher(None, name.lower(), legal_name.lower()).ratio()
            if score > SANCTIONS_MATCH_RATIO:
                hits.append({"name": name[:200], "score": round(score, 3), "source": self.name,
                             "list": (item.get("list") or item.get("dataset")) if isinstance(item, dict) else None,
                             "ref": str(item.get("id")) if isinstance(item, dict) and item.get("id") is not None else None})
        return hits

    def download(self) -> list[dict]:
        try:
            response = self._get("/list")
        except Exception as exc:  # noqa: BLE001
            raise SanctionsUnavailable(f"{type(exc).__name__}: {exc}")
        if response.status_code in (404, 405, 501):
            raise SanctionsNoDownload(f"{self.name} offers no list download (HTTP {response.status_code})")
        if response.status_code >= 400:
            raise SanctionsUnavailable(f"{self.name} list download failed (HTTP {response.status_code})")
        entries = []
        for item in self._items(response.json(), ("entries", "results", "data")):
            name = str(item.get("name") or item.get("caption") or "") if isinstance(item, dict) else str(item)
            if name.strip():
                entries.append({"name": name.strip()[:200],
                                "id": str(item.get("id")) if isinstance(item, dict) and item.get("id") is not None else None})
        return entries


def sanctions_provider() -> Optional[SanctionsProvider]:
    return SanctionsProvider.from_env()


def sync_sanctions(session: Session) -> dict:
    """Replace this provider's entries in sanction_entry with its current list (other sources, e.g. SAMPLE-LIST, stay)."""
    import hashlib
    from sqlalchemy import delete

    provider = sanctions_provider()
    if provider is None:
        raise Problem(409, "SANCTIONS_PROVIDER_NOT_CONFIGURED",
                      "Set PIC_SANCTIONS_PROVIDER and PIC_SANCTIONS_URL (and PIC_SANCTIONS_API_KEY) to use a licensed list", rule_ref="F8-03")
    if provider.name == "SAMPLE-LIST":
        raise Problem(422, "INVALID_PROVIDER", "The provider name must differ from the built-in SAMPLE-LIST", rule_ref="F8-03")
    try:
        entries = provider.download()
    except (SanctionsUnavailable, ValueError) as exc:  # ValueError: the list is not JSON
        raise Problem(409 if isinstance(exc, SanctionsNoDownload) else 502, "SANCTIONS_LIST_UNAVAILABLE", str(exc), rule_ref="F8-03")
    tenant_id = current_tenant(session)
    removed = session.execute(delete(SanctionEntry).where(SanctionEntry.source == provider.name)).rowcount
    unique = {e["name"].lower(): e for e in entries}
    for entry in unique.values():
        session.add(SanctionEntry(tenant_id=tenant_id, name=entry["name"], source=provider.name,
                                  identifier_hash=hashlib.sha256(entry["id"].encode()).hexdigest() if entry["id"] else None,
                                  created_by=principal(session).user_id))
    session.flush()
    kept = session.execute(select(SanctionEntry.source).where(SanctionEntry.source != provider.name)).scalars().all()
    result = {"provider": provider.name, "loaded": len(unique), "replaced": removed, "otherSourcesKept": sorted(set(kept)),
              "syncedAt": clock.now().isoformat()}
    audit.record(session, "SANCTIONS_LIST", uuid.uuid5(uuid.NAMESPACE_URL, f"pic-sanctions:{provider.name}"), "SANCTIONS_SYNCED",
                 object_ref=provider.name, after=result)
    return result


# ---------------------------------------------------------------- F8-03 screening
def screen(session: Session, supplier: Supplier, record_step: bool = True) -> dict:
    """F8-03 duplicate (GSTIN blind index, similar name) and sanctions screening. ``record_step`` is False when
    screening re-runs after a master change, so the completed onboarding instance is not touched."""
    duplicates = []
    for other in session.execute(select(Supplier).where(Supplier.id != supplier.id)).scalars():
        if other.gstin_hash and other.gstin_hash == supplier.gstin_hash:
            duplicates.append({"code": other.code, "reason": "same GSTIN"})
        elif difflib.SequenceMatcher(None, other.legal_name.lower(), supplier.legal_name.lower()).ratio() > 0.9:
            duplicates.append({"code": other.code, "reason": "similar legal name"})
    sanctions = [s.source for s in session.execute(select(SanctionEntry)).scalars()
                 if difflib.SequenceMatcher(None, s.name.lower(), supplier.legal_name.lower()).ratio() > SANCTIONS_MATCH_RATIO]
    provider = sanctions_provider()
    provider_hits, provider_error = [], None
    if provider is not None:
        try:
            provider_hits = provider.search(supplier.legal_name, supplier.country)
        except Exception as exc:  # noqa: BLE001 - a feed outage must not block registration; screening goes to REVIEW
            provider_error = f"{provider.name}: {type(exc).__name__}: {exc}"[:300]
        if provider_hits and provider.name not in sanctions:
            sanctions.append(provider.name)
    result = {"duplicates": duplicates, "sanctionsHits": sanctions, "screenedAt": clock.now().isoformat(),
              "outcome": "BLOCKED" if sanctions else ("REVIEW" if duplicates or provider_error else "CLEAR")}
    if provider is not None:
        result.update(provider=provider.name, providerHits=provider_hits, providerError=provider_error)
    supplier.screening = result
    instance = _instance(session, supplier) if record_step else None
    if instance:
        workflow.step(session, instance, "F8-03", outcome=f"screening {result['outcome']}")
    audit.record(session, "SUPPLIER", supplier.id, "SCREENED", object_ref=supplier.code, after=result)
    if sanctions:
        block(session, supplier, f"Sanctions match: {', '.join(sanctions)}")
    return result


# ---------------------------------------------------------------- MDM-04 bank change (F8-04)
def request_bank_change(session: Session, supplier: Supplier, *, bank_account: str, ifsc: str, holder_name: str,
                        in_onboarding: bool = False) -> BankChangeRequest:
    p = principal(session)
    tenant_id = current_tenant(session)
    account = SupplierBankAccount(
        tenant_id=tenant_id, supplier_id=supplier.id, account_enc=crypto.encrypt(tenant_id, "bank", bank_account),
        account_masked=crypto.mask(bank_account), ifsc=ifsc, holder_name=holder_name, active=False, created_by=p.user_id,
    )
    session.add(account)
    session.flush()
    change = BankChangeRequest(
        tenant_id=tenant_id, number=next_number(session, "BANK_CHANGE"), supplier_id=supplier.id, bank_account_id=account.id,
        status="PENDING_CALLBACK", requested_by=p.user_id, created_by=p.user_id,
    )
    session.add(change)
    session.flush()
    # SOD-02: the person changing bank details may not approve payments or post invoices for this supplier.
    sod.record(session, "SUPPLIER_BANK_CHANGE", {"supplier_id": supplier.id})
    audit.record(session, "SUPPLIER", supplier.id, "BANK_CHANGE_REQUESTED", object_ref=supplier.code,
                 after={"request": change.number, "account": account.account_masked, "ifsc": ifsc})
    if not in_onboarding:
        workflow.start(session, PROCESS, "BANK_CHANGE", change.id, change.number)
    return change


def callback_verify(session: Session, change: BankChangeRequest, note: str) -> BankChangeRequest:
    p = principal(session)
    if change.status != "PENDING_CALLBACK":
        raise illegal_transition("Bank change", change.number, change.status, "callback")
    if p.user_id == change.requested_by:
        raise Problem(409, "SOD_CONFLICT", "The requester cannot perform the call-back verification", rule_ref="MDM-04")
    change.status = "PENDING_APPROVAL"
    change.callback_verified_by = p.user_id
    change.callback_note = note
    supplier = session.get(Supplier, change.supplier_id)
    rule = rules.resolve(session, "SUPPLIER-QUAL")
    audit.record(session, "SUPPLIER", supplier.id, "BANK_CALLBACK_VERIFIED", object_ref=supplier.code,
                 after={"request": change.number}, reason=note, rule_set_version=rule.ref)
    instance = workflow.find(session, "BANK_CHANGE", change.id, PROCESS)
    if instance is None:
        onboarding = _instance(session, supplier)
        instance = onboarding if onboarding and onboarding.status == "RUNNING" else None
    if instance is not None:
        workflow.step(session, instance, "F8-03", outcome="bank call-back verified")
    workflow.start_approval(
        session, instance, "BANK_CHANGE", object_type="BANK_CHANGE", object_id=change.id, object_ref=change.number,
        chain=["FINANCE_CONTROLLER"] * int(rule.body["bankApprovers"]), step_id="F8-04" if instance else None,
        initiator_id=change.requested_by, exclude=[p.user_id], rule_set_version=rule.ref,
    )
    return change


@workflow.on_task("BANK_CHANGE")
def _bank_change_decided(session: Session, task: Task, outcome: str) -> None:
    change = session.get(BankChangeRequest, task.object_id)
    supplier = session.get(Supplier, change.supplier_id)
    approvers = [str(t.completed_by) for t in session.execute(select(Task).where(Task.group_key == task.group_key)).scalars()]
    change.approvals = approvers
    if outcome != "APPROVED":
        change.status = "REJECTED"
        audit.record(session, "SUPPLIER", supplier.id, "BANK_CHANGE_REJECTED", object_ref=supplier.code, reason=task.comment)
        return
    rule = rules.resolve(session, "SUPPLIER-QUAL")
    account = session.get(SupplierBankAccount, change.bank_account_id)
    for other in session.execute(select(SupplierBankAccount).where(SupplierBankAccount.supplier_id == supplier.id,
                                                                   SupplierBankAccount.id != account.id)).scalars():
        other.active = False
    account.active = True
    account.verified_on = clock.today()
    account.payable_from = clock.now() + timedelta(hours=int(rule.body["coolingOffHours"]))
    change.status = "APPROVED"
    audit.record(session, "SUPPLIER", supplier.id, "BANK_CHANGE_APPROVED", object_ref=supplier.code,
                 after={"account": account.account_masked, "payableFrom": account.payable_from.isoformat(),
                        "approvers": len(approvers)}, rule_set_version=rule.ref)
    # Verify tax IDs and certificates at the same dual check.
    for cert in session.execute(select(Certificate).where(Certificate.supplier_id == supplier.id)).scalars():
        cert.verified = True
    if supplier.status in ("ACTIVE",):
        integration.enqueue(session, target_system=integration.target_system(session), message_type="SUPPLIER_MASTER",
                            idempotency_key=f"{supplier.code}|BANK|{change.number}", object_type="SUPPLIER",
                            object_id=supplier.id, object_ref=supplier.code,
                            payload={"supplier": supplier.code, "bank": account.account_masked, "ifsc": account.ifsc})


# ---------------------------------------------------------------- F8-05/06 qualification
def start_qualification(session: Session, supplier: Supplier, category: str) -> Qualification:
    p = principal(session)
    qualification = Qualification(tenant_id=current_tenant(session), supplier_id=supplier.id, category=category,
                                  status="OPEN", created_by=p.user_id)
    session.add(qualification)
    session.flush()
    _set_category_status(session, supplier, category, "UNDER_QUALIFICATION", "qualification started")
    instance = _instance(session, supplier)
    if instance:
        workflow.wait(session, instance, "F8-05", outcome=f"qualifying for {category}")
    return qualification


def record_assessment(session: Session, qualification: Qualification, *, questionnaire: Optional[dict] = None,
                      questionnaire_score: Optional[Decimal] = None, audit_score: Optional[Decimal] = None,
                      sample_approval: Optional[str] = None) -> Qualification:
    if qualification.status != "OPEN":
        raise illegal_transition("Qualification", str(qualification.id), qualification.status, "assess")
    if questionnaire is not None:
        qualification.questionnaire = questionnaire
    if questionnaire_score is not None:
        qualification.questionnaire_score = questionnaire_score
    if audit_score is not None:
        qualification.audit_score = audit_score
    if sample_approval is not None:
        qualification.sample_approval = sample_approval
    audit.record(session, "SUPPLIER", qualification.supplier_id, "QUALIFICATION_ASSESSED", object_ref=qualification.category,
                 after={"questionnaire": str(qualification.questionnaire_score), "audit": str(qualification.audit_score),
                        "sample": qualification.sample_approval})
    return qualification


def decide_qualification(session: Session, qualification: Qualification, decision: str, reason: str,
                         waiver: Optional[str] = None) -> dict:
    supplier = session.get(Supplier, qualification.supplier_id)
    rule = rules.resolve(session, "SUPPLIER-QUAL", category=qualification.category)
    body = rule.body
    decision = decision.upper()
    if decision not in ("QUALIFIED", "CONDITIONAL", "REJECTED"):
        raise Problem(422, "INVALID_DECISION", "decision must be QUALIFIED, CONDITIONAL or REJECTED")
    gaps = []
    mandatory = body["mandatoryCertificates"].get(qualification.category, [])
    certs = {c.type: c for c in session.execute(select(Certificate).where(Certificate.supplier_id == supplier.id)).scalars()}
    for cert_type in mandatory:
        cert = certs.get(cert_type)
        if cert is None or cert.status != "VALID" or cert.expires_on < clock.today():
            gaps.append(f"certificate {cert_type} missing or expired")
        elif not cert.verified:
            gaps.append(f"certificate {cert_type} not verified")
    if (qualification.questionnaire_score or 0) < body["minQuestionnaireScore"]:
        gaps.append(f"questionnaire score below {body['minQuestionnaireScore']}")
    if (qualification.audit_score or 0) < body["minAuditScore"]:
        gaps.append(f"audit score below {body['minAuditScore']}")
    if qualification.category in body.get("sampleApprovalRequired", []) and qualification.sample_approval != "PPAP_APPROVED":
        gaps.append("PPAP sample approval missing")
    if decision == "QUALIFIED" and gaps:
        raise rule_violation("Supplier cannot be Qualified: " + "; ".join(gaps), rule.ref, gaps=gaps)
    if decision == "CONDITIONAL" and not waiver:
        raise rule_violation("A Conditional decision needs a written waiver", rule.ref)
    bank = session.execute(select(SupplierBankAccount).where(SupplierBankAccount.supplier_id == supplier.id,
                                                             SupplierBankAccount.active.is_(True))).scalar_one_or_none()
    if decision != "REJECTED" and bank is None:
        raise rule_violation("Bank details must be verified (dual finance approval) before qualification", "MDM-04")

    qualification.status = "DECIDED"
    qualification.decision = decision
    qualification.decision_reason = reason
    status = {"QUALIFIED": "QUALIFIED", "CONDITIONAL": "CONDITIONAL", "REJECTED": "EXITED"}[decision]
    _set_category_status(session, supplier, qualification.category, status, reason, waiver=waiver)
    instance = _instance(session, supplier)
    if instance:
        workflow.step(session, instance, "F8-05", outcome=f"{qualification.category}: assessment complete")
        workflow.step(session, instance, "F8-06", outcome=f"{decision.lower()}" + (f" (gaps: {'; '.join(gaps)})" if gaps else ""))

    if decision != "REJECTED" and supplier.status == "REGISTERED":
        supplier.status = "ACTIVE"
        message = integration.enqueue(
            session, target_system=integration.target_system(session), message_type="SUPPLIER_MASTER", idempotency_key=f"{supplier.code}|CREATE",
            object_type="SUPPLIER", object_id=supplier.id, object_ref=supplier.code,
            payload={"supplier": supplier.code, "name": supplier.legal_name, "gstin": supplier.gstin_masked,
                     "bank": bank.account_masked, "ifsc": bank.ifsc, "terms": supplier.payment_terms},
        )
        integration.process(session, message)
        if instance:
            workflow.step(session, instance, "F8-07", outcome=f"supplier master created; ERP vendor {message.erp_doc_no}")
    for cert in certs.values():
        workflow.create_timer(session, "CERTIFICATE_EXPIRY", "CERTIFICATE", cert.id, _expiry_due(cert))
    if instance:
        workflow.step(session, instance, "F8-08", outcome="risk & performance monitoring on; certificate expiry timers set")
        workflow.end(session, instance, "F8-09", outcome=status)
    return {"supplier": supplier.code, "category": qualification.category, "status": status, "gaps": gaps,
            "ruleSetVersion": rule.ref}


def _expiry_due(cert: Certificate):
    """A certificate is valid through its expiry date; it lapses at the start of the next day (IST)."""
    return clock.at_ist(cert.expires_on + timedelta(days=1), 0, 5)


@workflow.on_timer("CERTIFICATE_EXPIRY")
def _certificate_expired(session: Session, timer) -> None:
    cert = session.get(Certificate, timer.object_id)
    if cert is None or cert.status == "EXPIRED":
        return
    if cert.expires_on >= clock.today():
        # Timers armed on the expiry date itself (earlier releases) fire while the certificate is still valid: re-arm.
        if timer.due_at < _expiry_due(cert):
            workflow.create_timer(session, "CERTIFICATE_EXPIRY", "CERTIFICATE", cert.id, _expiry_due(cert), timer.payload)
        return
    cert.status = "EXPIRED"
    supplier = session.get(Supplier, cert.supplier_id)
    audit.record(session, "SUPPLIER", supplier.id, "CERTIFICATE_EXPIRED", object_ref=supplier.code,
                 after={"certificate": cert.type, "number": cert.number, "expiresOn": cert.expires_on.isoformat(),
                        "mandatoryFor": list(cert.mandatory_for or [])})
    for row in session.execute(select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == supplier.id)).scalars():
        if row.category in (cert.mandatory_for or []) and row.status in ACTIVE_CATEGORY_STATUSES:
            _set_category_status(session, supplier, row.category, "CONDITIONAL", f"mandatory certificate {cert.type} expired")


def block(session: Session, supplier: Supplier, reason: str) -> dict:
    before = supplier.status
    supplier.status = "BLOCKED"
    for row in session.execute(select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == supplier.id)).scalars():
        _set_category_status(session, supplier, row.category, "BLOCKED", reason)
    open_pos = session.execute(select(PurchaseOrder).where(
        PurchaseOrder.supplier_id == supplier.id,
        PurchaseOrder.status.in_(("RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED")))).scalars().all()
    for po in open_pos:
        workflow.start_approval(session, None, "BLOCKED_SUPPLIER_PO", object_type="PURCHASE_ORDER", object_id=po.id,
                                object_ref=po.number, chain=["BUYER"], step_id=None, initiator_id=None,
                                evidence={"reason": reason})
    audit.record(session, "SUPPLIER", supplier.id, "BLOCKED", object_ref=supplier.code, before={"status": before},
                 after={"status": "BLOCKED", "openPosFlagged": [po.number for po in open_pos]}, reason=reason)
    return {"supplier": supplier.code, "status": "BLOCKED", "openPosFlagged": [po.number for po in open_pos]}


@workflow.on_task("BLOCKED_SUPPLIER_PO")
def _blocked_po_reviewed(session: Session, task: Task, outcome: str) -> None:
    audit.record(session, "PURCHASE_ORDER", task.object_id, "BLOCKED_SUPPLIER_REVIEWED", object_ref=task.object_ref,
                 reason=task.comment, after={"outcome": outcome})


@integration.on_posted("SUPPLIER_MASTER")
def _supplier_synced(session: Session, message) -> None:
    supplier = session.get(Supplier, message.object_id)
    if supplier is not None and not supplier.twin_ref:
        supplier.twin_ref = f"ERP-VENDOR-{message.erp_doc_no}"


# ---------------------------------------------------------------- twin and scorecards (§12.3)
def twin(session: Session, supplier_id: uuid.UUID, category: str) -> Optional[TwinSnapshot]:
    return session.execute(select(TwinSnapshot).where(TwinSnapshot.supplier_id == supplier_id,
                                                      TwinSnapshot.category == category)).scalar_one_or_none()


def _scorecard(session: Session, supplier_id: uuid.UUID, period: str) -> Scorecard:
    card = session.execute(select(Scorecard).where(Scorecard.supplier_id == supplier_id, Scorecard.period == period)
                           .with_for_update()).scalar_one_or_none()
    if card is None:
        card = Scorecard(tenant_id=current_tenant(session), supplier_id=supplier_id, period=period, receipts=0,
                         on_time_in_full=0, qty_received=0, qty_rejected=0, invoices=0, invoices_first_pass=0)
        session.add(card)
        session.flush()
    return card


def _recompute(card: Scorecard) -> None:
    if card.receipts:
        card.otif_pct = (Decimal(card.on_time_in_full) * 100 / card.receipts).quantize(Decimal("0.01"))
    if card.qty_received:
        card.ppm = (Decimal(card.qty_rejected) * 1_000_000 / Decimal(card.qty_received)).quantize(Decimal("0.1"))
    if card.invoices:
        card.invoice_accuracy_pct = (Decimal(card.invoices_first_pass) * 100 / card.invoices).quantize(Decimal("0.01"))


def _feedback(session: Session, supplier_id: uuid.UUID, metric: str, value: Decimal, event, ref: str) -> None:
    session.add(TwinFeedback(tenant_id=current_tenant(session), supplier_id=supplier_id, metric=metric, value=value,
                             source_event=event.topic, source_ref=ref))


@outbox.consumer("quality.usage_decision", "supplier-scorecard")
def _scorecard_on_quality(session: Session, event) -> None:
    gr = session.get(GoodsReceipt, uuid.UUID(event.payload["grId"]))
    po = session.get(PurchaseOrder, gr.po_id)
    _score_receipt(session, gr, po, event)


@outbox.consumer("goods_receipt.posted", "supplier-scorecard")
def _scorecard_on_receipt(session: Session, event) -> None:
    if event.payload.get("qualityHold"):
        return  # scored when the usage decision is taken
    gr = session.get(GoodsReceipt, uuid.UUID(event.payload["grId"]))
    po = session.get(PurchaseOrder, gr.po_id)
    _score_receipt(session, gr, po, event)


def _score_receipt(session: Session, gr: GoodsReceipt, po: PurchaseOrder, event) -> None:
    card = _scorecard(session, po.supplier_id, gr.posting_date.strftime("%Y-%m"))
    lines = session.execute(select(GrLine).where(GrLine.gr_id == gr.id)).scalars().all()
    on_time = True
    for line in lines:
        po_line = session.get(PoLine, line.po_line_id)
        under = Decimal(str(po.tolerance.get("under_pct", 0)))
        in_full = po_line.received_qty >= po_line.qty * (1 - under / 100)
        on_time = on_time and gr.posting_date <= po_line.need_date and in_full
        card.qty_received += line.qty
        card.qty_rejected += line.rejected_qty or 0
    card.receipts += 1
    card.on_time_in_full += 1 if on_time else 0
    _recompute(card)
    _feedback(session, po.supplier_id, "OTIF", card.otif_pct or Decimal(0), event, gr.number)
    if card.ppm is not None:
        _feedback(session, po.supplier_id, "PPM", card.ppm, event, gr.number)


@outbox.consumer("invoice.posted", "supplier-scorecard")
def _scorecard_on_invoice(session: Session, event) -> None:
    invoice = session.get(Invoice, uuid.UUID(event.payload["invoiceId"]))
    card = _scorecard(session, invoice.supplier_id, invoice.invoice_date.strftime("%Y-%m"))
    card.invoices += 1
    card.invoices_first_pass += 1 if invoice.first_pass_matched else 0
    _recompute(card)
    _feedback(session, invoice.supplier_id, "INVOICE_ACCURACY", card.invoice_accuracy_pct or Decimal(0), event, invoice.number)
