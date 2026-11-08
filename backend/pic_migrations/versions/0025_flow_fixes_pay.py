"""Flow-audit fixes for receiving, invoice-to-pay, savings, AI and the platform (M09 to M12).

All changes are additive; nothing is dropped and existing rows keep their meaning.

- return_delivery.settled_qty / settlements / closed_at: how a return delivery was settled (credit notes or replacement receipts, or closed
  by hand with a reason) and when it closed. Existing returns start unsettled (0, [], NULL) and keep their status: the credit notes and
  replacement receipts that arrive from now on settle them.
- ix_invoice_tenant_supplier_invoice_no: look-up of an invoice by the supplier's own invoice number across suppliers and company codes
  (Copilot document look-up; the unique key starts with company code and supplier).

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-07 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0025'
down_revision: Union[str, Sequence[str], None] = '0024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('return_delivery', sa.Column('settled_qty', sa.Numeric(precision=18, scale=3), server_default='0', nullable=False), schema='pic')
    op.add_column('return_delivery', sa.Column('settlements', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
                  schema='pic')
    op.add_column('return_delivery', sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True), schema='pic')
    op.create_index('ix_invoice_tenant_supplier_invoice_no', 'invoice', ['tenant_id', 'supplier_invoice_no'], unique=False, schema='pic')


def downgrade() -> None:
    op.drop_index('ix_invoice_tenant_supplier_invoice_no', table_name='invoice', schema='pic')
    op.drop_column('return_delivery', 'closed_at', schema='pic')
    op.drop_column('return_delivery', 'settlements', schema='pic')
    op.drop_column('return_delivery', 'settled_qty', schema='pic')
