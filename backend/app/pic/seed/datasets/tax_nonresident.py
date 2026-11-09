"""D23 Section 195 TDS for non-resident suppliers, partial payments and Form 16A information copies (AXN, October 2027). MOCK, ILLUSTRATIVE SAMPLE.

Every name, number and rate below is fictional: the suppliers do not exist, the PAN / TRC / Form 10F / Form 15CA / 15CB numbers are made up, the
exchange rates are MOCK levels and the treaty (DTAA) rates come from the MOCK table of rule TDS-195, which the client's chartered accountant must
confirm (docs/PIC_Tax_Partial_Payments.md). Documents are built THROUGH THE REAL SERVICES (receiving, payables, nonresident_tax, bank_files,
tds_returns) with the business clock pinned to each step, so posting, the s.195 determination, SoD, the Form 15CA checkpoint, ERP messages, bank
files and returns behave as in production.

  masters    four non-resident vendors and one resident engineering firm, their verified bank accounts (SWIFT for the foreign ones), one open
             purchase order each (two for the German and the resident vendor), loaded like the ERP cutover loads open orders; MOCK FX rates
             EUR / USD / SGD -> INR on 1 and 15 October 2027; the tax residency of each vendor; a MOCK deductor TAN / PAN (rule TDS)
  NRDE01     Rheinmark Werkzeugtechnik GmbH (DE, EUR, fees for technical services): TRC and Form 10F valid -> treaty rate 10 % (DTAA) instead of
             the Act rate 20.8 %. Invoice 1 paid on 12 October with Form 15CA part C + 15CB; invoice 2 BLOCKED: no Form 15CA recorded
  NRUS01     Cascade Ridge Software Inc (US, USD, royalty): TRC valid but Form 10F expired on 31 March 2027 -> Act rate 20.8 %. Named in the
             12 October run without Form 15CA: the run is refused (409 FORM_15CA_REQUIRED); Form 15CA + 15CB recorded on 18 October; paid on 19 October
  NRSG01     Merlion Process Engineering Pte Ltd (SG, SGD, fees for technical services): no PAN and no tax identification number -> s.206AA
             (higher of 20 % and the Act rate), no treaty relief; paid on 12 October
  NRAE01     Gulf Crest Technical Consultancy FZE (AE, USD, fees for technical services): the India-UAE treaty (MOCK) has no FTS article -> Act
             rate; s.195A gross-up: the company bears the tax, the supplier receives the full invoice; paid on 12 October
  RVES01     Kaveri Valley Engineering Services Pvt Ltd (resident, MSME small, s.194J technical services 2 %):
             invoice 1 paid in three parts (12, 19 and 26 October; TDS deducted in full with the first part);
             invoice 2 paid in two parts (12 and 19 October), the bank returns the first part on 21 October (that amount and its TDS reopen),
             the rest is paid on 26 October
  challans   the TDS of October deposited on 6 November 2027 (one challan per section: 26Q and 27Q), so the Q3 2027-28 reconciliation and the
             Form 16A data (and its PDF information copy) are complete

Nothing of the signature case or of another pack is changed; every object is looked up by its business key and the pack is idempotent per step.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select

from app.pic.db import tenant_tx
from app.pic.models import (
    AuditEvent, Currency, FxRate, GoodsReceipt, Invoice, Payment, PaymentFile, PoLine, PoScheduleLine, PurchaseOrder, RemittanceCertificate, RuleSet,
    Supplier, SupplierBankAccount, SupplierCategoryStatus, TdsChallan,
)
from app.pic.platform import audit, clock, crypto, rules, workflow
from app.pic.platform.core import next_number
from app.pic.platform.errors import Problem
from app.pic.seed.axion import SIGNATURE_KEY, SIGNATURE_VERSION, Scenario, at
from app.pic.seed.datasets import _tenant_kit as kit

KEY = "tax-nonresident"
VERSION = "1"
TITLE = ("D23 section 195 TDS for non-resident suppliers, partial payments and Form 16A information copies (AXN, October 2027) "
         "(MOCK, ILLUSTRATIVE SAMPLE)")
TENANTS = ("AXN",)
CREATES_TENANT = False
READY = True
REQUIRES = {SIGNATURE_KEY: SIGNATURE_VERSION}

LABEL = "MOCK, ILLUSTRATIVE SAMPLE (tax_nonresident)"
ACTOR = "mock-data:tax_nonresident"
COMPANY, PLANT = "1000", "P100"
ADMIN, RECEIVER, AP, APPROVER, TREASURY, SUPPLIER_MANAGER = "admin", "receiver", "ap.clerk", "finance.controller", "finance.controller2", "supplier.manager"
FY, QUARTER = "2027-28", "Q3"
D = date


# ------------------------------------------------------------------------------------------------ specs
@dataclass
class Vendor:
    code: str
    name: str
    country: str
    currency: str
    terms: str
    address: dict
    bank: dict                                     # account, ifsc / swift, charge bearer, purpose code
    residency: dict                                # nonresident_tax.set_residency keyword arguments (without supplier / reason)
    gstin: Optional[str] = None
    tds_section: Optional[str] = None
    msme: Optional[tuple] = None                   # (class, Udyam number)
    orders: list = field(default_factory=list)     # [(erp document, [(description, sac, qty, unit price, gst rate)])]


VENDORS = [
    Vendor("NRDE01", "Rheinmark Werkzeugtechnik GmbH (fictional)", "DE", "EUR", "N30",
           {"line1": "Industriestrasse 14 (MOCK)", "city": "Remscheid", "postalCode": "42853", "country": "DE"},
           {"account": "DE89370400440532013000", "swift": "MOCKDEFFXXX", "bearer": "SHAR", "purpose": "S1007"},
           {"residency": "NON_RESIDENT", "country": "DE", "payee_type": "COMPANY", "pan": "AADCR4410F", "tax_id": "DE812345678",
            "trc_no": "TRC-DE-2027-004417", "trc_valid_from": D(2027, 1, 1), "trc_valid_to": D(2027, 12, 31), "trc_document_ref": "MOCK/TRC/NRDE01-2027.pdf",
            "form10f_ack": "10F-2027-DE-118804", "form10f_filed_on": D(2027, 4, 20), "form10f_valid_from": D(2027, 4, 1), "form10f_valid_to": D(2028, 3, 31),
            "no_pe_declared": True, "no_pe_valid_from": D(2027, 4, 1), "no_pe_valid_to": D(2028, 3, 31), "default_nature": "FTS"},
           orders=[("4502390001", [("Die design and try-out engineering, DC-340 housing die", "998331", 1, "8400.00", 18)]),
                   ("4502390002", [("Die design review and simulation, DC-341 cover die", "998331", 1, "6500.00", 18)])]),
    Vendor("NRUS01", "Cascade Ridge Software Inc (fictional)", "US", "USD", "N30",
           {"line1": "400 Pine Street Suite 12 (MOCK)", "city": "Seattle", "postalCode": "98101", "country": "US"},
           {"account": "000123456789", "swift": "MOCKUS33XXX", "bearer": "SHAR", "purpose": "S1006"},
           {"residency": "NON_RESIDENT", "country": "US", "payee_type": "COMPANY", "pan": "AAGCC7731H", "tax_id": "98-7654321",
            "trc_no": "IRS-6166-2027-55120", "trc_valid_from": D(2027, 1, 1), "trc_valid_to": D(2027, 12, 31), "trc_document_ref": "MOCK/TRC/NRUS01-6166.pdf",
            "form10f_ack": "10F-2026-US-087731", "form10f_filed_on": D(2026, 5, 10), "form10f_valid_from": D(2026, 4, 1), "form10f_valid_to": D(2027, 3, 31),
            "default_nature": "ROYALTY"},
           orders=[("4502390003", [("Die-casting simulation software licence, 12 seats, year 2027-28", "997331", 1, "9500.00", 18)])]),
    Vendor("NRSG01", "Merlion Process Engineering Pte Ltd (fictional)", "SG", "SGD", "N30",
           {"line1": "21 Tuas Avenue 7 (MOCK)", "city": "Singapore", "postalCode": "639278", "country": "SG"},
           {"account": "0123456789012", "swift": "MOCKSGSGXXX", "bearer": "SHAR", "purpose": "S1007"},
           {"residency": "NON_RESIDENT", "country": "SG", "payee_type": "COMPANY",
            "trc_no": "IRAS-COR-2027-33018", "trc_valid_from": D(2027, 1, 1), "trc_valid_to": D(2027, 12, 31), "trc_document_ref": "MOCK/TRC/NRSG01-2027.pdf",
            "form10f_ack": "10F-2027-SG-120455", "form10f_filed_on": D(2027, 5, 2), "form10f_valid_from": D(2027, 4, 1), "form10f_valid_to": D(2028, 3, 31),
            "default_nature": "FTS"},
           orders=[("4502390004", [("Process audit of the HPDC cell and cycle-time study", "998311", 1, "10500.00", 18)])]),
    Vendor("NRAE01", "Gulf Crest Technical Consultancy FZE (fictional)", "AE", "USD", "N30",
           {"line1": "Office 7, Free Zone Tower B (MOCK)", "city": "Dubai", "postalCode": "00000", "country": "AE"},
           {"account": "AE070331234567890123456", "swift": "MOCKAEADXXX", "bearer": "DEBT", "purpose": "S1007"},
           {"residency": "NON_RESIDENT", "country": "AE", "payee_type": "COMPANY", "pan": "AAHCG5512Q", "tax_id": "100234567800003",
            "trc_no": "UAE-TRC-2027-0098812", "trc_valid_from": D(2027, 3, 1), "trc_valid_to": D(2028, 2, 29), "trc_document_ref": "MOCK/TRC/NRAE01-2027.pdf",
            "form10f_ack": "10F-2027-AE-131902", "form10f_filed_on": D(2027, 6, 1), "form10f_valid_from": D(2027, 4, 1), "form10f_valid_to": D(2028, 3, 31),
            "gross_up": True, "default_nature": "FTS"},
           orders=[("4502390005", [("Melt-shop energy audit and furnace commissioning support", "998336", 1, "7000.00", 18)])]),
    Vendor("RVES01", "Kaveri Valley Engineering Services Pvt Ltd (fictional)", "IN", "INR", "N60",
           {"line1": "Plot 18, SIPCOT Phase II (MOCK)", "city": "Hosur", "state_code": "33", "pin": "635109", "country": "IN"},
           {"account": "50200098765432", "ifsc": "MOCK0000338"},
           {"residency": "RESIDENT", "country": "IN", "payee_type": "COMPANY"},
           gstin="33AAKCK4821P1Z", tds_section="194J-TECH", msme=("SMALL", "UDYAM-TN-31-0042817"),
           orders=[("4502390006", [("Fixture design and CMM programming, DC-340 line", "998313", 1, "600000.00", 18)]),
                   ("4502390007", [("PPAP documentation and capability study, DC-341", "998313", 1, "300000.00", 18)])]),
]
# invoices: key, vendor, order, supplier invoice number
INVOICES = [("DE1", "NRDE01", "4502390001", "RWT/2027/1184"), ("DE2", "NRDE01", "4502390002", "RWT/2027/1185"),
            ("US1", "NRUS01", "4502390003", "CRS-INV-27-0412"), ("SG1", "NRSG01", "4502390004", "MPE-2027-0918"),
            ("AE1", "NRAE01", "4502390005", "GC/FZE/27/044"), ("R1", "RVES01", "4502390006", "KVES/27-28/0233"),
            ("R2", "RVES01", "4502390007", "KVES/27-28/0234")]
FX = [("EUR", D(2027, 10, 1), "92.4000"), ("USD", D(2027, 10, 1), "84.1000"), ("SGD", D(2027, 10, 1), "63.2000"),
      ("EUR", D(2027, 10, 15), "92.8500"), ("USD", D(2027, 10, 15), "84.3500"), ("SGD", D(2027, 10, 15), "63.0500")]
CURRENCY_NAMES = {"SGD": "Singapore dollar", "AED": "UAE dirham"}
MASTER_DAY, RESIDENCY_DAY, GR_DAY, CAPTURE_DAY, POST_DAY = D(2027, 10, 1), D(2027, 10, 2), D(2027, 10, 4), D(2027, 10, 5), D(2027, 10, 6)
FORM15_DAY, RUN_A, BANK_A, FORM15_US_DAY, RUN_B, RETURN_DAY, RUN_C, BANK_C, CHALLAN_DAY = (
    D(2027, 10, 11), D(2027, 10, 12), D(2027, 10, 14), D(2027, 10, 18), D(2027, 10, 19), D(2027, 10, 21), D(2027, 10, 26), D(2027, 10, 28), D(2027, 11, 6))
# Form 15CA / 15CB (MOCK numbers): invoice key, day, part, acknowledgement, amount (invoice currency, minor), 15CB UDIN
FORMS = [("DE1", FORM15_DAY, "C", "152027100011841", 840_000, "27112233AAAABC1184"), ("SG1", FORM15_DAY, "C", "152027100019180", 1_050_000, "27112233AAAABC0918"),
         ("AE1", FORM15_DAY, "C", "152027100010044", 700_000, "27112233AAAABC0044"), ("US1", FORM15_US_DAY, "C", "152027100180412", 950_000, "27112233AAAABC0412")]
CA = {"ca_name": "R. Meenakshi, Chartered Accountant (fictional)", "ca_membership_no": "212345"}
DEDUCTOR = {"tan": "CHEA99999Z", "pan": "AAACA9999Z", "name": "Axion Components Pvt Ltd (MOCK deductor data)",
            "address": "MOCK: SIPCOT Industrial Park, Hosur 635126, Tamil Nadu"}
REASON_R1 = "Milestone billing agreed with the vendor: pay the fixture design part now, the CMM programming part after sign-off (MOCK)"
REASON_R2 = "Pay on the PPAP sample approval milestone; the capability study part follows its review (MOCK)"


def _stage_done(tenant_id, key: str) -> bool:
    with tenant_tx(tenant_id) as s:
        return s.execute(select(AuditEvent.seq).where(AuditEvent.action == "TAX_NONRESIDENT_STAGE", AuditEvent.object_ref == key).limit(1)).first() is not None


def _stage_mark(tenant_id, key: str, after: Optional[dict] = None) -> None:
    with tenant_tx(tenant_id) as s:
        audit.record(s, "DATASET", uuid.uuid5(uuid.NAMESPACE_URL, f"{KEY}:{key}"), "TAX_NONRESIDENT_STAGE", object_ref=key, after=after or {},
                     actor=ACTOR, reason=LABEL)


def category_of(spec: "Vendor") -> str:
    """Qualified category of a vendor: a category the TAXONOMY-UNSPSC mapping (D11) already covers, by what the vendor sells. Software licences
    (SAC 9973) are SOFTWARE-LICENCES, audits and consultancy (SAC 99831x, 99833x except 998331) PROF-SERVICES, die and fixture engineering
    TOOLING-SERVICES."""
    sacs = {sac for _, lines in spec.orders for _, sac, *_ in lines}
    if any(sac.startswith("9973") for sac in sacs):
        return "SOFTWARE-LICENCES"
    if sacs and all(sac.startswith(("99831", "99833")) and sac not in ("998331", "998313") for sac in sacs):
        return "PROF-SERVICES"
    return "TOOLING-SERVICES"


def _gstin(prefix14: str) -> str:
    total = 0
    for i, ch in enumerate(prefix14):
        v = kit.GSTIN_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += v // 36 + v % 36
    return prefix14 + kit.GSTIN_CHARS[(36 - total % 36) % 36]


# ------------------------------------------------------------------------------------------------ building blocks (also used by the tests)
def fx_rates(sc: Scenario, rows=FX) -> int:
    """MOCK reference rates (currency -> INR) on the given days; existing rates stay."""
    added = 0
    with tenant_tx(sc.tenant_id) as s:
        codes = set(s.execute(select(Currency.code)).scalars())
        for code, name in CURRENCY_NAMES.items():
            if code not in codes:
                s.add(Currency(tenant_id=sc.tenant_id, code=code, name=name, decimals=2, active=True))
        for code, day, rate in rows:
            if s.execute(select(FxRate.id).where(FxRate.from_ccy == code, FxRate.to_ccy == "INR", FxRate.valid_from == day)).first() is None:
                s.add(FxRate(tenant_id=sc.tenant_id, from_ccy=code, to_ccy="INR", rate=Decimal(rate), valid_from=day, source=f"MOCK {KEY}"))
                added += 1
    return added


def vendor(sc: Scenario, spec: Vendor, day: date) -> uuid.UUID:
    """Vendor master, verified bank account and qualified category, loaded like the ERP cutover loads vendors (seed-if-missing by code)."""
    with sc.act(ADMIN, at(day, 9)) as s:
        found = s.execute(select(Supplier).where(Supplier.code == spec.code)).scalar_one_or_none()
        if found is not None:
            return found.id
        tid, admin_id = sc.tenant_id, s.info["principal"].user_id
        supplier = Supplier(tenant_id=tid, code=spec.code, legal_name=spec.name, status="ACTIVE", country=spec.country, payment_terms=spec.terms,
                            risk_tier="LOW", contact_email=f"accounts@{spec.code.lower()}.mock.example", address=spec.address,
                            screening={"source": KEY, "outcome": "CLEAR", "mock": True}, created_by=admin_id)
        if spec.gstin:
            gstin = _gstin(spec.gstin) if len(spec.gstin) == 14 else spec.gstin
            supplier.gstin_enc, supplier.gstin_masked = crypto.encrypt(tid, "gstin", gstin), crypto.mask(gstin)
            supplier.gstin_hash, supplier.pan_hash, supplier.state_code = crypto.blind_index(tid, gstin), crypto.blind_index(tid, gstin[2:12]), gstin[:2]
        if spec.tds_section:
            supplier.tds_section = spec.tds_section
        if spec.msme:
            supplier.msme_class, supplier.udyam_no = spec.msme
        s.add(supplier)
        s.flush()
        bank = spec.bank
        account = SupplierBankAccount(tenant_id=tid, supplier_id=supplier.id, account_enc=crypto.encrypt(tid, "bank", bank["account"]),
                                      account_masked=crypto.mask(bank["account"]), ifsc=bank.get("ifsc") or bank["swift"], holder_name=spec.name[:200],
                                      active=True, verified_on=day - timedelta(days=60), created_by=admin_id)
        if spec.country != "IN":
            account.country, account.swift_bic, account.charge_bearer, account.purpose_code = spec.country, bank["swift"], bank["bearer"], bank["purpose"]
        s.add(account)
        s.add(SupplierCategoryStatus(tenant_id=tid, supplier_id=supplier.id, category=category_of(spec), status="QUALIFIED", qualified_on=day,
                                     created_by=admin_id))
        audit.record(s, "SUPPLIER", supplier.id, "MIGRATED", object_ref=spec.code, actor=ACTOR, reason=LABEL,
                     after={"source": "MOCK vendor master (tax_nonresident)", "country": spec.country, "currency": spec.currency})
        return supplier.id


def order(sc: Scenario, spec: Vendor, erp_doc: str, lines: list, day: date) -> str:
    """An open purchase order loaded from the ERP (seed-if-missing by ERP document number): free-text service lines received with a goods receipt."""
    with sc.act(ADMIN, at(day, 9)) as s:
        po = s.execute(select(PurchaseOrder).where(PurchaseOrder.erp_doc_no == erp_doc)).scalar_one_or_none()
        if po is not None:
            return po.number
        tid, admin_id = sc.tenant_id, s.info["principal"].user_id
        supplier = s.execute(select(Supplier).where(Supplier.code == spec.code)).scalar_one()
        total = sum(int((Decimal(q) * Decimal(p) * 100).quantize(Decimal(1))) for _, _, q, p, _ in lines)
        po = PurchaseOrder(tenant_id=tid, number=next_number(s, "PURCHASE_ORDER"), version=1, company_code=COMPANY, purch_org="1000", plant=PLANT,
                           supplier_id=supplier.id, status="CONFIRMED", purpose_code="ERP_OPEN_PO", currency=spec.currency, total_minor=total,
                           payment_terms=spec.terms, tolerance={"over_pct": "0", "price_pct": "0", "under_pct": "0"},
                           inherited={"migratedFrom": "MOCK_IMPORT", "erpDocument": erp_doc, "orderDate": day.isoformat(), "mock": KEY},
                           rule_set_version="MIGRATION", released_by="MOCK_IMPORT", released_at=at(day, 9), transmitted_via="ERP", transmitted_at=at(day, 9),
                           erp_doc_no=erp_doc, touchless=False, created_by=admin_id)
        s.add(po)
        s.flush()
        for k, (desc, sac, qty, price, gst) in enumerate(lines, start=1):
            minor = int((Decimal(price) * 100).quantize(Decimal(1)))
            line = PoLine(tenant_id=tid, po_id=po.id, line_no=k * 10, item_type="FREE_TEXT", purchase_type="NON_STOCK", description=desc[:200],
                          material_group="ENGINEERING", qty=Decimal(qty), uom="EA", unit_price_minor=minor, net_minor=int(Decimal(qty) * minor),
                          gst_rate=Decimal(gst), hsn_code=sac, need_date=day + timedelta(days=3), plant=PLANT, storage_location="0001", gr_required=True,
                          ir_required=True, ses_required=False, ers=False, quality_managed=False, price_source="MANUAL", received_qty=Decimal(0),
                          accepted_qty=Decimal(0), invoiced_qty=Decimal(0), invoiced_minor=0, created_by=admin_id)
            s.add(line)
            s.flush()
            s.add(PoScheduleLine(tenant_id=tid, po_id=po.id, po_line_id=line.id, seq=1, qty=Decimal(qty), delivery_date=day + timedelta(days=3),
                                 received_qty=Decimal(0), created_by=admin_id))
        instance = workflow.start(s, "pic.po", "PURCHASE_ORDER", po.id, po.number, {"migratedFrom": "MOCK_IMPORT", "erpDocument": erp_doc})
        workflow.step(s, instance, "F5-06", outcome=f"mock import order {erp_doc} ({spec.currency})")
        workflow.wait(s, instance, "F5-09", outcome="confirmed: awaiting delivery")
        audit.record(s, "PURCHASE_ORDER", po.id, "MIGRATED", object_ref=po.number, actor=ACTOR, reason=LABEL,
                     after={"erpDocument": erp_doc, "supplier": spec.code, "currency": spec.currency, "totalMinor": total})
        return po.number


def residency(sc: Scenario, spec: Vendor, day: date) -> None:
    from app.pic.services import nonresident_tax
    with sc.act(SUPPLIER_MANAGER, at(day, 10)) as s:
        supplier = s.execute(select(Supplier).where(Supplier.code == spec.code)).scalar_one()
        if nonresident_tax.residency_of(s, supplier.id) is None:
            nonresident_tax.set_residency(s, supplier, reason=f"{LABEL}: tax residency from the vendor's TRC and Form 10F", **spec.residency)


def find_invoice(s, supplier_code: str, number: str) -> Optional[Invoice]:
    return s.execute(select(Invoice).join(Supplier, Supplier.id == Invoice.supplier_id).where(
        Supplier.code == supplier_code, Invoice.supplier_invoice_no == number)).scalar_one_or_none()


def invoice(sc: Scenario, supplier_code: str, po_number: str, supplier_invoice_no: str, gr_day: date, capture_day: date, post_day: date) -> str:
    """Goods receipt (service acceptance), supplier invoice, accounts-payable approval (and any value-band chain), posting to the ERP."""
    from app.pic.services import payables, receiving
    with sc.act(RECEIVER, at(gr_day, 10)) as s:
        note = f"SVC-{supplier_invoice_no}"[:40]
        if not s.execute(select(GoodsReceipt.id).where(GoodsReceipt.delivery_note == note)).first():
            po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == po_number)).scalar_one()
            lines = s.execute(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).scalars().all()
            receiving.post_gr(s, po, lines=[{"line": l.line_no, "qty": str(l.qty.normalize())} for l in lines], delivery_note=note, posting_date=gr_day)
    with sc.act(AP, at(capture_day, 11)) as s:
        if find_invoice(s, supplier_code, supplier_invoice_no) is None:
            po = s.execute(select(PurchaseOrder).where(PurchaseOrder.number == po_number)).scalar_one()
            lines = s.execute(select(PoLine).where(PoLine.po_id == po.id).order_by(PoLine.line_no)).scalars().all()
            payables.capture(s, supplier=supplier_code, supplier_invoice_no=supplier_invoice_no, invoice_date=capture_day, channel="PDF_OCR",
                             company_code=COMPANY, lines=[{"po": po_number, "po_line": l.line_no, "qty": str(l.qty.normalize()),
                                                           "unit_price": f"{Decimal(l.unit_price_minor) / 100:.2f}", "gst_rate": str(l.gst_rate),
                                                           "hsn": l.hsn_code} for l in lines])
    with sc.act(APPROVER, at(post_day, 10)) as s:
        inv = find_invoice(s, supplier_code, supplier_invoice_no)
        if inv.status == "MATCHED" and not payables.open_approval_tasks(s, inv):
            payables.approve(s, inv)
        invoice_id = inv.id
    sc.approve_all(invoice_id, at(post_day, 10, 30), f"{LABEL}: within the approver's limit")  # value-band chain, when the tenant has one
    with sc.act(AP, at(post_day, 11)) as s:
        inv = find_invoice(s, supplier_code, supplier_invoice_no)
        if inv.status == "APPROVED":
            payables.post(s, inv, payables.posting_key(s, inv))
        return inv.number


def record_form15(sc: Scenario, supplier_code: str, supplier_invoice_no: str, day: date, part: str, ack: str, amount_minor: int, udin: Optional[str]) -> None:
    from app.pic.services import nonresident_tax
    with sc.act(TREASURY, at(day, 12)) as s:
        if s.execute(select(RemittanceCertificate.id).where(RemittanceCertificate.form15ca_ack_hash == crypto.blind_index(sc.tenant_id, ack))).first():
            return
        inv = find_invoice(s, supplier_code, supplier_invoice_no)
        nonresident_tax.record_form15(s, inv, part=part, acknowledgement=ack, filed_on=day, amount_minor=amount_minor,
                                      form15cb_certificate_no=udin, form15cb_date=day - timedelta(days=1) if udin else None,
                                      **(CA if udin else {}), note=f"{LABEL}: filed on the income-tax portal before the remittance")


def debtor_rule(sc: Scenario, day: date) -> None:
    """AXN may have no debtor bank account for payment files yet: publish a MOCK one only when none is configured."""
    with tenant_tx(sc.tenant_id) as s:
        try:
            body = rules.resolve(s, "PAYMENT-FILE", on=day, company_code=COMPANY).body
        except Problem:
            body = {}
        if body.get("debtorName"):
            return
        if s.execute(select(RuleSet.id).where(RuleSet.key == "PAYMENT-FILE", RuleSet.version == "2027.10-TAXNR-MOCK")).first():
            return
        rule = RuleSet(tenant_id=sc.tenant_id, key="PAYMENT-FILE", version="2027.10-TAXNR-MOCK", effective_from=D(2027, 10, 1), company_code=COMPANY,
                       body={"format": "ISO20022_PAIN001", "debtorName": "Axion Components Pvt Ltd (MOCK debtor account)", "debtorAccountRef": "MOCK-CA-AXN-0001",
                             "debtorIfsc": "MOCK0000001"}, description=f"{LABEL}: MOCK debtor account, not a real account")
        s.add(rule)
        s.flush()
        audit.record(s, "RULE_SET", rule.id, "VERSION_CREATED", object_ref="PAYMENT-FILE@2027.10-TAXNR-MOCK", actor=ACTOR, reason=LABEL)


def pay(sc: Scenario, day: date, numbers: list[str], partials: Optional[dict] = None) -> dict:
    """One payment run (as the treasury controller, who neither captured nor approved the invoices: SoD) with its pain.001 file, sent to the bank."""
    from app.pic.services import bank_files, payables
    with sc.act(TREASURY, at(day, 10)) as s:
        result = payables.payment_run(s, day, include_not_due=True, invoice_numbers=numbers, partials=partials)
        pf = bank_files.generate(s, result["run"], "ISO20022_PAIN001") if result["paid"] else None
        if pf is not None:
            bank_files.set_status(s, pf, "SENT")
        return {**result, "file": pf.number if pf is not None else None}


def bank_results(sc: Scenario, day: date, file_no: str, returned: tuple = (), only: Optional[set] = None) -> dict:
    """The bank's results for a file: CREDITED with a MOCK UTR, RETURNED for the payments named in ``returned``; ``only`` limits the payments reported."""
    from app.pic.services import bank_files
    with sc.act(TREASURY, at(day, 11)) as s:
        pf = bank_files.by_number(s, file_no, lock=True)
        payments = s.execute(select(Payment).where(Payment.run_ref == pf.run_ref, Payment.status == "COMPLETED", Payment.bank_status == "SENT")
                             .order_by(Payment.number)).scalars().all()
        items = []
        for n, payment in enumerate(payments, start=1):
            if only is not None and payment.number not in only:
                continue
            if payment.number in returned:
                items.append({"payment": payment.number, "status": "RETURNED", "reason": "AC06 Account blocked by the beneficiary bank (MOCK sample)"})
            else:
                items.append({"payment": payment.number, "status": "CREDITED", "utr": f"MOCKUTR{day:%y%m%d}{n:05d}"})
        return bank_files.record_bank_results(s, pf, items) if items else {}


# ------------------------------------------------------------------------------------------------ the pack
def _scenario() -> Scenario:
    from app.pic.seed.datasets import _tenants
    return Scenario(_tenants()["AXN"])


def _number(sc: Scenario, key: str) -> str:
    _, code, _, no = next(x for x in INVOICES if x[0] == key)
    with tenant_tx(sc.tenant_id) as s:
        return find_invoice(s, code, no).number


def _payment_of(sc: Scenario, key: str, installment: int) -> Optional[str]:
    _, code, _, no = next(x for x in INVOICES if x[0] == key)
    with tenant_tx(sc.tenant_id) as s:
        inv = find_invoice(s, code, no)
        return s.execute(select(Payment.number).where(Payment.invoice_id == inv.id, Payment.installment_no == installment,
                                                      Payment.debit_note_id.is_(None))).scalar_one_or_none()


def apply(tenant_code: str, password: str) -> dict:
    sc = _scenario()
    notes, counts = [], {}
    if not _stage_done(sc.tenant_id, "masters"):
        counts["fxRates"] = fx_rates(sc)
        for spec in VENDORS:
            vendor(sc, spec, MASTER_DAY)
            for erp_doc, lines in spec.orders:
                order(sc, spec, erp_doc, lines, MASTER_DAY)
            residency(sc, spec, RESIDENCY_DAY)
        kit.rule_version(sc, "TDS", "2027.10-AXN-DEDUCTOR-MOCK", D(2027, 10, 1), {"deductor": DEDUCTOR},
                         f"{LABEL}: MOCK deductor TAN / PAN for the Form 16A information copies (the client supplies the real ones)")
        debtor_rule(sc, MASTER_DAY)
        _stage_mark(sc.tenant_id, "masters", {"vendors": [v.code for v in VENDORS]})
    counts["vendors"] = len(VENDORS)
    po_by_erp = {}
    with tenant_tx(sc.tenant_id) as s:
        for number, erp in s.execute(select(PurchaseOrder.number, PurchaseOrder.erp_doc_no).where(PurchaseOrder.erp_doc_no.like("45023900%"))).all():
            po_by_erp[erp] = number
    for key, code, erp, no in INVOICES:
        invoice(sc, code, po_by_erp[erp], no, GR_DAY, CAPTURE_DAY, POST_DAY)
    counts["invoices"] = len(INVOICES)
    for key, day, part, ack, amount, udin in FORMS:
        if key == "US1":
            continue                          # the US remittance is first named in a run without its Form 15CA (refused), then filed
        _, code, _, no = next(x for x in INVOICES if x[0] == key)
        record_form15(sc, code, no, day, part, ack, amount, udin)
    n = {k: _number(sc, k) for k, *_ in INVOICES}
    # 12 October: a run that names the US royalty without its Form 15CA is refused before anything is written
    if not _stage_done(sc.tenant_id, "run-a-refused"):
        try:
            pay(sc, RUN_A, [n["US1"], n["DE1"]])
            refusal = {"refused": False}
        except Problem as exc:
            refusal = {"refused": True, "status": exc.status, "code": exc.code, "detail": exc.detail}
        _stage_mark(sc.tenant_id, "run-a-refused", refusal)
        notes.append(f"12 Oct run naming {n['US1']} without Form 15CA: {refusal}")
    if not _stage_done(sc.tenant_id, "run-a"):
        result = pay(sc, RUN_A, [n["DE1"], n["SG1"], n["AE1"], n["R1"], n["R2"]],
                     partials={n["R1"]: {"amountMinor": 250_000_00, "reason": REASON_R1}, n["R2"]: {"amountMinor": 100_000_00, "reason": REASON_R2}})
        _stage_mark(sc.tenant_id, "run-a", {"run": result["run"], "file": result["file"], "paid": [p["payment"] for p in result["paid"]],
                                            "skipped": result["skipped"]})
        counts["runA"] = len(result["paid"])
    file_a = _stage_file(sc, "run-a")
    if not _stage_done(sc.tenant_id, "bank-a"):
        r2_part1 = _payment_of(sc, "R2", 1)
        with tenant_tx(sc.tenant_id) as s:
            others = {p for p in s.execute(select(Payment.number).join(PaymentFile, PaymentFile.run_ref == Payment.run_ref)
                                            .where(PaymentFile.number == file_a)).scalars() if p != r2_part1}
        bank_results(sc, BANK_A, file_a, only=others)
        _stage_mark(sc.tenant_id, "bank-a")
    _, code, _, no = next(x for x in INVOICES if x[0] == "US1")
    us_form = next(f for f in FORMS if f[0] == "US1")
    record_form15(sc, code, no, us_form[1], us_form[2], us_form[3], us_form[4], us_form[5])
    if not _stage_done(sc.tenant_id, "run-b"):
        result = pay(sc, RUN_B, [n["US1"], n["R1"], n["R2"]],
                     partials={n["R1"]: {"amountMinor": 200_000_00, "reason": REASON_R1}, n["R2"]: {"amountMinor": 80_000_00, "reason": REASON_R2}})
        _stage_mark(sc.tenant_id, "run-b", {"run": result["run"], "file": result["file"], "paid": [p["payment"] for p in result["paid"]]})
        counts["runB"] = len(result["paid"])
    if not _stage_done(sc.tenant_id, "bank-b"):
        bank_results(sc, RETURN_DAY, file_a, returned=(_payment_of(sc, "R2", 1),))
        bank_results(sc, RETURN_DAY, _stage_file(sc, "run-b"))
        _stage_mark(sc.tenant_id, "bank-b")
        counts["paymentsReturned"] = 1
    if not _stage_done(sc.tenant_id, "run-c"):
        result = pay(sc, RUN_C, [n["R1"], n["R2"]])
        _stage_mark(sc.tenant_id, "run-c", {"run": result["run"], "file": result["file"], "paid": [p["payment"] for p in result["paid"]]})
        counts["runC"] = len(result["paid"])
    if not _stage_done(sc.tenant_id, "bank-c"):
        bank_results(sc, BANK_C, _stage_file(sc, "run-c"))
        _stage_mark(sc.tenant_id, "bank-c")
    counts["challans"] = challans(sc)
    blocked = proposal_skips(sc, n["DE2"])
    notes.append(f"{n['DE2']} stays blocked: {blocked}")
    clock.set_pinned(None)
    return {"notes": [f"{LABEL}: {x}" for x in notes], "counts": counts, "label": LABEL}


def _stage_file(sc: Scenario, key: str) -> str:
    with tenant_tx(sc.tenant_id) as s:
        row = s.execute(select(AuditEvent).where(AuditEvent.action == "TAX_NONRESIDENT_STAGE", AuditEvent.object_ref == key)
                        .order_by(AuditEvent.seq.desc())).scalars().first()
        return (row.after or {}).get("file")


def challans(sc: Scenario) -> int:
    """Deposit the TDS deducted in October (Q3) per section: what the reconciliation shows as deducted is deposited (26Q and 27Q)."""
    from app.pic.services import tds_returns
    added = 0
    with sc.act(TREASURY, at(CHALLAN_DAY, 15)) as s:
        taken = tds_returns.deducted(s, FY, QUARTER, [COMPANY])
        have = {(c.section, c.challan_no) for c in s.execute(select(TdsChallan).where(TdsChallan.fiscal_year == FY, TdsChallan.quarter == QUARTER)).scalars()}
        mine = [(company, section, amount) for (company, section), amount in sorted(taken.items())
                if section == "194J-TECH" or section.startswith("195-")]
        for k, (company, section, amount) in enumerate(mine, start=1):
            serial = f"{71100 + k:05d}"
            if (section, serial) in have or amount <= 0:
                continue
            tds_returns.record_challan(s, company_code=company, fiscal_year=FY, quarter=QUARTER, section=section, challan_no=serial, bsr_code="0510308",
                                       deposit_date=CHALLAN_DAY, amount_minor=amount, note=f"{LABEL}: October deductions of section {section}")
            added += 1
    return added


def proposal_skips(sc: Scenario, number: str) -> list:
    from app.pic.services import payables
    with sc.act(TREASURY, at(RUN_C, 9)) as s:
        return payables.payment_proposal(s, RUN_C, include_not_due=True, invoice_numbers=[number])["skipped"]
