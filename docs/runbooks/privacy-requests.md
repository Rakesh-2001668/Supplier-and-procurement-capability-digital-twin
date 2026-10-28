# Privacy requests (India DPDP Act 2023)

TD §14: purpose limitation, data residency, retention and deletion workflows. Code: `backend/app/pic/services/privacy.py`,
endpoints in `backend/app/pic/api/ops.py`. Only a **tenant administrator** can run them (role TENANT_ADMIN, MFA enrolled);
every request is audited. The tenant (the customer company) is the data fiduciary for its workforce users; AlphaHelion acts as
processor. Requests from a data principal reach the tenant's grievance officer, who instructs the tenant administrator.

## Access / export (s.11)

`GET /v1/admin/privacy/users/{userId}/export` returns JSON: profile (name, e-mail, roles, access attributes, status), MFA factor
metadata (never the secret), notifications, audit events where the user acted (`actor = u:<email>`) or was the subject, tasks the
user completed, counts of documents they created, and a note that sign-ins are not stored in the database (only in access logs).
The export is itself audited (`PERSONAL_DATA_EXPORTED`). Deliver it through the tenant's secure channel; do not e-mail it unencrypted.

## Erasure (s.12)

`POST /v1/admin/privacy/users/{userId}/erase {"reason": "<request ref and reason>"}`
- Pseudonymises `app_user`: e-mail → `erased-<id>@erased.invalid`, name → `Erased user <id>`, removes contact/personal attributes
  (phone, address, …) and keeps access-control attributes; deactivates the account; replaces the password hash with a random one;
  deletes MFA factors and notifications. The user **id** is kept so approvals and documents stay attributable.
- Refused (409) while the user can still work open tasks (`OPEN_TASKS` lists them): reassign by changing the user's roles first.
  Also refused for yourself and for the last active tenant administrator.
- **The audit trail is not modified.** It is append-only and hash-chained (the database role cannot update or delete it). Earlier
  events keep the actor string `u:<former e-mail>`; they are retained under the **legal-obligation basis** (Companies Act 2013
  s.128 books of account — 8 years; CGST Act 2017 s.36 — 72 months), which DPDP s.8(7) and s.17 allow. The erasure is appended as
  a new event `PERSONAL_DATA_ERASED` containing only the user id, the fields changed and the reason. Tell the data principal this
  in the response letter.
- After erasure the account is inactive and nobody can sign in, but an access token issued earlier is still accepted until it
  expires (`PIC_JWT_TTL_MINUTES`, 480). Known gap (owner: platform/auth.py): check `app_user.active` per request or keep a
  revocation list. For an urgent case (compromised account) rotate the JWT secret, which ends every session.
- Business documents may contain the person's name in free text (comments, reasons). These are business records under the same
  legal-obligation basis and are not rewritten.

## Retention report (s.8(7))

`GET /v1/admin/privacy/retention` lists each personal-data category with purpose, lawful basis, default and configured retention,
deletion mechanism, counts of deactivated/erased users, notifications due for purge, and the **database region** (parsed from the
connection host). Configure retention per tenant with a rule set:
`POST /v1/admin/rules {"key": "PRIVACY-RETENTION", "version": "2026.1", "effective_from": "2026-11-01",
"body": {"categories": {"notification": {"days": 180}, "access_logs": {"days": 90}}}}`.
A purge job for notifications past retention and for erasure of users deactivated > 90 days is **not yet scheduled** (backlog).

## Data residency — business decision required

Production data is in Neon **ap-southeast-1 (Singapore)**. DPDP s.16 permits transfer outside India except to countries the
Government restricts by notification, so Singapore is lawful today, but the Delivery Plan (DD-11) makes **India residency the
default** and some customer contracts (and sector rules such as RBI's for payment data) may require it. Options: Neon on AWS
`ap-south-1` (Mumbai) if available on the plan; Cloud SQL / AlloyDB in `asia-south1` with DR in `asia-south2`; or accept Singapore
with documented customer consent and contract terms. Owner: CPO + legal; record the decision in docs/PIC_Production_Readiness.md.

## Lawful basis summary (for counsel's review)

| Category | Basis |
|---|---|
| Workforce user profile, roles, MFA, notifications | Legitimate use — employment purposes (s.7) |
| Supplier contacts, bank details | Contract with the supplier; legal obligation (GST, TDS) |
| Audit trail, business documents | Legal obligation (books of account, GST records) |
| Access logs | Reasonable security safeguards (s.8(5)) |
