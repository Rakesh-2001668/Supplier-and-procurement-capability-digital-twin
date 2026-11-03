"""Batch master for opening balances: ``stock_batch`` (expiry and manufacturing date per material and batch).

A goods receipt carries its batch expiry on ``gr_line``; an opening balance (the loader ``tools/stock_opening_load.py``, an ERP stock extract with the
SAP batch master MCH1) has no goods receipt, so its expiry had nowhere to live and the expiry alerts, first-expiry-first-out and the minimum shelf
life could not see it. The new table is additive (no existing table or column changes); it gets the pic_app grants and forced row-level security like
the other tenant tables.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-02 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0019'
down_revision: Union[str, Sequence[str], None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "pic_app"
CTX = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table('stock_batch',
        sa.Column('material_id', sa.UUID(), nullable=False),
        sa.Column('batch', sa.String(length=30), nullable=False),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('manufactured_date', sa.Date(), nullable=True),
        sa.Column('source', sa.String(length=30), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_stock_batch_tenant_id_tenant')),
        sa.ForeignKeyConstraint(['material_id'], ['pic.material.id'], name=op.f('fk_stock_batch_material_id_material')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_stock_batch')),
        sa.CheckConstraint('expiry_date IS NULL OR manufactured_date IS NULL OR expiry_date >= manufactured_date', name='ck_stock_batch_expiry_after_manufacture'),
        sa.UniqueConstraint('tenant_id', 'material_id', 'batch', name=op.f('uq_stock_batch_tenant_id_material_id_batch')),
        schema='pic')
    op.create_index(op.f('ix_stock_batch_tenant_id'), 'stock_batch', ['tenant_id'], unique=False, schema='pic')
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pic.stock_batch TO {ROLE}")
    op.execute("ALTER TABLE pic.stock_batch ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE pic.stock_batch FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON pic.stock_batch USING (tenant_id = {CTX}) WITH CHECK (tenant_id = {CTX})")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON pic.stock_batch")
    op.drop_table('stock_batch', schema='pic')
