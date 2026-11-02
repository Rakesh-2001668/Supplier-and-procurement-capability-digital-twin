"""Inventory completion (M09 stock): governed stock postings, physical inventory, reservations, ledger values, indexes and constraints.

- stock_movement: ``value_minor`` (quantity at the standard price when posted), ``posting_ref`` (STP- / PHI- / RSV- document) and ``reason_code``;
  indexes (tenant, material, plant, created_at) and (tenant, reference_type, reference_id) for the movement ledger and the document lookups.
- stock: index (tenant, plant, stock_type), CHECK on the stock-type domain and CHECK qty >= 0 (the posting primitive already refuses a negative balance;
  the migration refuses to run when existing rows already violate either check, and names them).
- gr_line: index (tenant, material, batch) and a GIN index on ``serials`` (the "serial number already received" check is one indexed query).
- stock_posting / stock_posting_line, physical_inventory / physical_inventory_line, stock_reservation: new tenant tables with the pic_app grants and
  forced row-level security.
- for every existing tenant: SOD-10 (whoever submitted a stock posting may not approve it) and SOD-11 (whoever counted may not approve the count),
  the number ranges STP- / PHI- / RSV-, and the rule sets INVENTORY-POSTING, INVENTORY-COUNT, INVENTORY-RESERVATION, INVENTORY-ALERTS (the
  documented defaults of platform/inventory_defaults.py; new tenants get them from seed/reference.py).

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-02 18:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0018'
down_revision: Union[str, Sequence[str], None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "pic_app"
NEW_TABLES = ("stock_posting", "stock_posting_line", "physical_inventory", "physical_inventory_line", "stock_reservation")
CTX = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
SOD = [
    ("SOD-10", "INVENTORY_POST", "INVENTORY_APPROVE", "posting_id", "High", "Whoever submitted a stock posting may not approve it (maker-checker)"),
    ("SOD-11", "INVENTORY_COUNT", "INVENTORY_COUNT_APPROVE", "count_id", "High", "Whoever counted or recounted stock may not approve the differences of that count"),
]
RANGES = [("STOCK_POSTING", "STP-", 1001, 0), ("PHYSICAL_INVENTORY", "PHI-", 1001, 0), ("STOCK_RESERVATION", "RSV-", 1001, 0)]
STOCK_TYPES = "('UNRESTRICTED','QUALITY','BLOCKED','CONSIGNMENT','SUBCONTRACTOR')"


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


def _ledger() -> None:
    bad = op.get_bind().execute(sa.text(
        "SELECT count(*) FILTER (WHERE qty < 0), count(*) FILTER (WHERE stock_type NOT IN ('UNRESTRICTED','QUALITY','BLOCKED','CONSIGNMENT','SUBCONTRACTOR')) "
        "FROM pic.stock")).one()
    if bad[0] or bad[1]:
        raise RuntimeError(f"pic.stock holds {bad[0]} row(s) with a negative quantity and {bad[1]} row(s) with an unknown stock type: correct them "
                           "(a physical inventory or an ERP stock sync) before applying migration 0018")
    op.add_column('stock_movement', sa.Column('value_minor', sa.BigInteger(), nullable=True), schema='pic')
    op.add_column('stock_movement', sa.Column('posting_ref', sa.String(length=60), nullable=True), schema='pic')
    op.add_column('stock_movement', sa.Column('reason_code', sa.String(length=30), nullable=True), schema='pic')
    op.create_index('ix_stock_movement_material_plant_created', 'stock_movement', ['tenant_id', 'material_id', 'plant', 'created_at'], schema='pic')
    op.create_index('ix_stock_movement_reference', 'stock_movement', ['tenant_id', 'reference_type', 'reference_id'], schema='pic')
    op.create_index('ix_stock_plant_type', 'stock', ['tenant_id', 'plant', 'stock_type'], schema='pic')
    op.execute(f"ALTER TABLE pic.stock ADD CONSTRAINT ck_stock_stock_type CHECK (stock_type IN {STOCK_TYPES})")
    op.execute("ALTER TABLE pic.stock ADD CONSTRAINT ck_stock_qty_not_negative CHECK (qty >= 0)")
    op.create_index('ix_gr_line_material_batch', 'gr_line', ['tenant_id', 'material_id', 'batch'], schema='pic')
    op.create_index('ix_gr_line_serials', 'gr_line', ['serials'], schema='pic', postgresql_using='gin')


def _tables() -> None:
    op.create_table('stock_posting',
        sa.Column('number', sa.String(length=30), nullable=False),
        sa.Column('posting_type', sa.String(length=15), nullable=False),
        sa.Column('status', sa.String(length=15), nullable=False),
        sa.Column('company_code', sa.String(length=10), nullable=False),
        sa.Column('plant', sa.String(length=10), nullable=False),
        sa.Column('posting_date', sa.Date(), nullable=False),
        sa.Column('reason_code', sa.String(length=30), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('total_value_minor', sa.BigInteger(), nullable=False),
        sa.Column('auto_posted', sa.Boolean(), nullable=False),
        sa.Column('rule_set_version', sa.String(length=80), nullable=True),
        sa.Column('submitted_by', sa.UUID(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.UUID(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('posted_by', sa.UUID(), nullable=True),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision_comment', sa.Text(), nullable=True),
        sa.Column('erp_doc_no', sa.String(length=40), nullable=True),
        *_base(), *_tail('stock_posting'),
        sa.CheckConstraint("posting_type IN ('TRANSFER','BLOCK','UNBLOCK','RELEASE_QUALITY','SCRAP')", name='ck_stock_posting_type'),
        sa.CheckConstraint("status IN ('DRAFT','SUBMITTED','APPROVED','POSTED','REJECTED','CANCELLED')", name='ck_stock_posting_status'),
        sa.UniqueConstraint('tenant_id', 'number', name=op.f('uq_stock_posting_tenant_id_number')),
        schema='pic')
    op.create_index('ix_stock_posting_status', 'stock_posting', ['tenant_id', 'status', 'plant'], schema='pic')
    op.create_table('stock_posting_line',
        sa.Column('posting_id', sa.UUID(), nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('material_id', sa.UUID(), nullable=False),
        sa.Column('batch', sa.String(length=30), nullable=False),
        sa.Column('qty', sa.Numeric(18, 3), nullable=False),
        sa.Column('from_plant', sa.String(length=10), nullable=False),
        sa.Column('from_storage_location', sa.String(length=10), nullable=False),
        sa.Column('from_stock_type', sa.String(length=15), nullable=False),
        sa.Column('to_plant', sa.String(length=10), nullable=True),
        sa.Column('to_storage_location', sa.String(length=10), nullable=True),
        sa.Column('to_stock_type', sa.String(length=15), nullable=True),
        sa.Column('movement_type', sa.String(length=5), nullable=False),
        sa.Column('unit_price_minor', sa.BigInteger(), nullable=True),
        sa.Column('value_minor', sa.BigInteger(), nullable=False),
        *_base(), *_tail('stock_posting_line'),
        sa.ForeignKeyConstraint(['posting_id'], ['pic.stock_posting.id'], name=op.f('fk_stock_posting_line_posting_id_stock_posting')),
        sa.ForeignKeyConstraint(['material_id'], ['pic.material.id'], name=op.f('fk_stock_posting_line_material_id_material')),
        sa.CheckConstraint('qty > 0', name='ck_stock_posting_line_qty_positive'),
        sa.UniqueConstraint('tenant_id', 'posting_id', 'line_no', name=op.f('uq_stock_posting_line_tenant_id_posting_id_line_no')),
        schema='pic')
    op.create_index('ix_stock_posting_line_posting', 'stock_posting_line', ['tenant_id', 'posting_id'], schema='pic')
    op.create_table('physical_inventory',
        sa.Column('number', sa.String(length=30), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('company_code', sa.String(length=10), nullable=False),
        sa.Column('plant', sa.String(length=10), nullable=False),
        sa.Column('storage_location', sa.String(length=10), nullable=False),
        sa.Column('material_group', sa.String(length=30), nullable=True),
        sa.Column('scope', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('planned_date', sa.Date(), nullable=True),
        sa.Column('frozen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('line_count', sa.Integer(), nullable=False),
        sa.Column('gain_minor', sa.BigInteger(), nullable=False),
        sa.Column('loss_minor', sa.BigInteger(), nullable=False),
        sa.Column('accuracy_pct', sa.Numeric(6, 2), nullable=True),
        sa.Column('rule_set_version', sa.String(length=80), nullable=True),
        sa.Column('submitted_by', sa.UUID(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', sa.UUID(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('posted_by', sa.UUID(), nullable=True),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision_comment', sa.Text(), nullable=True),
        sa.Column('erp_doc_no', sa.String(length=40), nullable=True),
        *_base(), *_tail('physical_inventory'),
        sa.CheckConstraint("status IN ('PLANNED','COUNTING','COUNTED','PENDING_APPROVAL','APPROVED','POSTED','CANCELLED')", name='ck_physical_inventory_status'),
        sa.UniqueConstraint('tenant_id', 'number', name=op.f('uq_physical_inventory_tenant_id_number')),
        schema='pic')
    op.create_index('ix_physical_inventory_status', 'physical_inventory', ['tenant_id', 'status', 'plant'], schema='pic')
    op.create_table('physical_inventory_line',
        sa.Column('inventory_id', sa.UUID(), nullable=False),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('material_id', sa.UUID(), nullable=False),
        sa.Column('batch', sa.String(length=30), nullable=False),
        sa.Column('stock_type', sa.String(length=15), nullable=False),
        sa.Column('book_qty', sa.Numeric(18, 3), nullable=False),
        sa.Column('unit_price_minor', sa.BigInteger(), nullable=True),
        sa.Column('unlisted', sa.Boolean(), nullable=False),
        sa.Column('count_status', sa.String(length=20), nullable=False),
        sa.Column('counted_qty', sa.Numeric(18, 3), nullable=True),
        sa.Column('counted_by', sa.UUID(), nullable=True),
        sa.Column('counted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('first_count_ok', sa.Boolean(), nullable=True),
        sa.Column('recount_qty', sa.Numeric(18, 3), nullable=True),
        sa.Column('recounted_by', sa.UUID(), nullable=True),
        sa.Column('recounted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('recount_reason', sa.Text(), nullable=True),
        sa.Column('final_qty', sa.Numeric(18, 3), nullable=True),
        sa.Column('diff_qty', sa.Numeric(18, 3), nullable=True),
        sa.Column('diff_value_minor', sa.BigInteger(), nullable=True),
        sa.Column('posted_qty', sa.Numeric(18, 3), nullable=True),
        sa.Column('drift_qty', sa.Numeric(18, 3), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        *_base(), *_tail('physical_inventory_line'),
        sa.ForeignKeyConstraint(['inventory_id'], ['pic.physical_inventory.id'], name=op.f('fk_physical_inventory_line_inventory_id_physical_inventory')),
        sa.ForeignKeyConstraint(['material_id'], ['pic.material.id'], name=op.f('fk_physical_inventory_line_material_id_material')),
        sa.CheckConstraint("count_status IN ('PENDING','COUNTED','RECOUNT_REQUIRED','RECOUNTED')", name='ck_physical_inventory_line_count_status'),
        sa.UniqueConstraint('tenant_id', 'inventory_id', 'line_no', name=op.f('uq_physical_inventory_line_tenant_id_inventory_id_line_no')),
        schema='pic')
    op.create_index('ix_physical_inventory_line_inventory', 'physical_inventory_line', ['tenant_id', 'inventory_id'], schema='pic')
    op.create_table('stock_reservation',
        sa.Column('number', sa.String(length=30), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('company_code', sa.String(length=10), nullable=False),
        sa.Column('material_id', sa.UUID(), nullable=False),
        sa.Column('plant', sa.String(length=10), nullable=False),
        sa.Column('storage_location', sa.String(length=10), nullable=False),
        sa.Column('qty', sa.Numeric(18, 3), nullable=False),
        sa.Column('issued_qty', sa.Numeric(18, 3), nullable=False),
        sa.Column('need_date', sa.Date(), nullable=False),
        sa.Column('cost_object_type', sa.String(length=20), nullable=True),
        sa.Column('cost_object_code', sa.String(length=30), nullable=True),
        sa.Column('purpose', sa.String(length=200), nullable=True),
        sa.Column('requester_id', sa.UUID(), nullable=False),
        sa.Column('availability', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('demand_element_id', sa.UUID(), nullable=True),
        sa.Column('rule_set_version', sa.String(length=80), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_reason', sa.Text(), nullable=True),
        *_base(), *_tail('stock_reservation'),
        sa.ForeignKeyConstraint(['material_id'], ['pic.material.id'], name=op.f('fk_stock_reservation_material_id_material')),
        sa.CheckConstraint("status IN ('OPEN','PARTIALLY_ISSUED','ISSUED','CANCELLED','EXPIRED')", name='ck_stock_reservation_status'),
        sa.CheckConstraint('qty > 0 AND issued_qty >= 0 AND issued_qty <= qty', name='ck_stock_reservation_qty_range'),
        sa.UniqueConstraint('tenant_id', 'number', name=op.f('uq_stock_reservation_tenant_id_number')),
        schema='pic')
    op.create_index('ix_stock_reservation_material', 'stock_reservation', ['tenant_id', 'material_id', 'plant', 'status'], schema='pic')
    op.create_index('ix_stock_reservation_status', 'stock_reservation', ['tenant_id', 'status', 'need_date'], schema='pic')
    for table in NEW_TABLES:
        op.create_index(op.f(f'ix_{table}_tenant_id'), table, ['tenant_id'], unique=False, schema='pic')
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pic.{table} TO {ROLE}")
        op.execute(f"ALTER TABLE pic.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE pic.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON pic.{table} USING (tenant_id = {CTX}) WITH CHECK (tenant_id = {CTX})")


def _seed_tenants() -> None:
    from app.pic.platform import inventory_defaults
    for code, a, b, scope, risk, description in SOD:
        op.execute(sa.text(
            "INSERT INTO pic.sod_rule (id, created_at, row_version, tenant_id, code, action_a, action_b, scope, risk, mode, description, active) "
            "SELECT gen_random_uuid(), now(), 1, t.id, :code, :a, :b, :scope, :risk, 'BLOCK', :description, true FROM pic.tenant t "
            "WHERE NOT EXISTS (SELECT 1 FROM pic.sod_rule r WHERE r.tenant_id = t.id AND r.code = :code)"
        ).bindparams(code=code, a=a, b=b, scope=scope, risk=risk, description=description))
    for object_type, prefix, first, padding in RANGES:
        op.execute(sa.text(
            "INSERT INTO pic.number_range (id, created_at, row_version, tenant_id, object_type, prefix, next_value, padding) "
            "SELECT gen_random_uuid(), now(), 1, t.id, :t, :p, :n, :pad FROM pic.tenant t "
            "WHERE NOT EXISTS (SELECT 1 FROM pic.number_range r WHERE r.tenant_id = t.id AND r.object_type = :t)"
        ).bindparams(t=object_type, p=prefix, n=first, pad=padding))
    for key, (body, description) in inventory_defaults.BODIES.items():
        op.execute(sa.text(
            "INSERT INTO pic.rule_set (id, created_at, row_version, tenant_id, key, version, effective_from, body, description) "
            "SELECT gen_random_uuid(), now(), 1, t.id, :key, '2026.1', DATE '2026-04-01', CAST(:body AS jsonb), :description FROM pic.tenant t "
            "WHERE NOT EXISTS (SELECT 1 FROM pic.rule_set r WHERE r.tenant_id = t.id AND r.key = :key)"
        ).bindparams(key=key, body=json.dumps(body), description=description))


def upgrade() -> None:
    _ledger()
    _tables()
    _seed_tenants()


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON pic.{table}")
        op.drop_table(table, schema='pic')
    op.execute("DELETE FROM pic.rule_set WHERE key IN ('INVENTORY-POSTING','INVENTORY-COUNT','INVENTORY-RESERVATION','INVENTORY-ALERTS')")
    op.execute("DELETE FROM pic.number_range WHERE object_type IN ('STOCK_POSTING','PHYSICAL_INVENTORY','STOCK_RESERVATION')")
    op.execute("DELETE FROM pic.sod_rule WHERE code IN ('SOD-10', 'SOD-11')")
    op.drop_index('ix_gr_line_serials', table_name='gr_line', schema='pic')
    op.drop_index('ix_gr_line_material_batch', table_name='gr_line', schema='pic')
    op.execute("ALTER TABLE pic.stock DROP CONSTRAINT IF EXISTS ck_stock_qty_not_negative")
    op.execute("ALTER TABLE pic.stock DROP CONSTRAINT IF EXISTS ck_stock_stock_type")
    op.drop_index('ix_stock_plant_type', table_name='stock', schema='pic')
    op.drop_index('ix_stock_movement_reference', table_name='stock_movement', schema='pic')
    op.drop_index('ix_stock_movement_material_plant_created', table_name='stock_movement', schema='pic')
    for column in ('reason_code', 'posting_ref', 'value_minor'):
        op.drop_column('stock_movement', column, schema='pic')
