"""Finance completion (M10 / F7): MSME 45-day rule, TDS, foreign-currency invoices, posting periods, bank confirmation of payments, SoD.

- supplier: ``msme_class`` / ``udyam_no`` (MSMED Act s.15 payment rule), ``tds_section`` (key into rule set TDS).
- invoice: ``acceptance_date`` + ``msme_capped`` (45-day clock), ``tds_section`` / ``tds_rate`` / ``tds_base_minor``, ``fx_rate`` / ``fx_date`` /
  ``gross_group_minor`` (foreign-currency invoices), ``posting_date``.
- payment: ``bank_status`` / ``bank_utr`` / ``bank_confirmed_at`` / ``return_reason`` (bank acknowledgement per payment), ``tds_minor``.
- posting_period: closed periods per company code (cut-off); new tenant table with the pic_app grants and forced row-level security.
- debit_note: ``tds_base_minor`` / ``tds_minor`` (TDS on the additional taxable value); payment: ``tds_rate`` / ``tds_certificate`` (rate applied, s.197
  certificate used) and ``reversal_doc`` (ERP reversal document of a returned payment).
- grir_snapshot (GR/IR accrual per close), tds_certificate (s.197 lower-deduction certificates), bank_statement_import (camt.053 / MT940 imports,
  idempotent per statement id): new tenant tables with the pic_app grants and forced row-level security.
- sod_rule: SOD-08 (whoever captured an invoice may not approve it) and SOD-09 (whoever approved an invoice may not release its payment)
  for every existing tenant; new tenants get them from seed/reference.py.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-02 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0017'
down_revision: Union[str, Sequence[str], None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "pic_app"
NEW_TABLES = ("grir_snapshot", "tds_certificate", "bank_statement_import")
CTX = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
SOD = [
    ("SOD-08", "INVOICE_CAPTURE", "INVOICE_APPROVE", "invoice_id", "High", "Whoever captured an invoice may not approve it (four-eyes)"),
    ("SOD-09", "INVOICE_APPROVE", "PAYMENT_APPROVE", "invoice_id", "High", "Whoever approved an invoice may not release its payment"),
]


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


def _more_finance() -> None:
    op.add_column('debit_note', sa.Column('tds_base_minor', sa.BigInteger(), server_default='0', nullable=False), schema='pic')
    op.add_column('debit_note', sa.Column('tds_minor', sa.BigInteger(), server_default='0', nullable=False), schema='pic')
    op.add_column('payment', sa.Column('tds_base_minor', sa.BigInteger(), server_default='0', nullable=False), schema='pic')
    op.add_column('payment', sa.Column('tds_rate', sa.Numeric(6, 3), nullable=True), schema='pic')
    op.add_column('payment', sa.Column('tds_certificate', sa.String(length=40), nullable=True), schema='pic')
    op.add_column('payment', sa.Column('reversal_doc', sa.String(length=40), nullable=True), schema='pic')
    op.create_table('grir_snapshot',
        sa.Column('company_code', sa.String(length=10), nullable=False),
        sa.Column('period', sa.String(length=7), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closed_by', sa.UUID(), nullable=True),
        sa.Column('total_minor', sa.BigInteger(), nullable=False),
        sa.Column('line_count', sa.Integer(), nullable=False),
        sa.Column('lines', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_base(), *_tail('grir_snapshot'), schema='pic')
    op.create_index('ix_grir_snapshot_period', 'grir_snapshot', ['tenant_id', 'company_code', 'period'], schema='pic')
    op.create_table('tds_certificate',
        sa.Column('supplier_id', sa.UUID(), nullable=False),
        sa.Column('certificate_no', sa.String(length=40), nullable=False),
        sa.Column('section', sa.String(length=20), nullable=True),
        sa.Column('rate_pct', sa.Numeric(6, 3), nullable=False),
        sa.Column('valid_from', sa.Date(), nullable=False),
        sa.Column('valid_to', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('revoked_reason', sa.Text(), nullable=True),
        *_base(), *_tail('tds_certificate'),
        sa.ForeignKeyConstraint(['supplier_id'], ['pic.supplier.id'], name=op.f('fk_tds_certificate_supplier_id_supplier')),
        sa.CheckConstraint('rate_pct >= 0 AND rate_pct <= 100 AND valid_to >= valid_from', name='ck_tds_certificate_valid'),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED')", name='ck_tds_certificate_status'),
        sa.UniqueConstraint('tenant_id', 'supplier_id', 'certificate_no', name=op.f('uq_tds_certificate_tenant_id_supplier_id_certificate_no')),
        schema='pic')
    op.create_index('ix_tds_certificate_supplier', 'tds_certificate', ['tenant_id', 'supplier_id'], schema='pic')
    op.create_table('bank_statement_import',
        sa.Column('statement_id', sa.String(length=60), nullable=False),
        sa.Column('format', sa.String(length=10), nullable=False),
        sa.Column('account', sa.String(length=60), nullable=True),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('entries', sa.Integer(), nullable=False),
        sa.Column('credited', sa.Integer(), nullable=False),
        sa.Column('returned', sa.Integer(), nullable=False),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_base(), *_tail('bank_statement_import'),
        sa.UniqueConstraint('tenant_id', 'statement_id', name=op.f('uq_bank_statement_import_tenant_id_statement_id')),
        schema='pic')
    for table in NEW_TABLES:
        op.create_index(op.f(f'ix_{table}_tenant_id'), table, ['tenant_id'], unique=False, schema='pic')
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pic.{table} TO {ROLE}")
        op.execute(f"ALTER TABLE pic.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE pic.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON pic.{table} USING (tenant_id = {CTX}) WITH CHECK (tenant_id = {CTX})")


def upgrade() -> None:
    _more_finance()
    op.add_column('supplier', sa.Column('msme_class', sa.String(length=10), nullable=True), schema='pic')
    op.add_column('supplier', sa.Column('udyam_no', sa.String(length=30), nullable=True), schema='pic')
    op.add_column('supplier', sa.Column('tds_section', sa.String(length=20), nullable=True), schema='pic')
    op.add_column('invoice', sa.Column('acceptance_date', sa.Date(), nullable=True), schema='pic')
    op.add_column('invoice', sa.Column('msme_capped', sa.Boolean(), server_default='false', nullable=False), schema='pic')
    op.add_column('invoice', sa.Column('tds_section', sa.String(length=20), nullable=True), schema='pic')
    op.add_column('invoice', sa.Column('tds_rate', sa.Numeric(6, 3), nullable=True), schema='pic')
    op.add_column('invoice', sa.Column('tds_base_minor', sa.BigInteger(), server_default='0', nullable=False), schema='pic')
    op.add_column('invoice', sa.Column('fx_rate', sa.Numeric(18, 8), nullable=True), schema='pic')
    op.add_column('invoice', sa.Column('fx_date', sa.Date(), nullable=True), schema='pic')
    op.add_column('invoice', sa.Column('gross_group_minor', sa.BigInteger(), nullable=True), schema='pic')
    op.add_column('invoice', sa.Column('posting_date', sa.Date(), nullable=True), schema='pic')
    op.add_column('payment', sa.Column('bank_status', sa.String(length=10), server_default='NOT_SENT', nullable=False), schema='pic')
    op.add_column('payment', sa.Column('bank_utr', sa.String(length=40), nullable=True), schema='pic')
    op.add_column('payment', sa.Column('bank_confirmed_at', sa.DateTime(timezone=True), nullable=True), schema='pic')
    op.add_column('payment', sa.Column('return_reason', sa.Text(), nullable=True), schema='pic')
    op.add_column('payment', sa.Column('tds_minor', sa.BigInteger(), server_default='0', nullable=False), schema='pic')
    op.execute("ALTER TABLE pic.payment ADD CONSTRAINT ck_payment_bank_status CHECK (bank_status IN ('NOT_SENT','SENT','CREDITED','RETURNED'))")
    # Backfill: payments of a file already SENT / ACKNOWLEDGED keep that fact.
    op.execute("UPDATE pic.payment p SET bank_status = 'SENT' FROM pic.payment_file f "
               "WHERE f.run_ref = p.run_ref AND f.tenant_id = p.tenant_id AND f.status IN ('SENT','ACKNOWLEDGED')")
    # Backfill: invoices posted before this migration were posted on the day the ERP document was created.
    op.execute("UPDATE pic.invoice SET posting_date = posted_at::date WHERE posted_at IS NOT NULL AND posting_date IS NULL")

    op.create_table('posting_period',
        sa.Column('company_code', sa.String(length=10), nullable=False),
        sa.Column('period', sa.String(length=7), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('closed_by', sa.UUID(), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reopened_by', sa.UUID(), nullable=True),
        sa.Column('reopened_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('cutoff', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.CheckConstraint("status IN ('OPEN','CLOSED')", name='ck_posting_period_status'),
        sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_posting_period_tenant_id_tenant')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_posting_period')),
        sa.UniqueConstraint('tenant_id', 'company_code', 'period', name=op.f('uq_posting_period_tenant_id_company_code_period')),
        schema='pic')
    op.create_index(op.f('ix_posting_period_tenant_id'), 'posting_period', ['tenant_id'], unique=False, schema='pic')
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pic.posting_period TO {ROLE}")
    op.execute("ALTER TABLE pic.posting_period ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pic.posting_period FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON pic.posting_period USING (tenant_id = {CTX}) WITH CHECK (tenant_id = {CTX})")

    for code, a, b, scope, risk, description in SOD:
        op.execute(sa.text(
            "INSERT INTO pic.sod_rule (id, created_at, row_version, tenant_id, code, action_a, action_b, scope, risk, mode, description, active) "
            "SELECT gen_random_uuid(), now(), 1, t.id, :code, :a, :b, :scope, :risk, 'BLOCK', :description, true FROM pic.tenant t "
            "WHERE NOT EXISTS (SELECT 1 FROM pic.sod_rule r WHERE r.tenant_id = t.id AND r.code = :code)"
        ).bindparams(code=code, a=a, b=b, scope=scope, risk=risk, description=description))


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON pic.{table}")
        op.drop_table(table, schema='pic')
    for column in ('reversal_doc', 'tds_certificate', 'tds_rate', 'tds_base_minor'):
        op.drop_column('payment', column, schema='pic')
    for column in ('tds_minor', 'tds_base_minor'):
        op.drop_column('debit_note', column, schema='pic')
    op.execute("DELETE FROM pic.sod_rule WHERE code IN ('SOD-08', 'SOD-09')")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON pic.posting_period")
    op.drop_index(op.f('ix_posting_period_tenant_id'), table_name='posting_period', schema='pic')
    op.drop_table('posting_period', schema='pic')
    op.execute("ALTER TABLE pic.payment DROP CONSTRAINT IF EXISTS ck_payment_bank_status")
    for column in ('tds_minor', 'return_reason', 'bank_confirmed_at', 'bank_utr', 'bank_status'):
        op.drop_column('payment', column, schema='pic')
    for column in ('posting_date', 'gross_group_minor', 'fx_date', 'fx_rate', 'tds_base_minor', 'tds_rate', 'tds_section', 'msme_capped', 'acceptance_date'):
        op.drop_column('invoice', column, schema='pic')
    for column in ('tds_section', 'udyam_no', 'msme_class'):
        op.drop_column('supplier', column, schema='pic')
