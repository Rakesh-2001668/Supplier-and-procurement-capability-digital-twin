"""Flow-audit fixes for sourcing, suppliers, contracts and purchase orders (M05 to M08).

All changes are additive; nothing is dropped and existing rows keep their meaning.

- purchase_order.origin (REQUISITION | CONTRACT | PLANNED_ORDER | MANUAL; existing orders: REQUISITION, or IMPORTED when no line came from a
  requisition, e.g. open orders loaded from the ERP), fx_rate / fx_date (reference rate of a foreign-currency order, fixed at creation) and
  reason (why a manual order was raised without a requisition).
- contract.renews_contract_id (successor renewal: the contract this one renews; the predecessor becomes RENEWED) and contract.erp_doc_no
  (ERP outline agreement of the current version).
- number ranges per sourcing event type (RFI-, RFP-, AUC-) and per contract type (QC-, VC-, RC-, SOW-, MA-, NDA-) for every existing
  tenant. They number NEW documents only: RFQs keep the SOURCING_EVENT range and scheduling agreements the CONTRACT range (RFQ-2231 and
  SA-5520 of the signature case); documents already numbered keep their numbers.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-07 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0024'
down_revision: Union[str, Sequence[str], None] = '0023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (object type, prefix, first number, padding): the same as seed/reference.py NUMBER_RANGES
RANGES = [
    ("SOURCING_EVENT_RFI", "RFI-", 1101, 0), ("SOURCING_EVENT_RFP", "RFP-", 3101, 0), ("SOURCING_EVENT_AUC", "AUC-", 4101, 0),
    ("CONTRACT_QC", "QC-", 6101, 0), ("CONTRACT_VC", "VC-", 6501, 0), ("CONTRACT_RC", "RC-", 7101, 0), ("CONTRACT_SOW", "SOW-", 7501, 0),
    ("CONTRACT_MA", "MA-", 8101, 0), ("CONTRACT_NDA", "NDA-", 8501, 0),
]


def upgrade() -> None:
    op.add_column('purchase_order', sa.Column('origin', sa.String(length=20), server_default='REQUISITION', nullable=False), schema='pic')
    op.add_column('purchase_order', sa.Column('fx_rate', sa.Numeric(precision=18, scale=8), nullable=True), schema='pic')
    op.add_column('purchase_order', sa.Column('fx_date', sa.Date(), nullable=True), schema='pic')
    op.add_column('purchase_order', sa.Column('reason', sa.Text(), nullable=True), schema='pic')
    op.add_column('contract', sa.Column('renews_contract_id', sa.UUID(), nullable=True), schema='pic')
    op.add_column('contract', sa.Column('erp_doc_no', sa.String(length=40), nullable=True), schema='pic')
    op.create_foreign_key(op.f('fk_contract_renews_contract_id_contract'), 'contract', 'contract', ['renews_contract_id'], ['id'],
                          source_schema='pic', referent_schema='pic')
    op.execute("UPDATE pic.purchase_order po SET origin = 'IMPORTED' WHERE NOT EXISTS "
               "(SELECT 1 FROM pic.po_line l WHERE l.po_id = po.id AND l.requisition_id IS NOT NULL)")
    for object_type, prefix, first, padding in RANGES:
        op.execute(sa.text(
            "INSERT INTO pic.number_range (id, created_at, row_version, tenant_id, object_type, prefix, next_value, padding) "
            "SELECT gen_random_uuid(), now(), 1, t.id, :t, :p, :n, :pad FROM pic.tenant t "
            "WHERE EXISTS (SELECT 1 FROM pic.number_range r0 WHERE r0.tenant_id = t.id) "
            "AND NOT EXISTS (SELECT 1 FROM pic.number_range r WHERE r.tenant_id = t.id AND r.object_type = :t)"
        ).bindparams(t=object_type, p=prefix, n=first, pad=padding))


def downgrade() -> None:
    op.execute("DELETE FROM pic.number_range WHERE object_type IN (" + ", ".join(f"'{r[0]}'" for r in RANGES) + ")")
    op.drop_constraint(op.f('fk_contract_renews_contract_id_contract'), 'contract', schema='pic', type_='foreignkey')
    op.drop_column('contract', 'erp_doc_no', schema='pic')
    op.drop_column('contract', 'renews_contract_id', schema='pic')
    op.drop_column('purchase_order', 'reason', schema='pic')
    op.drop_column('purchase_order', 'fx_date', schema='pic')
    op.drop_column('purchase_order', 'fx_rate', schema='pic')
    op.drop_column('purchase_order', 'origin', schema='pic')
