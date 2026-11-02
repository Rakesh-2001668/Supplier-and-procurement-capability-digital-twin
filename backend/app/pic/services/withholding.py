"""Superseded by services/finance_controls.py (TDS sections, thresholds, no-PAN rate, determination at posting, ``at_payment`` at payment):
the payment run no longer calls this module. The helpers below stay for callers that only hold an invoice row (no session).

TDS / withholding tax on supplier invoices (India: income-tax Act TDS, deducted when the supplier is paid).

``Invoice.withholding_tax_minor`` holds the tax a payment must keep back for the tax authority. Open items migrated from SAP with a
withholding amount (BSIK-QBSHB) carry it; the payment run pays ``gross - credit notes - retention - withholding``. This module
is the single place for that arithmetic so the payment run (payables.py) needs one call.
"""


def deduction_minor(invoice) -> int:
    """The withholding tax a payment of this invoice keeps back (0 when none)."""
    return max(int(getattr(invoice, "withholding_tax_minor", 0) or 0), 0)


def payable_minor(invoice, credit_minor: int = 0) -> int:
    """Amount to pay the supplier: gross less credit notes, retention and withholding tax (may be zero or negative: the caller skips it)."""
    return int(invoice.gross_minor) - int(credit_minor) - int(getattr(invoice, "retention_minor", 0) or 0) - deduction_minor(invoice)
