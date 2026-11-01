# Administration operations (M13, ADM-01 to ADM-04)

How to set up and run a tenant: provisioning a new customer, building the organisation, inviting users, custom roles, industry
templates. Code: `backend/app/pic/services/{org_admin,user_admin,role_admin,template_admin}.py`, routes in
`backend/app/pic/api/admin_enterprise.py`, the provisioning tool in `backend/app/pic/tools/tenant_admin.py`, screens under
`frontend/src/app/pic/admin` (tabs Organisation, Users & roles, Permission matrix, Approval matrix, Industry templates) and the
public page `/pic/activate`. Tenant administrators (role TENANT_ADMIN, MFA enrolled) do everything except provisioning; everyone
with `pic:read` can read the organisation and the permission matrix.

Every write is audited (who, when, before and after), carries the record's version as ETag (send `If-Match` on updates; a stale one
is `412 STALE_WRITE`) and, for creating POSTs, honours `Idempotency-Key`. Errors are problem+json with a business `code`.

## 1. Provision a new tenant (platform operator, command line only)

Creating a tenant needs authority no tenant role has, so there is no web API for it. Run on a machine that has `DATABASE_URL`
(and the field-encryption key) of the target environment, from `backend/`:

```
python -m app.pic.tools.tenant_admin create --code ACME --name "Acme Industries Ltd" --template MANUFACTURING \
    --admin-email cio@acme.example --admin-name "Asha Rao" \
    --company-code 1000 --gstin 33AABCA1234F1Z5 --plant P100 --plant-name "Chennai plant" --state-code 33
python -m app.pic.tools.tenant_admin reissue --code ACME --admin-email cio@acme.example     # new link, admin not yet activated
python -m app.pic.tools.tenant_admin list
```

`create` makes: the tenant (MFA enforced for approver, finance and admin roles from the first day), number ranges, currencies, SoD
rules, agents, the rule sets of the chosen template, one company code with one plant and storage location, and the first
administrator (no password). It prints the **activation link once**; copy it to the customer through a secure channel (it is also
e-mailed when `PIC_SMTP_HOST` is set). The link works once and expires after `PIC_ACTIVATION_HOURS` (default 72); `reissue` makes
another. The link is never logged and never written to the audit trail (only its SHA-256 is stored). The run is audited as
`TENANT PROVISIONED` (actor `agent:tenant_admin_tool`). Repeating `create` for a tenant that already has users changes nothing and
exits with code 2; a run that stopped half-way can be repeated.

The administrator opens the link (`/pic/activate?token=...`), chooses a password (12+ characters, no common or breached password),
then signs in with the organisation code and is asked to register an authenticator app (MFA) before the first session.

## 2. Build the organisation (ADM-01)

Screen: Administration > Organisation. API: `/v1/admin/org/{kind}` with kind = `company-codes`, `plants`, `storage-locations`,
`cost-objects`, `purchasing-orgs`, `purchasing-groups`, `currencies`; `GET /v1/admin/organisation` returns everything in one call.

| Master | Rules |
|---|---|
| Company code | code 1-10 characters (capitals, digits, `.`, `_`, `-`), unique; GSTIN checked (format, state code, check character); currency must be active; the currency cannot change once documents exist |
| Plant | company code must exist and be active; GST state code 01-38 or 97; working days 0 (Monday) to 6 (Sunday) |
| Storage location | unique per plant |
| Cost object | type COST_CENTER, WBS, ORDER or ASSET; unique per type; optional owner and department head (active internal users) |
| Purchasing organisation / group | org belongs to a company code; a group may name an organisation, a plant and buyer users |
| Currency | 3-letter code; decimals 0-4, fixed once in use |

Codes never change after creation (documents refer to them by value); names and attributes can.

**Calendar.** `POST /v1/admin/org/plants/{id}/holidays {"dates": [...], "source": "<gazette notification>"}` adds public holidays (a
source is mandatory; dates are only ever added, so planned dates already computed keep their basis). `DELETE
.../holidays/{date}?reason=...` removes a wrongly entered one, with a reason.

**Deactivate or delete.** `DELETE /v1/admin/org/{kind}/{id}` deletes a record nothing refers to and *deactivates* one that anything
refers to (the response says `outcome: DELETED` or `DEACTIVATED`). References are found from the table definitions: any table with
a column of that name (company_code, plant, storage_location, cost_object_code, purch_org, ...), including rule sets scoped to it.
A record with active children (a company code with active plants) cannot be deactivated until they are: `409 HAS_ACTIVE_CHILDREN`.
Deactivated plants and cost objects leave the selection lists of the forms (`GET /v1/reference`) but stay on history and in the
Organisation screen; `POST .../activate` brings them back.
A deactivated company code, plant, storage location, cost object, purchasing organisation or purchasing group is refused on every
**new** requisition, purchase order and goods receipt that names it (`422 ORG_RECORD_INACTIVE`, rule ADM-01; the problem lists the
inactive records). Documents that already exist are not touched: open orders can still be received, changed and settled.

## 3. Users (ADM-04)

Screen: Administration > Users & roles. Needs TENANT_ADMIN.

- **Invite**: `POST /v1/admin/users {email, name, roles, attributes}`. Attributes (ABAC): `plants`, `company_codes`, `cost_objects`
  (`COST_CENTER:CC-100`), `categories`, `steward_domains` (lists of codes, `*` for all), `value_limit_minor` (paise). Codes must
  exist. Role combinations that span a segregation-of-duties pair are refused (`409 SOD_CONFLICT`). The response carries the
  activation link **once**; the user shows as INVITED until it is used. `POST .../resend-invitation` replaces an unused link
  (the old one stops working: `LINK_REVOKED`).
- **Password reset**: `POST /v1/admin/users/{id}/password-reset {reason}` returns a single-use link (valid `PIC_RESET_HOURS`, default 2).
  The current password keeps working until the link is used; using it ends every open session of the user.
- **Revoke sessions**: `POST /v1/admin/users/{id}/revoke-sessions {reason}`: every token the user holds is refused on its next
  request (`401 SESSION_REVOKED`); the user signs in again. Deactivation (`PUT .../active`) and role or attribute changes end
  sessions the same way.
- **Links** (`/v1/public/user-tokens/{token}`, public, throttled per client address): work once (`410 LINK_USED`), expire
  (`LINK_EXPIRED`) and are replaced by newer ones (`LINK_REVOKED`). A wrong or foreign token answers `404 LINK_NOT_FOUND`.
- **Bulk import**: `POST /v1/admin/users/import {"csv": "...", "dry_run": true}`. Columns `email,name,roles,plants,company_codes,
  value_limit_minor` (several values separated by `;`). The dry run reports every row (OK or its errors) and creates nothing; a real
  import is all-or-nothing and returns every activation link once (the screen offers them as a download). At most 500 rows.
- **Reset MFA** (lost phone): `POST /v1/admin/users/{id}/mfa/reset {reason}`, see the privacy runbook for identity checks.

## 4. Roles and the permission matrix (ADM-04)

Screen: Administration > Permission matrix. The 21 built-in roles live in code and are read-only. A tenant can add its own roles
(`POST /v1/admin/roles {code, name, description, scopes}`) from the **assignable scope catalogue** (`GET /v1/admin/roles/matrix`).
Platform-level scopes (`admin:*`, `agents:manage`) and supplier-portal scopes are never assignable (`422 SCOPE_NOT_ASSIGNABLE`).

**SoD check before saving.** `POST /v1/admin/roles/preview {code, scopes}` (and every create or update) computes the impact: a role
may not hold both sides of a scope-level SoD pair (SOD-02 `supplier:bank` with `payment:run`; SOD-03 `po:create`/`po:release` with
`gr:post`; SOD-04 `po:create`/`po:release` with `invoice:capture`/`invoice:resolve`/`invoice:post`), and no current holder may end up
spanning a pair he or she did not span before. A conflict is `409 SOD_CONFLICT` with the evidence (`impact`). The same pairs are
checked whenever roles are assigned to a user, across built-in and custom roles.

**Effect on sessions.** The scopes of a custom role are put into the access token at sign-in. Changing, deactivating or
reactivating a role ends the sessions of everyone who holds it (`SESSION_REVOKED`), so the new scopes apply at their next sign-in.
**Delete** removes an unused role; a role that users hold or tasks name is deactivated instead and its holders lose its scopes.
A custom role can be used as an approver role in workflow definitions (the designer accepts the tenant's active roles).

## 5. Industry templates

Screen: Administration > Industry templates. `GET /v1/admin/templates/{code}/preview` lists what applying would do: rule sets
**added**, **changed** (a new effective-dated version of a rule the template sets differently), **reverted** (a setting of the previous
template the new one does not use, returned to the default pack) and rules **left alone** because the tenant customised them since.
`POST /v1/admin/templates/{code}/apply` does it: no rule version is ever edited; `industry_template` switches; who and when are
recorded (`template_application`, audit `TEMPLATE_APPLIED`). Applying the template already in place with every rule set present
changes nothing (`applied: false, noop: true`). The MFA rule is not touched by templates. Documents already in flight keep the rule
version they started under.

## 6. Approval matrix (ADM-03, DMN-01)

Screen: Administration > Approval matrix. The grid edits the requisition approval route by value band and saves it as a new
effective-dated `DMN-01` version (`POST /v1/admin/rules`). Check the result in "Approval simulation" with a date after the
effective-from date. Requisitions already in approval keep the chain they started with.

## 7. Admin KPIs

Administration header shows the M13 KPIs: integration success % (messages POSTED / all), mean time to resolve an integration error
(hours from first attempt to posting, for messages that needed a retry) and SoD conflicts open (blocked or mitigation-required
violations). Targets are in rule `KPI-THRESHOLDS`. For dead-lettered messages see [dead-lettered-postings.md](dead-lettered-postings.md).

## 8. Troubleshooting

| Symptom | Cause and action |
|---|---|
| Customer says the activation link is invalid | Used (`LINK_USED`), expired, or replaced. Admin: "New link" in Users; operator (first admin): `tenant_admin reissue`. |
| `409 SOD_CONFLICT` on a role or an assignment | Working as designed. Split the duties, or use an SoD mitigation (Roles & SoD tab) for a documented exception. |
| User keeps getting `SESSION_REVOKED` | A role, attribute, password reset or revocation ended the session; sign in again. |
| Delete returned `DEACTIVATED` | Something refers to the record. Deactivate children first if `HAS_ACTIVE_CHILDREN`; history is kept on purpose. |
| `412 STALE_WRITE` on an edit | Someone saved first. Reload the record (new ETag) and repeat the change. |
| E-mail status `DISABLED` in an invitation | No SMTP configured (`PIC_SMTP_HOST`); hand the link to the user yourself. |

## Environment variables

`DATABASE_URL`, `PIC_JWT_SECRET`, `PIC_FIELD_KEY` (as for the API), `PIC_WEB_URL` (base of the links; default first CORS origin),
`PIC_ACTIVATION_HOURS` (72), `PIC_RESET_HOURS` (2), `PIC_SMTP_HOST` / `PIC_SMTP_PORT` / `PIC_SMTP_USER` / `PIC_SMTP_PASSWORD` /
`PIC_SMTP_FROM` / `PIC_SMTP_STARTTLS` for e-mail.
