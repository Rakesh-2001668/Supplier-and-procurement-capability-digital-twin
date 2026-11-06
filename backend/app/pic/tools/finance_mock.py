"""MOCK finance datasets for the demo tenants AXN and KAC (ILLUSTRATIVE SAMPLE, not RBI / bank / IRP data).

    python -m app.pic.tools.finance_mock --write     # regenerate the bank statements in data/erp_mock/KAC_FINANCE from the payments in DATABASE_URL
    python -m app.pic.tools.finance_mock --check     # verify the committed files against MANIFEST.json (and against the database when it holds the pack)

One module holds the deterministic rules the dataset pack ``finance_ops`` (seed/datasets/finance_ops.py), the tests and the data README share, so a
second run gives the same bytes. Nothing is random: every "random" choice is a SHA-256 of a document number.

  FX series      INR per unit of USD, EUR, GBP, JPY, CNY on every weekday from 1 April to 31 October 2026. The level is anchored on the FBIL reference
                 rate of 28 October 2026 that data/reference/fx_reference_rates.csv carries for USD, EUR, GBP and JPY (CNY has no official anchor here
                 and is taken at USD / 7.25). For a weekday d, x = days from 28 October 2026:
                     rate(d) = anchor x raw(x) / raw(0) x (1 + noise(d))    for d up to the anchor day, rate(d) = anchor for 29-31 October
                     raw(x)  = 1 + 0.018 sin(2 pi x / 97 + phase) + 0.007 sin(2 pi x / 31 + 1.7 phase) + drift x
                 phase and drift are fixed per currency, noise is +-0.12 % from SHA-256(currency|date), and noise(28 October) = 0, so the series is
                 smooth, bounded (about +-3 % around the anchor) and passes through the official value on the anchor day. It is NOT market data.
  e-invoice      IRN = SHA-256(supplier GSTIN + financial year + document type + document number) in lower-case hex (the construction the
                 e-invoice schema and services/einvoice.py use); the signed QR is a JWT-shaped token (header.payload.signature) whose payload carries the
                 standard fields (SellerGstin, BuyerGstin, DocNo, DocTyp, DocDt dd/mm/yyyy, TotInvVal, ItemCnt, MainHsnCode, Irn, IrnDt). The
                 signature is a fixed MOCK string: the NIC signature cannot be produced here and PIC does not verify it locally either.
  bank statement camt.053.001.02 and MT940 files built from the payments of the pack: one entry per payment (debit, EndToEndId = payment number,
                 bank reference = a MOCK UTR), plus the deliberate lines listed in data/erp_mock/KAC_FINANCE/README.md.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import sys
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Optional

from app.pic.config import BACKEND_DIR

OUT_DIR = BACKEND_DIR / "data" / "erp_mock" / "KAC_FINANCE"
TAG = "MOCK sample data (finance_ops)"
FX_START, FX_END, FX_ANCHOR = date(2026, 4, 1), date(2026, 10, 31), date(2026, 10, 28)
FX_SOURCE = "MOCK series (finance_ops)"
# currency -> (anchor INR per unit, phase, drift per day). JPY is per 1 yen (the FBIL page quotes it per 100 yen).
FX_ANCHORS = {"USD": (Decimal("95.2278"), 0.4, 0.00004), "EUR": (Decimal("105.8641"), 1.9, -0.00003), "GBP": (Decimal("126.4657"), 3.1, 0.00002),
              "JPY": (Decimal("0.603100"), 4.4, -0.00005), "CNY": (Decimal("95.2278") / Decimal("7.25"), 5.2, 0.00001)}


def unit(*parts) -> float:
    """A repeatable number in [0, 1) from the parts (SHA-256), the only source of 'randomness'."""
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:12], 16) / float(16 ** 12)


# ---------------------------------------------------------------- FX series
def weekdays(first: date = FX_START, last: date = FX_END) -> list[date]:
    out, day = [], first
    while day <= last:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def _raw(code: str, x: int) -> float:
    _, phase, drift = FX_ANCHORS[code]
    return 1 + 0.018 * math.sin(2 * math.pi * x / 97 + phase) + 0.007 * math.sin(2 * math.pi * x / 31 + 1.7 * phase) + drift * x


def fx_rate(code: str, day: date, anchors: Optional[dict] = None) -> Decimal:
    """INR per unit of ``code`` on ``day`` (8 decimals). ``anchors`` overrides the anchor level (the reference file's FBIL values)."""
    anchor = (anchors or {}).get(code) or FX_ANCHORS[code][0]
    x = (day - FX_ANCHOR).days
    if x > 0:
        return Decimal(anchor).quantize(Decimal("0.00000001"), ROUND_HALF_UP)       # flat after the FBIL anchor day: later documents keep the official value
    noise = 0.0 if x == 0 else (unit("fx", code, day.isoformat()) - 0.5) * 0.0024
    value = Decimal(anchor) * Decimal(repr(_raw(code, x) / _raw(code, 0) * (1 + noise)))
    return value.quantize(Decimal("0.00000001"), ROUND_HALF_UP)


def fx_series(anchors: Optional[dict] = None) -> list[tuple[str, date, Decimal]]:
    """[(currency, valid_from, INR per unit)] for every weekday and currency; the anchor day carries the exact anchor."""
    out = []
    for code in FX_ANCHORS:
        for day in weekdays():
            out.append((code, day, fx_rate(code, day, anchors)))
    return out


# ---------------------------------------------------------------- e-invoice IRN and signed QR
def irn_of(gstin: str, fiscal_year: str, doc_type: str, doc_no: str) -> str:
    return hashlib.sha256(f"{gstin}{fiscal_year}{doc_type}{doc_no}".encode()).hexdigest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def signed_qr(*, irn: str, seller_gstin: str, buyer_gstin: str, doc_no: str, doc_date: date, total_minor: int, hsn: str = "", items: int = 1,
              doc_type: str = "INV") -> str:
    """A JWT-shaped signed QR token with the standard e-invoice QR fields; the signature segment is a fixed MOCK string."""
    data = {"SellerGstin": seller_gstin, "BuyerGstin": buyer_gstin, "DocNo": doc_no, "DocTyp": doc_type, "DocDt": doc_date.strftime("%d/%m/%Y"),
            "TotInvVal": float((Decimal(total_minor) / 100).quantize(Decimal("0.01"))), "ItemCnt": items, "MainHsnCode": hsn, "Irn": irn,
            "IrnDt": doc_date.isoformat() + " 09:30:00"}
    header = {"alg": "RS256", "typ": "JWT", "kid": "MOCK-NIC-KEY-1"}
    payload = {"iss": "MOCK-NIC (finance_ops)", "data": json.dumps(data, separators=(",", ":"))}
    signature = _b64(hashlib.sha256(("MOCK-SIGNATURE|" + irn).encode()).digest())
    return ".".join([_b64(json.dumps(header, separators=(",", ":")).encode()), _b64(json.dumps(payload, separators=(",", ":")).encode()), signature])


# ---------------------------------------------------------------- bank statements
def _amount(minor: int) -> str:
    return f"{Decimal(minor) / 100:.2f}"


def _mt_amount(minor: int) -> str:
    return _amount(minor).replace(".", ",")


def utr(bank: str, day: date, n: int) -> str:
    """A MOCK bank reference / UTR: bank code + yymmdd + running number (never a real bank's format guarantee)."""
    return f"MOCK{bank}{day.strftime('%y%m%d')}{n:05d}"


def camt053(*, statement_id: str, account: str, bank: str, day: date, opening_minor: int, entries: list[dict]) -> str:
    """camt.053.001.02 for one day. An entry: {amountMinor, direction DBIT|CRDT, payment (EndToEndId or None), text, bankRef, returned, reason, rsn}."""
    debit = sum(e["amountMinor"] for e in entries if e["direction"] == "DBIT")
    credit = sum(e["amountMinor"] for e in entries if e["direction"] == "CRDT")
    closing = opening_minor - debit + credit
    iso = day.isoformat()
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">', "  <BkToCstmrStmt>",
             f"    <GrpHdr><MsgId>MSG-{statement_id}</MsgId><CreDtTm>{iso}T20:00:00+05:30</CreDtTm></GrpHdr>", "    <Stmt>",
             f"      <Id>{statement_id}</Id>", "      <ElctrncSeqNb>1</ElctrncSeqNb>",
             f"      <Acct><Id><Othr><Id>{account}</Id></Othr></Id><Ccy>INR</Ccy><Ownr><Nm>{TAG}</Nm></Ownr></Acct>",
             f'      <Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="INR">{_amount(opening_minor)}</Amt><CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>{iso}</Dt></Dt></Bal>']
    for e in entries:
        lines += ["      <Ntry>", f'        <Amt Ccy="INR">{_amount(e["amountMinor"])}</Amt>', f'        <CdtDbtInd>{e["direction"]}</CdtDbtInd>']
        if e.get("returned"):
            lines.append("        <RvslInd>true</RvslInd>")
        lines += ["        <Sts>BOOK</Sts>", f"        <BookgDt><Dt>{e.get('date', iso)}</Dt></BookgDt>", f"        <ValDt><Dt>{e.get('date', iso)}</Dt></ValDt>",
                  f"        <AcctSvcrRef>{e['bankRef']}</AcctSvcrRef>", "        <NtryDtls><TxDtls>"]
        if e.get("payment"):
            lines.append(f"          <Refs><EndToEndId>{e['payment']}</EndToEndId></Refs>")
        if e.get("returned"):
            lines.append(f"          <RtrInf><Rsn><Cd>{e.get('rsn', 'AC04')}</Cd></Rsn><AddtlInf>{e['reason']}</AddtlInf></RtrInf>")
        lines += [f"          <RmtInf><Ustrd>{e['text']}</Ustrd></RmtInf>", "        </TxDtls></NtryDtls>", "      </Ntry>"]
    lines += [f'      <Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="INR">{_amount(closing)}</Amt><CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>{iso}</Dt></Dt></Bal>',
              "    </Stmt>", "  </BkToCstmrStmt>", "</Document>", ""]
    return "\n".join(lines)


def mt940(*, statement_id: str, account: str, day: date, sequence: str, opening_minor: int, entries: list[dict]) -> str:
    """MT940 for one day (one :61:/:86: pair per entry; the payment number is the customer reference, the bank reference follows //)."""
    debit = sum(e["amountMinor"] for e in entries if e["direction"] == "DBIT")
    credit = sum(e["amountMinor"] for e in entries if e["direction"] == "CRDT")
    closing = opening_minor - debit + credit
    short = day.strftime("%y%m%d")
    out = [f":20:{statement_id}", f":25:{account}", f":28C:{sequence}", f":60F:C{short}INR{_mt_amount(opening_minor)}"]
    for e in entries:
        mark = ("RD" if e.get("returned") else "D") if e["direction"] == "DBIT" else ("RC" if e.get("returned") else "C")
        entry_day = date.fromisoformat(e.get("date", day.isoformat()))
        reference = e.get("payment") or "NONREF"
        code = "RTN" if e.get("returned") else "TRF"
        out.append(f":61:{entry_day.strftime('%y%m%d')}{entry_day.strftime('%m%d')}{mark}{_mt_amount(e['amountMinor'])}N{code}{reference}//{e['bankRef']}")
        out.append(f":86:{e['text']}" if not e.get("returned") else f":86:RETURN {e.get('rsn', 'AC04')} {e['reason']} {reference}")
    out += [f":62F:{'C' if closing >= 0 else 'D'}{short}INR{_mt_amount(abs(closing))}", ""]
    return "\r\n".join(out)


def statement_plan(payments: list[dict], *, fmt: str) -> list[dict]:
    """Entries for one payment file from its payments ([{number, amountMinor, valueDate, supplier, utr}]): one debit per payment."""
    return [{"amountMinor": p["amountMinor"], "direction": "DBIT", "payment": p["number"], "text": f"{p['number']} {p['supplier']} {TAG}",
             "bankRef": p["utr"], "date": p["valueDate"]} for p in payments]


# ---------------------------------------------------------------- manifest
def normalise(text: str) -> str:
    """The statement with its payment numbers replaced by their order of appearance (PAY-880016 -> P001): the numbers depend on how many payments the
    tenant had already numbered in the database the file was generated from; everything else (amounts, dates, references, structure) is fixed by the pack."""
    import re
    seen: dict[str, str] = {}
    return re.sub(r"PAY-\d+", lambda m: seen.setdefault(m.group(0), f"P{len(seen) + 1:03d}"), text)


def plan_sha(plan: dict) -> str:
    """Fingerprint of the cases the pack planned (purchase orders, suppliers, invoice numbers and dates): equal fingerprints mean equal statements."""
    rows = [(s["id"], s["po"], s["supplier"], s["inv_no"], s["inv"], s.get("run")) for s in plan.get("scenarios", [])] + [sorted(plan.get("runs", {}).items())]
    return hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()



def manifest_for(files: dict[str, str], extra: Optional[dict] = None) -> dict:
    return {"label": TAG, "fictional": True, "client": "Kaveri Auto Components Pvt Ltd", "currency": "INR",
            "files": {name: {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "bytes": len(text.encode("utf-8"))} for name, text in sorted(files.items())},
            **(extra or {})}


def write_files(files: dict[str, str], extra: Optional[dict] = None, out_dir: Path = OUT_DIR) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (out_dir / name).write_text(text, encoding="utf-8", newline="")
    manifest = manifest_for(files, extra)
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def verify_files(out_dir: Path = OUT_DIR) -> list[str]:
    """Problems between the committed files and MANIFEST.json (empty = the files are exactly what the manifest says)."""
    path = out_dir / "MANIFEST.json"
    if not path.exists():
        return [f"{path} does not exist"]
    manifest = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    for name, meta in manifest.get("files", {}).items():
        file = out_dir / name
        if not file.exists():
            problems.append(f"{name} is listed in the manifest but missing")
        else:
            raw = file.read_bytes()
            if hashlib.sha256(raw).hexdigest() == meta["sha256"]:
                continue
            # SWIFT MT940 (.sta) requires CRLF; if git checkout converted to LF on Linux, test CRLF bytes
            if name.endswith(".sta") and hashlib.sha256(raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")).hexdigest() == meta["sha256"]:
                continue
            problems.append(f"{name} differs from its manifest hash")
    return problems


def statements_from_database(tenant_code: str = "KAC") -> tuple[dict[str, str], dict]:
    """Rebuild the statement files from the pack's own payments in DATABASE_URL (the pack keeps their specification in its dataset_load summary)."""
    from sqlalchemy import select

    from app.pic.db import system_tx
    from app.pic.models import Tenant
    from app.pic.seed.datasets import finance_ops

    with system_tx() as s:
        tenant_id = s.execute(select(Tenant.id).where(Tenant.code == tenant_code)).scalar_one_or_none()
    if tenant_id is None:
        raise SystemExit(f"tenant {tenant_code} does not exist in this database")
    return finance_ops.rebuild_statement_files(tenant_id)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate or verify the MOCK bank statements of tenant KAC (data/erp_mock/KAC_FINANCE).")
    parser.add_argument("--write", action="store_true", help="rebuild the statement files and MANIFEST.json from the pack's payments in DATABASE_URL")
    parser.add_argument("--check", action="store_true", help="verify the files against MANIFEST.json and, when DATABASE_URL holds the pack, against the database")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not (args.write or args.check):
        parser.print_help()
        return 0
    if args.write:
        import app.pic.services  # noqa: F401
        files, extra = statements_from_database()
        manifest = write_files(files, extra, args.out)
        print(f"wrote {len(files)} statement file(s) to {args.out}: " + ", ".join(sorted(files)))
        return 0 if not manifest.get("problems") else 1
    problems = verify_files(args.out)
    if os.environ.get("DATABASE_URL"):
        import app.pic.services  # noqa: F401
        try:
            files, extra = statements_from_database()
        except Exception as exc:  # noqa: BLE001 - the database may not hold the pack: the manifest check above still stands
            print(f"database comparison skipped: {type(exc).__name__}: {exc}")
        else:
            on_disk = {p.name: p.read_bytes().decode("utf-8") for p in args.out.glob("*") if p.name != "MANIFEST.json" and p.suffix in (".xml", ".sta")}
            manifest = json.loads((args.out / "MANIFEST.json").read_text(encoding="utf-8"))
            if extra.get("planSha256") != manifest.get("planSha256"):
                print("database comparison skipped: this database planned different cases than the ones the files were generated from")
            else:
                for name, text in files.items():
                    if normalise(on_disk.get(name, "")) != normalise(text):
                        problems.append(f"{name} differs from what the generator builds from the database")
    for p in problems:
        print("MISMATCH:", p)
    print("OK" if not problems else "CHECK FAILED")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
