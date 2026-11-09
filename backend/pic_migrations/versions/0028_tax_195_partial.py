"""Section 195 non-resident TDS, partial payments and the Form 16A PDF.

- invoice: ``paid_minor`` (cash paid by the live payments, backfilled from the existing payments), ``tax_nature`` (s.195 payment nature) and
  ``tax_gross_up`` (s.195A override); check ``paid_minor >= 0``.
- payment: ``installment_no`` (sequence of the payments of an invoice, backfilled by creation order; returned payments keep theirs),
  ``settles_invoice`` (true for every existing payment), ``partial_reason``, ``debit_memo_minor`` (debit notes netted into the payment, backfilled
  from the PAYMENT message), ``tds_inr_minor`` / ``tds_base_inr_minor`` / ``tax_borne_minor`` / ``tax_detail`` (s.195 determination).
  The one-live-payment index ``uq_payment_invoice_live`` now covers the settling payment only; ``uq_payment_invoice_installment`` numbers the
  payments of an invoice.
- contract: ``tax_gross_up`` (s.195A agreed in the contract).
- supplier_tax_residency and remittance_certificate (Form 15CA / 15CB): new tenant tables with the pic_app grants and forced row-level security.

Existing rows keep their meaning: every existing payment settles its invoice, and no invoice becomes partially paid.

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-09 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "pic_app"
NEW_TABLES = ("supplier_tax_residency", "remittance_certificate")
CTX = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
INVOICE_COLUMNS = (
    ('paid_minor', sa.Column('paid_minor', sa.BigInteger(), server_default='0', nullable=False)),
    ('tax_nature', sa.Column('tax_nature', sa.String(length=20), nullable=True)),
    ('tax_gross_up', sa.Column('tax_gross_up', sa.Boolean(), nullable=True)),
)
PAYMENT_COLUMNS = (
    ('installment_no', sa.Column('installment_no', sa.Integer(), server_default='1', nullable=False)),
    ('settles_invoice', sa.Column('settles_invoice', sa.Boolean(), server_default='true', nullable=False)),
    ('partial_reason', sa.Column('partial_reason', sa.Text(), nullable=True)),
    ('debit_memo_minor', sa.Column('debit_memo_minor', sa.BigInteger(), server_default='0', nullable=False)),
    ('tds_inr_minor', sa.Column('tds_inr_minor', sa.BigInteger(), nullable=True)),
    ('tds_base_inr_minor', sa.Column('tds_base_inr_minor', sa.BigInteger(), nullable=True)),
    ('tax_borne_minor', sa.Column('tax_borne_minor', sa.BigInteger(), server_default='0', nullable=False)),
    ('tax_detail', sa.Column('tax_detail', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False)),
)


def _base():
    return [
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
    ]


def _tail(table: str):
    return [
        sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f(f'fk_{table}_tenant_id_tenant')),
        sa.PrimaryKeyConstraint('id', name=op.f(f'pk_{table}')),
    ]


def upgrade() -> None:
    for _, column in INVOICE_COLUMNS:
        op.add_column('invoice', column.copy(), schema='pic')
    for _, column in PAYMENT_COLUMNS:
        op.add_column('payment', column.copy(), schema='pic')
    op.add_column('contract', sa.Column('tax_gross_up', sa.Boolean(), nullable=True), schema='pic')

    # Backfill: cash paid per invoice by its live payments (the debit-note payments are paid on their own and do not count).
    op.execute("""
        UPDATE pic.invoice i SET paid_minor = p.paid
        FROM (SELECT tenant_id, invoice_id, SUM(amount_minor) AS paid FROM pic.payment
              WHERE status <> 'CANCELLED' AND debit_note_id IS NULL GROUP BY tenant_id, invoice_id) p
        WHERE p.invoice_id = i.id AND p.tenant_id = i.tenant_id AND p.paid > 0""")
    # Sequence of the payments of each invoice in creation order (a payment returned by the bank and the one that paid the invoice again).
    op.execute("""
        UPDATE pic.payment p SET installment_no = n.seq
        FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY tenant_id, invoice_id ORDER BY created_at, number) AS seq
              FROM pic.payment WHERE debit_note_id IS NULL) n
        WHERE n.id = p.id AND n.seq <> 1""")
    # Debit notes netted into a payment, as its PAYMENT message carried them.
    op.execute("""
        UPDATE pic.payment p SET debit_memo_minor = (m.payload->>'debitMemoMinor')::bigint
        FROM pic.integration_message m
        WHERE m.tenant_id = p.tenant_id AND m.idempotency_key = 'PAY|' || p.number AND m.message_type = 'PAYMENT'
          AND p.debit_note_id IS NULL AND (m.payload->>'debitMemoMinor') ~ '^[0-9]+$'""")
    op.create_check_constraint('ck_invoice_paid_minor', 'invoice', 'paid_minor >= 0', schema='pic')

    op.drop_index('uq_payment_invoice_live', table_name='payment', schema='pic')
    op.create_index('uq_payment_invoice_live', 'payment', ['tenant_id', 'invoice_id'], unique=True, schema='pic',
                    postgresql_where=sa.text("status <> 'CANCELLED' AND debit_note_id IS NULL AND settles_invoice"))
    op.create_index('uq_payment_invoice_installment', 'payment', ['tenant_id', 'invoice_id', 'installment_no'], unique=True, schema='pic',
                    postgresql_where=sa.text("debit_note_id IS NULL"))

    op.create_table('supplier_tax_residency',
        sa.Column('supplier_id', sa.UUID(), nullable=False),
        sa.Column('residency', sa.String(length=15), nullable=False),
        sa.Column('country', sa.String(length=2), nullable=False),
        sa.Column('payee_type', sa.String(length=12), server_default='COMPANY', nullable=False),
        sa.Column('pan_enc', sa.LargeBinary(), nullable=True),
        sa.Column('pan_masked', sa.String(length=12), nullable=True),
        sa.Column('tax_id_enc', sa.LargeBinary(), nullable=True),
        sa.Column('tax_id_masked', sa.String(length=40), nullable=True),
        sa.Column('trc_no_enc', sa.LargeBinary(), nullable=True),
        sa.Column('trc_masked', sa.String(length=40), nullable=True),
        sa.Column('trc_valid_from', sa.Date(), nullable=True),
        sa.Column('trc_valid_to', sa.Date(), nullable=True),
        sa.Column('trc_document_ref', sa.String(length=200), nullable=True),
        sa.Column('form10f_ack_enc', sa.LargeBinary(), nullable=True),
        sa.Column('form10f_masked', sa.String(length=40), nullable=True),
        sa.Column('form10f_filed_on', sa.Date(), nullable=True),
        sa.Column('form10f_valid_from', sa.Date(), nullable=True),
        sa.Column('form10f_valid_to', sa.Date(), nullable=True),
        sa.Column('no_pe_declared', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('no_pe_valid_from', sa.Date(), nullable=True),
        sa.Column('no_pe_valid_to', sa.Date(), nullable=True),
        sa.Column('gross_up', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('default_nature', sa.String(length=20), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        *_base(), *_tail('supplier_tax_residency'),
        sa.ForeignKeyConstraint(['supplier_id'], ['pic.supplier.id'], name=op.f('fk_supplier_tax_residency_supplier_id_supplier')),
        sa.CheckConstraint("residency IN ('RESIDENT','NON_RESIDENT')", name='ck_supplier_tax_residency_residency'),
        sa.CheckConstraint("payee_type IN ('COMPANY','NON_COMPANY')", name='ck_supplier_tax_residency_payee_type'),
        sa.UniqueConstraint('tenant_id', 'supplier_id', name=op.f('uq_supplier_tax_residency_tenant_id_supplier_id')),
        schema='pic')
    op.create_table('remittance_certificate',
        sa.Column('invoice_id', sa.UUID(), nullable=False),
        sa.Column('supplier_id', sa.UUID(), nullable=False),
        sa.Column('payment_id', sa.UUID(), nullable=True),
        sa.Column('form15ca_part', sa.String(length=1), nullable=False),
        sa.Column('form15ca_ack_enc', sa.LargeBinary(), nullable=False),
        sa.Column('form15ca_ack_masked', sa.String(length=40), nullable=False),
        sa.Column('form15ca_ack_hash', sa.String(length=64), nullable=False),
        sa.Column('form15ca_filed_on', sa.Date(), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('form15cb_certificate_no', sa.String(length=40), nullable=True),
        sa.Column('form15cb_date', sa.Date(), nullable=True),
        sa.Column('ca_name', sa.String(length=200), nullable=True),
        sa.Column('ca_membership_no', sa.String(length=10), nullable=True),
        sa.Column('status', sa.String(length=10), server_default='RECORDED', nullable=False),
        sa.Column('void_reason', sa.Text(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        *_base(), *_tail('remittance_certificate'),
        sa.ForeignKeyConstraint(['invoice_id'], ['pic.invoice.id'], name=op.f('fk_remittance_certificate_invoice_id_invoice')),
        sa.ForeignKeyConstraint(['supplier_id'], ['pic.supplier.id'], name=op.f('fk_remittance_certificate_supplier_id_supplier')),
        sa.ForeignKeyConstraint(['payment_id'], ['pic.payment.id'], name=op.f('fk_remittance_certificate_payment_id_payment')),
        sa.CheckConstraint("status IN ('RECORDED','USED','VOID')", name='ck_remittance_certificate_status'),
        sa.CheckConstraint("form15ca_part IN ('A','B','C','D')", name='ck_remittance_certificate_form15ca_part'),
        sa.CheckConstraint('amount_minor > 0', name='ck_remittance_certificate_amount'),
        sa.UniqueConstraint('tenant_id', 'form15ca_ack_hash', name=op.f('uq_remittance_certificate_tenant_id_form15ca_ack_hash')),
        schema='pic')
    op.create_index('ix_remittance_certificate_invoice', 'remittance_certificate', ['tenant_id', 'invoice_id'], schema='pic')
    for table in NEW_TABLES:
        op.create_index(op.f(f'ix_{table}_tenant_id'), table, ['tenant_id'], unique=False, schema='pic')
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pic.{table} TO {ROLE}")
        op.execute(f"ALTER TABLE pic.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE pic.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON pic.{table} USING (tenant_id = {CTX}) WITH CHECK (tenant_id = {CTX})")


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON pic.{table}")
        op.drop_table(table, schema='pic')
    op.drop_index('uq_payment_invoice_installment', table_name='payment', schema='pic')
    op.drop_index('uq_payment_invoice_live', table_name='payment', schema='pic')
    # The old index allows one live payment per invoice: a database with live partial payments cannot be downgraded (the index build fails
    # and the downgrade rolls back) until those invoices are settled or their partial payments cancelled.
    op.create_index('uq_payment_invoice_live', 'payment', ['tenant_id', 'invoice_id'], unique=True, schema='pic',
                    postgresql_where=sa.text("status <> 'CANCELLED' AND debit_note_id IS NULL"))
    op.drop_constraint('ck_invoice_paid_minor', 'invoice', schema='pic', type_='check')
    op.drop_column('contract', 'tax_gross_up', schema='pic')
    for name, _ in reversed(PAYMENT_COLUMNS):
        op.drop_column('payment', name, schema='pic')
    for name, _ in reversed(INVOICE_COLUMNS):
        op.drop_column('invoice', name, schema='pic')
