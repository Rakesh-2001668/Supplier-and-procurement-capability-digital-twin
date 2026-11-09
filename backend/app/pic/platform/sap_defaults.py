"""Rule bodies of the live SAP S/4HANA mapping of outline agreements, payment reversals and supply-chain-finance postings (seeded for every
tenant by seed/reference.py RULE_SETS; ``resolve`` falls back to these bodies for a tenant bootstrapped before they existed).

Every key is a tenant-editable, effective-dated rule set (P14) that can be scoped per company code (POST /v1/admin/rules). A stored body is
completed with the default's keys, so a version only needs the keys it changes. The values are SAP customizing of the client's system: they
must be confirmed in the client's sandbox before go-live (docs/PIC_SAP_Document_Types.md).

SAP-OUTLINE-AGREEMENT  PIC contract type -> SAP purchasing document type. The type decides the API: a type listed in ``contractTypes``
                       (document category K) goes to the purchase contract API, one listed in ``schedulingAgreementTypes`` (category L)
                       to the scheduling agreement API. ``notSent`` types are legal documents that never reach SAP (skipped, not an
                       error). Lines without a material are text items with a material group (``textItemMaterialGroup``) and account
                       assignment category ``textItemAccountAssignment``; ``serviceItemCategory`` (e.g. "D" lean service, "9" service with
                       service lines) is sent for them when the client uses service items. ``purchasingOrg`` / ``purchasingGroup`` empty
                       = the PIC purchasing-org master of the company code (live) or the mock customizing (simulator).
SAP-PAYMENT-REVERSAL   reversal of the clearing document of a payment the bank returned: reversal reason (SAP T041C) and posting date
                       (ORIGINAL = the payment's posting date, which reason 01 requires; RETURN_DATE = the day PIC recorded the return,
                       which needs a reason that allows an alternative posting date, e.g. 02). When the payment's posting period is closed
                       in PIC, ``closedPeriodReason`` is used with the return date.
SAP-SCF-FINANCING      journal entry that moves the payable from the supplier to the financier: FI document type, posting keys and, per
                       PIC financier code (rule EARLY-PAYMENT scf.financier), the financier's business partner (vendor line) or G/L
                       account. SAP has no standard API for this: the client designs it (clearing of the invoice, fees, withholding tax).
"""
import copy
from typing import Optional

from sqlalchemy.orm import Session

OUTLINE_KEY = "SAP-OUTLINE-AGREEMENT"
REVERSAL_KEY = "SAP-PAYMENT-REVERSAL"
SCF_KEY = "SAP-SCF-FINANCING"

CONTRACT_TYPES = ("SCHEDULING_AGREEMENT", "QUANTITY_CONTRACT", "VALUE_CONTRACT", "RATE_CARD", "SOW", "MASTER_AGREEMENT", "NDA")
CALL_OFF_TYPES = ("SCHEDULING_AGREEMENT", "QUANTITY_CONTRACT", "VALUE_CONTRACT", "RATE_CARD", "SOW")

OUTLINE_AGREEMENT = {
    "documentTypes": {"QUANTITY_CONTRACT": "MK", "VALUE_CONTRACT": "WK", "SCHEDULING_AGREEMENT": "LP", "RATE_CARD": "WK", "SOW": "WK"},
    "contractTypes": ["MK", "WK"],               # document category K: API_PURCHASECONTRACT_PROCESS_SRV
    "schedulingAgreementTypes": ["LP", "LPA"],   # document category L: API_SCHED_AGRMT_PROCESS_SRV
    "notSent": ["MASTER_AGREEMENT", "NDA"],      # legal documents: never sent to SAP
    "purchasingOrg": None,
    "purchasingGroup": None,
    "textItemMaterialGroup": None,               # material group of lines without a material (SAP needs one); required in live mode
    "textItemAccountAssignment": "U",            # U = unknown: the call-off order assigns the cost object
    "serviceItemCategory": None,                 # item category of text lines of serviceItems types (None = standard item)
    "serviceItems": ["RATE_CARD", "SOW"],
    "closeOnTermination": True,                  # a terminated contract gets its SAP validity end set to the last day in force
    "closeOnRenewal": True,                      # a renewed predecessor ends in SAP the day before its successor starts
}

PAYMENT_REVERSAL = {
    "reversalReason": "01",                      # SAP standard: reversal in current period (no alternative posting date)
    "postingDate": "ORIGINAL",                   # ORIGINAL | RETURN_DATE
    "closedPeriodReason": "02",                  # SAP standard: reversal in closed period (alternative posting date allowed); None = never
    "resetClearing": True,                       # reset the cleared items before the reversal (FBRA); False = the client's service decides
}

SCF_FINANCING = {
    "documentType": "KA",                        # FI document type of the reclassification (vendor document)
    "postingKeys": {"supplierDebit": "21", "financierCredit": "31", "glCredit": "50"},
    "financiers": {},                            # PIC financier code -> {"businessPartner": "...", "glAccount": None, "paymentMethod": "R"}
}

BODIES = {
    OUTLINE_KEY: (OUTLINE_AGREEMENT, "SAP S/4HANA outline agreements: PIC contract type -> SAP document type (MK, WK, LP), legal documents not "
                                     "sent, purchasing org / group and text items; confirm in the client's sandbox"),
    REVERSAL_KEY: (PAYMENT_REVERSAL, "SAP S/4HANA reversal of a returned payment's clearing document: reversal reason and posting date"),
    SCF_KEY: (SCF_FINANCING, "SAP S/4HANA supply-chain-finance journal entry: document type, posting keys and the financier's business partner "
                             "or G/L account per PIC financier code (no standard SAP API: the client designs it)"),
}
DEFAULTS = {key: body for key, (body, _) in BODIES.items()}


class Config:
    """A resolved SAP rule: the stored body completed with the default's keys, and the version reference for the audit trail."""

    def __init__(self, key: str, ref: str, body: dict):
        self.key, self.ref, self.body = key, ref, body

    def __getitem__(self, item: str):
        return self.body[item]

    def get(self, item: str, default=None):
        return self.body.get(item, default)


def resolve(session: Session, key: str, company_code: Optional[str] = None) -> Config:
    """The effective rule of the company code (or the tenant), else the documented default."""
    from app.pic.platform import rules
    from app.pic.platform.errors import Problem
    try:
        found = rules.resolve(session, key, company_code=company_code)
        return Config(key, found.ref, {**copy.deepcopy(DEFAULTS[key]), **(found.body or {})})
    except Problem as exc:
        if exc.code != "RULE_SET_MISSING":
            raise
        return Config(key, f"{key}@code-default", copy.deepcopy(DEFAULTS[key]))


# ---------------------------------------------------------------- outline agreement helpers
def api_of(config: Config, contract_type: str) -> Optional[str]:
    """CONTRACT or SCHEDULING_AGREEMENT: the API a PIC contract type is sent to, or None when the type is not sent."""
    doc_type = (config.get("documentTypes") or {}).get(contract_type)
    if contract_type in (config.get("notSent") or []) or not doc_type:
        return None
    if doc_type in (config.get("schedulingAgreementTypes") or []):
        return "SCHEDULING_AGREEMENT"
    if doc_type in (config.get("contractTypes") or []):
        return "CONTRACT"
    return None


def skip_reason(config: Config, contract_type: str) -> Optional[str]:
    """Why a contract of this type is not sent to SAP (a legal document, or no document type configured), else None."""
    if contract_type in (config.get("notSent") or []):
        return f"{contract_type} is a legal document that is not sent to SAP (rule {config.ref} notSent)"
    if not (config.get("documentTypes") or {}).get(contract_type):
        return f"no SAP document type for {contract_type} in rule {config.ref} documentTypes"
    return None


# ---------------------------------------------------------------- validation (POST /v1/admin/rules)
def _code(value, length: int) -> bool:
    return isinstance(value, str) and 0 < len(value.strip()) <= length and value == value.strip()


def _bool(errors: list[str], body: dict, *keys: str) -> None:
    for k in keys:
        if k in body and not isinstance(body[k], bool):
            errors.append(f"{k} must be true or false")


def _optional_code(errors: list[str], body: dict, key: str, length: int) -> None:
    if body.get(key) is not None and not _code(body[key], length):
        errors.append(f"{key} must be an SAP code of at most {length} characters, or null")


def validate(key: str, body: dict) -> list[str]:
    """Problems of a new version of an SAP mapping rule (empty when usable). Other keys are not checked here."""
    if key not in DEFAULTS:
        return []
    if not isinstance(body, dict):
        return ["the body must be an object"]
    errors: list[str] = []
    unknown = sorted(set(body) - set(DEFAULTS[key]))
    if unknown:
        errors.append(f"unknown key(s) {', '.join(unknown)}; allowed: {', '.join(sorted(DEFAULTS[key]))}")
    merged = {**DEFAULTS[key], **body}
    if key == OUTLINE_KEY:
        errors += _validate_outline(merged)
    elif key == REVERSAL_KEY:
        errors += _validate_reversal(merged)
    else:
        errors += _validate_scf(merged)
    return errors


def _validate_outline(body: dict) -> list[str]:
    errors: list[str] = []
    lists = {}
    for k in ("contractTypes", "schedulingAgreementTypes"):
        values = body.get(k)
        if not isinstance(values, list) or not all(_code(v, 4) for v in values):
            errors.append(f"{k} must be a list of SAP document types (at most 4 characters each)")
            values = []
        lists[k] = set(values)
    if lists["contractTypes"] & lists["schedulingAgreementTypes"]:
        errors.append(f"document type(s) {', '.join(sorted(lists['contractTypes'] & lists['schedulingAgreementTypes']))} cannot be both a "
                      "contract type and a scheduling agreement type")
    not_sent = body.get("notSent")
    if not isinstance(not_sent, list) or any(t not in CONTRACT_TYPES for t in not_sent):
        errors.append(f"notSent must be a list of PIC contract types ({', '.join(CONTRACT_TYPES)})")
        not_sent = []
    types = body.get("documentTypes")
    if not isinstance(types, dict):
        errors.append("documentTypes must map PIC contract types to SAP document types")
        types = {}
    for pic_type, sap_type in types.items():
        if pic_type not in CONTRACT_TYPES:
            errors.append(f"documentTypes: {pic_type} is not a PIC contract type")
        elif pic_type in not_sent:
            errors.append(f"documentTypes: {pic_type} is listed in notSent; remove one of the two")
        elif not _code(sap_type, 4):
            errors.append(f"documentTypes.{pic_type} must be an SAP document type (at most 4 characters)")
        elif pic_type == "SCHEDULING_AGREEMENT" and sap_type not in lists["schedulingAgreementTypes"]:
            errors.append(f"documentTypes.SCHEDULING_AGREEMENT is {sap_type}, which is not in schedulingAgreementTypes")
        elif pic_type != "SCHEDULING_AGREEMENT" and sap_type not in lists["contractTypes"]:
            errors.append(f"documentTypes.{pic_type} is {sap_type}, which is not in contractTypes (a {pic_type} is a purchase contract)")
    missing = [t for t in CALL_OFF_TYPES if t not in types and t not in not_sent]
    if missing:
        errors.append(f"documentTypes has no SAP document type for {', '.join(missing)} (map it or list it in notSent)")
    service_items = body.get("serviceItems")
    if not isinstance(service_items, list) or any(t not in CALL_OFF_TYPES for t in service_items):
        errors.append(f"serviceItems must be a list of PIC call-off contract types ({', '.join(CALL_OFF_TYPES)})")
    _optional_code(errors, body, "purchasingOrg", 4)
    _optional_code(errors, body, "purchasingGroup", 3)
    _optional_code(errors, body, "textItemMaterialGroup", 9)
    _optional_code(errors, body, "textItemAccountAssignment", 1)
    _optional_code(errors, body, "serviceItemCategory", 1)
    _bool(errors, body, "closeOnTermination", "closeOnRenewal")
    return errors


def _validate_reversal(body: dict) -> list[str]:
    errors: list[str] = []
    if not _code(body.get("reversalReason"), 2):
        errors.append("reversalReason must be an SAP reversal reason (2 characters, e.g. 01)")
    if body.get("postingDate") not in ("ORIGINAL", "RETURN_DATE"):
        errors.append("postingDate must be ORIGINAL or RETURN_DATE")
    _optional_code(errors, body, "closedPeriodReason", 2)
    _bool(errors, body, "resetClearing")
    return errors


def _validate_scf(body: dict) -> list[str]:
    errors: list[str] = []
    if not _code(body.get("documentType"), 2):
        errors.append("documentType must be an SAP FI document type (2 characters, e.g. KA)")
    keys = body.get("postingKeys")
    if not isinstance(keys, dict) or set(keys) != {"supplierDebit", "financierCredit", "glCredit"} or not all(
            isinstance(v, str) and len(v) == 2 and v.isdigit() for v in keys.values()):
        errors.append("postingKeys must give supplierDebit, financierCredit and glCredit as two-digit SAP posting keys")
    financiers = body.get("financiers")
    if not isinstance(financiers, dict):
        return errors + ["financiers must map PIC financier codes to {businessPartner | glAccount, paymentMethod}"]
    for code, entry in financiers.items():
        if not isinstance(entry, dict):
            errors.append(f"financiers.{code} must be an object")
            continue
        extra = sorted(set(entry) - {"businessPartner", "glAccount", "paymentMethod", "name"})
        if extra:
            errors.append(f"financiers.{code}: unknown key(s) {', '.join(extra)}")
        bp, gl = entry.get("businessPartner"), entry.get("glAccount")
        if bool(bp) == bool(gl):
            errors.append(f"financiers.{code} needs exactly one of businessPartner (credit the financier as a vendor) or glAccount")
        if bp and not _code(bp, 10):
            errors.append(f"financiers.{code}.businessPartner must be an SAP business partner number (at most 10 characters)")
        if gl and not _code(gl, 10):
            errors.append(f"financiers.{code}.glAccount must be an SAP G/L account (at most 10 characters)")
        if entry.get("paymentMethod") is not None and not _code(entry["paymentMethod"], 1):
            errors.append(f"financiers.{code}.paymentMethod must be one SAP payment method character, or null")
    return errors
