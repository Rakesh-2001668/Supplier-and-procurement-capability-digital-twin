"""Code-review integrity constraints: outbox back-off column, unique internal invoice / credit-note numbers, and CHECKs that
make negative or zero quantities and amounts impossible even for code paths that bypass the API validation (requisition and
PO lines, ASN / GR / SES lines, inspection lots, return deliveries, budget commitments). Existing data was checked before
adding them (no violations in the seeded tenants).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-29 21:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, constraint name, condition)
CHECKS = (
    ("pr_line", "ck_pr_line_qty_positive", "qty > 0"),
    ("pr_line", "ck_pr_line_price_not_negative", "price_est_minor IS NULL OR price_est_minor >= 0"),
    ("pr_line", "ck_pr_line_ordered_not_negative", "ordered_qty >= 0"),
    ("requisition", "ck_requisition_total_not_negative", "total_minor >= 0"),
    ("budget_commitment", "ck_budget_commitment_not_negative", "amount_minor >= 0"),
    ("po_line", "ck_po_line_quantities_not_negative",
     "received_qty >= 0 AND accepted_qty >= 0 AND shipped_qty >= 0 AND rejected_qty >= 0"),
    ("po_line", "ck_po_line_ses_within_value", "ses_approved_minor <= net_minor"),
    ("asn_line", "ck_asn_line_qty_positive", "qty > 0"),
    ("gr_line", "ck_gr_line_qty_positive", "qty > 0"),
    ("gr_line", "ck_gr_line_decision_not_negative", "accepted_qty >= 0 AND rejected_qty >= 0"),
    ("ses_line", "ck_ses_line_positive", "qty > 0 AND unit_rate_minor > 0"),
    ("inspection_lot", "ck_inspection_lot_decision_not_negative",
     "(accepted_qty IS NULL OR accepted_qty >= 0) AND (rejected_qty IS NULL OR rejected_qty >= 0)"),
    ("return_delivery", "ck_return_delivery_qty_positive", "qty > 0"),
)


def upgrade() -> None:
    op.add_column('outbox_event', sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True), schema='pic')
    op.create_index('ix_outbox_event_due', 'outbox_event', ['tenant_id', 'published_at', 'next_attempt_at'], unique=False, schema='pic')
    op.create_unique_constraint('uq_invoice_tenant_number', 'invoice', ['tenant_id', 'number'], schema='pic')
    op.create_unique_constraint('uq_credit_note_supplier_number', 'credit_note', ['tenant_id', 'supplier_id', 'number'], schema='pic')
    for table, name, condition in CHECKS:
        op.create_check_constraint(name, table, condition, schema='pic')


def downgrade() -> None:
    for table, name, _ in reversed(CHECKS):
        op.drop_constraint(name, table, type_='check', schema='pic')
    op.drop_constraint('uq_credit_note_supplier_number', 'credit_note', type_='unique', schema='pic')
    op.drop_constraint('uq_invoice_tenant_number', 'invoice', type_='unique', schema='pic')
    op.drop_index('ix_outbox_event_due', table_name='outbox_event', schema='pic')
    op.drop_column('outbox_event', 'next_attempt_at', schema='pic')
