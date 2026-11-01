"""Regenerates the recorded INVOIC interchanges in tests/pic/fixtures/edi (run from backend/: python tests/pic/fixtures/make_edi_fixtures.py).

The files are committed so the parser is tested against fixed text, not only against what the builder writes today."""
from datetime import date, datetime
from pathlib import Path

from app.pic.platform import clock
from app.pic.services.edi_invoice import build_invoic

OUT = Path(__file__).parent / "edi"
AT = datetime(2027, 3, 20, 10, 30, tzinfo=clock.IST)
COMMON = dict(sender="KOVAIEDI01", receiver="AXN", document_date=date(2027, 3, 20), at=AT)

FILES = {
    # commercial invoice against PO-77416 line 10: 100 fastener kits at 12.50, 18% GST (gross 1,475.00)
    "invoic_380_valid.edi": dict(control_ref="5551001", document="KD/EDI-0001", po="PO-77416",
                                 lines=[{"line": 10, "qty": 100, "unit_price": "12.50", "hsn": "73181500", "material": "FK-M8-50",
                                         "description": "Fastener kit M8 x 50", "uom": "EA"}]),
    # the declared invoice total (MOA+77) is 1.00 instead of 1,475.00
    "invoic_380_bad_total.edi": dict(control_ref="5551002", document="KD/EDI-0002", po="PO-77416", declared_gross_minor=100,
                                     lines=[{"line": 10, "qty": 100, "unit_price": "12.50", "hsn": "73181500"}]),
    # order that does not exist for this supplier
    "invoic_380_unknown_po.edi": dict(control_ref="5551003", document="KD/EDI-0003", po="PO-00000",
                                      lines=[{"line": 10, "qty": 100, "unit_price": "12.50", "hsn": "73181500"}]),
    # debit note (BGM 383) correcting the price of KD/EDI-0201 line 10 by 0.05 per unit for 100 units
    "invoic_383_debit.edi": dict(control_ref="5553010", document="KD/EDI-DN-1", function="383", po=None, original_invoice="KD/EDI-0201",
                                 lines=[{"line": 10, "qty": 100, "unit_price": "0.05", "hsn": "73181500"}]),
}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, kwargs in FILES.items():
        (OUT / name).write_text(build_invoic(**COMMON, **kwargs).replace("'", "'\n") + "\n", encoding="utf-8")
        print("written", name)
