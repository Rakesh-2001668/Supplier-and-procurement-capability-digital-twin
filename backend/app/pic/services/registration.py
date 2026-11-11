"""Organisation registration (unified platform, phase 3; docs/PIC_Unified_Platform_Design.md §3.4).

A company registers itself as a buyer organisation with its **shared company mailbox** (info@, purchase@, ... on its own domain; free e-mail
domains refused) and names its **first administrator**, a person with a work e-mail on the same domain who becomes the sign-in account.
An optional "authorised by" person (for example a director) is recorded for the platform operator.

1. ``submit`` validates and stores the request (PENDING_VERIFICATION) and e-mails a single-use verification link (24 h) to the shared mailbox.
   The answer is the same whether or not the domain is already known ("check the mailbox"), so registration cannot be used to probe.
2. ``verify`` confirms the mailbox: PENDING_APPROVAL, screening (sanctions, similar organisation names, the domain already in use, other
   open requests), e-mail to the platform operators.
3. A platform operator (role PLATFORM_OPERATOR, the platform's own organisation) approves or rejects. Approval runs the same provisioning as
   the command-line tool (tools/tenant_admin.create: rule sets of the template, SoD rules, agents, company code, plant, MFA enforced) and the
   first administrator receives the activation e-mail. Every decision is audited in the platform organisation's hash chain.

Registration is open only when e-mail sending (PIC_SMTP_HOST) and the public web address (PIC_WEB_URL) are configured.
"""
from __future__ import annotations

import difflib
import hashlib
import os
import re
import secrets
import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Optional
from urllib.parse import quote

from fastapi import Request
from sqlalchemy import func, select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import AppUser, LoginDirectory, OrgRegistration, RuleSet, SanctionEntry, Tenant
from app.pic.platform import audit, clock, http, mailer
from app.pic.platform.auth import Principal
from app.pic.platform.errors import Problem, not_found
from app.pic.seed.templates import TEMPLATES
from app.pic.services import master_changes

PLATFORM_CODE = "AHPLATFORM"
PLATFORM_NAME = "AlphaHelion Platform"
OPERATOR_ROLE = "PLATFORM_OPERATOR"

# Defaults of rule ORG-REGISTRATION (platform organisation); the platform operator can publish a new version.
SHARED_MAILBOXES = ["info", "contact", "sales", "accounts", "purchase", "procurement", "admin", "finance", "office", "enquiry", "enquiries",
                    "support", "operations", "business", "vendor", "supply"]
FREE_MAIL_DOMAINS = ["gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "outlook.com", "hotmail.com", "live.com", "msn.com",
                     "icloud.com", "me.com", "aol.com", "rediffmail.com", "protonmail.com", "proton.me", "zoho.com", "zohomail.in", "gmx.com",
                     "mail.com", "yandex.com"]
RULE_DEFAULTS = {"sharedMailboxes": SHARED_MAILBOXES, "freeMailDomains": FREE_MAIL_DOMAINS, "verifyHours": 24, "maxPerIpPerHour": 5,
                 "openKinds": ["BUYER"]}
SANCTIONS_RATIO = 0.88
SIMILAR_NAME_RATIO = 0.9
PHONE_RE = re.compile(r"^\+?[0-9 ]{9,18}$")
CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,19}$")
NEUTRAL = ("Thank you. If the details are complete, a confirmation link has been sent to {email}. Open it within 24 hours to send the "
           "request to the platform team.")


# ---------------------------------------------------------------- platform organisation
def _platform_principal(tenant_id: uuid.UUID, actor_email: str = "registration@platform.pic") -> Principal:
    return Principal(user_id=uuid.uuid5(uuid.NAMESPACE_URL, "pic:platform:registration"), tenant_id=tenant_id, tenant_code=PLATFORM_CODE,
                     email=actor_email, name="Organisation registration", roles=[], scopes=set(), attributes={}, agent_code="registration")


def ensure_platform() -> uuid.UUID:
    """The platform's own organisation (kind PLATFORM): created once, with MFA enforced for its operators and rule ORG-REGISTRATION."""
    from app.pic.seed import reference
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == PLATFORM_CODE)).scalar_one_or_none()
        if tenant is not None and tenant.kind == "PLATFORM":
            existing = tenant.id
        else:
            existing = None
    if existing is not None:
        return existing
    tenant_id = reference.create_tenant(PLATFORM_CODE, PLATFORM_NAME, "GENERAL", mfa_enforce=True)
    with system_tx() as s:
        s.get(Tenant, tenant_id).kind = "PLATFORM"
    reference.bootstrap(tenant_id, company=("PLAT", PLATFORM_NAME, None), plants=[("PL01", "Platform", "33")], cost_objects=[])
    with tenant_tx(tenant_id) as s:
        mfa_rule = s.execute(select(RuleSet).where(RuleSet.key == "MFA").order_by(RuleSet.effective_from.desc())).scalars().first()
        start = mfa_rule.effective_from if mfa_rule else date(2026, 1, 1)
        keys = set(s.execute(select(RuleSet.version).where(RuleSet.key.in_(["MFA", "ORG-REGISTRATION"]))).scalars())
        if "platform-operators" not in keys:
            body = dict(mfa_rule.body) if mfa_rule else {}
            body.update(enforce=True, requiredRoles=sorted(set(body.get("requiredRoles") or []) | {OPERATOR_ROLE, "TENANT_ADMIN"}))
            s.add(RuleSet(tenant_id=tenant_id, key="MFA", version="platform-operators", effective_from=start, body=body,
                          description="Platform operators always sign in with two-step verification"))
        if "default" not in keys:
            s.add(RuleSet(tenant_id=tenant_id, key="ORG-REGISTRATION", version="default", effective_from=start, body=dict(RULE_DEFAULTS),
                          description="Self-service organisation registration: shared mailbox names, free e-mail domains, link validity"))
    return tenant_id


def policy() -> dict:
    from app.pic.platform import rules
    tenant_id = ensure_platform()
    with tenant_tx(tenant_id) as s:
        try:
            body = rules.resolve(s, "ORG-REGISTRATION").body
        except Problem:
            body = {}
    return {**RULE_DEFAULTS, **(body or {})}


def web_url() -> Optional[str]:
    value = (os.environ.get("PIC_WEB_URL") or "").strip().rstrip("/")
    return value or None


def enabled() -> bool:
    return mailer.configured() and web_url() is not None


def status() -> dict:
    p = policy() if enabled() else RULE_DEFAULTS
    return {"enabled": enabled(), "openKinds": p["openKinds"], "sharedMailboxes": p["sharedMailboxes"],
            "templates": sorted(TEMPLATES)}


# ---------------------------------------------------------------- validation
def _split(email: str) -> tuple[str, str]:
    local, _, domain = email.partition("@")
    return local, domain


def validate(data: dict, p: dict) -> tuple[dict, list[str]]:
    errors: list[str] = []
    kind = str(data.get("kind") or "").upper()
    if kind not in ("BUYER", "SUPPLIER"):
        errors.append("choose buyer or supplier")
    elif kind not in p["openKinds"]:
        errors.append("supplier organisations can register from the next release; ask your buyer for an invitation meanwhile")
    company = " ".join(str(data.get("companyName") or "").split())
    if not 3 <= len(company) <= 200:
        errors.append("company name: 3-200 characters")
    country = str(data.get("country") or "IN").upper()
    if not re.fullmatch(r"[A-Z]{2}", country):
        errors.append("country: two-letter code, e.g. IN")
    state = str(data.get("stateCode") or "").strip() or None
    gstin = str(data.get("gstin") or "").strip().upper() or None
    if country == "IN":
        if state not in master_changes.STATE_CODES:
            errors.append("state: the GST state code of the registered office (01-38 or 97)")
        if gstin:
            errors += [f"GSTIN: {e}" for e in master_changes.gstin_errors(gstin, state_code=state)]
    elif gstin:
        errors.append("GSTIN applies to Indian organisations only")
    template = str(data.get("industryTemplate") or "MANUFACTURING").upper()
    if template not in TEMPLATES:
        errors.append(f"industry: one of {', '.join(sorted(TEMPLATES))}")

    org_email = str(data.get("organisationEmail") or "").strip().lower()
    admin_email = str(data.get("adminEmail") or "").strip().lower()
    shared = {m.lower() for m in p["sharedMailboxes"]}
    free = {d.lower() for d in p["freeMailDomains"]}
    org_local, org_domain = _split(org_email)
    if not master_changes.EMAIL_RE.match(org_email):
        errors.append("organisation e-mail: not a valid address")
    else:
        if org_local not in shared:
            errors.append("organisation e-mail: use the company's shared mailbox (" + ", ".join(f"{m}@" for m in sorted(shared)) + ")")
        if org_domain in free:
            errors.append("organisation e-mail: use the company's own domain, not a free e-mail service")
    admin_local, admin_domain = _split(admin_email)
    if not master_changes.EMAIL_RE.match(admin_email):
        errors.append("administrator e-mail: not a valid address")
    else:
        if admin_domain != org_domain:
            errors.append(f"administrator e-mail: a work address on the company domain {org_domain or '(organisation e-mail)'}")
        if admin_local in shared or admin_email == org_email:
            errors.append("administrator e-mail: the personal work address of the administrator, not a shared mailbox")
    admin_name = " ".join(str(data.get("adminName") or "").split())
    if not 2 <= len(admin_name) <= 200:
        errors.append("administrator name: 2-200 characters")
    phone = str(data.get("adminPhone") or "").strip() or None
    if phone and not PHONE_RE.match(phone):
        errors.append("administrator phone: 9-18 digits, optional +country code")
    by_name = " ".join(str(data.get("authorisedByName") or "").split()) or None
    by_role = " ".join(str(data.get("authorisedByDesignation") or "").split()) or None
    if bool(by_name) != bool(by_role):
        errors.append("authorised by: give both the name and the designation, or neither")
    elif by_name and (len(by_name) > 200 or len(by_role) > 120):
        errors.append("authorised by: name up to 200, designation up to 120 characters")
    users = data.get("expectedUsers")
    try:
        users = int(users) if users not in (None, "") else None
    except (TypeError, ValueError):
        users = -1
    if users is not None and not 1 <= users <= 100000:
        errors.append("expected users: 1-100000")
    if data.get("acceptTerms") is not True:
        errors.append("accept the terms of use and the privacy notice")
    values = {"kind": kind, "company_name": company, "country": country, "state_code": state, "gstin": gstin, "industry_template": template,
              "org_email": org_email, "org_domain": org_domain, "admin_name": admin_name, "admin_email": admin_email, "admin_phone": phone,
              "authorised_by_name": by_name, "authorised_by_designation": by_role, "expected_users": users}
    return values, errors


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _next_number(s) -> str:
    count = s.execute(select(func.count()).select_from(OrgRegistration)).scalar() or 0
    return f"REG-{10001 + count}"


# ---------------------------------------------------------------- public steps
def submit(data: dict, request: Request) -> dict:
    if not enabled():
        raise Problem(503, "REGISTRATION_CLOSED", "Organisation registration is not open yet. Contact the AlphaHelion team.")
    p = policy()
    values, errors = validate(data or {}, p)
    if errors:
        raise Problem(422, "VALIDATION_FAILED", "; ".join(errors), errors=errors)
    ip = http._client_ip(request)
    now = clock.now()
    with system_tx() as s:
        recent = s.execute(select(func.count()).select_from(OrgRegistration).where(
            OrgRegistration.request_ip == ip, OrgRegistration.created_at > now - timedelta(hours=1))).scalar()
        if recent >= int(p["maxPerIpPerHour"]):
            raise Problem(429, "TOO_MANY_REQUESTS", "Too many registration requests from this network. Try again in an hour.")
        open_request = s.execute(select(OrgRegistration.id).where(
            OrgRegistration.org_domain == values["org_domain"],
            OrgRegistration.status.in_(["PENDING_VERIFICATION", "PENDING_APPROVAL"]))).first()
        if open_request is None:
            token = secrets.token_urlsafe(32)
            reg = OrgRegistration(number=_next_number(s), status="PENDING_VERIFICATION", verify_token_hash=_hash(token),
                                  verify_expires_at=now + timedelta(hours=int(p["verifyHours"])), request_ip=ip, screening={}, **values)
            s.add(reg)
            s.flush()
            link = f"{web_url()}/register/verify?token={quote(token, safe='')}"
            mailer.send(values["org_email"], f"Confirm the registration of {values['company_name']}",
                        f"Hello,\n\n{values['admin_name']} asked to register {values['company_name']} as a {values['kind'].lower()} organisation on "
                        f"AlphaHelion Purchasing Intelligence Cloud, with {values['admin_email']} as its first administrator.\n\n"
                        f"Confirm the request here (the link works once and expires in {p['verifyHours']} hours):\n{link}\n\n"
                        f"Request number: {reg.number}. If you did not expect this message, ignore it; nothing is created without "
                        f"this confirmation and a review by the AlphaHelion team.\n")
    # The same answer for a new request and for a domain that already has one: registration does not reveal which companies are known.
    return {"status": "CHECK_MAILBOX", "detail": NEUTRAL.format(email=values["org_email"])}


def verify(token: str, request: Request) -> dict:
    token = (token or "").strip()
    if not token:
        raise Problem(400, "LINK_INVALID", "The confirmation link is incomplete")
    now = clock.now()
    with system_tx() as s:
        reg = s.execute(select(OrgRegistration).where(OrgRegistration.verify_token_hash == _hash(token)).with_for_update()).scalar_one_or_none()
        if reg is None or reg.status != "PENDING_VERIFICATION":
            http.record_login_failure(request)
            raise Problem(410, "LINK_INVALID", "This confirmation link is not valid or was already used")
        if reg.verify_expires_at and reg.verify_expires_at < now:
            reg.status, reg.verify_token_hash = "EXPIRED", None
            raise Problem(410, "LINK_EXPIRED", "This confirmation link has expired. Register again.")
        reg.status, reg.verified_at, reg.verify_token_hash = "PENDING_APPROVAL", now, None
        reg_id, number, company = reg.id, reg.number, reg.company_name
    screening = screen(reg_id)
    _notify_operators(number, company, screening)
    return {"status": "PENDING_APPROVAL", "number": number, "company": company,
            "detail": "Thank you. The request is confirmed and is now reviewed by the AlphaHelion team. The decision is sent to the shared mailbox."}


# ---------------------------------------------------------------- screening
def screen(reg_id: uuid.UUID) -> dict:
    from app.pic.services.supplier import normalise_legal_name, sanctions_provider
    platform_id = ensure_platform()
    with system_tx() as s:
        reg = s.get(OrgRegistration, reg_id)
        name = normalise_legal_name(reg.company_name)
        similar = [t.code for t in s.execute(select(Tenant).where(Tenant.kind != "PLATFORM")).scalars()
                   if difflib.SequenceMatcher(None, normalise_legal_name(t.name), name).ratio() >= SIMILAR_NAME_RATIO]
        domain_in_use = s.execute(select(func.count(func.distinct(LoginDirectory.org_id))).where(
            func.split_part(LoginDirectory.email, "@", 2) == reg.org_domain)).scalar() or 0
        other_requests = [n for n in s.execute(select(OrgRegistration.number).where(
            OrgRegistration.id != reg.id, OrgRegistration.status.in_(["PENDING_APPROVAL", "APPROVED"]),
            (OrgRegistration.org_domain == reg.org_domain) | ((OrgRegistration.gstin == reg.gstin) & (OrgRegistration.gstin.is_not(None))))).scalars()]
        company, country = reg.company_name, reg.country
    with tenant_tx(platform_id) as ts:
        hits = [e.source for e in ts.execute(select(SanctionEntry)).scalars()
                if difflib.SequenceMatcher(None, e.name.lower(), company.lower()).ratio() > SANCTIONS_RATIO]
    provider, provider_error = sanctions_provider(), None
    if provider is not None:
        try:
            if provider.search(company, country) and provider.name not in hits:
                hits.append(provider.name)
        except Exception as exc:  # noqa: BLE001 - a feed outage must not lose the request; the operator sees it
            provider_error = f"{provider.name}: {type(exc).__name__}"[:200]
    result = {"sanctionsHits": hits, "similarOrganisations": similar, "domainInUse": domain_in_use > 0, "otherRequests": other_requests,
              "providerError": provider_error, "screenedAt": clock.now().isoformat(),
              "outcome": "HIT" if hits else ("REVIEW" if similar or domain_in_use or other_requests or provider_error else "CLEAR")}
    with system_tx() as s:
        s.get(OrgRegistration, reg_id).screening = result
    return result


def _operator_emails(platform_id: uuid.UUID) -> list[str]:
    with tenant_tx(platform_id) as s:
        return [u.email for u in s.execute(select(AppUser).where(AppUser.active.is_(True))).scalars() if OPERATOR_ROLE in (u.roles or [])]


def _notify_operators(number: str, company: str, screening: dict) -> None:
    platform_id = ensure_platform()
    link = f"{web_url()}/pic/platform/registrations"
    for email in _operator_emails(platform_id):
        mailer.send(email, f"Organisation registration {number} to review: {company}",
                    f"{company} confirmed its registration request {number}. Screening: {screening['outcome']}.\n\nReview it here:\n{link}\n")


# ---------------------------------------------------------------- platform operator console
def _require_operator(p: Principal) -> uuid.UUID:
    platform_id = ensure_platform()
    if p.tenant_id != platform_id or OPERATOR_ROLE not in p.roles or "platform:registrations" not in p.scopes:
        raise Problem(403, "FORBIDDEN", "Only platform operators review organisation registrations", rule_ref="RBAC")
    return platform_id


def view(reg: OrgRegistration, detail: bool = False) -> dict:
    out = {"id": str(reg.id), "number": reg.number, "kind": reg.kind, "status": reg.status, "companyName": reg.company_name,
           "country": reg.country, "organisationEmail": reg.org_email, "adminName": reg.admin_name, "adminEmail": reg.admin_email,
           "screeningOutcome": (reg.screening or {}).get("outcome"), "createdAt": reg.created_at.isoformat() if reg.created_at else None,
           "verifiedAt": reg.verified_at.isoformat() if reg.verified_at else None, "organisationCode": reg.organisation_code}
    if detail:
        out.update({"stateCode": reg.state_code, "industryTemplate": reg.industry_template, "gstin": reg.gstin, "domain": reg.org_domain,
                    "adminPhone": reg.admin_phone, "authorisedByName": reg.authorised_by_name,
                    "authorisedByDesignation": reg.authorised_by_designation, "expectedUsers": reg.expected_users,
                    "screening": reg.screening or {}, "decidedBy": reg.decided_by,
                    "decidedAt": reg.decided_at.isoformat() if reg.decided_at else None, "decisionReason": reg.decision_reason,
                    "proposedCode": reg.organisation_code or propose_code(reg.company_name)})
    return out


def list_registrations(p: Principal, status_filter: Optional[str]) -> list[dict]:
    _require_operator(p)
    with system_tx() as s:
        query = select(OrgRegistration).order_by(OrgRegistration.created_at.desc()).limit(500)
        if status_filter:
            query = query.where(OrgRegistration.status == status_filter.upper())
        return [view(r) for r in s.execute(query).scalars()]


def get(p: Principal, reg_id: uuid.UUID) -> dict:
    _require_operator(p)
    with system_tx() as s:
        reg = s.get(OrgRegistration, reg_id)
        if reg is None:
            raise not_found("ORG_REGISTRATION", str(reg_id))
        return view(reg, detail=True)


def propose_code(company: str) -> str:
    """A free organisation code from the company name: initials of the significant words, else the first letters (2-8 characters)."""
    from app.pic.services.supplier import normalise_legal_name
    words = [w for w in normalise_legal_name(company).upper().split() if w.isalnum()]
    base = "".join(w[0] for w in words) if len(words) >= 3 else "".join(words)[:6]
    base = re.sub(r"[^A-Z0-9]", "", base) or "ORG"
    if not base[0].isalpha():
        base = "O" + base
    base = base[:8]
    with system_tx() as s:
        taken = set(s.execute(select(Tenant.code)).scalars())
    code, n = base if len(base) >= 2 else base + "X", 2
    while code in taken:
        code, n = f"{base[:6]}{n}", n + 1
    return code


def _decided(reg: OrgRegistration, p: Principal, status_value: str, reason: Optional[str]) -> None:
    reg.status, reg.decided_by, reg.decided_at, reg.decision_reason = status_value, p.email, clock.now(), reason


def approve(p: Principal, reg_id: uuid.UUID, code: Optional[str], note: Optional[str]) -> dict:
    from app.pic.tools import tenant_admin
    platform_id = _require_operator(p)
    with system_tx() as s:
        reg = s.get(OrgRegistration, reg_id)
        if reg is None:
            raise not_found("ORG_REGISTRATION", str(reg_id))
        if reg.status != "PENDING_APPROVAL":
            raise Problem(409, "ILLEGAL_TRANSITION", f"Registration {reg.number} is {reg.status}; only a confirmed request can be approved")
        if (reg.screening or {}).get("outcome") == "HIT" and len((note or "").strip()) < 20:
            raise Problem(422, "SCREENING_HIT", "The screening found a sanctions match: give a reason of at least 20 characters to approve")
        snapshot = {k: getattr(reg, k) for k in ("number", "company_name", "industry_template", "admin_email", "admin_name", "gstin", "state_code",
                                                 "country", "org_email", "kind")}
    org_code = (code or "").strip().upper() or propose_code(snapshot["company_name"])
    if not CODE_RE.match(org_code):
        raise Problem(422, "VALIDATION_FAILED", "Organisation code: 2-20 capital letters and digits, starting with a letter")
    with system_tx() as s:
        if s.execute(select(Tenant.id).where(Tenant.code == org_code)).first():
            raise Problem(409, "CODE_TAKEN", f"Organisation code {org_code} is already used; choose another")
    args = SimpleNamespace(code=org_code, name=snapshot["company_name"], template=snapshot["industry_template"], admin_email=snapshot["admin_email"],
                           admin_name=snapshot["admin_name"], company_code="1000", company_name=snapshot["company_name"], gstin=snapshot["gstin"],
                           plant="P100", plant_name="Main plant",
                           state_code=snapshot["state_code"] if snapshot["country"] == "IN" and snapshot["state_code"] else "97")
    try:
        result = tenant_admin.create(args)
    except tenant_admin.ToolError as exc:
        raise Problem(409, "PROVISIONING_FAILED", str(exc))
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == org_code)).scalar_one()
        tenant.kind = snapshot["kind"]
        reg = s.get(OrgRegistration, reg_id)
        _decided(reg, p, "APPROVED", (note or "").strip() or None)
        reg.organisation_code, reg.tenant_id = org_code, tenant.id
    with tenant_tx(platform_id, p.user_id, p) as ts:
        audit.record(ts, "ORG_REGISTRATION", reg_id, "APPROVED", object_ref=snapshot["number"], reason=note,
                     after={"organisation": org_code, "company": snapshot["company_name"], "firstAdmin": snapshot["admin_email"],
                            "activationEmail": result["emailStatus"]})
    mailer.send(snapshot["org_email"], f"{snapshot['company_name']} is registered",
                f"Hello,\n\nThe registration {snapshot['number']} of {snapshot['company_name']} is approved. Organisation code: {org_code}.\n\n"
                f"{snapshot['admin_name']} ({snapshot['admin_email']}) has received an e-mail to set a password and two-step verification. "
                f"Sign in at {web_url() or ''}/signin.\n")
    return {"status": "APPROVED", "organisation": org_code, "activationEmail": result["emailStatus"]}


def reject(p: Principal, reg_id: uuid.UUID, reason: str) -> dict:
    platform_id = _require_operator(p)
    reason = " ".join((reason or "").split())
    if len(reason) < 10:
        raise Problem(422, "VALIDATION_FAILED", "Give the reason for the rejection (at least 10 characters); it is sent to the company")
    with system_tx() as s:
        reg = s.get(OrgRegistration, reg_id)
        if reg is None:
            raise not_found("ORG_REGISTRATION", str(reg_id))
        if reg.status not in ("PENDING_APPROVAL", "PENDING_VERIFICATION"):
            raise Problem(409, "ILLEGAL_TRANSITION", f"Registration {reg.number} is {reg.status}")
        _decided(reg, p, "REJECTED", reason)
        reg.verify_token_hash = None
        number, company, mailbox = reg.number, reg.company_name, reg.org_email
    with tenant_tx(platform_id, p.user_id, p) as ts:
        audit.record(ts, "ORG_REGISTRATION", reg_id, "REJECTED", object_ref=number, reason=reason, after={"company": company})
    mailer.send(mailbox, f"Registration {number} of {company}", f"Hello,\n\nThe registration {number} of {company} was not approved.\n\n"
                f"Reason: {reason}\n\nYou can reply to this message or register again with corrected details.\n")
    return {"status": "REJECTED"}


# ---------------------------------------------------------------- operator accounts (command line only)
def create_operator(email: str, name: str) -> dict:
    """A platform operator account in the platform organisation, with a single-use activation link (tools/tenant_admin create-operator)."""
    from app.pic.services import user_admin
    email = (email or "").strip().lower()
    if not master_changes.EMAIL_RE.match(email):
        raise Problem(422, "VALIDATION_FAILED", "operator e-mail: not a valid address")
    platform_id = ensure_platform()
    principal = _platform_principal(platform_id, "tenant_admin@tool.pic")
    with tenant_tx(platform_id, principal.user_id, principal) as s:
        if s.execute(select(AppUser.id).where(AppUser.email == email)).first():
            raise Problem(409, "ALREADY_EXISTS", f"{email} is already a platform operator")
        result = user_admin._create(s, {"email": email, "name": " ".join((name or email.split("@")[0]).split()), "roles": [OPERATOR_ROLE],
                                        "attributes": {}})
    return {"operator": email, "activationUrl": result["activationUrl"], "expiresAt": result["expiresAt"], "emailStatus": result["emailStatus"]}
