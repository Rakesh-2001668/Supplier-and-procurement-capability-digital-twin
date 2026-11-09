"""Mock SAP S/4HANA customizing (backend/data/erp_mock/SAP_CONFIG) and the checks the sandbox simulator applies to the request bodies the live
mapping builds (platform/sap_mapping.py) for OUTLINE_AGREEMENT, PAYMENT_REVERSAL and SCF_FINANCING.

The simulator runs the same mapping as the live connector and refuses, like SAP would, a body whose document type, reversal reason, FI
document type, business partner or payment method is not in the customizing, or that lacks a field the posting needs. The mandatory fields
are what SAP needs to create the document in a standard client; the client's own field status and screen layout can require more (confirm
in the sandbox, docs/PIC_SAP_Document_Types.md).

The customizing is client-wide (one mock SAP client serves every tenant). ``SIMULATOR_DEFAULTS.json`` holds the values the simulator uses
when a tenant's SAP rules leave one empty; a live connector rejects such a message instead.
"""
import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Optional

from app.pic.config import BACKEND_DIR

DIRECTORY = BACKEND_DIR / "data" / "erp_mock" / "SAP_CONFIG"


@dataclass(frozen=True)
class Customizing:
    document_types: dict = field(default_factory=dict)     # BSTYP (K, L, F, B) -> {BSART}
    reversal_reasons: dict = field(default_factory=dict)   # STGRD -> {"text", "alternativeDate": bool, "negative": bool}
    fi_document_types: frozenset = frozenset()             # BLART
    payment_methods: frozenset = frozenset()               # ZLSCH (country IN)
    financiers: dict = field(default_factory=dict)         # business partner -> {company codes}
    material_groups: frozenset = frozenset()               # MATKL
    defaults: dict = field(default_factory=dict)           # SIMULATOR_DEFAULTS.json


def _rows(name: str) -> list[dict]:
    path = DIRECTORY / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=1)
def load() -> Customizing:
    types: dict[str, set] = {}
    for row in _rows("T161.csv"):
        types.setdefault(row["BSTYP"], set()).add(row["BSART"])
    reasons = {row["STGRD"]: {"text": row["TXT40"], "alternativeDate": row["XABWD"] == "X", "negative": row["XNEGP"] == "X"}
               for row in _rows("T041C.csv")}
    financiers: dict[str, set] = {}
    for row in _rows("BP_FINANCIER.csv"):
        financiers.setdefault(row["PARTNER"], set()).add(row["BUKRS"])
    defaults_path = DIRECTORY / "SIMULATOR_DEFAULTS.json"
    defaults = json.loads(defaults_path.read_text(encoding="utf-8")) if defaults_path.exists() else {}
    return Customizing(document_types={k: frozenset(v) for k, v in types.items()}, reversal_reasons=reasons,
                       fi_document_types=frozenset(r["BLART"] for r in _rows("T003.csv")),
                       payment_methods=frozenset(r["ZLSCH"] for r in _rows("T042Z.csv") if r["LAND1"] == "IN"),
                       financiers={k: frozenset(v) for k, v in financiers.items()},
                       material_groups=frozenset(r["MATKL"] for r in _rows("T023.csv")), defaults=defaults)


def odata_day(value) -> Optional[date]:
    """The date of an OData v2 ``/Date(ms)/`` or v4 ISO value (None when absent or unreadable)."""
    if value in (None, ""):
        return None
    text = str(value)
    found = re.fullmatch(r"/Date\((-?\d+)\)/", text)
    if found:
        return datetime.fromtimestamp(int(found.group(1)) / 1000, tz=timezone.utc).date()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _missing(body: dict, fields: tuple, where: str) -> list[str]:
    return [f"{where}: {f} is missing" for f in fields if body.get(f) in (None, "")]


def _positive(value) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _items(value) -> list[dict]:
    if isinstance(value, dict):
        return list(value.get("results") or [])
    return list(value or [])


# ---------------------------------------------------------------- OUTLINE_AGREEMENT
def check_outline(plan, contract_type: Optional[str] = None, customizing: Optional[Customizing] = None) -> list[str]:
    """Problems of an outline-agreement plan (sap_mapping.OutlinePlan) against the customizing."""
    c = customizing or load()
    names, problems = plan.names, []
    allowed = c.document_types.get(names["category"], frozenset())
    if plan.doc_type not in allowed:
        problems.append(f"document type {plan.doc_type} is not a purchasing document type of category {names['category']} "
                        f"(allowed: {', '.join(sorted(allowed)) or 'none'})")
    if not plan.ops:
        return problems + ["nothing to send"]
    if plan.action == "CREATE":
        body = plan.ops[0].body
        problems += _missing(body, (names["type"], "CompanyCode", "PurchasingOrganization", "PurchasingGroup", "Supplier", "DocumentCurrency",
                                    "ValidityStartDate", "ValidityEndDate", "CorrespncExternalReference"), "header")
        if body.get(names["type"]) != plan.doc_type:
            problems.append(f"header: {names['type']} is {body.get(names['type'])}, expected {plan.doc_type}")
        start, end = odata_day(body.get("ValidityStartDate")), odata_day(body.get("ValidityEndDate"))
        if start and end and end < start:
            problems.append("header: ValidityEndDate is before ValidityStartDate")
        value_contract = names["category"] == "K" and contract_type not in (None, "QUANTITY_CONTRACT")
        if value_contract and not _positive(body.get("PurchaseContractTargetAmount")):
            problems.append(f"header: PurchaseContractTargetAmount is missing (a {plan.doc_type} value contract is consumed against it)")
        items = _items(body.get(names["items"]))
        if not items and not value_contract:
            problems.append(f"a {plan.doc_type} needs at least one item")
        for item in items:
            problems += _check_item(names, item, c, needs_qty=not value_contract)
    else:
        *item_ops, header = plan.ops
        if header.method != "PATCH" or not header.body.get("CorrespncExternalReference"):
            problems.append("the last write of a change must PATCH the header with the new CorrespncExternalReference")
        if plan.action == "CLOSE" and not header.body.get("ValidityEndDate"):
            problems.append("a close needs the ValidityEndDate")
        for op in item_ops:
            if op.method == "POST":
                problems += _check_item(names, op.body, c, needs_qty=True)
            elif not _positive(op.body.get("TargetQuantity")):
                problems.append(f"{op.path}: TargetQuantity is missing")
    return problems


def _check_item(names: dict, item: dict, c: Customizing, needs_qty: bool) -> list[str]:
    where = f"item {item.get(names['item'], '?')}"
    problems = _missing(item, (names["item"], names["text"], "OrderQuantityUnit", names["price"]), where)
    if not item.get("Material") and not item.get("MaterialGroup"):
        problems.append(f"{where}: a text item (no Material) needs a MaterialGroup")
    if item.get("MaterialGroup") and not item.get("Material") and c.material_groups and item["MaterialGroup"] not in c.material_groups:
        problems.append(f"{where}: material group {item['MaterialGroup']} is not in the customizing (T023)")
    if needs_qty and not _positive(item.get("TargetQuantity")):
        problems.append(f"{where}: TargetQuantity is missing")
    if names["category"] == "L" and not item.get("Plant"):
        problems.append(f"{where}: a scheduling agreement item needs a Plant")
    return problems


# ---------------------------------------------------------------- PAYMENT_REVERSAL
def check_reversal(body: dict, original_posting: Optional[date], customizing: Optional[Customizing] = None) -> list[str]:
    """Problems of a reversal body (sap_mapping.payment_reversal) against the reversal reasons (T041C)."""
    c = customizing or load()
    problems = _missing(body, ("CompanyCode", "AccountingDocument", "FiscalYear", "ReversalReason", "PostingDate", "DocumentHeaderText"), "reversal")
    reason = c.reversal_reasons.get(body.get("ReversalReason"))
    if body.get("ReversalReason") and reason is None:
        problems.append(f"reversal reason {body['ReversalReason']} is not in the customizing (T041C: {', '.join(sorted(c.reversal_reasons))})")
    elif reason is not None and not reason["alternativeDate"] and original_posting and odata_day(body.get("PostingDate")) != original_posting:
        problems.append(f"reversal reason {body['ReversalReason']} ({reason['text']}) does not allow an alternative posting date: post on "
                        f"{original_posting.isoformat()} or use a reason that allows one")
    if body.get("FiscalYear") and not re.fullmatch(r"\d{4}", str(body["FiscalYear"])):
        problems.append("reversal: FiscalYear must have four digits")
    return problems


# ---------------------------------------------------------------- SCF_FINANCING
def check_journal(body: dict, customizing: Optional[Customizing] = None) -> list[str]:
    """Problems of a supply-chain-finance journal entry (sap_mapping.scf_journal_entry): FI document type (T003), balanced lines, the
    financier's business partner (BP_FINANCIER, extended to the company code) and payment method (T042Z)."""
    c = customizing or load()
    problems = _missing(body, ("CompanyCode", "AccountingDocumentType", "PostingDate", "DocumentHeaderText", "TransactionCurrency"), "journal entry")
    if body.get("AccountingDocumentType") and body["AccountingDocumentType"] not in c.fi_document_types:
        problems.append(f"FI document type {body['AccountingDocumentType']} is not in the customizing (T003)")
    items = _items(body.get("to_Item"))
    if len(items) < 2:
        return problems + ["journal entry: needs a debit and a credit line"]
    totals = {"S": 0, "H": 0}
    for item in items:
        where = f"line {item.get('JournalEntryItem', '?')}"
        problems += _missing(item, ("PostingKey", "DebitCreditCode", "AmountInTransactionCurrency"), where)
        if not item.get("Supplier") and not item.get("GLAccount"):
            problems.append(f"{where}: needs a Supplier or a GLAccount")
        if item.get("DebitCreditCode") in totals:
            totals[item["DebitCreditCode"]] += round(float(item.get("AmountInTransactionCurrency") or 0) * 100)
        if item.get("PaymentMethod") and item["PaymentMethod"] not in c.payment_methods:
            problems.append(f"{where}: payment method {item['PaymentMethod']} is not in the customizing (T042Z)")
    if totals["S"] != totals["H"] or totals["S"] == 0:
        problems.append(f"journal entry is not balanced (debit {totals['S'] / 100:.2f}, credit {totals['H'] / 100:.2f})")
    credit = items[-1]
    if credit.get("Supplier"):
        companies = c.financiers.get(credit["Supplier"])
        if companies is None:
            problems.append(f"business partner {credit['Supplier']} is not a financier in the customizing (BP_FINANCIER)")
        elif body.get("CompanyCode") not in companies:
            problems.append(f"financier {credit['Supplier']} is not extended to company code {body.get('CompanyCode')}")
    return problems
