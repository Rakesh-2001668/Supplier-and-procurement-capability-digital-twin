"""Load a client's contract register (contract repository export) into PIC: ``python -m app.pic.tools.contract_load --tenant KAC --dir <folder>``.

The layout is docs/PIC_ERP_Extract_Spec.md section 10 (CLM_CONTRACT, CLM_LINE, CLM_CLAUSE, CLM_OBLIGATION, CLM_REBATE, CLM_AMENDMENT,
CLM_REDLINE, MANIFEST.json). The mock register of tenant KAC (``app.pic.tools.erp_mock_contracts``, ILLUSTRATIVE SAMPLE) uses it, and
a real export in the same layout loads the same way, with no code change. Like the SAP loader it is a migration: contracts arrive in
the state the register shows (ACTIVE, EXPIRING, EXPIRED, TERMINATED, IN_NEGOTIATION, ...), not through the approval steps, with these
differences from a new draft: the clauses are the contract's own wording, checked against the tenant's clause library (the library
text becomes ``standard_text``; a clause without a position is classified STANDARD / FALLBACK / NON_STANDARD by comparing its wording
with the library and its pre-approved fallbacks), signed contracts get signature records bound to the hash of the loaded text, obligations keep
their evidence dates, supplier redlines in negotiation are left pending for the contract manager, rebate agreements go through the
real service (tiers validated), every contract has a workflow instance and timers like an activated one, and everything is audited as
``MIGRATED`` by ``integration:CLM_REPOSITORY``.

Idempotent: a contract number that exists is skipped. A row that cannot be loaded goes to the reject list (reason, detail) and the load goes on.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from app.pic.config import BACKEND_DIR
from app.pic.db import system_tx, tenant_tx
from app.pic.models import (
    AppUser, Clause, Contract, ContractAmendment, ContractLine, Material, Obligation, PriceValidity, Signature, Supplier, Tenant,
)
from app.pic.platform import audit, clock, rules, workflow
from app.pic.platform.auth import Principal
from app.pic.platform.core import next_number
from app.pic.platform.money import D, line_amount
from app.pic.services import contract as contract_svc
from app.pic.services import rebates

log = logging.getLogger("pic.contract_load")

SOURCE = "CLM_REPOSITORY"
ACTOR = "integration:CLM_REPOSITORY"
DEFAULT_DIR = BACKEND_DIR / "data" / "erp_mock" / "KAC_CLM"
NS = uuid.UUID("7d1f5c0e-3b52-4c1e-9a77-2f64d0a1c0b3")
REQUIRED = ["CLM_CONTRACT", "CLM_LINE", "CLM_CLAUSE", "CLM_OBLIGATION"]
OPTIONAL = ["CLM_REBATE", "CLM_AMENDMENT", "CLM_REDLINE"]
STATUSES = ("DRAFT", "IN_NEGOTIATION", "IN_APPROVAL", "OUT_FOR_SIGNATURE", "ACTIVE", "EXPIRING", "EXPIRED", "TERMINATED")
LIVE = ("ACTIVE", "EXPIRING", "EXPIRED", "TERMINATED")
TYPES = ("MASTER_AGREEMENT", "QUANTITY_CONTRACT", "VALUE_CONTRACT", "SCHEDULING_AGREEMENT", "RATE_CARD", "SOW", "NDA")
UOM = {"ST": "EA", "PC": "EA", "EA": "EA", "KG": "KG", "L": "L", "M": "M", "SET": "SET", "AU": "AU", "LE": "AU", "MON": "MON", "PAC": "PAC", "PAA": "PR",
       "PR": "PR", "TO": "TON", "TON": "TON", "M2": "M2", "M3": "M3", "H": "HR", "HR": "HR", "D": "DAY", "DAY": "DAY", "KM": "KM"}


class ExtractError(Exception):
    """The register cannot be loaded at all (missing or altered file, unknown tenant): nothing is written."""


@dataclass
class IntegrationPrincipal(Principal):
    @property
    def actor(self) -> str:
        return ACTOR


def read_extract(directory) -> dict:
    """Read and verify the register export: every file in MANIFEST.json must exist with the stated row count and SHA-256."""
    directory = Path(directory)
    manifest_path = directory / "MANIFEST.json"
    if not manifest_path.exists():
        raise ExtractError(f"{manifest_path} is missing: the hand-over needs MANIFEST.json (row counts and SHA-256 per file)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files") or {}
    missing = [f"{n}.csv" for n in REQUIRED if f"{n}.csv" not in files]
    if missing:
        raise ExtractError(f"MANIFEST.json does not list required file(s): {', '.join(missing)}")
    tables = {}
    for name, entry in sorted(files.items()):
        path = directory / name
        if not path.exists():
            raise ExtractError(f"{name} is listed in MANIFEST.json but missing from {directory}")
        data = path.read_bytes()
        if entry.get("sha256") and hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ExtractError(f"{name}: SHA-256 differs from MANIFEST.json: the file changed after extraction")
        rows = []
        for index, record in enumerate(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))), start=2):
            row = {k.strip(): (v or "").strip() for k, v in record.items() if k}
            row["_row"] = index
            rows.append(row)
        if "rows" in entry and int(entry["rows"]) != len(rows):
            raise ExtractError(f"{name}: {len(rows)} data rows, MANIFEST.json says {entry['rows']}")
        tables[name[:-4]] = rows
    return {"directory": directory, "manifest": manifest, "tables": tables}


def _alpha(value: str) -> str:
    return value.lstrip("0") or "0" if value.isdigit() else value


def _date(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _dec(value: str) -> Optional[Decimal]:
    try:
        return Decimal(value) if value not in ("", None) else None
    except InvalidOperation:
        return None


def classify(text: str, standard: Optional[str], fallbacks: list) -> str:
    """Position of a clause the register gives no position for: library wording STANDARD, a pre-approved fallback wording FALLBACK, else NON_STANDARD."""
    norm = lambda t: " ".join((t or "").split())
    if standard is not None and norm(text) == norm(standard):
        return "STANDARD"
    if any(norm(text) == norm(f.get("text")) for f in fallbacks):
        return "FALLBACK"
    return "NON_STANDARD"


def load(tenant_code: str, directory=None, *, when: Optional[datetime] = None) -> dict:
    extract = read_extract(directory or DEFAULT_DIR)
    tables = extract["tables"]
    with system_tx() as s:
        tenant = s.execute(select(Tenant).where(Tenant.code == tenant_code)).scalar_one_or_none()
    if tenant is None:
        raise ExtractError(f"Tenant {tenant_code} does not exist: create it first (tenant onboarding or the dataset pack erp-client-kac)")
    principal = IntegrationPrincipal(user_id=uuid.UUID(int=0), tenant_id=tenant.id, tenant_code=tenant_code, email="integration.clm_repository",
                                     name="Contract repository inbound", roles=[], scopes={"contract:manage"}, agent_code=None)
    if when:
        clock.set_pinned(when)
    rejects: list = []
    counts: Counter = Counter()
    by_contract = lambda name: _group(tables.get(name, []), "CONTRACT_NO")
    lines, clauses, obligations = by_contract("CLM_LINE"), by_contract("CLM_CLAUSE"), by_contract("CLM_OBLIGATION")
    rebate_rows, amendments, redlines = by_contract("CLM_REBATE"), by_contract("CLM_AMENDMENT"), by_contract("CLM_REDLINE")

    def reject(row: dict, reason: str, detail: str) -> None:
        rejects.append({"file": "CLM_CONTRACT", "row": row["_row"], "key": row.get("CONTRACT_NO"), "reason": reason, "detail": detail})

    with tenant_tx(tenant.id, principal.user_id, principal) as s:
        playbook = rules.resolve(s, "CLM-PLAYBOOK")
        approval = rules.resolve(s, "CONTRACT-APPROVAL")
        notice = int(approval.body["renewalNoticeDays"])
        library_meta = {code: meta for code, meta in clause_meta(playbook.body).items()}
        suppliers = {x.code: x for x in s.execute(select(Supplier)).scalars()}
        materials = {m.number: m.id for m in s.execute(select(Material)).scalars()}
        users = {x.email.split("@")[0]: x for x in s.execute(select(AppUser).where(AppUser.active.is_(True), AppUser.supplier_id.is_(None))).scalars()}
        fallback_owner = next((u for u in sorted(users.values(), key=lambda u: u.email) if "CONTRACT_MANAGER" in u.roles), None)
        approver = next((u for u in sorted(users.values(), key=lambda u: u.email) if "CPO" in u.roles), fallback_owner)
        existing = {c.number: c for c in s.execute(select(Contract)).scalars()}
        positions = playbook.body["positionRisk"]
        order = sorted(tables["CLM_CONTRACT"], key=lambda r: (0 if r.get("CONTRACT_TYPE") == "MASTER_AGREEMENT" else 1, r.get("CONTRACT_NO", "")))
        loaded_value = 0
        for row in order:
            number = row.get("CONTRACT_NO", "")
            if number in existing:
                counts["existing"] += 1
                continue
            supplier = suppliers.get(_alpha(row.get("LIFNR", "")))
            start, end = _date(row.get("VALID_FROM", "")), _date(row.get("VALID_TO", ""))
            parent = existing.get(row.get("PARENT_NO", "")) if row.get("PARENT_NO") else None
            if not number or row.get("CONTRACT_TYPE") not in TYPES:
                reject(row, "TYPE_UNKNOWN", f"contract type {row.get('CONTRACT_TYPE')!r} is not one of {', '.join(TYPES)}")
            elif row.get("STATUS") not in STATUSES:
                reject(row, "STATUS_UNKNOWN", f"status {row.get('STATUS')!r} is not one of {', '.join(STATUSES)}")
            elif supplier is None:
                reject(row, "VENDOR_NOT_LOADED", f"supplier {_alpha(row.get('LIFNR', ''))} is not in PIC: load the vendor master first")
            elif start is None or end is None or end <= start:
                reject(row, "VALIDITY_INVALID", f"validity {row.get('VALID_FROM')} to {row.get('VALID_TO')} is not usable")
            elif row.get("PARENT_NO") and parent is None:
                reject(row, "PARENT_NOT_LOADED", f"the master agreement {row['PARENT_NO']} is not loaded")
            elif not row.get("PAYMENT_TERMS"):
                reject(row, "PAYMENT_TERMS_MISSING", "payment terms are required")
            else:
                contract = _load_contract(s, principal, row, supplier, parent, start, end, lines.get(number, []), clauses.get(number, []), obligations.get(number, []),
                                          amendments.get(number, []), redlines.get(number, []), playbook, library_meta, positions, materials, users,
                                          fallback_owner, approver, notice, rejects, counts)
                existing[number] = contract
                loaded_value += contract.target_value_minor
                counts["loaded"] += 1
                counts[f"type:{contract.type}"] += 1
                counts[f"status:{contract.status}"] += 1
        s.flush()
        # rebate agreements go through the real service (tiers validated, linked to the contract)
        for number, items in rebate_rows.items():
            contract = existing.get(number)
            for item in items:
                if contract is None or any(a.title == item["TITLE"] for a in contract_rebates(s, contract)):
                    continue
                try:
                    tiers = [{"from": part.split(":")[0], "ratePct": part.split(":")[1]} for part in item["TIERS"].split("|")]
                    agreement = rebates.create_agreement(s, contract, title=item["TITLE"], basis=item["BASIS"], period=item["PERIOD"], tiers=tiers,
                                                         tier_mode=item["TIER_MODE"], scope=item["SCOPE"], valid_from=_date(item["VALID_FROM"]),
                                                         valid_to=_date(item["VALID_TO"]))
                    rebates.accrue(s, agreement, clock.today())
                    counts["rebates"] += 1
                except Exception as exc:  # noqa: BLE001 - a bad rebate row is a reject, the contract stays loaded
                    rejects.append({"file": "CLM_REBATE", "row": item["_row"], "key": item.get("REBATE_NO"), "reason": "REBATE_INVALID", "detail": str(exc)[:300]})
        if counts["loaded"]:
            audit.record(s, "MIGRATION", uuid.uuid5(NS, f"{tenant_code}|{extract['manifest'].get('extractId')}|contracts"), "INITIAL_LOAD",
                         object_ref=f"{SOURCE} contracts", after={"extract": extract["manifest"].get("extractId"), "object": "contracts", "loaded": counts["loaded"],
                                                                  "alreadyLoaded": counts["existing"], "rejects": len(rejects)}, actor=ACTOR)
    summary = {"extractId": extract["manifest"].get("extractId"), "loaded": counts["loaded"], "existing": counts["existing"], "rejects": rejects,
               "byType": {k[5:]: v for k, v in counts.items() if k.startswith("type:")}, "byStatus": {k[7:]: v for k, v in counts.items() if k.startswith("status:")},
               "rebates": counts["rebates"], "clauses": dict(counts_by(counts, "clause:")), "obligations": dict(counts_by(counts, "obligation:")),
               "amendments": counts["amendments"], "signatures": counts["signatures"], "redlinesPending": counts["redlines"], "targetValueMinor": loaded_value}
    return summary


def counts_by(counts: Counter, prefix: str):
    return {k[len(prefix):]: v for k, v in counts.items() if k.startswith(prefix)}


def contract_rebates(s, contract) -> list:
    from app.pic.models import RebateAgreement
    return list(s.execute(select(RebateAgreement).where(RebateAgreement.contract_id == contract.id)).scalars())


def clause_meta(playbook_body: dict) -> dict:
    from app.pic.seed import clause_library
    return clause_library.metadata(playbook_body)


def _group(rows: list, key: str) -> dict:
    out: dict = {}
    for r in rows:
        out.setdefault(r.get(key, ""), []).append(r)
    return out


def _load_contract(s, principal, row, supplier, parent, start, end, line_rows, clause_rows, obligation_rows, amendment_rows, redline_rows, playbook,
                   library_meta, positions, materials, users, fallback_owner, approver, notice, rejects, counts) -> Contract:
    tid, status, number = principal.tenant_id, row["STATUS"], row["CONTRACT_NO"]
    owner = users.get(row.get("OWNER", ""), fallback_owner)
    owner_id = owner.id if owner else principal.user_id
    index = ({"index": row["INDEX_NAME"], "base": row["INDEX_BASE"], "band_pct": row["INDEX_BAND"], "reset": row.get("INDEX_RESET") or "QUARTERLY"}
             if row.get("INDEX_NAME") else None)
    terminated_on = _date(row.get("TERMINATED_ON", ""))
    contract = Contract(tenant_id=tid, number=number, type=row["CONTRACT_TYPE"], title=row["TITLE"][:200], supplier_id=supplier.id, company_code=row.get("BUKRS") or "1000",
                        status=status, valid_from=start, valid_to=end, payment_terms=row["PAYMENT_TERMS"][:10], incoterms=row.get("INCO1") or None,
                        over_tolerance_pct=_dec(row.get("OVER_TOL", "")) or Decimal(0), under_tolerance_pct=_dec(row.get("UNDER_TOL", "")) or Decimal(0),
                        price_tolerance_pct=_dec(row.get("PRICE_TOL", "")) or Decimal(0), index_ref=index, owner_id=owner_id, rule_set_version=playbook.ref,
                        version=int(row.get("VERSION") or 1), framework_contract_id=parent.id if parent else None,
                        jurisdiction=row.get("JURISDICTION") or None, category=(row.get("CATEGORY") or None), created_by=principal.user_id,
                        activated_at=clock.at_ist(start, 0) if status in LIVE else None,
                        terminated_at=clock.at_ist(terminated_on, 0) if terminated_on else None, termination_reason=row.get("TERMINATION_REASON") or None)
    s.add(contract)
    s.flush()
    # lines and price validities (a price revision splits the validity)
    published = status in ("ACTIVE", "EXPIRING", "EXPIRED")
    target = 0
    for ln in sorted(line_rows, key=lambda r: int(r["LINE_NO"])):
        line = ContractLine(tenant_id=tid, contract_id=contract.id, line_no=int(ln["LINE_NO"]), material_id=materials.get(ln.get("MATNR", "")),
                            description=(ln["TXZ01"] or ln.get("MATNR") or "")[:200], plant=ln["WERKS"], uom=UOM.get(ln["MEINS"], ln["MEINS"])[:5],
                            target_qty=_dec(ln["KTMNG"]), created_by=principal.user_id)
        s.add(line)
        s.flush()
        price = int((_dec(ln["NETPR"]) * 100).to_integral_value())
        revised = _date(ln.get("REVISED_ON", ""))
        if revised and ln.get("PREV_NETPR"):
            s.add(PriceValidity(tenant_id=tid, contract_line_id=line.id, valid_from=start, valid_to=revised - timedelta(days=1),
                                unit_price_minor=int((_dec(ln["PREV_NETPR"]) * 100).to_integral_value()), reason="INITIAL", published=published, created_by=principal.user_id))
            s.add(PriceValidity(tenant_id=tid, contract_line_id=line.id, valid_from=revised, valid_to=end, unit_price_minor=price, reason="AMENDMENT",
                                published=published, created_by=principal.user_id))
        else:
            s.add(PriceValidity(tenant_id=tid, contract_line_id=line.id, valid_from=start, valid_to=end, unit_price_minor=price, reason="MIGRATED",
                                published=published, created_by=principal.user_id))
        target += line_amount(line.target_qty, price)
    contract.target_value_minor = target
    declared = _dec(row.get("TARGET_VALUE", ""))
    if declared is not None and abs(int((declared * 100).to_integral_value()) - target) > 100:
        rejects.append({"file": "CLM_CONTRACT", "row": row["_row"], "key": number, "reason": "TARGET_VALUE_DIFFERS",
                        "detail": f"register value {declared} differs from lines {target / 100:.2f} (loaded, flagged)"})
    # clauses: the contract's own wording against the tenant's library
    library = contract_svc._library(playbook.body, type=contract.type, payment_terms=contract.payment_terms, incoterms=contract.incoterms,
                                    supplier_name=supplier.legal_name, index_ref=({**index, "band_pct": index["band_pct"]} if index else None),
                                    tolerances={"over_pct": str(contract.over_tolerance_pct), "under_pct": str(contract.under_tolerance_pct)},
                                    jurisdiction=contract.jurisdiction, category=contract.category)
    non_standard = []
    for cl in clause_rows:
        code = cl["CLAUSE_CODE"]
        standard = library.get(code, {}).get("text")
        fallbacks = (library_meta.get(code) or {}).get("fallbackPositions") or []
        position = cl.get("POSITION") if cl.get("POSITION") in positions else classify(cl["TEXT"], standard, fallbacks)
        if standard is None and position == "STANDARD":
            position = "NON_STANDARD"       # a clause the library does not know cannot be standard
        if position == "NON_STANDARD":
            non_standard.append(code)
        s.add(Clause(tenant_id=tid, contract_id=contract.id, code=code[:30], title=(cl.get("TITLE") or library.get(code, {}).get("title") or code)[:200], text=cl["TEXT"],
                     standard_text=standard, position=position, risk_score=int(positions[position]), created_by=principal.user_id))
        counts[f"clause:{position}"] += 1
    # obligations and milestones
    for ob in obligation_rows:
        done = ob["STATUS"] == "DONE"
        s.add(Obligation(tenant_id=tid, contract_id=contract.id, party=ob["PARTY"], description=ob["DESCRIPTION"], kind=ob.get("KIND") or "OBLIGATION",
                         due_date=date.fromisoformat(ob["DUE_DATE"]), status=ob["STATUS"] if ob["STATUS"] in ("OPEN", "DONE", "CANCELLED") else "OPEN",
                         completed_at=clock.at_ist(date.fromisoformat(ob["COMPLETED_ON"]), 11) if done and ob.get("COMPLETED_ON") else None,
                         completed_by=owner_id if done else None, completion_note=ob.get("NOTE") or None, created_by=principal.user_id))
        counts[f"obligation:{ob['STATUS']}"] += 1
    s.flush()
    # amendment history
    version = 1
    for am in sorted(amendment_rows, key=lambda r: int(r["SEQ"])):
        effective = am["STATUS"] == "EFFECTIVE"
        s.add(ContractAmendment(tenant_id=tid, number=next_number(s, "CONTRACT_AMENDMENT"), contract_id=contract.id, kind=am["KIND"],
                                changes=json.loads(am["CHANGES"] or "{}"), reason=am["REASON"], status=am["STATUS"], effective_from=date.fromisoformat(am["EFFECTIVE_FROM"]),
                                from_version=version, to_version=version + 1 if effective else None, snapshot=json.loads(am["BEFORE"] or "{}"),
                                requested_by=owner_id, approved_by=(approver.id if approver and am["STATUS"] in ("EFFECTIVE", "APPROVED") else None),
                                decided_at=clock.at_ist(date.fromisoformat(am["DECIDED_ON"]), 15) if am.get("DECIDED_ON") else None, created_by=principal.user_id))
        version += 1 if effective else 0
        counts["amendments"] += 1
    s.flush()
    # signatures of signed contracts, bound to the hash of the loaded document
    signed_on = _date(row.get("SIGNED_ON", ""))
    document_hash = contract_svc._document_hash(s, contract) if signed_on and status not in ("DRAFT", "IN_NEGOTIATION", "IN_APPROVAL") else None
    for party, signer, hour in (("BUYER", row.get("BUYER_SIGNER"), 11), ("SUPPLIER", row.get("SUPPLIER_SIGNER"), 15)):
        if document_hash and signer:
            s.add(Signature(tenant_id=tid, contract_id=contract.id, party=party, signer_name=signer[:200], signer_user_id=None, signed_at=clock.at_ist(signed_on, hour),
                            envelope_ref=f"MIG-{number}-{party[0]}"[:60], document_hash=document_hash, created_by=principal.user_id))
            counts["signatures"] += 1
    # pending supplier redlines
    for rl in redline_rows:
        clause = next((c for c in clause_rows if c["CLAUSE_CODE"] == rl["CLAUSE_CODE"]), None)
        if clause is None:
            continue
        audit.record(s, "CONTRACT", contract.id, "CLAUSE_REDLINED", object_ref=number, before={"clause": rl["CLAUSE_CODE"], "text": library.get(rl["CLAUSE_CODE"], {}).get("text"),
                                                                                              "position": "STANDARD"},
                     after={"clause": rl["CLAUSE_CODE"], "text": rl["SUPPLIER_TEXT"], "position": "NON_STANDARD", "party": "SUPPLIER", "pendingReview": True,
                            "proposedPosition": None}, actor=f"supplier:{supplier.code}")
        counts["redlines"] += 1
    # workflow instance, timers, renewal decision
    instance = workflow.start(s, contract_svc.PROCESS, "CONTRACT", contract.id, number, {"trigger": "migration", "source": SOURCE})
    workflow.step(s, instance, "F4-02", outcome=f"migrated from {SOURCE}: {len(clause_rows)} clauses")
    if status in ("IN_NEGOTIATION", "OUT_FOR_SIGNATURE") or status in LIVE:
        workflow.step(s, instance, "F4-03", outcome=f"risk {max([int(positions[(c['POSITION'] if c.get('POSITION') in positions else 'STANDARD')]) for c in clause_rows] or [0])}")
    if status == "IN_NEGOTIATION":
        workflow.wait(s, instance, "F4-04", outcome="supplier review / redline")
    elif status == "OUT_FOR_SIGNATURE" or status in LIVE:
        for step in ("F4-04", "F4-05", "F4-06"):
            workflow.step(s, instance, step, outcome="migrated: approved before the cutover")
        if status == "OUT_FOR_SIGNATURE":
            workflow.wait(s, instance, "F4-07", outcome="out for e-signature (buyer signed)")
        else:
            workflow.step(s, instance, "F4-07", outcome="signed by buyer and supplier")
            workflow.step(s, instance, "F4-08", outcome=f"migrated {status.lower()}: {len(line_rows)} line(s)")
            if status in ("ACTIVE", "EXPIRING"):
                workflow.wait(s, instance, "F4-09", outcome="tracking consumption & obligations")
                workflow.create_timer(s, "CONTRACT_EXPIRY", "CONTRACT", contract.id, clock.at_ist(end + timedelta(days=1), 0, 5))
                if status == "ACTIVE":
                    workflow.create_timer(s, "CONTRACT_RENEWAL", "CONTRACT", contract.id, clock.at_ist(end - timedelta(days=notice), 9))
                else:
                    workflow.start_approval(s, instance, "CONTRACT_RENEWAL", object_type="CONTRACT", object_id=contract.id, object_ref=number, chain=["CONTRACT_MANAGER"],
                                            step_id=None, initiator_id=None, evidence={"validTo": end.isoformat()})
            else:
                workflow.step(s, instance, "F4-09", outcome="consumption tracking ended")
                workflow.end(s, instance, "F4-10", outcome=(f"terminated on {terminated_on}" if status == "TERMINATED" else f"expired on {end}"))
    audit.record(s, "CONTRACT", contract.id, "MIGRATED", object_ref=number,
                 after={"source": f"{SOURCE} {row.get('DOC_REF') or 'no signed document'}", "type": contract.type, "supplier": supplier.code, "status": status,
                        "validFrom": start, "validTo": end, "targetValueMinor": target, "framework": parent.number if parent else None,
                        "signedOn": signed_on, "documentRef": row.get("DOC_REF") or None, "documentHash": document_hash, "clauses": len(clause_rows),
                        "nonStandardClauses": non_standard}, actor=ACTOR)
    return contract


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Load a contract register export (docs/PIC_ERP_Extract_Spec.md section 10) into a tenant")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--dir", default=str(DEFAULT_DIR))
    args = parser.parse_args(argv)
    summary = load(args.tenant, args.dir)
    clock.set_pinned(None)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
