"""Re-encrypt field-level ciphertext under the active key (key rotation, TD §14).

    python -m app.pic.tools.reencrypt                       # dry run: counts per tenant, table and key id; changes nothing
    python -m app.pic.tools.reencrypt --apply               # re-encrypt every row whose key is not the active one
    python -m app.pic.tools.reencrypt --apply --tenant AXN --batch 500

Rotation procedure: (1) add the new key to PIC_FIELD_KEYS as ``<id>:<key>`` in front of the old ones and deploy (new writes use it,
old ciphertext still decrypts); (2) run this job with --apply; (3) run it again without --apply and confirm "0 to rotate";
(4) only then remove the old key from PIC_FIELD_KEYS. PIC_FIELD_KEY (key id v1) stays configured: it is also the blind-index key.
Each tenant is processed in its own transactions (row-level security applies), in batches, and the run is audited per tenant.
"""
import argparse
import sys
import uuid
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import Bid, MfaFactor, PaymentFile, Supplier, SupplierBankAccount, SupplierMasterChange, Tenant
from app.pic.platform import audit, crypto


@dataclass
class Target:
    name: str
    model: type
    column: str
    purpose: Callable  # (row) -> purpose string
    text: bool = False  # stored as str (token decoded) rather than bytes


TARGETS = [
    Target("supplier.gstin_enc", Supplier, "gstin_enc", lambda r: "gstin"),
    Target("supplier.punchout_secret_enc", Supplier, "punchout_secret_enc", lambda r: "punchout", text=True),
    Target("supplier_bank_account.account_enc", SupplierBankAccount, "account_enc", lambda r: "bank"),
    Target("bid.sealed_payload", Bid, "sealed_payload", lambda r: f"bid:{r.event_id}"),
    Target("mfa_factor.secret_enc", MfaFactor, "secret_enc", lambda r: "mfa-totp", text=True),
    Target("payment_file.content", PaymentFile, "content", lambda r: "payment_file", text=True),
    Target("supplier_master_change.after_enc", SupplierMasterChange, "after_enc", lambda r: "supplier-master-change", text=True),
]


def _token(target: Target, row) -> bytes | None:
    value = getattr(row, target.column)
    if value is None:
        return None
    return value.encode() if target.text else bytes(value)


def run(apply: bool = False, tenant_code: str | None = None, batch: int = 500) -> dict:
    """{"active": key id, "tenants": {code: {target: {"byKey": {id: n}, "rotated": n, "failed": n}}}, "toRotate": n}."""
    with system_tx() as s:
        tenants = [(t.id, t.code) for t in s.execute(select(Tenant).order_by(Tenant.code)).scalars()
                   if tenant_code is None or t.code == tenant_code]
    report: dict = {"active": crypto.active_key_id(), "apply": apply, "tenants": {}, "toRotate": 0, "rotated": 0, "failed": 0}
    for tenant_id, code in tenants:
        per_tenant: dict = {}
        for target in TARGETS:
            stats = per_tenant[target.name] = {"byKey": {}, "rotated": 0, "failed": 0}
            last: uuid.UUID | None = None
            while True:
                with tenant_tx(tenant_id) as session:
                    query = select(target.model).where(getattr(target.model, target.column).is_not(None)).order_by(target.model.id).limit(batch)
                    if last is not None:
                        query = query.where(target.model.id > last)
                    rows = session.execute(query).scalars().all()
                    if not rows:
                        break
                    last = rows[-1].id
                    for row in rows:
                        token = _token(target, row)
                        key_id = crypto.key_id_of(token)
                        stats["byKey"][key_id] = stats["byKey"].get(key_id, 0) + 1
                        if key_id == crypto.active_key_id():
                            continue
                        report["toRotate"] += 1
                        if not apply:
                            continue
                        try:
                            fresh = crypto.rotate(tenant_id, target.purpose(row), token)
                            setattr(row, target.column, fresh.decode() if target.text else fresh)
                            stats["rotated"] += 1
                        except Exception as exc:  # noqa: BLE001 - wrong key / corrupt value: report, continue with the others
                            stats["failed"] += 1
                            print(f"  {code} {target.name} {row.id}: {type(exc).__name__}: {exc}", file=sys.stderr)
                    session.flush()
            report["rotated"] += stats["rotated"]
            report["failed"] += stats["failed"]
        report["tenants"][code] = per_tenant
        if apply:
            moved = sum(v["rotated"] for v in per_tenant.values())
            if moved:
                with tenant_tx(tenant_id) as session:
                    audit.record(session, "TENANT", tenant_id, "FIELDS_REENCRYPTED", object_ref=code, actor="job:reencrypt",
                                 after={"activeKey": crypto.active_key_id(), "rows": moved,
                                        "tables": {k: v["rotated"] for k, v in per_tenant.items() if v["rotated"]}})
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="re-encrypt (default: dry run)")
    parser.add_argument("--tenant", help="only this tenant code")
    parser.add_argument("--batch", type=int, default=500)
    args = parser.parse_args(argv)
    report = run(args.apply, args.tenant, args.batch)
    print(f"active key: {report['active']}  keys in ring: {', '.join(crypto.key_ids())}  mode: {'APPLY' if args.apply else 'DRY RUN'}")
    for code, targets in report["tenants"].items():
        for name, stats in targets.items():
            if stats["byKey"]:
                print(f"  {code:8} {name:38} {stats['byKey']}" + (f"  rotated {stats['rotated']}" if args.apply else ""))
    print(f"{report['toRotate']} to rotate" + (f", {report['rotated']} rotated, {report['failed']} failed" if args.apply else ""))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
