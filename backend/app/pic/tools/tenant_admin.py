"""Tenant provisioning from the command line (no public API: creating a tenant needs platform-level authority that no tenant role has).

    python -m app.pic.tools.tenant_admin create --code ACME --name "Acme Industries Ltd" --template MANUFACTURING \\
        --admin-email cio@acme.example [--admin-name "Asha Rao"] [--company-code 1000] [--company-name "Acme Industries Ltd"] \\
        [--gstin 33AABCA1234F1Z5] [--plant P100] [--plant-name "Chennai plant"] [--state-code 33] [--json]
    python -m app.pic.tools.tenant_admin reissue --code ACME --admin-email cio@acme.example [--json]
    python -m app.pic.tools.tenant_admin list

``create`` makes the tenant (MFA enforced for approver, finance and admin roles from the start), its number ranges, rule sets of the
chosen industry template, currencies, SoD rules and agents (seed.reference.bootstrap), one company code with one plant and storage
location, and the first administrator: a user with no password and a single-use activation link. The link is printed once on
standard output (and e-mailed when SMTP is configured); it is never written to a log or to the audit trail. The run is audited in the
new tenant's trail. A half-finished run can be repeated. The database is the one in DATABASE_URL (backend/.env).
"""
import argparse
import json
import re
import sys
import uuid

from sqlalchemy import func, select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import AppUser, Tenant
from app.pic.platform import audit
from app.pic.platform.auth import Principal
from app.pic.seed import reference
from app.pic.seed.templates import TEMPLATES
from app.pic.services import master_changes, user_admin

TENANT_CODE = re.compile(r"^[A-Z][A-Z0-9]{1,19}$")
TOOL_ID = uuid.uuid5(uuid.NAMESPACE_URL, "pic:tool:tenant_admin")


class ToolError(Exception):
    pass


def _tool_principal(tenant_id: uuid.UUID, code: str) -> Principal:
    return Principal(user_id=TOOL_ID, tenant_id=tenant_id, tenant_code=code, email="tenant_admin@tool.pic", name="Tenant provisioning tool",
                     roles=["TENANT_ADMIN"], scopes=set(), attributes={}, agent_code="tenant_admin_tool")


def _validate(args) -> None:
    errors = []
    if not TENANT_CODE.match(args.code):
        errors.append("--code: 2-20 characters, capital letters and digits, starting with a letter")
    if args.template not in TEMPLATES:
        errors.append(f"--template: one of {', '.join(TEMPLATES)}")
    if len((args.name or "").strip()) < 3:
        errors.append("--name: at least 3 characters")
    if not master_changes.EMAIL_RE.match(args.admin_email or ""):
        errors.append("--admin-email: not a valid address")
    if args.gstin and master_changes.gstin_errors(args.gstin.upper()):
        errors.append("--gstin: " + "; ".join(master_changes.gstin_errors(args.gstin.upper())))
    if args.state_code not in master_changes.STATE_CODES:
        errors.append("--state-code: a 2-digit GST state code (01-38 or 97)")
    if not re.match(r"^[A-Z0-9]{2,10}$", args.company_code) or not re.match(r"^[A-Z0-9]{2,10}$", args.plant):
        errors.append("--company-code and --plant: 2-10 capital letters or digits")
    if errors:
        raise ToolError("; ".join(errors))


def _issue_link(tenant_id: uuid.UUID, code: str, email: str, name: str, *, create_user: bool) -> dict:
    with tenant_tx(tenant_id, TOOL_ID, _tool_principal(tenant_id, code)) as s:
        if create_user:
            result = user_admin._create(s, {"email": email.lower(), "name": name, "roles": ["TENANT_ADMIN"], "attributes": {"plants": ["*"], "company_codes": ["*"]}})
            return result
        user = s.execute(select(AppUser).where(AppUser.email == email.lower())).scalar_one_or_none()
        if user is None:
            raise ToolError(f"{email} is not a user of tenant {code}")
        if not user.activation_pending:
            raise ToolError(f"{email} has already activated the account; use the administrator password reset instead")
        return user_admin.resend_invitation(s, user)


def create(args) -> dict:
    _validate(args)
    code = args.code
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == code)).scalar_one_or_none()
        existing_id = tenant.id if tenant else None
    if existing_id is not None:
        with tenant_tx(existing_id) as s:
            users = s.execute(select(func.count()).select_from(AppUser)).scalar()
        if users:
            raise ToolError(f"Tenant {code} already exists with {users} user(s); nothing was changed")
        # no users yet: a run that stopped after creating the tenant (or its base data) is continued below
    tenant_id = reference.create_tenant(code, args.name.strip(), args.template, mfa_enforce=True)
    reference.bootstrap(tenant_id, company=(args.company_code, args.company_name or args.name.strip(), args.gstin.upper() if args.gstin else None),
                        plants=[(args.plant, args.plant_name, args.state_code)], cost_objects=[])
    result = _issue_link(tenant_id, code, args.admin_email, args.admin_name or args.admin_email.split("@")[0].replace(".", " ").title(),
                         create_user=True)
    with tenant_tx(tenant_id, TOOL_ID, _tool_principal(tenant_id, code)) as s:
        audit.record(s, "TENANT", tenant_id, "PROVISIONED", object_ref=code,
                     after={"template": args.template, "companyCode": args.company_code, "plant": args.plant, "mfaEnforced": True,
                            "firstAdmin": args.admin_email.lower()})
    return {"tenant": code, "tenantId": str(tenant_id), "template": args.template, "admin": args.admin_email.lower(),
            "activationUrl": result["activationUrl"], "expiresAt": result["expiresAt"], "emailStatus": result["emailStatus"]}


def reissue(args) -> dict:
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == args.code)).scalar_one_or_none()
        if tenant is None:
            raise ToolError(f"No tenant {args.code}")
        tenant_id = tenant.id
    result = _issue_link(tenant_id, args.code, args.admin_email, "", create_user=False)
    return {"tenant": args.code, "admin": args.admin_email.lower(), "activationUrl": result["activationUrl"], "expiresAt": result["expiresAt"],
            "emailStatus": result["emailStatus"]}


def list_tenants(_args) -> list[dict]:
    with system_tx() as s:
        return [{"code": t.code, "name": t.name, "template": t.industry_template, "mfaEnforce": t.mfa_enforce, "createdAt": t.created_at.isoformat()}
                for t in s.execute(select(Tenant).order_by(Tenant.code)).scalars()]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.pic.tools.tenant_admin", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create", help="provision a tenant with base organisation, template and first administrator")
    c.add_argument("--code", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--template", required=True, choices=sorted(TEMPLATES))
    c.add_argument("--admin-email", required=True)
    c.add_argument("--admin-name")
    c.add_argument("--company-code", default="1000")
    c.add_argument("--company-name")
    c.add_argument("--gstin")
    c.add_argument("--plant", default="P100")
    c.add_argument("--plant-name", default="Main plant")
    c.add_argument("--state-code", default="33")
    r = sub.add_parser("reissue", help="new activation link for an administrator who has not activated yet")
    r.add_argument("--code", required=True)
    r.add_argument("--admin-email", required=True)
    sub.add_parser("list", help="list tenants")
    for p in (c, r, sub.choices["list"]):
        p.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = {"create": create, "reissue": reissue, "list": list_tenants}[args.command](args)
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    elif args.command == "list":
        for t in result:
            print(f"{t['code']:<12} {t['template']:<14} mfa={t['mfaEnforce']}  {t['name']}")
    else:
        print(f"Tenant {result['tenant']} ready.")
        print(f"First administrator: {result['admin']}")
        print(f"Activation link (shown once, valid until {result['expiresAt']}; e-mail: {result['emailStatus']}):\n  {result['activationUrl']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
