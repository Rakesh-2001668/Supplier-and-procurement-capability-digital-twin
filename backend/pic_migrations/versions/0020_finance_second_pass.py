"""Finance second pass (M10 / F7): GST tax heads and reverse charge, TCS, s.197 certificate cap, MSME written agreement and interest accrual, TDS challans,
realised FX difference, foreign beneficiary bank details.

All changes are additive (new nullable / defaulted columns and two new tables); nothing existing is altered or dropped.

- invoice: ``place_of_supply``, ``cgst_minor`` / ``sgst_minor`` / ``igst_minor`` (tax heads), ``reverse_charge`` / ``rcm_tax_minor`` (self-assessed GST),
  ``tcs_section`` / ``tcs_rate`` / ``tcs_minor`` (TCS flag, rule TDS.tcs, off by default).
- invoice_line: ``tax_split`` (the heads the supplier charged).
- supplier: ``msme_written_agreement`` (15 days without a written agreement, 45 with one).
- supplier_bank_account: ``country``, ``swift_bic``, ``intermediary_bic``, ``charge_bearer``, ``purpose_code`` (foreign beneficiary payment files).
- tds_certificate: ``max_base_minor`` (amount cap of a s.197 certificate).
- payment: ``tds_cert_base_minor`` (base taxed at the certificate rate), ``tcs_minor``, ``fx_rate`` / ``amount_group_minor`` / ``fx_gain_loss_minor`` (realised FX).
- tds_challan (BSR code, challan serial, deposit date per quarter and section) and msme_interest (interest accrued per late MSME payment): new tenant tables
  with the pic_app grants and forced row-level security, like the other tenant tables.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-03 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0020'
down_revision: Union[str, Sequence[str], None] = '0019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "pic_app"
NEW_TABLES = ("tds_challan", "msme_interest")
CTX = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
INVOICE_COLUMNS = (
    ('place_of_supply', sa.Column('place_of_supply', sa.String(length=2), nullable=True)),
    ('cgst_minor', sa.Column('cgst_minor', sa.BigInteger(), server_default='0', nullable=False)),
    ('sgst_minor', sa.Column('sgst_minor', sa.BigInteger(), server_default='0', nullable=False)),
    ('igst_minor', sa.Column('igst_minor', sa.BigInteger(), server_default='0', nullable=False)),
    ('reverse_charge', sa.Column('reverse_charge', sa.Boolean(), server_default='false', nullable=False)),
    ('rcm_tax_minor', sa.Column('rcm_tax_minor', sa.BigInteger(), server_default='0', nullable=False)),
    ('tcs_section', sa.Column('tcs_section', sa.String(length=20), nullable=True)),
    ('tcs_rate', sa.Column('tcs_rate', sa.Numeric(6, 3), nullable=True)),
    ('tcs_minor', sa.Column('tcs_minor', sa.BigInteger(), server_default='0', nullable=False)),
)
PAYMENT_COLUMNS = (
    ('tds_cert_base_minor', sa.Column('tds_cert_base_minor', sa.BigInteger(), server_default='0', nullable=False)),
    ('tcs_minor', sa.Column('tcs_minor', sa.BigInteger(), server_default='0', nullable=False)),
    ('fx_rate', sa.Column('fx_rate', sa.Numeric(18, 8), nullable=True)),
    ('amount_group_minor', sa.Column('amount_group_minor', sa.BigInteger(), nullable=True)),
    ('fx_gain_loss_minor', sa.Column('fx_gain_loss_minor', sa.BigInteger(), nullable=True)),
)
BANK_COLUMNS = (
    ('country', sa.Column('country', sa.String(length=2), server_default='IN', nullable=False)),
    ('swift_bic', sa.Column('swift_bic', sa.String(length=11), nullable=True)),
    ('intermediary_bic', sa.Column('intermediary_bic', sa.String(length=11), nullable=True)),
    ('charge_bearer', sa.Column('charge_bearer', sa.String(length=4), nullable=True)),
    ('purpose_code', sa.Column('purpose_code', sa.String(length=10), nullable=True)),
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
    op.add_column('invoice_line', sa.Column('tax_split', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False), schema='pic')
    op.add_column('supplier', sa.Column('msme_written_agreement', sa.Boolean(), server_default='true', nullable=False), schema='pic')
    for _, column in BANK_COLUMNS:
        op.add_column('supplier_bank_account', column.copy(), schema='pic')
    op.add_column('tds_certificate', sa.Column('max_base_minor', sa.BigInteger(), nullable=True), schema='pic')
    for _, column in PAYMENT_COLUMNS:
        op.add_column('payment', column.copy(), schema='pic')
    op.create_table('tds_challan',
        sa.Column('company_code', sa.String(length=10), nullable=False),
        sa.Column('fiscal_year', sa.String(length=7), nullable=False),
        sa.Column('quarter', sa.String(length=2), nullable=False),
        sa.Column('section', sa.String(length=20), nullable=False),
        sa.Column('challan_no', sa.String(length=10), nullable=False),
        sa.Column('bsr_code', sa.String(length=7), nullable=False),
        sa.Column('deposit_date', sa.Date(), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('void_reason', sa.Text(), nullable=True),
        *_base(), *_tail('tds_challan'),
        sa.CheckConstraint('amount_minor > 0', name='ck_tds_challan_amount'),
        sa.CheckConstraint("status IN ('RECORDED','VOID')", name='ck_tds_challan_status'),
        sa.UniqueConstraint('tenant_id', 'bsr_code', 'deposit_date', 'challan_no', name=op.f('uq_tds_challan_tenant_id_bsr_code_deposit_date_challan_no')),
        schema='pic')
    op.create_index('ix_tds_challan_quarter', 'tds_challan', ['tenant_id', 'company_code', 'fiscal_year', 'quarter'], schema='pic')
    op.create_table('msme_interest',
        sa.Column('invoice_id', sa.UUID(), nullable=False),
        sa.Column('payment_id', sa.UUID(), nullable=False),
        sa.Column('supplier_id', sa.UUID(), nullable=False),
        sa.Column('company_code', sa.String(length=10), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('paid_on', sa.Date(), nullable=False),
        sa.Column('days_late', sa.Integer(), nullable=False),
        sa.Column('principal_minor', sa.BigInteger(), nullable=False),
        sa.Column('rate_pct', sa.Numeric(7, 3), nullable=False),
        sa.Column('interest_minor', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        *_base(), *_tail('msme_interest'),
        sa.ForeignKeyConstraint(['invoice_id'], ['pic.invoice.id'], name=op.f('fk_msme_interest_invoice_id_invoice')),
        sa.ForeignKeyConstraint(['payment_id'], ['pic.payment.id'], name=op.f('fk_msme_interest_payment_id_payment')),
        sa.ForeignKeyConstraint(['supplier_id'], ['pic.supplier.id'], name=op.f('fk_msme_interest_supplier_id_supplier')),
        sa.CheckConstraint("status IN ('ACCRUED','WAIVED','SETTLED')", name='ck_msme_interest_status'),
        sa.UniqueConstraint('tenant_id', 'payment_id', name=op.f('uq_msme_interest_tenant_id_payment_id')),
        schema='pic')
    op.create_index('ix_msme_interest_supplier', 'msme_interest', ['tenant_id', 'supplier_id'], schema='pic')
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
    for name, _ in PAYMENT_COLUMNS:
        op.drop_column('payment', name, schema='pic')
    op.drop_column('tds_certificate', 'max_base_minor', schema='pic')
    for name, _ in BANK_COLUMNS:
        op.drop_column('supplier_bank_account', name, schema='pic')
    op.drop_column('supplier', 'msme_written_agreement', schema='pic')
    op.drop_column('invoice_line', 'tax_split', schema='pic')
    for name, _ in INVOICE_COLUMNS:
        op.drop_column('invoice', name, schema='pic')
