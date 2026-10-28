"""M10 bank payment files (F7-07): ISO 20022 pain.001.001.03 credit transfers or a NEFT bulk CSV for a payment run.

- The debtor (paying) account comes from the PAYMENT-FILE rule set (debtorName, debtorAccountRef, debtorIfsc), configured
  per tenant / company code through POST /v1/admin/rules. Until it is configured generation answers 409.
- Creditor accounts are decrypted from supplier_bank_account only while the file is built. The file content is stored
  field-encrypted (purpose "payment_file"); the SHA-256 is of the plain file the bank receives. Account numbers never
  appear in audit events, events or logs.
- Banks identify Indian accounts by IFSC: agents are given as ClrSysMmbId with clearing system INFSC.
- Delivery to the bank is manual (download, upload in the bank portal, then mark SENT / ACKNOWLEDGED / REJECTED) until a
  host-to-host connector exists. ``bank_connector()`` reports the optional SFTP adapter (PIC_BANK_SFTP_HOST, _USER, _KEY_PATH,
  _DIR) and ``transmit`` answers "not configured" without it.
"""
import csv
import hashlib
import io
import os
import xml.etree.ElementTree as ET
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pic.db import current_tenant
from app.pic.models import CompanyCode, Invoice, Payment, PaymentFile, Supplier, SupplierBankAccount
from app.pic.platform import audit, clock, crypto, outbox, rules
from app.pic.platform.core import StateMachine, next_number
from app.pic.platform.errors import Problem, not_found
from app.pic.platform.money import from_minor
from app.pic.services.common import principal

FORMATS = ("ISO20022_PAIN001", "NEFT_CSV")
PAIN_NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"
SM = StateMachine("PAYMENT_FILE", {
    ("GENERATED", "send"): "SENT",
    ("GENERATED", "reject"): "REJECTED",
    ("SENT", "acknowledge"): "ACKNOWLEDGED",
    ("SENT", "reject"): "REJECTED",
})
STATUS_COMMANDS = {"SENT": "send", "ACKNOWLEDGED": "acknowledge", "REJECTED": "reject"}


def _payments(session: Session, run_ref: str) -> list[tuple[Payment, Invoice]]:
    return session.execute(select(Payment, Invoice).join(Invoice, Invoice.id == Payment.invoice_id)
                           .where(Payment.run_ref == run_ref, Payment.status == "COMPLETED").order_by(Payment.number)).all()


def runs(session: Session) -> list[dict]:
    """Payment runs (payments grouped by run_ref) with the files generated for them."""
    out: dict[str, dict] = {}
    for payment, invoice in session.execute(select(Payment, Invoice).join(Invoice, Invoice.id == Payment.invoice_id)
                                            .order_by(Payment.created_at.desc())).all():
        run = out.setdefault(payment.run_ref, {"run": payment.run_ref, "valueDate": payment.value_date.isoformat(), "payments": 0,
                                               "totalMinor": 0, "companyCodes": set(), "files": []})
        run["payments"] += 1
        run["totalMinor"] += payment.amount_minor
        run["companyCodes"].add(invoice.company_code)
    for pf in session.execute(select(PaymentFile).order_by(PaymentFile.created_at)).scalars():
        if pf.run_ref in out:
            out[pf.run_ref]["files"].append({"number": pf.number, "format": pf.format, "status": pf.status})
    return [{**r, "companyCodes": sorted(r["companyCodes"])} for r in out.values()]


def _debtor(session: Session, company_code: str) -> tuple[dict, str]:
    rule = rules.resolve(session, "PAYMENT-FILE", company_code=company_code)
    body = rule.body
    missing = [k for k in ("debtorName", "debtorAccountRef", "debtorIfsc") if not body.get(k)]
    if missing:
        raise Problem(409, "PAYMENT_FILE_NOT_CONFIGURED",
                      f"Debtor bank details for company code {company_code} are not configured ({', '.join(missing)}). "
                      "Publish a PAYMENT-FILE rule version with debtorName, debtorAccountRef and debtorIfsc (POST /v1/admin/rules).",
                      rule_ref=rule.ref, missing=missing)
    return body, rule.ref


def _sub(parent: ET.Element, tag: str, text: Optional[str] = None, **attrs) -> ET.Element:
    element = ET.SubElement(parent, tag, attrs)
    if text is not None:
        element.text = text
    return element


def _agent(parent: ET.Element, tag: str, ifsc: str) -> None:
    clearing = _sub(_sub(_sub(parent, tag), "FinInstnId"), "ClrSysMmbId")
    _sub(_sub(clearing, "ClrSysId"), "Cd", "INFSC")
    _sub(clearing, "MmbId", ifsc)


def _amount(minor: int) -> str:
    return f"{from_minor(minor):.2f}"


def _transactions(session: Session, run_ref: str) -> list[dict]:
    tenant = current_tenant(session)
    items = []
    for payment, invoice in _payments(session, run_ref):
        account = session.get(SupplierBankAccount, payment.bank_account_id)
        supplier = session.get(Supplier, payment.supplier_id)
        items.append({"payment": payment.number, "invoice": invoice.number, "supplierInvoiceNo": invoice.supplier_invoice_no,
                      "companyCode": invoice.company_code, "valueDate": payment.value_date, "amountMinor": payment.amount_minor,
                      "currency": payment.currency, "creditor": (account.holder_name or supplier.legal_name)[:70], "ifsc": account.ifsc,
                      "account": crypto.decrypt(tenant, "bank", account.account_enc), "supplier": supplier.code})
    return items


def pain001(message_id: str, initiating_party: str, groups: list[tuple[dict, list[dict]]]) -> str:
    """pain.001.001.03: GrpHdr, then one PmtInf per company code and execution date with a CdtTrfTxInf per payment."""
    document = ET.Element("Document", {"xmlns": PAIN_NS})
    root = _sub(document, "CstmrCdtTrfInitn")
    every = [t for _, txs in groups for t in txs]
    header = _sub(root, "GrpHdr")
    _sub(header, "MsgId", message_id[:35])
    _sub(header, "CreDtTm", clock.now().astimezone(clock.IST).replace(microsecond=0).isoformat())
    _sub(header, "NbOfTxs", str(len(every)))
    _sub(header, "CtrlSum", _amount(sum(t["amountMinor"] for t in every)))
    _sub(_sub(header, "InitgPty"), "Nm", initiating_party[:70])
    for index, (debtor, txs) in enumerate(groups, start=1):
        info = _sub(root, "PmtInf")
        _sub(info, "PmtInfId", f"{message_id}-{index}"[:35])
        _sub(info, "PmtMtd", "TRF")
        _sub(info, "BtchBookg", "false")
        _sub(info, "NbOfTxs", str(len(txs)))
        _sub(info, "CtrlSum", _amount(sum(t["amountMinor"] for t in txs)))
        _sub(_sub(info, "PmtTpInf"), "InstrPrty", "NORM")
        _sub(info, "ReqdExctnDt", txs[0]["valueDate"].isoformat())
        _sub(_sub(info, "Dbtr"), "Nm", str(debtor["debtorName"])[:70])
        debtor_account = _sub(info, "DbtrAcct")
        _sub(_sub(_sub(debtor_account, "Id"), "Othr"), "Id", str(debtor["debtorAccountRef"])[:34])
        _sub(debtor_account, "Ccy", txs[0]["currency"])
        _agent(info, "DbtrAgt", str(debtor["debtorIfsc"]))
        _sub(info, "ChrgBr", "SLEV")
        for t in txs:
            tx = _sub(info, "CdtTrfTxInf")
            ids = _sub(tx, "PmtId")
            _sub(ids, "InstrId", t["payment"][:35])
            _sub(ids, "EndToEndId", t["payment"][:35])
            _sub(_sub(tx, "Amt"), "InstdAmt", _amount(t["amountMinor"]), Ccy=t["currency"])
            _agent(tx, "CdtrAgt", t["ifsc"])
            _sub(_sub(tx, "Cdtr"), "Nm", t["creditor"])
            _sub(_sub(_sub(_sub(tx, "CdtrAcct"), "Id"), "Othr"), "Id", t["account"][:34])
            _sub(_sub(tx, "RmtInf"), "Ustrd", f"{t['supplierInvoiceNo']} {t['payment']}"[:140])
    ET.indent(document)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(document, encoding="unicode") + "\n"


NEFT_HEADER = ["Transaction Type", "Debit Account", "Debit IFSC", "Beneficiary Name", "Beneficiary Account", "Beneficiary IFSC", "Amount",
               "Currency", "Value Date", "Customer Reference", "Remarks"]


def neft_csv(groups: list[tuple[dict, list[dict]]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(NEFT_HEADER)
    for debtor, txs in groups:
        for t in txs:
            writer.writerow(["NEFT", debtor["debtorAccountRef"], debtor["debtorIfsc"], t["creditor"], t["account"], t["ifsc"],
                             _amount(t["amountMinor"]), t["currency"], t["valueDate"].strftime("%d-%m-%Y"), t["payment"],
                             f"{t['supplierInvoiceNo']}"[:30]])
    return buffer.getvalue()


def generate(session: Session, run_ref: str, fmt: str) -> PaymentFile:
    fmt = fmt.upper()
    if fmt not in FORMATS:
        raise Problem(422, "INVALID_FORMAT", f"format must be one of {list(FORMATS)}")
    txs = _transactions(session, run_ref)
    if not txs:
        raise not_found("Payment run", run_ref)
    active = session.execute(select(PaymentFile).where(PaymentFile.run_ref == run_ref, PaymentFile.status != "REJECTED")).scalars().first()
    if active is not None:
        raise Problem(409, "PAYMENT_FILE_EXISTS", f"{active.number} ({active.format}, {active.status}) already carries run {run_ref}; "
                      "a run is sent to the bank once. Mark it REJECTED before generating a replacement.", rule_ref="F7-07",
                      paymentFile=active.number)
    grouped: dict[tuple[str, date], list[dict]] = {}
    for t in txs:
        grouped.setdefault((t["companyCode"], t["valueDate"]), []).append(t)
    groups, refs = [], []
    for (company_code, _), items in sorted(grouped.items()):
        debtor, ref = _debtor(session, company_code)
        groups.append((debtor, items))
        refs.append(ref)
    number = next_number(session, "PAYMENT_FILE")
    if fmt == "ISO20022_PAIN001":
        company = session.execute(select(CompanyCode).where(CompanyCode.code == txs[0]["companyCode"])).scalar_one_or_none()
        content = pain001(number, company.name if company else str(groups[0][0]["debtorName"]), groups)
        file_name = f"{number}_{run_ref}_pain001.xml"
    else:
        content = neft_csv(groups)
        file_name = f"{number}_{run_ref}_neft.csv"
    total = sum(t["amountMinor"] for t in txs)
    p = principal(session)
    pf = PaymentFile(tenant_id=current_tenant(session), number=number, run_ref=run_ref, format=fmt, file_name=file_name,
                     content=crypto.encrypt(current_tenant(session), "payment_file", content).decode(),
                     sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(), payments=len(txs), total_minor=total, status="GENERATED",
                     created_by=p.user_id)
    session.add(pf)
    session.flush()
    summary = {"run": run_ref, "format": fmt, "fileName": file_name, "payments": len(txs), "totalMinor": total, "sha256": pf.sha256,
               "paymentNumbers": [t["payment"] for t in txs]}
    audit.record(session, "PAYMENT_FILE", pf.id, "GENERATED", object_ref=number, after=summary, rule_set_version=";".join(dict.fromkeys(refs)))
    outbox.emit(session, "payment_file.generated", "PAYMENT_FILE", pf.id, number, summary)
    return pf


def by_number(session: Session, number: str, lock: bool = False) -> PaymentFile:
    query = select(PaymentFile).where(PaymentFile.number == number)
    pf = session.execute(query.with_for_update() if lock else query).scalar_one_or_none()
    if pf is None:
        raise not_found("Payment file", number)
    return pf


def content_of(session: Session, pf: PaymentFile) -> str:
    """Decrypted file for download; every read is audited (who, which file, hash), never the content."""
    content = crypto.decrypt(pf.tenant_id, "payment_file", pf.content.encode())
    audit.record(session, "PAYMENT_FILE", pf.id, "CONTENT_DOWNLOADED", object_ref=pf.number, after={"sha256": pf.sha256, "fileName": pf.file_name})
    return content


def set_status(session: Session, pf: PaymentFile, status: str, bank_ref: Optional[str] = None, reason: Optional[str] = None) -> PaymentFile:
    status = status.upper()
    command = STATUS_COMMANDS.get(status)
    if command is None:
        raise Problem(422, "INVALID_STATUS", f"status must be one of {sorted(STATUS_COMMANDS)}")
    if status == "ACKNOWLEDGED" and not (bank_ref or pf.bank_ref):
        raise Problem(422, "BANK_REF_REQUIRED", "Give the bank's acknowledgement reference (bankRef)")
    SM.apply(session, pf, command, reason=reason, extra_after={"bankRef": bank_ref})
    if bank_ref:
        pf.bank_ref = bank_ref
    if status == "SENT":
        pf.sent_at = clock.now()
    outbox.emit(session, f"payment_file.{status.lower()}", "PAYMENT_FILE", pf.id, pf.number,
                {"run": pf.run_ref, "status": status, "bankRef": pf.bank_ref, "totalMinor": pf.total_minor})
    return pf


def bank_connector() -> dict:
    host = os.environ.get("PIC_BANK_SFTP_HOST")
    if not host:
        return {"type": "SFTP", "configured": False,
                "detail": "Bank host-to-host (SFTP) is not configured; download the file, upload it in the bank portal and record the status here"}
    return {"type": "SFTP", "configured": False, "host": host,
            "detail": "PIC_BANK_SFTP_HOST is set but no SFTP client is installed in this build; transmit manually"}


def transmit(pf: PaymentFile) -> dict:
    connector = bank_connector()
    raise Problem(503, "BANK_CONNECTOR_NOT_CONFIGURED", connector["detail"], connector=connector)


def view(pf: PaymentFile) -> dict:
    return {"number": pf.number, "run": pf.run_ref, "format": pf.format, "fileName": pf.file_name, "sha256": pf.sha256, "payments": pf.payments,
            "totalMinor": pf.total_minor, "status": pf.status, "bankRef": pf.bank_ref, "sentAt": pf.sent_at.isoformat() if pf.sent_at else None,
            "createdAt": pf.created_at.isoformat(), "id": str(pf.id)}


def listing(session: Session) -> dict:
    files = session.execute(select(PaymentFile).order_by(PaymentFile.created_at.desc()).limit(200)).scalars().all()
    return {"items": [view(pf) for pf in files], "nextCursor": None, "bankConnector": bank_connector()}


