"""Flow-audit fixes for plan to requisition (M01 to M04).

All changes are additive; nothing is dropped and existing rows keep their meaning.

- pr_line.sow, po_line.sow, event_line.sow: the structured statement of work of a category SOW form (template, title, full text, attributes).
  The line description stays the 200-character short text; the SOW travels with the line to the sourcing event and the purchase order.
- mrp_exception: plant (backfilled from the run), closed_at / closed_by / close_reason (closed by the MRP controller) and superseded_by_run_id
  (a newer run of the same material and plant replaced it). Existing OPEN exceptions that a later run of the same material and plant replaced
  are marked SUPERSEDED, so the M02.EXCEPTION_BACKLOG KPI counts only the exceptions still open.
- material_request.mrp_type (MRP type the new material is created with) and withdrawal_reason (requester withdrawal).
- catalogue_item: valid_from, valid_to, lead_time_days (hosted catalogue maintenance) and a supplier / part number index.
- Net-change MRP indexes on the supply tables: stock movements by plant and posting time, and "touched since" expression indexes
  (coalesce(updated_at, created_at)) on purchase orders, PO lines, ASNs, planned orders, requisitions and requisition lines; plus the open
  requisition supply index pr_line (material, plant).

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0023'
down_revision: Union[str, Sequence[str], None] = '0022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TOUCHED = "coalesce(updated_at, created_at)"
JSON = postgresql.JSONB(astext_type=sa.Text())
INDEXES = [
    # (name, table, columns)
    ('ix_mrp_exception_material_status', 'mrp_exception', ['tenant_id', 'material_id', 'status']),
    ('ix_catalogue_item_supplier_part', 'catalogue_item', ['tenant_id', 'supplier_id', 'supplier_part_no']),
    ('ix_stock_movement_plant_created', 'stock_movement', ['tenant_id', 'plant', 'created_at']),
    ('ix_pr_line_material_plant', 'pr_line', ['tenant_id', 'material_id', 'plant']),
    ('ix_pr_line_plant_touched', 'pr_line', ['tenant_id', 'plant', sa.text(TOUCHED)]),
    ('ix_requisition_touched', 'requisition', ['tenant_id', sa.text(TOUCHED)]),
    ('ix_planned_order_plant_touched', 'planned_order', ['tenant_id', 'plant', sa.text(TOUCHED)]),
    ('ix_purchase_order_touched', 'purchase_order', ['tenant_id', sa.text(TOUCHED)]),
    ('ix_po_line_plant_touched', 'po_line', ['tenant_id', 'plant', sa.text(TOUCHED)]),
    ('ix_asn_touched', 'asn', ['tenant_id', sa.text(TOUCHED)]),
]


def upgrade() -> None:
    def add(table, column):
        op.add_column(table, column, schema='pic')

    add('pr_line', sa.Column('sow', JSON, nullable=True))
    add('po_line', sa.Column('sow', JSON, nullable=True))
    add('event_line', sa.Column('sow', JSON, nullable=True))
    add('mrp_exception', sa.Column('plant', sa.String(length=10), nullable=True))
    add('mrp_exception', sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True))
    add('mrp_exception', sa.Column('closed_by', sa.UUID(), nullable=True))
    add('mrp_exception', sa.Column('close_reason', sa.Text(), nullable=True))
    add('mrp_exception', sa.Column('superseded_by_run_id', sa.UUID(), nullable=True))
    add('material_request', sa.Column('mrp_type', sa.String(length=4), nullable=True))
    add('material_request', sa.Column('withdrawal_reason', sa.Text(), nullable=True))
    add('catalogue_item', sa.Column('valid_from', sa.Date(), nullable=True))
    add('catalogue_item', sa.Column('valid_to', sa.Date(), nullable=True))
    add('catalogue_item', sa.Column('lead_time_days', sa.Integer(), nullable=True))
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns, unique=False, schema='pic')
    # backfill: the plant of every exception, then supersede the open exceptions a later run of the same material and plant replaced
    op.execute("UPDATE pic.mrp_exception e SET plant = r.plant FROM pic.mrp_run r WHERE r.id = e.mrp_run_id AND e.plant IS NULL")
    op.execute("""
        UPDATE pic.mrp_exception e SET status = 'SUPERSEDED', superseded_by_run_id = x.run_id, closed_at = x.created_at,
               close_reason = 'superseded by a later MRP run of the same material and plant (migration 0023)'
        FROM (SELECT DISTINCT ON (e2.tenant_id, e2.material_id, e2.plant) e2.tenant_id, e2.material_id, e2.plant, e2.mrp_run_id AS run_id,
                     r2.created_at
              FROM pic.mrp_exception e2 JOIN pic.mrp_run r2 ON r2.id = e2.mrp_run_id
              WHERE r2.mode <> 'SIMULATION'
              ORDER BY e2.tenant_id, e2.material_id, e2.plant, r2.created_at DESC) x
        WHERE e.tenant_id = x.tenant_id AND e.material_id = x.material_id AND e.plant = x.plant AND e.mrp_run_id <> x.run_id
          AND e.status = 'OPEN'
          AND (SELECT r3.created_at FROM pic.mrp_run r3 WHERE r3.id = e.mrp_run_id) < x.created_at""")


def downgrade() -> None:
    op.execute("UPDATE pic.mrp_exception SET status = 'OPEN' WHERE status IN ('SUPERSEDED', 'CLOSED')")
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table, schema='pic')
    for table, column in (('catalogue_item', 'lead_time_days'), ('catalogue_item', 'valid_to'), ('catalogue_item', 'valid_from'),
                          ('material_request', 'withdrawal_reason'), ('material_request', 'mrp_type'),
                          ('mrp_exception', 'superseded_by_run_id'), ('mrp_exception', 'close_reason'), ('mrp_exception', 'closed_by'),
                          ('mrp_exception', 'closed_at'), ('mrp_exception', 'plant'), ('event_line', 'sow'), ('po_line', 'sow'),
                          ('pr_line', 'sow')):
        op.drop_column(table, column, schema='pic')
