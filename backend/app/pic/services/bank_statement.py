"""Bank statement import (F7-09): camt.053 (ISO 20022 XML) and a basic MT940 turned into the per-payment bank results of
``bank_files.record_bank_results`` (credited with the bank reference as UTR, or returned with the reason).

Matching is by payment number: the bank echoes the EndToEndId of our pain.001 (or the reference of the NEFT file) in the entry, so every
entry is searched for the payment numbers of the tenant. An import is analysed first (dry run: nothing is written), then applied; the statement
id makes the apply idempotent (the same statement again returns the first result, a different content under the same id is refused).
Entries that match no payment, differ in amount or contradict an earlier result are reported and left alone; the rest is applied.
"""
import hashlib
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import BankStatementImport, Payment, PaymentFile
from app.pic.platform import audit
from app.pic.platform.errors import Problem
from app.pic.services import bank_files
from app.pic.services.common import principal

MAX_BYTES = 5 * 1024 * 1024
RETURN_WORDS = ("RETURN", "RTRN", "REVERSAL", "REFUND")


def _invalid(detail: str) -> Problem:
    return Problem(422, "INVALID_STATEMENT", detail, rule_ref="F7-09")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _minor(text: str) -> int:
    try:
        return int((Decimal(text.strip().replace(",", ".")) * 100).quantize(Decimal(1)))
    except (InvalidOperation, AttributeError):
        raise _invalid(f"amount '{text}' is not a number")


def _child(node: ET.Element, *path: str) -> Optional[ET.Element]:
    for name in path:
        found = next((c for c in node if _local(c.tag) == name), None)
        if found is None:
            return None
        node = found
    return node


def _text(node: Optional[ET.Element], *path: str) -> str:
    target = _child(node, *path) if node is not None and path else node
    return (target.text or "").strip() if target is not None and target.text else ""


def _all(node: ET.Element, name: str) -> list[ET.Element]:
    return [e for e in node.iter() if _local(e.tag) == name]


def _day(text: str) -> Optional[date]:
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------- camt.053
def parse_camt053(data: bytes) -> dict:
    lowered = data[:200_000].lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise _invalid("DTD and entity declarations are not accepted in a bank statement")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise _invalid(f"the XML cannot be read: {exc}")
    statements = _all(root, "Stmt")
    if not statements:
        raise _invalid("no Stmt element: this is not a camt.053 bank-to-customer statement")
    first = statements[0]
    statement_id = _text(first, "Id") or _text(root, "BkToCstmrStmt", "GrpHdr", "MsgId")
    if not statement_id:
        raise _invalid("the statement has no Id")
    account = _text(first, "Acct", "Id", "IBAN") or _text(first, "Acct", "Id", "Othr", "Id")
    entries = []
    for stmt in statements:
        for ntry in [e for e in stmt if _local(e.tag) == "Ntry"]:
            details = _all(ntry, "TxDtls") or [ntry]
            refs = [t.text.strip() for d in details for name in ("EndToEndId", "InstrId", "TxId", "AcctSvcrRef", "Ref")
                    for t in _all(d, name) if t.text and t.text.strip()]
            refs += [t.text.strip() for name in ("AcctSvcrRef", "NtryRef", "Ustrd", "AddtlTxInf", "AddtlNtryInf") for t in _all(ntry, name) if t.text and t.text.strip()]
            bank_ref = next((t.text.strip() for name in ("AcctSvcrRef", "TxId", "NtryRef") for t in _all(ntry, name) if t.text and t.text.strip()), "")
            returned = _text(ntry, "RvslInd").lower() == "true" or bool(_all(ntry, "RtrInf")) or any(
                (t.text or "").strip().upper() in ("RTRN", "RRTN", "RFND") for t in _all(ntry, "SubFmlyCd"))
            reasons = [t.text.strip() for name in ("Cd", "Prtry") for r in _all(ntry, "Rsn") for t in _all(r, name) if t.text and t.text.strip()]
            reasons += [t.text.strip() for r in _all(ntry, "RtrInf") for t in _all(r, "AddtlInf") if t.text and t.text.strip()]
            amount = _text(ntry, "Amt")
            if not amount:
                continue
            entries.append({"amountMinor": _minor(amount), "direction": "D" if _text(ntry, "CdtDbtInd") == "DBIT" else "C", "returned": returned,
                            "bankRef": bank_ref, "text": " ".join(refs), "reason": "; ".join(dict.fromkeys(reasons)) or "Returned by the bank",
                            "valueDate": (_day(_text(ntry, "ValDt", "Dt")) or _day(_text(ntry, "BookgDt", "Dt")) or date.min).isoformat()})
    return {"format": "CAMT053", "statementId": statement_id[:60], "account": account[:60], "entries": entries}


# ---------------------------------------------------------------- MT940
_LINE61 = re.compile(r"^(\d{6})(\d{4})?(RC|RD|C|D)([A-Z])?(\d+,\d*)N([A-Z0-9]{3})(.*)$", re.S)


def parse_mt940(text: str) -> dict:
    fields: list[tuple[str, str]] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()
        match = re.match(r"^:(\d{2}[A-Z]?):(.*)$", line)
        if match:
            fields.append((match.group(1), match.group(2)))
        elif line.startswith("-}") or line.startswith("{") or line == "-" or not line:
            continue
        elif fields:
            fields[-1] = (fields[-1][0], fields[-1][1] + "\n" + line)
    tags = {tag: value for tag, value in fields if tag in ("20", "25", "28C")}
    if "20" not in tags:
        raise _invalid("no :20: transaction reference: this is not an MT940 statement")
    statement_id = f"{tags['20'].strip()}-{tags['28C'].strip().replace('/', '.')}" if "28C" in tags else tags["20"].strip()
    entries: list[dict] = []
    for tag, value in fields:
        if tag == "61":
            parsed = _LINE61.match(value.replace("\n", ""))
            if not parsed:
                raise _invalid(f"statement line :61: '{value[:40]}' cannot be read")
            day, _, mark, _, amount, _, rest = parsed.groups()
            reference, _, bank_ref = rest.partition("//")
            entries.append({"amountMinor": _minor(amount), "direction": "D" if mark in ("D", "RC") else "C", "returned": mark in ("RC", "RD"),
                            "bankRef": bank_ref.strip()[:40], "text": reference.strip(), "reason": "Returned by the bank",
                            "valueDate": datetime.strptime(day, "%y%m%d").date().isoformat()})
        elif tag == "86" and entries:
            info = value.replace("\n", " ")
            entries[-1]["text"] = f"{entries[-1]['text']} {info}".strip()
            if any(word in info.upper() for word in RETURN_WORDS):
                entries[-1]["returned"] = True
            if entries[-1]["returned"]:
                entries[-1]["reason"] = info.strip()[:200] or entries[-1]["reason"]
    return {"format": "MT940", "statementId": statement_id[:60], "account": tags.get("25", "").strip()[:60], "entries": entries}


def parse(data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        raise Problem(413, "STATEMENT_TOO_LARGE", f"A bank statement is at most {MAX_BYTES // (1024 * 1024)} MB")
    head = data[:2000].lstrip(b"\xef\xbb\xbf \r\n\t")
    if head.startswith(b"<"):
        return parse_camt053(data)
    try:
        return parse_mt940(data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise _invalid("the file is neither camt.053 XML nor MT940 text (UTF-8)")


# ---------------------------------------------------------------- analysis and apply
def _candidates(text: str) -> set[str]:
    return set(re.findall(r"[A-Z0-9][A-Z0-9\-/]{3,34}", text.upper()))


def analyse(session: Session, statement: dict) -> dict:
    """Match every entry to a payment and decide what applying it would do. Nothing is written."""
    tokens = set().union(*[_candidates(e["text"]) for e in statement["entries"]]) if statement["entries"] else set()
    by_number: dict[str, Payment] = {}
    if tokens:  # payment numbers are matched case-insensitively
        for pay in session.execute(select(Payment).where(func.upper(Payment.number).in_(tokens))).scalars():
            by_number[pay.number.upper()] = pay
    files = {f.run_ref: f for f in session.execute(select(PaymentFile).where(PaymentFile.status != "REJECTED").order_by(PaymentFile.created_at)).scalars()}
    out = []
    for n, e in enumerate(statement["entries"], start=1):
        hits = [by_number[t] for t in sorted(_candidates(e["text"])) if t in by_number]
        item = {"line": n, "amountMinor": e["amountMinor"], "bankRef": e["bankRef"], "valueDate": e["valueDate"], "returned": e["returned"], "payment": None,
                "action": None, "state": "UNMATCHED", "detail": "no payment number found in the entry"}
        if len(hits) > 1:
            item.update(state="AMBIGUOUS", detail=f"the entry names {len(hits)} payments: {', '.join(h.number for h in hits)}")
        elif hits:
            pay = hits[0]
            action = "RETURNED" if e["returned"] else ("CREDITED" if e["direction"] == "D" else None)
            item.update(payment=pay.number, action=action)
            file = files.get(pay.run_ref)
            if action is None:
                item.update(state="IGNORED", detail="a credit that is not a return of a payment")
            elif e["amountMinor"] != pay.amount_minor:
                item.update(state="AMOUNT_MISMATCH", detail=f"bank {e['amountMinor']} vs payment {pay.amount_minor} (paise)")
            elif action == "CREDITED" and not e["bankRef"]:
                item.update(state="NO_REFERENCE", detail="the entry carries no bank reference (UTR)")
            elif file is None or file.status not in ("SENT", "ACKNOWLEDGED"):
                item.update(state="FILE_NOT_SENT", detail=f"the bank file of {pay.run_ref} is {file.status.lower() if file else 'missing'}: mark it sent first")
            elif pay.bank_status == action and (action == "RETURNED" or pay.bank_utr == e["bankRef"]):
                item.update(state="UNCHANGED", detail="already recorded")
            elif pay.bank_status in ("CREDITED", "RETURNED"):
                item.update(state="CONFLICT", detail=f"the payment is already {pay.bank_status.lower()}"
                            + (f" under UTR {pay.bank_utr}" if pay.bank_utr else ""))
            elif pay.status != "COMPLETED":
                item.update(state="CONFLICT", detail=f"the payment is {pay.status.lower()}")
            else:
                item.update(state="READY", detail="will be recorded", file=file.number, reason=e["reason"] if action == "RETURNED" else None)
        out.append(item)
    counts: dict[str, int] = {}
    for item in out:
        counts[item["state"]] = counts.get(item["state"], 0) + 1
    return {"statementId": statement["statementId"], "format": statement["format"], "account": statement["account"], "entries": len(out), "counts": counts,
            "items": out}


def _existing(session: Session, statement_id: str) -> Optional[BankStatementImport]:
    return session.execute(select(BankStatementImport).where(BankStatementImport.statement_id == statement_id)).scalar_one_or_none()


def run_import(session: Session, data: bytes, *, dry_run: bool) -> dict:
    statement = parse(data)
    sha = hashlib.sha256(data).hexdigest()
    prior = _existing(session, statement["statementId"])
    if prior is not None and prior.sha256 != sha:
        raise Problem(409, "STATEMENT_ID_REUSED", f"Statement {statement['statementId']} was imported with different content; a corrected statement needs a new id",
                      rule_ref="F7-09")
    analysis = analyse(session, statement)
    if dry_run:
        return {**analysis, "dryRun": True, "alreadyImported": prior is not None}
    if prior is not None:
        return {**prior.result, "replayed": True, "dryRun": False}
    ready = [i for i in analysis["items"] if i["state"] == "READY"]
    by_file: dict[str, list[dict]] = {}
    for item in ready:
        by_file.setdefault(item["file"], []).append({"payment": item["payment"], "status": item["action"], "utr": item["bankRef"], "reason": item["reason"]})
    for number, items in by_file.items():
        bank_files.record_bank_results(session, bank_files.by_number(session, number, lock=True), items)
    credited = sum(1 for i in ready if i["action"] == "CREDITED")
    returned = sum(1 for i in ready if i["action"] == "RETURNED")
    result = {**analysis, "dryRun": False, "applied": len(ready), "credited": credited, "returned": returned, "replayed": False}
    if ready or analysis["counts"].get("UNCHANGED"):
        p = principal(session)
        session.add(BankStatementImport(tenant_id=current_tenant(session), statement_id=statement["statementId"], format=statement["format"],
                                        account=statement["account"] or None, sha256=sha, entries=analysis["entries"], credited=credited, returned=returned,
                                        result=result, created_by=p.user_id))
        session.flush()
        audit.record(session, "BANK_STATEMENT", uuid.uuid5(uuid.NAMESPACE_URL, f"bank-statement:{current_tenant(session)}:{statement['statementId']}"),
                     "IMPORTED", object_ref=statement["statementId"], after={"format": statement["format"], "entries": analysis["entries"], "credited": credited,
                                                                          "returned": returned, "counts": analysis["counts"], "sha256": sha})
    return result


def listing(session: Session) -> list[dict]:
    return [{"statementId": r.statement_id, "format": r.format, "account": r.account, "entries": r.entries, "credited": r.credited, "returned": r.returned,
             "importedAt": r.created_at.isoformat()} for r in session.execute(select(BankStatementImport).order_by(BankStatementImport.created_at.desc()).limit(100)).scalars()]
