"""F8 Supplier onboarding & qualification, bank changes (MDM-04), status and performance (M06)."""
import difflib
import os
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import (
    AuditEvent, BankChangeRequest, Certificate, GoodsReceipt, GrLine, Invoice, InvoiceException, PoLine, PoScheduleLine, PurchaseOrder,
    Qualification, SanctionEntry, Scorecard, Supplier, SupplierBankAccount, SupplierCategoryStatus, Task, Timer, TwinFeedback, TwinSnapshot,
)
from app.pic.platform import audit, clock, crypto, integration, outbox, rules, sod, workflow
from app.pic.platform.core import next_number
from app.pic.platform.errors import Problem, illegal_transition, not_found, rule_violation
from app.pic.services import master_changes
from app.pic.services.common import principal, require_supplier_user, supplier_ref

PROCESS = "pic.supplier-onboarding"
ACTIVE_CATEGORY_STATUSES = ("QUALIFIED", "PREFERRED")
IN_ONBOARDING_STATUSES = ("REGISTERED", "UNDER_QUALIFICATION")  # categories still being qualified (F8-05)
# Payment terms key: net days ('N60' or '60'), optionally after an early-payment discount ('2/10 N45' = 2% within 10 days, net 45).
PAYMENT_TERMS_PATTERN = r"^(?:\d{1,2}(?:\.\d{1,2})?/\d{1,3} )?N?\d{1,3}$"


def payment_terms_errors(terms: Optional[str]) -> list[str]:
    if not re.fullmatch(PAYMENT_TERMS_PATTERN, (terms or "").strip().upper()):
        return [f"payment terms '{terms}' are not a terms key: use net days (N60 or 60) or discount + net days (2/10 N45)"]
    return []


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
    # F8-01: the same tax-ID checks as an MDM-04 change (format, state code, check character, PAN inside the GSTIN).
    if errors := master_changes.gstin_errors(gstin, pan, state_code) + master_changes.pan_errors(pan):
        raise master_changes.validation_problem(errors)
    if terms_errors := payment_terms_errors(payment_terms):
        raise Problem(422, "VALIDATION_FAILED", "; ".join(terms_errors), rule_ref="F8-01", errors=terms_errors)
    payment_terms = payment_terms.strip().upper()
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


def mandatory_categories(session: Session, supplier: Supplier, cert_type: str) -> list[str]:
    """The supplier's categories for which SUPPLIER-QUAL (category version where one exists) makes this certificate type
    mandatory. Derived from the rule, never from what the supplier declares."""
    categories = []
    for row in session.execute(select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == supplier.id)
                               .order_by(SupplierCategoryStatus.category)).scalars():
        try:
            body = rules.resolve(session, "SUPPLIER-QUAL", category=row.category).body
        except Problem:
            continue
        if cert_type in (body.get("mandatoryCertificates") or {}).get(row.category, []):
            categories.append(row.category)
    return categories


def _arm_expiry(session: Session, cert: Certificate) -> None:
    """(Re-)arm the expiry timer of a certificate: one pending CERTIFICATE_EXPIRY timer per certificate, due the day after
    its last valid day."""
    for timer in session.execute(select(Timer).where(Timer.kind == "CERTIFICATE_EXPIRY", Timer.object_id == cert.id,
                                                     Timer.fired_at.is_(None))).scalars():
        timer.fired_at = clock.now()
        timer.payload = {**(timer.payload or {}), "cancelled": True}
    workflow.create_timer(session, "CERTIFICATE_EXPIRY", "CERTIFICATE", cert.id, _expiry_due(cert))


def _ensure_expiry_timer(session: Session, cert: Certificate) -> None:
    pending = session.execute(select(Timer.id).where(Timer.kind == "CERTIFICATE_EXPIRY", Timer.object_id == cert.id,
                                                     Timer.fired_at.is_(None))).first()
    if pending is None and cert.status == "VALID":
        workflow.create_timer(session, "CERTIFICATE_EXPIRY", "CERTIFICATE", cert.id, _expiry_due(cert))


def add_certificates(session: Session, supplier: Supplier, certificates: list[dict]) -> list[Certificate]:
    """Store certificates (a new one of a type already on file is a renewal) unverified, with the categories they are
    mandatory for derived from SUPPLIER-QUAL, and arm each expiry timer at once (F8-08)."""
    p = principal(session)
    created = []
    for cert in certificates:
        try:
            cert_type, number = str(cert["type"]).strip().upper(), str(cert["number"]).strip()
            issued_on = cert["issued_on"] if isinstance(cert["issued_on"], date) else date.fromisoformat(str(cert["issued_on"]))
            expires_on = cert["expires_on"] if isinstance(cert["expires_on"], date) else date.fromisoformat(str(cert["expires_on"]))
        except (KeyError, TypeError, ValueError):
            raise Problem(422, "VALIDATION_FAILED", "Each certificate needs type, number, issued_on and expires_on (YYYY-MM-DD)", rule_ref="F8-02")
        if not cert_type or not number:
            raise Problem(422, "VALIDATION_FAILED", "Certificate type and number are required", rule_ref="F8-02")
        if expires_on <= issued_on:
            raise Problem(422, "VALIDATION_FAILED", f"Certificate {cert_type} {number} expires before it is issued", rule_ref="F8-02")
        if expires_on < clock.today():
            raise Problem(422, "VALIDATION_FAILED", f"Certificate {cert_type} {number} expired on {expires_on.isoformat()}", rule_ref="F8-02")
        row = Certificate(tenant_id=current_tenant(session), supplier_id=supplier.id, type=cert_type, number=number, issued_on=issued_on,
                          expires_on=expires_on, mandatory_for=mandatory_categories(session, supplier, cert_type), verified=False,
                          status="VALID", created_by=p.user_id)
        session.add(row)
        session.flush()
        _arm_expiry(session, row)
        created.append(row)
    if created:
        audit.record(session, "SUPPLIER", supplier.id, "CERTIFICATES_SUBMITTED", object_ref=supplier.code,
                     after={"certificates": [{"type": c.type, "number": c.number, "expiresOn": c.expires_on.isoformat(),
                                              "mandatoryFor": list(c.mandatory_for or [])} for c in created]})
    return created


def submit_profile(session: Session, supplier: Supplier, *, bank_account: Optional[str] = None, ifsc: Optional[str] = None,
                   holder_name: Optional[str] = None, certificates: Optional[list[dict]] = None) -> dict:
    """F8-02 supplier profile: certificates at any time; bank details only while onboarding is still running. After
    onboarding a bank change goes through POST /v1/suppliers/{code}/bank-changes (its own BANK_CHANGE process: call-back,
    dual finance approval, cooling-off)."""
    require_supplier_user(session, supplier.id)
    certificates = list(certificates or [])
    bank = [v for v in (bank_account, ifsc, holder_name) if v and str(v).strip()]
    if bank and len(bank) < 3:
        raise Problem(422, "VALIDATION_FAILED", "Bank details need account number, IFSC and account holder", rule_ref="F8-02")
    if not bank and not certificates:
        raise Problem(422, "VALIDATION_FAILED", "Submit bank details or at least one certificate", rule_ref="F8-02")
    instance = _instance(session, supplier)
    onboarding = instance is not None and instance.status == "RUNNING"
    if bank:
        if supplier.status == "BLOCKED":
            raise Problem(409, "SUPPLIER_BLOCKED", f"{supplier.code} is blocked; bank details cannot be changed", rule_ref="MDM-04")
        if not onboarding:
            raise Problem(409, "BANK_CHANGE_PROCESS_REQUIRED",
                          f"Onboarding of {supplier.code} has ended: bank details change only through POST /v1/suppliers/{supplier.code}/bank-changes "
                          "(call-back and dual finance approval)", rule_ref="MDM-04", endpoint=f"/v1/suppliers/{supplier.code}/bank-changes")
        pending = session.execute(select(BankChangeRequest.number).where(
            BankChangeRequest.supplier_id == supplier.id, BankChangeRequest.status.in_(("PENDING_CALLBACK", "PENDING_APPROVAL")))).scalar()
        if pending:
            raise Problem(409, "BANK_CHANGE_PENDING", f"Bank change {pending} is still being verified; wait for its decision", rule_ref="MDM-04")
    created = add_certificates(session, supplier, certificates)
    result = {"certificates": [{"id": str(c.id), "type": c.type, "number": c.number, "mandatoryFor": list(c.mandatory_for or [])}
                               for c in created]}
    if not bank:
        return result
    change = request_bank_change(session, supplier, bank_account=bank_account, ifsc=ifsc, holder_name=holder_name,
                                 in_onboarding=True)
    workflow.step(session, instance, "F8-02", outcome=f"profile submitted with {len(certificates)} certificates")
    screening = screen(session, supplier)
    return {**result, "screening": screening, "bankChange": change.number}


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
DUPLICATE_NAME_RATIO = 0.9
_LEGAL_FORM_WORDS = re.compile(r"\b(?:the|messrs|pvt|private|ltd|limited|llp|inc|llc|plc|co|company|corp|corporation)\b")


def normalise_legal_name(name: str) -> str:
    """Legal name for duplicate matching: case, punctuation and dots ("K.P.R." = "KPR", "L.L.P." = "LLP"), '&' = 'and',
    an "M/s" prefix and the legal form (Pvt Ltd / Private Limited / Ltd / Limited / LLP, "The") do not distinguish
    entities. Mirrors the SPD-03 duplicate-cluster normalisation (spend._norm_name) plus '&', dots and M/s."""
    text = (name or "").lower().replace("&", " and ")
    text = re.sub(r"^\s*m\s*/\s*s\b\.?", " ", text)
    text = text.replace(".", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", _LEGAL_FORM_WORDS.sub(" ", text)).strip()


def screen(session: Session, supplier: Supplier, record_step: bool = True) -> dict:
    """F8-03 duplicate (GSTIN and PAN blind index, similar normalised name) and sanctions screening. A GSTIN of the same
    PAN in another state (or a second registration in the same state) is the same legal entity. ``record_step`` is False
    when screening re-runs after a master change, so the completed onboarding instance is not touched."""
    duplicates = []
    name = normalise_legal_name(supplier.legal_name)
    for other in session.execute(select(Supplier).where(Supplier.id != supplier.id)).scalars():
        if other.gstin_hash and other.gstin_hash == supplier.gstin_hash:
            duplicates.append({"code": other.code, "reason": "same GSTIN"})
        elif other.pan_hash and other.pan_hash == supplier.pan_hash:
            duplicates.append({"code": other.code, "reason": "same PAN (another GST registration of the same legal entity)"})
        elif (other_name := normalise_legal_name(other.legal_name)) and name and \
                difflib.SequenceMatcher(None, other_name, name).ratio() > DUPLICATE_NAME_RATIO:
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


SCREENING_DECISIONS = ("CLEAR", "MERGE", "RESCREEN")


def screening_gate(session: Session, supplier: Supplier) -> dict:
    """F8-03 → F8-05: a supplier is qualified (QUALIFIED / CONDITIONAL) and created in the ERP only on a CLEAR screening,
    or on a REVIEW screening (possible duplicate, sanctions provider unreachable) that a supplier manager other than the
    requester has cleared. A supplier never screened is screened now."""
    screening = supplier.screening or {}
    if not screening.get("outcome"):
        instance = _instance(session, supplier)
        screening = screen(session, supplier, record_step=instance is not None and instance.status == "RUNNING")
    outcome = screening.get("outcome")
    if outcome == "BLOCKED":
        raise rule_violation(f"{supplier.code} has a sanctions match ({', '.join(screening.get('sanctionsHits') or [])})", "F8-03")
    if outcome == "REVIEW":
        disposition = screening.get("disposition") or {}
        if disposition.get("decision") != "CLEARED" or disposition.get("screenedAt") != screening.get("screenedAt"):
            reasons = [f"{d['code']}: {d['reason']}" for d in screening.get("duplicates") or []]
            if screening.get("providerError"):
                reasons.append(f"sanctions provider error: {screening['providerError']}")
            raise rule_violation(f"Screening of {supplier.code} is REVIEW ({'; '.join(reasons) or 'needs review'}): a supplier manager other "
                                 "than the requester must clear it, merge the duplicate or re-screen first", "F8-03",
                                 screening=outcome)
    return screening


def dispose_screening(session: Session, supplier: Supplier, decision: str, note: str, merge_into: Optional[str] = None) -> dict:
    """Screening disposition by a supplier manager: CLEAR a REVIEW result (not a duplicate / provider outage checked
    manually), MERGE the registration into the existing supplier it duplicates, or RESCREEN (re-run duplicate and
    sanctions checks, e.g. once the provider is reachable). Clearing and merging are four-eyes against the requester."""
    p = principal(session)
    if "SUPPLIER_MANAGER" not in p.roles:
        raise Problem(403, "FORBIDDEN", "Screening results are disposed by a supplier manager", rule_ref="F8-03")
    decision = (decision or "").strip().upper()
    if decision not in SCREENING_DECISIONS:
        raise Problem(422, "INVALID_DECISION", f"decision must be one of {', '.join(SCREENING_DECISIONS)}")
    note = (note or "").strip()
    if len(note) < 3:
        raise Problem(422, "REASON_REQUIRED", "Record why (call notes, documents checked)", rule_ref="F8-03")
    before = dict(supplier.screening or {})
    instance = _instance(session, supplier)
    running = instance is not None and instance.status == "RUNNING"
    if decision == "RESCREEN":
        result = screen(session, supplier, record_step=running)
        audit.record(session, "SUPPLIER", supplier.id, "SCREENING_DISPOSED", object_ref=supplier.code, reason=note,
                     before={"outcome": before.get("outcome")}, after={"decision": "RESCREEN", "outcome": result["outcome"]})
        return {"supplier": supplier.code, "decision": "RESCREEN", "screening": result}
    if before.get("outcome") != "REVIEW":
        raise Problem(409, "NOTHING_TO_DISPOSE", f"Screening of {supplier.code} is {before.get('outcome') or 'not run'}; only a REVIEW "
                      "result is cleared or merged (re-screen to refresh it)", rule_ref="F8-03")
    if p.user_id == supplier.created_by:
        raise Problem(409, "SOD_CONFLICT", "The person who registered the supplier cannot dispose its screening", rule_ref="F8-03")
    disposition = {"decision": "CLEARED" if decision == "CLEAR" else "MERGED", "by": str(p.user_id), "byName": p.name,
                   "at": clock.now().isoformat(), "note": note, "screenedAt": before.get("screenedAt")}
    if decision == "MERGE":
        candidates = {d["code"] for d in before.get("duplicates") or []}
        if not merge_into or merge_into not in candidates:
            raise Problem(422, "MERGE_TARGET_REQUIRED", f"Merge into one of the suspected duplicates: {', '.join(sorted(candidates)) or 'none'}",
                          rule_ref="F8-03")
        disposition["mergedInto"] = merge_into
        previous = supplier.status
        supplier.status = "MERGED"
        for q in session.execute(select(Qualification).where(Qualification.supplier_id == supplier.id, Qualification.status == "OPEN")).scalars():
            q.status, q.decision, q.decision_reason = "DECIDED", "REJECTED", f"registration merged into {merge_into}"
        for row in session.execute(select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == supplier.id)).scalars():
            _set_category_status(session, supplier, row.category, "EXITED", f"duplicate registration merged into {merge_into}")
        audit.record(session, "SUPPLIER", supplier.id, "MERGED", object_ref=supplier.code, before={"status": previous},
                     after={"status": "MERGED", "mergedInto": merge_into}, reason=note)
        if running:
            workflow.end(session, instance, "F8-09", outcome=f"duplicate registration merged into {merge_into}", status="CANCELLED")
    supplier.screening = {**before, "disposition": disposition}
    audit.record(session, "SUPPLIER", supplier.id, "SCREENING_DISPOSED", object_ref=supplier.code, reason=note,
                 before={"outcome": "REVIEW"}, after=disposition)
    if running and decision == "CLEAR":
        workflow.step(session, instance, "F8-03", outcome=f"screening review cleared by {p.name}")
    return {"supplier": supplier.code, "decision": decision, "screening": supplier.screening}


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
    if instance is None:
        # An onboarding bank change whose onboarding has ended meanwhile: run it as its own BANK_CHANGE process, so the
        # approval chain (bankApprovers finance controllers) lives on an instance and never collapses to one approval.
        instance = workflow.start(session, PROCESS, "BANK_CHANGE", change.id, change.number)
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
    # Certificates are not verified here: the finance approvers checked the bank letter, not the certificates
    # (verify_certificate, by a supplier manager or quality inspector).
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


def current_certificate(session: Session, supplier_id: uuid.UUID, cert_type: str) -> Optional[Certificate]:
    """The certificate of a type that counts: the VALID, unexpired one that runs longest (latest issue, then latest
    upload on a tie), so a renewal replaces the certificate it renews deterministically."""
    return session.execute(select(Certificate).where(
        Certificate.supplier_id == supplier_id, Certificate.type == cert_type, Certificate.status == "VALID",
        Certificate.expires_on >= clock.today()).order_by(
        Certificate.expires_on.desc(), Certificate.issued_on.desc(), Certificate.created_at.desc(), Certificate.id.desc())
        .limit(1)).scalar_one_or_none()


VERIFIER_ROLES = ("SUPPLIER_MANAGER", "QUALITY_INSPECTOR")


def verify_certificate(session: Session, cert: Certificate, note: str) -> Certificate:
    """Explicit certificate verification (issuer register / original sighted) by a supplier manager or quality inspector,
    never by the person who uploaded it; audited on the supplier."""
    p = principal(session)
    if not set(p.roles) & set(VERIFIER_ROLES):
        raise Problem(403, "FORBIDDEN", "Certificates are verified by a supplier manager or a quality inspector", rule_ref="F8-04")
    note = (note or "").strip()
    if len(note) < 3:
        raise Problem(422, "REASON_REQUIRED", "Record how the certificate was verified (e.g. issuer register checked)", rule_ref="F8-04")
    if cert.verified:
        raise Problem(409, "ALREADY_VERIFIED", f"Certificate {cert.type} {cert.number} is already verified")
    if cert.status != "VALID" or cert.expires_on < clock.today():
        raise illegal_transition("Certificate", cert.number, "EXPIRED" if cert.status == "VALID" else cert.status, "verify")
    if cert.created_by == p.user_id:
        raise Problem(409, "SOD_CONFLICT", "The person who uploaded a certificate cannot verify it", rule_ref="F8-04")
    cert.verified = True
    supplier = session.get(Supplier, cert.supplier_id)
    audit.record(session, "SUPPLIER", supplier.id, "CERTIFICATE_VERIFIED", object_ref=supplier.code, reason=note,
                 before={"certificate": cert.type, "number": cert.number, "verified": False},
                 after={"certificate": cert.type, "number": cert.number, "verified": True, "expiresOn": cert.expires_on.isoformat()})
    return cert


def verify_certificates(session: Session, supplier: Supplier, note: str) -> list[Certificate]:
    """Verify every unverified, valid certificate of a supplier (one audited verification each)."""
    certs = session.execute(select(Certificate).where(Certificate.supplier_id == supplier.id, Certificate.verified.is_(False),
                                                      Certificate.status == "VALID", Certificate.expires_on >= clock.today())
                            .order_by(Certificate.type, Certificate.created_at)).scalars().all()
    return [verify_certificate(session, cert, note) for cert in certs]


def decide_qualification(session: Session, qualification: Qualification, decision: str, reason: str,
                         waiver: Optional[str] = None) -> dict:
    qualification = session.execute(select(Qualification).where(Qualification.id == qualification.id).with_for_update()
                                    .execution_options(populate_existing=True)).scalar_one()
    if qualification.status != "OPEN":
        raise illegal_transition("Qualification", f"{qualification.category}/{qualification.id}", qualification.status, "decide")
    supplier = session.get(Supplier, qualification.supplier_id)
    rule = rules.resolve(session, "SUPPLIER-QUAL", category=qualification.category)
    body = rule.body
    decision = decision.upper()
    if decision not in ("QUALIFIED", "CONDITIONAL", "REJECTED"):
        raise Problem(422, "INVALID_DECISION", "decision must be QUALIFIED, CONDITIONAL or REJECTED")
    gaps = []
    mandatory = body["mandatoryCertificates"].get(qualification.category, [])
    for cert_type in mandatory:
        cert = current_certificate(session, supplier.id, cert_type)
        if cert is None:
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
    if decision != "REJECTED":
        if supplier.status in ("BLOCKED", "MERGED"):
            raise rule_violation(f"{supplier.code} is {supplier.status}; it cannot be qualified", "F8-06")
        if bank is None:
            raise rule_violation("Bank details must be verified (dual finance approval) before qualification", "MDM-04")
        screening_gate(session, supplier)

    qualification.status = "DECIDED"
    qualification.decision = decision
    qualification.decision_reason = reason
    status = {"QUALIFIED": "QUALIFIED", "CONDITIONAL": "CONDITIONAL", "REJECTED": "EXITED"}[decision]
    _set_category_status(session, supplier, qualification.category, status, reason, waiver=waiver)
    instance = _instance(session, supplier)
    running = instance is not None and instance.status == "RUNNING"
    if running:
        workflow.step(session, instance, "F8-05", outcome=f"{qualification.category}: assessment complete")
        workflow.step(session, instance, "F8-06", outcome=f"{decision.lower()}" + (f" (gaps: {'; '.join(gaps)})" if gaps else ""))

    if decision != "REJECTED" and supplier.status == "REGISTERED":
        supplier.status = "ACTIVE"
        target = integration.target_system(session)
        from app.pic.platform import connectors
        connectors.require_mapped(target, "SUPPLIER_MASTER")
        message = integration.enqueue(
            session, target_system=target, message_type="SUPPLIER_MASTER", idempotency_key=f"{supplier.code}|CREATE",
            object_type="SUPPLIER", object_id=supplier.id, object_ref=supplier.code,
            payload={"supplier": supplier.code, "name": supplier.legal_name, "gstin": supplier.gstin_masked,
                     "bank": bank.account_masked, "ifsc": bank.ifsc, "terms": supplier.payment_terms},
        )
        integration.process(session, message)
        if running:
            workflow.step(session, instance, "F8-07", outcome=f"supplier master created; ERP vendor {message.erp_doc_no}")
    for cert in session.execute(select(Certificate).where(Certificate.supplier_id == supplier.id)).scalars():
        _ensure_expiry_timer(session, cert)  # normally armed at upload; certificates loaded before that get theirs now
    categories = {r.category: r.status for r in session.execute(
        select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == supplier.id)).scalars()}
    pending = sorted(c for c, st in categories.items() if st in IN_ONBOARDING_STATUSES)
    if running:
        workflow.step(session, instance, "F8-08", outcome="risk & performance monitoring on; certificate expiry timers set")
        if pending:
            # Qualification is per category: onboarding ends when the last invited category is decided.
            workflow.wait(session, instance, "F8-05", outcome=f"still qualifying for {', '.join(pending)}")
        else:
            outcome = status if len(categories) == 1 else "; ".join(f"{c}: {st}" for c, st in sorted(categories.items()))
            workflow.end(session, instance, "F8-09", outcome=outcome)
    return {"supplier": supplier.code, "category": qualification.category, "status": status, "gaps": gaps,
            "ruleSetVersion": rule.ref, "stillQualifying": pending}


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
    # The categories that need this certificate come from SUPPLIER-QUAL, not from what the supplier declared; a renewal
    # (another VALID, unexpired certificate of the same type) keeps the categories qualified.
    mandatory = mandatory_categories(session, supplier, cert.type)
    replacement = current_certificate(session, supplier.id, cert.type)
    audit.record(session, "SUPPLIER", supplier.id, "CERTIFICATE_EXPIRED", object_ref=supplier.code,
                 after={"certificate": cert.type, "number": cert.number, "expiresOn": cert.expires_on.isoformat(),
                        "mandatoryFor": mandatory, **({"renewedBy": replacement.number} if replacement is not None else {})})
    if replacement is not None:
        return
    for row in session.execute(select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == supplier.id)).scalars():
        if row.category in mandatory and row.status in ACTIVE_CATEGORY_STATUSES:
            _set_category_status(session, supplier, row.category, "CONDITIONAL", f"mandatory certificate {cert.type} expired")


def block(session: Session, supplier: Supplier, reason: str) -> dict:
    before = supplier.status
    before_categories = {r.category: r.status for r in session.execute(
        select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == supplier.id)).scalars()}
    supplier.status = "BLOCKED"
    for row in session.execute(select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == supplier.id)).scalars():
        _set_category_status(session, supplier, row.category, "BLOCKED", reason)
    # A blocked supplier is not paid: every unpaid invoice gets a payment block (the payment run also skips blocked
    # suppliers); only an explicit unblock lifts the blocks set here.
    payment_blocked = []
    for invoice in session.execute(select(Invoice).where(Invoice.supplier_id == supplier.id, Invoice.payment_status == "UNPAID",
                                                         Invoice.status.notin_(("REJECTED", "PAID"))).order_by(Invoice.number)).scalars():
        if not invoice.payment_block:
            invoice.payment_block = True
            payment_blocked.append(invoice.number)
            audit.record(session, "INVOICE", invoice.id, "PAYMENT_BLOCKED", object_ref=invoice.number, reason=reason,
                         before={"paymentBlock": False}, after={"paymentBlock": True, "cause": "SUPPLIER_BLOCKED", "supplier": supplier.code})
    open_pos = session.execute(select(PurchaseOrder).where(
        PurchaseOrder.supplier_id == supplier.id,
        PurchaseOrder.status.in_(("RELEASED", "TRANSMITTED", "CONFIRMED", "PARTIALLY_RECEIVED")))).scalars().all()
    for po in open_pos:
        workflow.start_approval(session, None, "BLOCKED_SUPPLIER_PO", object_type="PURCHASE_ORDER", object_id=po.id,
                                object_ref=po.number, chain=["BUYER"], step_id=None, initiator_id=None,
                                evidence={"reason": reason})
    audit.record(session, "SUPPLIER", supplier.id, "BLOCKED", object_ref=supplier.code, before={"status": before, "categories": before_categories},
                 after={"status": "BLOCKED", "openPosFlagged": [po.number for po in open_pos], "paymentBlocked": payment_blocked}, reason=reason)
    return {"supplier": supplier.code, "status": "BLOCKED", "openPosFlagged": [po.number for po in open_pos], "paymentBlocked": payment_blocked}


def unblock(session: Session, supplier: Supplier, reason: str) -> dict:
    """Explicit, audited unblock by a supplier manager: restores the status before the block and lifts the payment blocks
    the block set (on posted invoices without open exceptions). A sanctions match must be re-screened clear first."""
    p = principal(session)
    if "SUPPLIER_MANAGER" not in p.roles:
        raise Problem(403, "FORBIDDEN", "Suppliers are unblocked by a supplier manager")
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise Problem(422, "REASON_REQUIRED", "Give the reason for lifting the block")
    if supplier.status != "BLOCKED":
        raise illegal_transition("Supplier", supplier.code, supplier.status, "unblock")
    if (supplier.screening or {}).get("outcome") == "BLOCKED":
        raise rule_violation(f"{supplier.code} has a sanctions match ({', '.join(supplier.screening.get('sanctionsHits') or [])}); "
                             "re-screen it (screening disposition RESCREEN) before unblocking", "F8-03")
    blocked = session.execute(select(AuditEvent).where(AuditEvent.object_type == "SUPPLIER", AuditEvent.object_id == supplier.id,
                                                       AuditEvent.action == "BLOCKED").order_by(AuditEvent.seq.desc()).limit(1)).scalar_one_or_none()
    before = (blocked.before or {}) if blocked is not None else {}
    restored = before.get("status") or ("ACTIVE" if supplier.twin_ref else "REGISTERED")
    if restored == "BLOCKED":
        restored = "ACTIVE" if supplier.twin_ref else "REGISTERED"
    supplier.status = restored
    categories = before.get("categories") or {}
    for row in session.execute(select(SupplierCategoryStatus).where(SupplierCategoryStatus.supplier_id == supplier.id)).scalars():
        if row.status == "BLOCKED":
            _set_category_status(session, supplier, row.category, categories.get(row.category) or "REGISTERED", f"unblocked: {reason}")
    lifted = []
    for number in ((blocked.after or {}).get("paymentBlocked") or []) if blocked is not None else []:
        invoice = session.execute(select(Invoice).where(Invoice.number == number, Invoice.supplier_id == supplier.id)).scalar_one_or_none()
        if invoice is None or not invoice.payment_block or invoice.payment_status != "UNPAID" or invoice.status != "POSTED":
            continue  # not yet posted: matching and posting decide the block; paid or rejected: nothing to lift
        if invoice.duplicate_of or session.execute(select(InvoiceException.id).where(InvoiceException.invoice_id == invoice.id,
                                                                                    InvoiceException.status == "OPEN")).first():
            continue
        invoice.payment_block = False
        lifted.append(invoice.number)
        audit.record(session, "INVOICE", invoice.id, "PAYMENT_BLOCK_LIFTED", object_ref=invoice.number, reason=reason,
                     before={"paymentBlock": True}, after={"paymentBlock": False, "cause": "SUPPLIER_UNBLOCKED"})
    audit.record(session, "SUPPLIER", supplier.id, "UNBLOCKED", object_ref=supplier.code, before={"status": "BLOCKED"},
                 after={"status": restored, "paymentBlockLifted": lifted}, reason=reason)
    outbox.emit(session, "supplier.status.changed", "SUPPLIER", supplier.id, supplier.code,
                {"supplierCode": supplier.code, "from": "BLOCKED", "to": restored, "reason": reason})
    return {"supplier": supplier.code, "status": restored, "paymentBlockLifted": lifted}


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


RECEIPT_OTIF = "RECEIPT_OTIF"  # per-receipt contribution (1 on time in full, 0 not), so a reversal can take it back out


def _earlier_receipts_qty(session: Session, gr: GoodsReceipt, po_line_id: uuid.UUID) -> Decimal:
    """Quantity received on the PO line by receipts posted before this one (reversed receipts do not count)."""
    total = Decimal(0)
    for other, qty in session.execute(select(GoodsReceipt, GrLine.qty).join(GrLine, GrLine.gr_id == GoodsReceipt.id).where(
            GrLine.po_line_id == po_line_id, GoodsReceipt.id != gr.id, GoodsReceipt.status != "REVERSED")).all():
        if (other.posting_date, other.created_at, str(other.id)) < (gr.posting_date, gr.created_at, str(gr.id)):
            total += qty
    return total


def receipt_line_otif(session: Session, gr: GoodsReceipt, po: PurchaseOrder, line: GrLine) -> bool:
    """On time in full for one receipt line, against the delivery-schedule lines this receipt fulfils: receipts fill the
    schedule earliest date first, so this receipt covers the cumulative range (earlier receipts, earlier + this qty]. It is
    on time when posted by the (confirmed) date of every schedule line in that range, and in full when it completes the
    last of them (within the under-delivery tolerance). Lines without a schedule use the line quantity and need date."""
    po_line = session.get(PoLine, line.po_line_id)
    under = Decimal(str(po.tolerance.get("under_pct", 0)))
    schedule = [(sl.qty, sl.confirmed_date or sl.delivery_date) for sl in session.execute(
        select(PoScheduleLine).where(PoScheduleLine.po_line_id == po_line.id)
        .order_by(PoScheduleLine.delivery_date, PoScheduleLine.seq)).scalars()] or [(po_line.qty, po_line.need_date)]
    start = _earlier_receipts_qty(session, gr, po_line.id)
    end = start + line.qty
    cumulative, touched = Decimal(0), []
    for qty, due in schedule:
        low, high = cumulative, cumulative + qty
        cumulative = high
        if end > low and start < high:
            touched.append((qty, due, high))
    if not touched:
        touched = [(schedule[-1][0], schedule[-1][1], cumulative)]  # over-delivery beyond the schedule counts on the last line
    on_time = all(gr.posting_date <= due for _, due, _ in touched)
    last_qty, _, last_end = touched[-1]
    in_full = end >= last_end - last_qty * under / 100
    return on_time and in_full


def _score_receipt(session: Session, gr: GoodsReceipt, po: PurchaseOrder, event) -> None:
    if gr.status == "REVERSED" or session.execute(select(TwinFeedback.id).where(
            TwinFeedback.metric == RECEIPT_OTIF, TwinFeedback.source_ref == gr.number, TwinFeedback.supplier_id == po.supplier_id)).first():
        return  # reversed before it was scored, or already scored
    card = _scorecard(session, po.supplier_id, gr.posting_date.strftime("%Y-%m"))
    lines = session.execute(select(GrLine).where(GrLine.gr_id == gr.id)).scalars().all()
    on_time = True
    for line in lines:
        on_time = receipt_line_otif(session, gr, po, line) and on_time
        card.qty_received += line.qty
        card.qty_rejected += line.rejected_qty or 0
    card.receipts += 1
    card.on_time_in_full += 1 if on_time else 0
    _recompute(card)
    _feedback(session, po.supplier_id, RECEIPT_OTIF, Decimal(1 if on_time else 0), event, gr.number)
    _feedback(session, po.supplier_id, "OTIF", card.otif_pct or Decimal(0), event, gr.number)
    if card.ppm is not None:
        _feedback(session, po.supplier_id, "PPM", card.ppm, event, gr.number)


@outbox.consumer("goods_receipt.reversed", "supplier-scorecard")
def _scorecard_on_reversal(session: Session, event) -> None:
    """A reversed receipt (movement 102) leaves the scorecard: its receipt, OTIF hit and quantities are taken back out."""
    gr = session.get(GoodsReceipt, uuid.UUID(event.payload["grId"]))
    po = session.get(PurchaseOrder, gr.po_id)
    scored = session.execute(select(TwinFeedback).where(TwinFeedback.metric == RECEIPT_OTIF, TwinFeedback.source_ref == gr.number,
                                                        TwinFeedback.supplier_id == po.supplier_id)).scalars().first()
    if scored is None or session.execute(select(TwinFeedback.id).where(
            TwinFeedback.metric == f"{RECEIPT_OTIF}_REVERSED", TwinFeedback.source_ref == gr.number,
            TwinFeedback.supplier_id == po.supplier_id)).first():
        return  # never scored (reversed while in quality inspection) or already taken out
    card = _scorecard(session, po.supplier_id, gr.posting_date.strftime("%Y-%m"))
    for line in session.execute(select(GrLine).where(GrLine.gr_id == gr.id)).scalars():
        card.qty_received -= line.qty
        card.qty_rejected -= line.rejected_qty or 0
    card.receipts = max(card.receipts - 1, 0)
    card.on_time_in_full = max(card.on_time_in_full - (1 if scored.value == 1 else 0), 0)
    card.otif_pct = None if not card.receipts else card.otif_pct
    card.ppm = None if not card.qty_received else card.ppm
    _recompute(card)
    _feedback(session, po.supplier_id, f"{RECEIPT_OTIF}_REVERSED", Decimal(-scored.value), event, gr.number)
    _feedback(session, po.supplier_id, "OTIF", card.otif_pct or Decimal(0), event, gr.number)


@outbox.consumer("invoice.posted", "supplier-scorecard")
def _scorecard_on_invoice(session: Session, event) -> None:
    invoice = session.get(Invoice, uuid.UUID(event.payload["invoiceId"]))
    card = _scorecard(session, invoice.supplier_id, invoice.invoice_date.strftime("%Y-%m"))
    card.invoices += 1
    card.invoices_first_pass += 1 if invoice.first_pass_matched else 0
    _recompute(card)
    _feedback(session, invoice.supplier_id, "INVOICE_ACCURACY", card.invoice_accuracy_pct or Decimal(0), event, invoice.number)
