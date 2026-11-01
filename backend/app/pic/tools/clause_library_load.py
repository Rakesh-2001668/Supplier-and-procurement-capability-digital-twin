"""Load a clause library into a tenant: replace the illustrative sample with the client's legal-approved text, no code change.

    python -m app.pic.tools.clause_library_load --tenant KAC --file clauses.csv [--validate-only]
    python -m app.pic.tools.clause_library_load --export-sample data/clause_library/illustrative_clause_library.csv   (the format, filled in)

The file is CSV or JSON in the format of docs/runbooks/clause_library.md (the illustrative sample, ``seed/clause_library.py``, written out
by ``--export-sample``, is the template). It is validated completely first (codes, contract types, risk weight 1-10, escalation role, at most two
fallbacks, placeholders), then added to the tenant as a NEW effective-dated version of the CLM-PLAYBOOK rule set: an existing version is never
edited, the library replaces the sample's clause library, categoryClauses, jurisdictions and fallbacks per key, and everything else in the playbook
(templates, obligations, position risk, award defaults, the tenant's own entries) stays. Contracts already drafted keep the wording they were drafted with.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.pic.db import system_tx, tenant_tx
from app.pic.models import RuleSet, Tenant
from app.pic.platform import audit, clock
from app.pic.seed import clause_library

ACTOR = "integration:CLAUSE_LIBRARY_LOAD"


def apply(tenant_code: str, doc: dict, *, label: str = "file") -> dict:
    """Add the (validated) library document to the tenant as a new CLM-PLAYBOOK version. Returns what was written."""
    clause_library.validate(doc)
    patch = clause_library.playbook_patch(doc)
    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == tenant_code)).scalar_one_or_none()
    if tenant_id is None:
        raise SystemExit(f"Tenant {tenant_code} does not exist")
    with tenant_tx(tenant_id) as s:
        current = s.execute(select(RuleSet).where(RuleSet.key == "CLM-PLAYBOOK", RuleSet.company_code.is_(None), RuleSet.plant.is_(None),
                                                  RuleSet.category.is_(None), RuleSet.purchase_type.is_(None))
                            .order_by(RuleSet.effective_from.desc(), RuleSet.created_at.desc())).scalars().first()
        if current is None:
            raise SystemExit(f"Tenant {tenant_code} has no CLM-PLAYBOOK rule set: bootstrap the tenant first")
        stem = f"LIB-{clock.today():%Y%m%d}"
        version, n = stem, 1
        while s.execute(select(RuleSet.id).where(RuleSet.key == "CLM-PLAYBOOK", RuleSet.version == version)).first():
            n += 1
            version = f"{stem}-{n}"
        rule = RuleSet(tenant_id=tenant_id, key="CLM-PLAYBOOK", version=version, effective_from=max(clock.today(), current.effective_from),
                       body=clause_library.merge_into(current.body, patch, replace=True),
                       description=f"Clause library loaded from {label}: {len(doc['clauses'])} clauses, {len(doc.get('overlays') or [])} category overlays, "
                                   f"{len(doc.get('jurisdictions') or {})} jurisdictions")
        s.add(rule)
        s.flush()
        audit.record(s, "RULE_SET", rule.id, "VERSION_ADDED", object_ref=f"CLM-PLAYBOOK@{version}",
                     after={"previous": current.version, "source": doc.get("source"), "library": clause_library.summary(doc)}, actor=ACTOR)
    return {"tenant": tenant_code, "version": version, "previous": current.version, "summary": clause_library.summary(doc)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate a clause library file and load it into a tenant's CLM-PLAYBOOK as a new version")
    parser.add_argument("--tenant")
    parser.add_argument("--file")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--export-sample", help="write the illustrative sample library to this .csv or .json file (the format to fill in) and exit")
    args = parser.parse_args(argv)
    if args.export_sample:
        path = Path(args.export_sample)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = clause_library.library()
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n" if path.suffix.lower() == ".json" else clause_library.to_csv(doc), encoding="utf-8", newline="\n")
        print(f"Wrote the illustrative sample ({clause_library.summary(doc)}) to {path}")
        return 0
    if not args.file:
        parser.error("--file is required (or --export-sample)")
    try:
        doc = clause_library.read_file(args.file)
    except clause_library.LibraryError as exc:
        print(f"{args.file} is not a usable clause library:\n  " + "\n  ".join(str(exc).split("; ")), file=sys.stderr)
        return 1
    print(f"{args.file}: valid. {clause_library.summary(doc)}")
    if args.validate_only:
        return 0
    if not args.tenant:
        parser.error("--tenant is required to load")
    print(json.dumps(apply(args.tenant, doc, label=Path(args.file).name), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
