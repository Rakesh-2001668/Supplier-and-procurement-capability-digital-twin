"""Information copy of the Form 16A data as PDF (one deductee, one quarter; one section per certificate).

PIC does not issue the statutory TDS certificate: Form 16A is generated and digitally signed in TRACES from the filed 26Q / 27Q return. This
module prints the certificate data PIC holds (``tds_returns.certificate_data``) so the tax team and the supplier can check it, and marks every
page as an information copy (banner and diagonal watermark).

No PDF library is installed in the platform (requirements.txt), so the document is written directly as PDF 1.4: uncompressed content streams,
the standard Type 1 fonts Helvetica and Helvetica-Bold with WinAnsiEncoding (no embedding needed), A4 pages. Text outside Windows-1252 is
replaced by "?"; amounts are printed in INR with Indian digit grouping.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.pic.platform import clock

PAGE_W, PAGE_H = 595.28, 841.89          # A4 in points
MARGIN = 40
BANNER = "INFORMATION COPY - the statutory Form 16A must be downloaded from TRACES"
BANNER_TEXT = "Information copy \u2014 the statutory Form 16A must be downloaded from TRACES"
WATERMARK = "INFORMATION COPY"
PRODUCER = "AlphaHelion PIC"


def inr(minor: Optional[int]) -> str:
    """Indian digit grouping without the rupee sign (not in WinAnsiEncoding): 2149200_00 -> 'INR 21,49,200.00'."""
    if minor is None:
        return ""
    sign = "-" if minor < 0 else ""
    whole, frac = divmod(abs(int(minor)), 100)
    digits = str(whole)
    if len(digits) > 3:
        head, tail, groups = digits[:-3], digits[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"{sign}{digits}.{frac:02d}"


def _dmy(iso: Optional[str]) -> str:
    if not iso:
        return ""
    return f"{iso[8:10]}-{iso[5:7]}-{iso[0:4]}"


def _escape(text: str) -> str:
    raw = str(text).encode("cp1252", errors="replace").decode("latin-1")
    return raw.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\r", " ").replace("\n", " ")


def _width(text: str, size: float) -> float:
    """Approximate Helvetica advance width (digits 0.556 em, average letter 0.52 em, narrow punctuation 0.28 em)."""
    total = 0.0
    for ch in str(text):
        total += 0.556 if ch.isdigit() else 0.28 if ch in " .,:;-/()'|" else 0.72 if ch.isupper() else 0.5
    return total * size


def _fit(text: str, size: float, width: float) -> str:
    text = str(text or "")
    if _width(text, size) <= width:
        return text
    while text and _width(text + "...", size) > width:
        text = text[:-1]
    return text + "..."


class _Page:
    def __init__(self) -> None:
        self.ops: list[str] = []
        self.y = PAGE_H - MARGIN
        # watermark first, so everything else is printed over it
        self.ops.append("q 0.88 g BT /F2 64 Tf 0.7071 0.7071 -0.7071 0.7071 150 210 Tm (%s) Tj ET Q" % _escape(WATERMARK))
        self.ops.append("q 0.85 0.12 0.12 rg %.2f %.2f %.2f 22 re f Q" % (MARGIN, PAGE_H - MARGIN - 22, PAGE_W - 2 * MARGIN))
        self.text(MARGIN + 8, PAGE_H - MARGIN - 15, BANNER_TEXT, size=10, bold=True, color="1 g")
        self.y = PAGE_H - MARGIN - 40

    def text(self, x: float, y: float, value: str, size: float = 9, bold: bool = False, color: str = "0 g") -> None:
        self.ops.append("BT %s /%s %.1f Tf 1 0 0 1 %.2f %.2f Tm (%s) Tj ET" % (color, "F2" if bold else "F1", size, x, y, _escape(value)))

    def right(self, x_right: float, y: float, value: str, size: float = 9, bold: bool = False) -> None:
        self.text(x_right - _width(value, size), y, value, size, bold)

    def line(self, y: float, gray: float = 0.6) -> None:
        self.ops.append("q %.2f G 0.5 w %.2f %.2f m %.2f %.2f l S Q" % (gray, MARGIN, y, PAGE_W - MARGIN, y))

    def stream(self) -> bytes:
        return "\n".join(self.ops).encode("latin-1")


class _Doc:
    def __init__(self) -> None:
        self.pages: list[_Page] = [_Page()]

    @property
    def page(self) -> _Page:
        return self.pages[-1]

    def need(self, height: float) -> bool:
        """Start a new page when ``height`` points do not fit; True when it did."""
        if self.page.y - height < MARGIN + 30:
            self.pages.append(_Page())
            return True
        return False

    def heading(self, value: str, size: float = 12) -> None:
        self.need(size + 10)
        self.page.text(MARGIN, self.page.y, value, size=size, bold=True)
        self.page.y -= size + 6

    def pairs(self, rows: list[tuple[str, str]], label_width: float = 150) -> None:
        for label, value in rows:
            self.need(13)
            self.page.text(MARGIN, self.page.y, label, bold=True)
            self.page.text(MARGIN + label_width, self.page.y, _fit(value, 9, PAGE_W - 2 * MARGIN - label_width))
            self.page.y -= 13

    def table(self, columns: list[tuple[str, float, str]], rows: list[list[str]], size: float = 8) -> None:
        """columns: (title, width, align L|R)."""
        def header() -> None:
            x = MARGIN
            for title, width, align in columns:
                if align == "R":
                    self.page.right(x + width - 2, self.page.y, title, size, bold=True)
                else:
                    self.page.text(x, self.page.y, _fit(title, size, width - 2), size, bold=True)
                x += width
            self.page.line(self.page.y - 3)
            self.page.y -= 13
        self.need(30)
        header()
        for values in rows:
            if self.need(12):
                header()
            x = MARGIN
            for (title, width, align), value in zip(columns, values):
                value = _fit(value, size, width - 4)
                if align == "R":
                    self.page.right(x + width - 2, self.page.y, value, size)
                else:
                    self.page.text(x, self.page.y, value, size)
                x += width
            self.page.y -= 11
        self.page.y -= 4

    def gap(self, points: float = 8) -> None:
        self.page.y -= points


def _certificate(doc: _Doc, cert: dict, first: bool) -> None:
    if not first:
        doc.pages.append(_Page())
    form = cert.get("returnForm") or "26Q"
    doc.heading("Form 16A data - certificate of tax deducted at source (other than salary)", 13)
    doc.page.text(MARGIN, doc.page.y, f"Information copy prepared by PIC from the {form} return data; it is not the TRACES certificate and carries no "
                  "signature.", size=8)
    doc.page.y -= 16
    deductor, deductee = cert.get("deductor") or {}, cert.get("deductee") or {}
    address = deductor.get("address")
    if isinstance(address, dict):
        address = ", ".join(str(v) for v in address.values() if v)
    doc.heading("Period", 10)
    doc.pairs([("Financial year", cert.get("financialYear") or ""), ("Assessment year", cert.get("assessmentYear") or ""),
               ("Quarter", f"{cert.get('quarter')} ({_dmy(cert.get('periodFrom'))} to {_dmy(cert.get('periodTo'))})"),
               ("TDS return", f"Form {form}" + (" (payments to non-residents)" if form == "27Q" else "")),
               ("Certificate number", cert.get("certificateNo") or "issued by TRACES")])
    doc.gap()
    doc.heading("Deductor", 10)
    doc.pairs([("Name", deductor.get("name") or "not on file"), ("TAN", deductor.get("tan") or "not on file"),
               ("PAN", deductor.get("pan") or "not on file"), ("Address", address or "not on file"), ("Company code", cert.get("companyCode") or "")])
    doc.gap()
    doc.heading("Deductee", 10)
    d_address = deductee.get("address") or {}
    if isinstance(d_address, dict):
        d_address = ", ".join(str(v) for k, v in d_address.items() if v and k != "mock")
    doc.pairs([("Name", deductee.get("name") or ""), ("PAN", deductee.get("pan") or "PANNOTAVBL"), ("Supplier code", deductee.get("supplier") or ""),
               ("Residential status", f"{(deductee.get('residency') or 'RESIDENT').replace('_', '-').title()} ({deductee.get('country') or 'IN'})"),
               ("Address", d_address or "not on file")])
    doc.gap()
    doc.heading(f"Section {cert.get('sectionLabel') or cert.get('section')}", 10)
    non_resident = form == "27Q"
    columns = [("Payment", 62, "L"), ("Invoice", 92, "L"), ("Paid / credited", 62, "L"), ("Amount (INR)", 82, "R"), ("Rate %", 44, "R"),
               ("Tax deducted (INR)", 82, "R"), ("Deducted on", 60, "L")]
    columns.append(("Basis", 31, "L") if non_resident else ("s.197 cert.", 31, "L"))
    rows = []
    for line in cert.get("payments") or []:
        basis = (line.get("basis") or "") + (" GU" if line.get("grossedUp") else "")
        rows.append([line.get("payment") or "", line.get("invoice") or "", _dmy(line.get("dateOfPaymentCredit")), inr(line.get("amountPaidCreditedMinor")),
                     line.get("ratePct") or "", inr(line.get("taxDeductedMinor")), _dmy(line.get("dateOfDeduction")),
                     basis if non_resident else (line.get("certificate197") or "")])
    doc.table(columns, rows)
    totals = cert.get("totals") or {}
    doc.pairs([("Total amount paid / credited", f"INR {inr(totals.get('amountPaidCreditedMinor'))}"),
               ("Total tax deducted", f"INR {inr(totals.get('taxDeductedMinor'))}"),
               ("Tax deposited (deductee share)", f"INR {inr(totals.get('taxDepositedMinor'))} ({(cert.get('depositAllocation') or '').replace('_', ' ').lower()})")],
              label_width=170)
    if non_resident:
        doc.page.text(MARGIN, doc.page.y, "Basis: DTAA = treaty rate with valid TRC and Form 10F; ACT = Act rate with surcharge and cess; NO_PAN_206AA = "
                      "higher rate without PAN; GU = grossed up (tax borne by the deductor).", size=7)
        doc.page.y -= 12
    doc.gap()
    doc.heading("Challans of the section in the quarter", 10)
    challans = cert.get("challans") or []
    if challans:
        doc.table([("BSR code", 90, "L"), ("Challan serial no.", 110, "L"), ("Date of deposit", 100, "L"), ("Challan amount (INR)", 120, "R")],
                  [[c.get("bsrCode") or "", c.get("challanSerialNo") or "", _dmy(c.get("depositDate")), inr(c.get("challanAmountMinor"))] for c in challans])
    else:
        doc.need(13)
        doc.page.text(MARGIN, doc.page.y, "No challan is recorded for this section and quarter yet.", size=9)
        doc.page.y -= 13
    missing = cert.get("missingMandatory") or []
    if missing:
        doc.gap()
        doc.need(13)
        doc.page.text(MARGIN, doc.page.y, "Mandatory data PIC does not hold: " + ", ".join(missing), size=9, bold=True, color="0.7 0 0 rg")
        doc.page.y -= 13


def render(certificates: list[dict], generated_at: Optional[datetime] = None) -> bytes:
    """PDF bytes of the information copy of the given certificates (the ``certificates`` of one deductee from ``certificate_data``)."""
    doc = _Doc()
    for n, cert in enumerate(certificates):
        _certificate(doc, cert, first=n == 0)
    when = generated_at or clock.now()
    stamp = when.strftime("%d-%m-%Y %H:%M")
    total = len(doc.pages)
    for n, page in enumerate(doc.pages, start=1):
        page.line(MARGIN + 14)
        page.text(MARGIN, MARGIN, f"{BANNER}. Generated by PIC on {stamp}.", size=7)
        page.right(PAGE_W - MARGIN, MARGIN, f"Page {n} of {total}", size=7)
    return _serialize(doc, certificates, when)


def _serialize(doc: _Doc, certificates: list[dict], when: datetime) -> bytes:
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")            # 1, filled below
    pages = add(b"")              # 2
    regular = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    kids = []
    for page in doc.pages:
        content = page.stream()
        stream = add(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        kids.append(add(("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> "
                         "/Contents %d 0 R >>" % (pages, PAGE_W, PAGE_H, regular, bold, stream)).encode("latin-1")))
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages
    objects[pages - 1] = ("<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join(f"{k} 0 R" for k in kids), len(kids))).encode("latin-1")
    first = certificates[0] if certificates else {}
    title = f"Form 16A information copy {first.get('financialYear', '')} {first.get('quarter', '')} {(first.get('deductee') or {}).get('supplier', '')}"
    info = add(("<< /Title (%s) /Producer (%s) /Subject (%s) /CreationDate (D:%s) >>" % (
        _escape(title), _escape(PRODUCER), _escape(BANNER), when.strftime("%Y%m%d%H%M%S"))).encode("latin-1"))
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog, info, xref)
    return bytes(out)
