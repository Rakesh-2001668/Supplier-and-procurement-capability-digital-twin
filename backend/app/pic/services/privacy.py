"""DPDP Act data-principal rights: personal-data export, erasure (pseudonymisation) and retention reporting.

Technical Document §14: India Digital Personal Data Protection Act 2023 alignment — purpose limitation, data residency,
retention and deletion workflows.

Erasure pseudonymises the person's identity on ``app_user`` (name, e-mail, contact attributes), revokes sign-in
(deactivated, password and MFA factors destroyed) and deletes their notifications. The user id is kept so business
documents and approvals stay attributable to "a user" for the statutory retention period. The audit trail is
append-only and hash-chained: existing events (whose ``actor`` strings contain the e-mail at the time) are NOT altered —
they are retained under the legal-obligation basis (books of account and GST records) and the erasure itself is recorded
as a new audit event that holds no personal data. See docs/runbooks/privacy-requests.md.
"""
import re
import secrets
import uuid
from datetime import timedelta
from typing import Optional
from urllib.parse import urlsplit

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.pic.config import get_settings
from app.pic.models import (
    AppUser, AuditEvent, Invoice, MfaFactor, Notification, PurchaseOrder, Requisition, Task, Tenant,
)
from app.pic.platform import audit, clock, rules, workflow
from app.pic.platform.auth import Principal, hash_password, scopes_for
from app.pic.platform.errors import Problem, not_found
from app.pic.services.common import principal

ERASED_DOMAIN = "erased.invalid"
EXPORT_LIMIT = 5000
# ABAC attributes are access-control data, not personal data; anything else on the user record is treated as personal.
ACCESS_ATTRIBUTES = {"company_codes", "plants", "cost_objects", "categories", "steward_domains", "value_limit_minor", "purchasing_groups"}
PERSONAL_ATTRIBUTE = re.compile(r"(?i)(phone|mobile|tel|whatsapp|address|personal|email|name|dob|birth|pan|aadhaar)")
INDIA_REGIONS = {"ap-south-1", "ap-south-2", "asia-south1", "asia-south2", "centralindia", "southindia", "westindia"}

# Personal-data categories PIC holds. Retention defaults apply until the tenant configures rule set PRIVACY-RETENTION
# ({"categories": {"<key>": {"days": n}}}) through POST /v1/admin/rules. Legal basis wording needs counsel's review.
CATEGORIES = [
    {"key": "user_profile", "category": "Workforce user profile: name, work e-mail, roles, access attributes", "store": "pic.app_user",
     "purpose": "Account administration, authorisation (RBAC/ABAC), approval routing", "lawfulBasis":
     "DPDP Act 2023 s.7 legitimate use — employment purposes (workforce users); consent / contract for supplier users",
     "defaultDays": None, "defaultRetention": "Account lifetime; pseudonymised on erasure request or 90 days after deactivation",
     "deletion": "POST /v1/admin/privacy/users/{id}/erase (pseudonymise; id kept)"},
    {"key": "mfa_factor", "category": "MFA factors (encrypted TOTP secret, last used step)", "store": "pic.mfa_factor",
     "purpose": "Authentication security", "lawfulBasis": "DPDP s.7 legitimate use — employment / security of the service",
     "defaultDays": None, "defaultRetention": "Until the factor is replaced or the account is erased", "deletion": "Deleted on erasure"},
    {"key": "notification", "category": "In-app notifications addressed to the user", "store": "pic.notification",
     "purpose": "Task and exception alerts", "lawfulBasis": "DPDP s.7 legitimate use — employment purposes",
     "defaultDays": 180, "defaultRetention": "180 days", "deletion": "Deleted on erasure; purge older rows by retention job"},
    {"key": "audit_actor", "category": "Audit-trail actor identifiers (e-mail at the time of action) and reasons", "store": "pic.audit_event",
     "purpose": "Statutory audit trail, SoD evidence, fraud investigation", "lawfulBasis":
     "Compliance with law: Companies Act 2013 s.128 (books of account, 8 years), CGST Act 2017 s.36 (records, 72 months); "
     "DPDP s.8(7) permits retention required by law", "defaultDays": 8 * 365, "defaultRetention": "8 years",
     "deletion": "Not erasable: append-only, hash-chained; erasure recorded as a new event"},
    {"key": "business_documents", "category": "Creator / approver user ids on requisitions, POs, receipts, invoices, tasks",
     "store": "pic.requisition, pic.purchase_order, pic.invoice, pic.task, pic.action_log", "purpose": "Procure-to-pay records and approvals",
     "lawfulBasis": "Compliance with law (books of account, GST)", "defaultDays": 8 * 365, "defaultRetention": "8 years",
     "deletion": "Retained; ids resolve to the pseudonymised user after erasure"},
    {"key": "supplier_contacts", "category": "Supplier contact persons, bank account details (field-encrypted), tax ids",
     "store": "pic.supplier and related", "purpose": "Supplier onboarding, payment", "lawfulBasis": "Contract; compliance with law (GST, TDS)",
     "defaultDays": 8 * 365, "defaultRetention": "Relationship + 8 years", "deletion": "Supplier off-boarding (manual, Supplier Manager)"},
    {"key": "access_logs", "category": "API access logs: user id, tenant, client IP, trace id", "store": "Log platform (stdout JSON)",
     "purpose": "Security monitoring and incident response", "lawfulBasis": "DPDP s.7 legitimate use / security safeguards (s.8(5))",
     "defaultDays": 90, "defaultRetention": "90 days", "deletion": "Log-sink retention policy (configure in the logging platform)"},
    {"key": "sign_in_attempts", "category": "Failed sign-in counters per client IP", "store": "API process memory only",
     "purpose": "Brute-force protection", "lawfulBasis": "Security safeguards (s.8(5))", "defaultDays": 0,
     "defaultRetention": "5 minutes, never persisted", "deletion": "Automatic"},
]


def _require_admin(session: Session) -> Principal:
    p = principal(session)
    if "TENANT_ADMIN" not in p.roles:
        raise Problem(403, "FORBIDDEN", "Privacy requests need the tenant administrator", rule_ref="DPDP")
    return p


def _user(session: Session, user_id: uuid.UUID, lock: bool = False) -> AppUser:
    query = select(AppUser).where(AppUser.id == user_id)
    user = session.execute(query.with_for_update() if lock else query).scalar_one_or_none()
    if user is None:
        raise not_found("User", user_id)
    return user


def _iso(value) -> Optional[str]:
    return value.isoformat() if value is not None else None


def is_erased(user: AppUser) -> bool:
    return bool((user.attributes or {}).get("erased")) or user.email.endswith("@" + ERASED_DOMAIN)


# ---------------------------------------------------------------- export (right to access, DPDP s.11)
def export(session: Session, user_id: uuid.UUID) -> dict:
    admin = _require_admin(session)
    user = _user(session, user_id)
    actor_keys = [f"u:{user.email}"]
    as_actor = session.execute(
        select(AuditEvent).where(or_(AuditEvent.actor.in_(actor_keys), AuditEvent.on_behalf_of.in_(actor_keys + [user.email])))
        .order_by(AuditEvent.seq).limit(EXPORT_LIMIT + 1)).scalars().all()
    about = session.execute(
        select(AuditEvent).where(AuditEvent.object_type == "APP_USER", AuditEvent.object_id == user.id)
        .order_by(AuditEvent.seq).limit(EXPORT_LIMIT)).scalars().all()
    notifications = session.execute(select(Notification).where(Notification.user_id == user.id)
                                    .order_by(Notification.created_at).limit(EXPORT_LIMIT)).scalars().all()
    factors = session.execute(select(MfaFactor).where(MfaFactor.user_id == user.id)).scalars().all()
    tasks = session.execute(select(Task).where(Task.completed_by == user.id).order_by(Task.completed_at).limit(EXPORT_LIMIT)).scalars().all()
    counts = {name: session.execute(select(func.count()).select_from(model).where(model.created_by == user.id)).scalar_one()
              for name, model in (("requisitions", Requisition), ("purchaseOrders", PurchaseOrder), ("invoices", Invoice))}

    def event(e: AuditEvent) -> dict:
        return {"seq": e.seq, "ts": _iso(e.ts), "objectType": e.object_type, "objectRef": e.object_ref, "action": e.action,
                "actor": e.actor, "onBehalfOf": e.on_behalf_of, "reason": e.reason}

    result = {
        "subject": {"userId": str(user.id), "tenant": admin.tenant_code},
        "generatedAt": _iso(clock.now()),
        "profile": {"id": str(user.id), "email": user.email, "fullName": user.full_name, "roles": list(user.roles or []),
                    "attributes": user.attributes or {}, "supplierId": str(user.supplier_id) if user.supplier_id else None,
                    "active": user.active, "mfaEnrolled": user.mfa_enrolled, "createdAt": _iso(user.created_at),
                    "updatedAt": _iso(user.updated_at), "erased": is_erased(user)},
        "mfaFactors": [{"kind": f.kind, "confirmedAt": _iso(f.confirmed_at), "createdAt": _iso(f.created_at)} for f in factors],
        "notifications": [{"kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "objectRef": n.object_ref,
                           "createdAt": _iso(n.created_at), "readAt": _iso(n.read_at), "emailStatus": n.email_status} for n in notifications],
        "auditAsActor": [event(e) for e in as_actor[:EXPORT_LIMIT]],
        "auditAboutUser": [event(e) for e in about],
        "tasksCompleted": [{"task": t.name, "objectType": t.object_type, "objectRef": t.object_ref, "decision": t.decision,
                            "comment": t.comment, "completedAt": _iso(t.completed_at)} for t in tasks],
        "documentsCreated": counts,
        "signIns": {"recorded": False, "detail": "PIC does not store a sign-in history in the database. Successful and failed sign-ins appear "
                                                 "only in API access logs (retained by the log platform; see the retention report)."},
        "truncated": len(as_actor) > EXPORT_LIMIT,
        "notes": ["Business documents reference the user by id; they are retained under legal obligation and are summarised as counts.",
                  "Secrets (password hash, MFA secret) are never exported."],
    }
    audit.record(session, "APP_USER", user.id, "PERSONAL_DATA_EXPORTED", object_ref=f"user:{user.id}",
                 after={"auditEvents": len(result["auditAsActor"]), "notifications": len(notifications)}, rule_set_version="DPDP-EXPORT")
    return result


# ---------------------------------------------------------------- erasure (DPDP s.12)
def _as_principal(user: AppUser, tenant: Tenant) -> Principal:
    return Principal(user_id=user.id, tenant_id=user.tenant_id, tenant_code=tenant.code, email=user.email, name=user.full_name,
                     roles=list(user.roles or []), scopes=scopes_for(list(user.roles or [])), attributes=user.attributes or {},
                     supplier_id=user.supplier_id)


def erase(session: Session, user_id: uuid.UUID, reason: str) -> dict:
    admin = _require_admin(session)
    reason = (reason or "").strip()
    if len(reason) < 10:
        raise Problem(422, "REASON_REQUIRED", "Give the request reference and reason (at least 10 characters)", rule_ref="DPDP")
    user = _user(session, user_id, lock=True)
    if user.id == admin.user_id:
        raise Problem(409, "SELF_ERASURE", "You cannot erase your own account; ask another tenant administrator", rule_ref="DPDP")
    if is_erased(user):
        raise Problem(409, "ALREADY_ERASED", "This user's personal data has already been erased", rule_ref="DPDP")
    tenant = session.get(Tenant, user.tenant_id)
    open_tasks = workflow.open_tasks_for(session, _as_principal(user, tenant))
    if open_tasks:
        refs = sorted({t.object_ref for t in open_tasks})
        raise Problem(409, "OPEN_TASKS", f"The user can still work {len(open_tasks)} open task(s) ({', '.join(refs[:10])}). Complete or "
                      "reassign them (change the user's roles) before erasure.", rule_ref="DPDP", tasks=refs)
    if "TENANT_ADMIN" in (user.roles or []) and user.active:
        admins = session.execute(select(func.count()).select_from(AppUser).where(
            AppUser.active.is_(True), AppUser.roles.any("TENANT_ADMIN"), AppUser.id != user.id)).scalar_one()
        if admins == 0:
            raise Problem(409, "LAST_ADMIN", "This is the only active tenant administrator", rule_ref="DPDP")

    pseudonym = f"erased-{user.id.hex[:12]}"
    personal_attrs = [k for k in (user.attributes or {}) if k not in ACCESS_ATTRIBUTES or PERSONAL_ATTRIBUTE.search(k)]
    kept = {k: v for k, v in (user.attributes or {}).items() if k not in personal_attrs}
    now = clock.now()
    user.email = f"{pseudonym}@{ERASED_DOMAIN}"
    user.full_name = f"Erased user {user.id.hex[:8]}"
    user.password_hash = hash_password(secrets.token_urlsafe(32))  # nobody knows it: sign-in is impossible
    user.attributes = {**kept, "erased": {"at": now.isoformat(), "by": str(admin.user_id)}}
    user.active = False
    user.mfa_enrolled = False
    factors = session.execute(delete(MfaFactor).where(MfaFactor.user_id == user.id)).rowcount
    notifications = session.execute(delete(Notification).where(Notification.user_id == user.id)).rowcount
    session.flush()
    summary = {"pseudonym": pseudonym, "fieldsPseudonymised": ["email", "full_name", "password_hash"] + [f"attributes.{k}" for k in personal_attrs],
               "deactivated": True, "mfaFactorsDeleted": factors, "notificationsDeleted": notifications,
               "auditTrail": "retained unchanged (legal obligation); actor strings of earlier events still contain the former e-mail"}
    # No personal data in the event itself: the subject is identified by id only.
    audit.record(session, "APP_USER", user.id, "PERSONAL_DATA_ERASED", object_ref=f"user:{user.id}", after=summary, reason=reason,
                 rule_set_version="DPDP-ERASURE")
    return {"userId": str(user.id), "status": "ERASED", **summary}


# ---------------------------------------------------------------- retention report (DPDP s.8(7))
def _database_region() -> dict:
    host = (urlsplit(get_settings().database_url.strip()).hostname or "").lower()
    match = re.search(r"\b((?:ap|us|eu|sa|ca|me|af|il)-[a-z]+-\d|asia-[a-z]+\d|europe-[a-z]+\d|us-[a-z]+\d)\b", host)
    region = match.group(1) if match else None
    provider = "Neon" if host.endswith("neon.tech") else ("local" if host in ("localhost", "127.0.0.1") else "unknown")
    return {"provider": provider, "region": region, "inIndia": (region in INDIA_REGIONS) if region else None,
            "decision": None if (region in INDIA_REGIONS) else
            "Business decision needed: the database region is not in India (Neon ap-southeast-1 is Singapore). DPDP s.16 allows transfer "
            "except to countries the Government restricts, but the Delivery Plan (DD-11) sets India residency as the default."}


def retention(session: Session) -> dict:
    _require_admin(session)
    configured: dict = {}
    rule_ref = None
    try:
        rule = rules.resolve(session, "PRIVACY-RETENTION")
        configured = (rule.body or {}).get("categories", {})
        rule_ref = rule.ref
    except Problem:
        pass
    now = clock.now()
    categories = []
    for c in CATEGORIES:
        days = configured.get(c["key"], {}).get("days", c["defaultDays"])
        row = {k: v for k, v in c.items() if k != "defaultDays"}
        row.update({"configuredDays": configured.get(c["key"], {}).get("days"), "effectiveDays": days,
                    "source": rule_ref if c["key"] in configured else "default"})
        categories.append(row)
    deactivated = session.execute(select(func.count()).select_from(AppUser).where(AppUser.active.is_(False))).scalar_one()
    erased = session.execute(select(func.count()).select_from(AppUser).where(AppUser.email.like(f"%@{ERASED_DOMAIN}"))).scalar_one()
    note_days = next(c["effectiveDays"] for c in categories if c["key"] == "notification")
    overdue_notifications = session.execute(select(func.count()).select_from(Notification).where(
        Notification.created_at < now - timedelta(days=note_days))).scalar_one() if note_days else 0
    return {"generatedAt": _iso(now), "ruleSet": rule_ref, "categories": categories, "dataResidency": _database_region(),
            "subjects": {"deactivatedUsers": deactivated, "erasedUsers": erased, "deactivatedNotErased": deactivated - erased},
            "dueForPurge": {"notifications": overdue_notifications},
            "howToConfigure": "POST /v1/admin/rules with key PRIVACY-RETENTION and body {\"categories\": {\"notification\": {\"days\": 180}}}"}
