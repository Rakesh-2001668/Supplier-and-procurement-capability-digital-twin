"""Wave 1 procure-to-pay completion: debit notes, inbound EDI interchanges, early-payment / SCF offers, receipt tolerance overrides,
one-time-vendor exception on purchase orders, supplier-group rule scope.

New tables get forced RLS and pic_app grants like every tenant table.

Revision ID: 0009
Revises: 0007
Create Date: 2026-10-30 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "pic_app"
NEW_TABLES = ("debit_note", "edi_interchange", "early_payment_offer", "receipt_tolerance")
BASE = [
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
]


def _base():
    return [c.copy() for c in BASE]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('debit_note',
        sa.Column('number', sa.String(length=40), nullable=False),
        sa.Column('supplier_debit_note_no', sa.String(length=40), nullable=False),
        sa.Column('supplier_id', sa.UUID(), nullable=False),
        sa.Column('invoice_id', sa.UUID(), nullable=False),
        sa.Column('note_date', sa.Date(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('net_minor', sa.BigInteger(), nullable=False),
        sa.Column('tax_minor', sa.BigInteger(), nullable=False),
        sa.Column('gross_minor', sa.BigInteger(), nullable=False),
        sa.Column('retention_minor', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('lines', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('match_result', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('approved_by', sa.UUID(), nullable=True),
        sa.Column('posting_key', sa.String(length=200), nullable=True),
        sa.Column('erp_doc_no', sa.String(length=40), nullable=True),
        sa.Column('payment_status', sa.String(length=15), server_default='UNPAID', nullable=False),
        sa.Column('rule_set_version', sa.String(length=80), nullable=True),
        *_base(),
        sa.CheckConstraint("status IN ('RECEIVED','MATCHED','PENDING_APPROVAL','APPROVED','POSTED','REJECTED')", name=op.f('ck_debit_note_status')),
        sa.CheckConstraint('net_minor > 0 AND tax_minor >= 0 AND gross_minor = net_minor + tax_minor', name=op.f('ck_debit_note_amounts')),
        sa.ForeignKeyConstraint(['invoice_id'], ['pic.invoice.id'], name=op.f('fk_debit_note_invoice_id_invoice')),
        sa.ForeignKeyConstraint(['supplier_id'], ['pic.supplier.id'], name=op.f('fk_debit_note_supplier_id_supplier')),
        sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_debit_note_tenant_id_tenant')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_debit_note')),
        sa.UniqueConstraint('tenant_id', 'number', name='uq_debit_note_tenant_number'),
        sa.UniqueConstraint('tenant_id', 'supplier_id', 'supplier_debit_note_no', name='uq_debit_note_supplier_no'),
        schema='pic')
    op.create_index(op.f('ix_debit_note_tenant_id'), 'debit_note', ['tenant_id'], unique=False, schema='pic')
    op.create_index('ix_debit_note_invoice', 'debit_note', ['tenant_id', 'invoice_id'], unique=False, schema='pic')

    op.create_table('edi_interchange',
        sa.Column('sender', sa.String(length=35), nullable=False),
        sa.Column('receiver', sa.String(length=35), nullable=False),
        sa.Column('control_ref', sa.String(length=14), nullable=False),
        sa.Column('supplier_id', sa.UUID(), nullable=True),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('message_types', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('raw', sa.Text(), nullable=False),
        sa.Column('contrl', sa.Text(), nullable=False),
        sa.Column('aperak', sa.Text(), nullable=True),
        *_base(),
        sa.CheckConstraint("status IN ('ACCEPTED','PARTIAL','REJECTED')", name=op.f('ck_edi_interchange_status')),
        sa.ForeignKeyConstraint(['supplier_id'], ['pic.supplier.id'], name=op.f('fk_edi_interchange_supplier_id_supplier')),
        sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_edi_interchange_tenant_id_tenant')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_edi_interchange')),
        sa.UniqueConstraint('tenant_id', 'sender', 'control_ref', name='uq_edi_interchange_ref'),
        schema='pic')
    op.create_index(op.f('ix_edi_interchange_tenant_id'), 'edi_interchange', ['tenant_id'], unique=False, schema='pic')

    op.create_table('early_payment_offer',
        sa.Column('invoice_id', sa.UUID(), nullable=False),
        sa.Column('supplier_id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('discount_pct', sa.Numeric(precision=6, scale=3), nullable=False),
        sa.Column('discount_minor', sa.BigInteger(), nullable=False),
        sa.Column('pay_on', sa.Date(), nullable=True),
        sa.Column('original_due', sa.Date(), nullable=True),
        sa.Column('expires_on', sa.Date(), nullable=False),
        sa.Column('annualised_pct', sa.Numeric(precision=7, scale=2), nullable=True),
        sa.Column('offered_by', sa.UUID(), nullable=False),
        sa.Column('decided_by', sa.UUID(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('erp_doc_no', sa.String(length=40), nullable=True),
        *_base(),
        sa.CheckConstraint("kind IN ('DISCOUNT','SCF')", name=op.f('ck_early_payment_offer_kind')),
        sa.CheckConstraint("status IN ('OFFERED','ACCEPTED','DECLINED','EXPIRED','APPLIED','CANCELLED')", name=op.f('ck_early_payment_offer_status')),
        sa.CheckConstraint("source IN ('TERMS','BUYER','SUPPLIER')", name=op.f('ck_early_payment_offer_source')),
        sa.CheckConstraint('discount_pct >= 0 AND discount_pct < 100 AND discount_minor >= 0', name=op.f('ck_early_payment_offer_discount')),
        sa.ForeignKeyConstraint(['invoice_id'], ['pic.invoice.id'], name=op.f('fk_early_payment_offer_invoice_id_invoice')),
        sa.ForeignKeyConstraint(['supplier_id'], ['pic.supplier.id'], name=op.f('fk_early_payment_offer_supplier_id_supplier')),
        sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_early_payment_offer_tenant_id_tenant')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_early_payment_offer')),
        schema='pic')
    op.create_index(op.f('ix_early_payment_offer_tenant_id'), 'early_payment_offer', ['tenant_id'], unique=False, schema='pic')
    op.create_index('ix_early_payment_offer_invoice', 'early_payment_offer', ['tenant_id', 'invoice_id'], unique=False, schema='pic')
    op.create_index('uq_early_payment_offer_live', 'early_payment_offer', ['tenant_id', 'invoice_id'], unique=True, schema='pic',
                    postgresql_where=sa.text("status IN ('OFFERED','ACCEPTED')"))

    op.create_table('receipt_tolerance',
        sa.Column('material_id', sa.UUID(), nullable=True),
        sa.Column('supplier_id', sa.UUID(), nullable=True),
        sa.Column('over_pct', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('under_pct', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('set_by', sa.UUID(), nullable=False),
        *_base(),
        sa.CheckConstraint('material_id IS NOT NULL OR supplier_id IS NOT NULL', name=op.f('ck_receipt_tolerance_scope')),
        sa.CheckConstraint('over_pct >= 0 AND over_pct <= 100 AND under_pct >= 0 AND under_pct <= 100', name=op.f('ck_receipt_tolerance_pct_range')),
        sa.ForeignKeyConstraint(['material_id'], ['pic.material.id'], name=op.f('fk_receipt_tolerance_material_id_material')),
        sa.ForeignKeyConstraint(['supplier_id'], ['pic.supplier.id'], name=op.f('fk_receipt_tolerance_supplier_id_supplier')),
        sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_receipt_tolerance_tenant_id_tenant')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_receipt_tolerance')),
        schema='pic')
    op.create_index(op.f('ix_receipt_tolerance_tenant_id'), 'receipt_tolerance', ['tenant_id'], unique=False, schema='pic')
    op.execute("CREATE UNIQUE INDEX uq_receipt_tolerance_scope ON pic.receipt_tolerance (tenant_id, "
               "COALESCE(material_id, '00000000-0000-0000-0000-000000000000'::uuid), "
               "COALESCE(supplier_id, '00000000-0000-0000-0000-000000000000'::uuid))")

    # Columns on existing tables.
    op.add_column('invoice', sa.Column('payment_option', sa.String(length=15), server_default='STANDARD', nullable=False), schema='pic')
    op.add_column('invoice', sa.Column('discount_minor', sa.BigInteger(), server_default='0', nullable=False), schema='pic')
    op.create_check_constraint('ck_invoice_payment_option', 'invoice', "payment_option IN ('STANDARD','EARLY_DISCOUNT','SCF')", schema='pic')
    op.add_column('payment', sa.Column('debit_note_id', sa.UUID(), nullable=True), schema='pic')
    op.drop_index('uq_payment_invoice_live', table_name='payment', schema='pic')
    op.create_index('uq_payment_invoice_live', 'payment', ['tenant_id', 'invoice_id'], unique=True, schema='pic',
                    postgresql_where=sa.text("status <> 'CANCELLED' AND debit_note_id IS NULL"))
    op.create_index('uq_payment_debit_note_live', 'payment', ['tenant_id', 'debit_note_id'], unique=True, schema='pic',
                    postgresql_where=sa.text("status <> 'CANCELLED' AND debit_note_id IS NOT NULL"))
    op.add_column('purchase_order', sa.Column('one_time_vendor', postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema='pic')
    op.add_column('po_line', sa.Column('over_tol_pct', sa.Numeric(precision=5, scale=2), nullable=True), schema='pic')
    op.add_column('po_line', sa.Column('under_tol_pct', sa.Numeric(precision=5, scale=2), nullable=True), schema='pic')
    op.add_column('rule_set', sa.Column('supplier_group', sa.String(length=30), nullable=True), schema='pic')
    op.add_column('supplier', sa.Column('supplier_group', sa.String(length=30), nullable=True), schema='pic')

    for table in NEW_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pic.{table} TO {ROLE}")
        op.execute(f"ALTER TABLE pic.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE pic.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON pic.{table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)""")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('supplier', 'supplier_group', schema='pic')
    op.drop_column('rule_set', 'supplier_group', schema='pic')
    op.drop_column('po_line', 'under_tol_pct', schema='pic')
    op.drop_column('po_line', 'over_tol_pct', schema='pic')
    op.drop_column('purchase_order', 'one_time_vendor', schema='pic')
    op.drop_index('uq_payment_debit_note_live', table_name='payment', schema='pic')
    op.drop_index('uq_payment_invoice_live', table_name='payment', schema='pic')
    op.create_index('uq_payment_invoice_live', 'payment', ['tenant_id', 'invoice_id'], unique=True, schema='pic',
                    postgresql_where=sa.text("status <> 'CANCELLED'"))
    op.drop_column('payment', 'debit_note_id', schema='pic')
    op.drop_constraint('ck_invoice_payment_option', 'invoice', schema='pic', type_='check')
    op.drop_column('invoice', 'discount_minor', schema='pic')
    op.drop_column('invoice', 'payment_option', schema='pic')
    op.execute("DROP INDEX IF EXISTS pic.uq_receipt_tolerance_scope")
    op.drop_index(op.f('ix_receipt_tolerance_tenant_id'), table_name='receipt_tolerance', schema='pic')
    op.drop_table('receipt_tolerance', schema='pic')
    op.drop_index('uq_early_payment_offer_live', table_name='early_payment_offer', schema='pic')
    op.drop_index('ix_early_payment_offer_invoice', table_name='early_payment_offer', schema='pic')
    op.drop_index(op.f('ix_early_payment_offer_tenant_id'), table_name='early_payment_offer', schema='pic')
    op.drop_table('early_payment_offer', schema='pic')
    op.drop_index(op.f('ix_edi_interchange_tenant_id'), table_name='edi_interchange', schema='pic')
    op.drop_table('edi_interchange', schema='pic')
    op.drop_index('ix_debit_note_invoice', table_name='debit_note', schema='pic')
    op.drop_index(op.f('ix_debit_note_tenant_id'), table_name='debit_note', schema='pic')
    op.drop_table('debit_note', schema='pic')
