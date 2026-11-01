"""Spend cube at scale, KPI history and saved views (wave 1, engineer C2).

* spend_cube_summary / spend_commitment_summary: tenant summary tables the cube reads instead of scanning spend_line
  (maintained by ``spend.refresh_spend_views``; spend_view_state records each refresh, spend_view_dirty the periods whose
  spend lines changed since).
* spend_line: ERP system tag, cost-object type (cost centre / WBS), FX rate + date + group-currency amount, variance against
  the last price paid; indexes for refresh and drill-down; a partial index for the off-contract worklist.
  Existing rows are backfilled (cost-object type from the PO line, group amount from the line currency and the FX table) and
  every existing (tenant, period) is marked dirty so the first read or scheduled run builds the summaries.
* supplier.parent_supplier_id: corporate parent for the parent/child roll-up.
* kpi_snapshot: month-end KPI values (BP Table 28); saved_view: per-user saved filters.

All new tenant tables carry forced row-level security and pic_app grants like every other pic table.

Revision ID: 0011
Revises: 0007
Create Date: 2026-10-31 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "pic_app"
NEW_TABLES = ("spend_cube_summary", "spend_commitment_summary", "spend_view_state", "spend_view_dirty", "kpi_snapshot", "saved_view")


def _base(table: str) -> list:
    """id, audit columns and tenant_id: what TenantScoped adds to every tenant table."""
    return [
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
    ]


def _finish(table: str, *constraints) -> list:
    return [*constraints, sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f(f'fk_{table}_tenant_id_tenant')),
            sa.PrimaryKeyConstraint('id', name=op.f(f'pk_{table}'))]


def upgrade() -> None:
    # ------------------------------------------------------------ supplier, spend_line
    op.add_column('supplier', sa.Column('parent_supplier_id', sa.UUID(), nullable=True), schema='pic')
    op.create_foreign_key(op.f('fk_supplier_parent_supplier_id_supplier'), 'supplier', 'supplier', ['parent_supplier_id'], ['id'],
                          source_schema='pic', referent_schema='pic')
    op.add_column('spend_line', sa.Column('source_system', sa.String(length=30), server_default='PIC', nullable=False), schema='pic')
    op.add_column('spend_line', sa.Column('cost_object_type', sa.String(length=20), nullable=True), schema='pic')
    op.add_column('spend_line', sa.Column('fx_rate', sa.Numeric(precision=18, scale=8), nullable=True), schema='pic')
    op.add_column('spend_line', sa.Column('fx_date', sa.Date(), nullable=True), schema='pic')
    op.add_column('spend_line', sa.Column('amount_group_minor', sa.BigInteger(), nullable=True), schema='pic')
    op.add_column('spend_line', sa.Column('price_variance_last_minor', sa.BigInteger(), nullable=True), schema='pic')
    op.execute("UPDATE pic.spend_line sl SET cost_object_type = pl.account_assignment_type FROM pic.po_line pl "
               "WHERE sl.po_line_id = pl.id AND sl.cost_object_type IS NULL AND pl.account_assignment_type IS NOT NULL")
    op.execute("UPDATE pic.spend_line sl SET fx_rate = 1, amount_group_minor = sl.amount_minor FROM pic.tenant t "
               "WHERE t.id = sl.tenant_id AND t.base_currency = sl.currency")
    op.execute("""
        WITH pairs AS (
            SELECT DISTINCT sl.tenant_id, sl.currency, sl.period, t.base_currency
            FROM pic.spend_line sl JOIN pic.tenant t ON t.id = sl.tenant_id
            WHERE t.base_currency <> sl.currency AND sl.amount_group_minor IS NULL),
        rates AS (
            SELECT p.tenant_id, p.currency, p.period, r.rate, r.valid_from FROM pairs p, LATERAL (
                SELECT f.rate, f.valid_from FROM pic.fx_rate f
                WHERE f.tenant_id = p.tenant_id AND f.from_ccy = p.currency AND f.to_ccy = p.base_currency
                  AND f.valid_from <= (to_date(p.period, 'YYYY-MM') + interval '1 month - 1 day')::date
                ORDER BY f.valid_from DESC LIMIT 1) r)
        UPDATE pic.spend_line sl SET fx_rate = rates.rate, fx_date = rates.valid_from, amount_group_minor = round(sl.amount_minor * rates.rate)
        FROM rates
        WHERE rates.tenant_id = sl.tenant_id AND rates.currency = sl.currency AND rates.period = sl.period AND sl.amount_group_minor IS NULL""")
    op.create_index('ix_spend_line_tenant_period', 'spend_line', ['tenant_id', 'period'], unique=False, schema='pic')
    op.create_index('ix_spend_line_tenant_supplier_period', 'spend_line', ['tenant_id', 'supplier_id', 'period'], unique=False, schema='pic')
    op.create_index('ix_spend_line_tenant_category_period', 'spend_line', ['tenant_id', 'category', 'period'], unique=False, schema='pic')
    op.create_index('ix_spend_line_offcontract', 'spend_line', ['tenant_id', sa.text('amount_minor DESC')], unique=False, schema='pic',
                    postgresql_where=sa.text("maverick_flags ?| array['OFF_CONTRACT','OFF_CONTRACT_PRICE']"))

    # ------------------------------------------------------------ summary tables
    op.create_table(
        'spend_cube_summary',
        sa.Column('period', sa.String(length=7), nullable=False),
        sa.Column('category', sa.String(length=40), nullable=False),
        sa.Column('supplier_id', sa.UUID(), nullable=False),
        sa.Column('parent_supplier_id', sa.UUID(), nullable=False),
        sa.Column('plant', sa.String(length=10), nullable=False),
        sa.Column('company_code', sa.String(length=10), nullable=False),
        sa.Column('cost_object', sa.String(length=40), nullable=False),
        sa.Column('cost_object_type', sa.String(length=20), nullable=False),
        sa.Column('material_group', sa.String(length=30), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('group_currency', sa.String(length=3), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('source_system', sa.String(length=30), nullable=False),
        sa.Column('contracted', sa.Boolean(), nullable=False),
        sa.Column('addressable', sa.Boolean(), nullable=False),
        sa.Column('maverick', sa.Boolean(), nullable=False),
        sa.Column('lines', sa.BigInteger(), nullable=False),
        sa.Column('invoices', sa.BigInteger(), nullable=False),
        sa.Column('pos', sa.BigInteger(), nullable=False),
        sa.Column('auto_classified_lines', sa.BigInteger(), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('amount_group_minor', sa.BigInteger(), nullable=False),
        sa.Column('price_variance_group_minor', sa.BigInteger(), nullable=False),
        sa.Column('price_variance_last_group_minor', sa.BigInteger(), nullable=False),
        sa.Column('fx_missing_lines', sa.BigInteger(), nullable=False),
        *_base('spend_cube_summary'),
        *_finish('spend_cube_summary', sa.CheckConstraint('lines >= 0 AND invoices >= 0 AND pos >= 0 AND fx_missing_lines >= 0',
                                                          name=op.f('ck_spend_cube_summary_counts'))),
        schema='pic')
    op.create_index(op.f('ix_spend_cube_summary_tenant_id'), 'spend_cube_summary', ['tenant_id'], unique=False, schema='pic')
    op.create_index('uq_spend_cube_summary_grain', 'spend_cube_summary',
                    ['tenant_id', 'period', 'category', 'supplier_id', 'plant', 'company_code', 'cost_object', 'cost_object_type', 'material_group', 'currency',
                     'source', 'source_system', 'contracted', 'addressable', 'maverick'], unique=True, schema='pic')
    op.create_index('ix_spend_cube_summary_supplier', 'spend_cube_summary', ['tenant_id', 'supplier_id', 'period'], unique=False, schema='pic')
    op.create_index('ix_spend_cube_summary_parent', 'spend_cube_summary', ['tenant_id', 'parent_supplier_id', 'period'], unique=False, schema='pic')
    op.create_index('ix_spend_cube_summary_category', 'spend_cube_summary', ['tenant_id', 'category', 'period'], unique=False, schema='pic')
    op.create_index('ix_spend_cube_summary_plant', 'spend_cube_summary', ['tenant_id', 'plant', 'period'], unique=False, schema='pic')

    op.create_table(
        'spend_commitment_summary',
        sa.Column('period', sa.String(length=7), nullable=False),
        sa.Column('category', sa.String(length=40), nullable=False),
        sa.Column('supplier_id', sa.UUID(), nullable=False),
        sa.Column('parent_supplier_id', sa.UUID(), nullable=False),
        sa.Column('plant', sa.String(length=10), nullable=False),
        sa.Column('company_code', sa.String(length=10), nullable=False),
        sa.Column('cost_object', sa.String(length=40), nullable=False),
        sa.Column('cost_object_type', sa.String(length=20), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('group_currency', sa.String(length=3), nullable=False),
        sa.Column('fx_rate', sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column('fx_date', sa.Date(), nullable=True),
        sa.Column('pos', sa.BigInteger(), nullable=False),
        sa.Column('lines', sa.BigInteger(), nullable=False),
        sa.Column('committed_minor', sa.BigInteger(), nullable=False),
        sa.Column('committed_group_minor', sa.BigInteger(), nullable=True),
        sa.Column('received_not_invoiced_minor', sa.BigInteger(), nullable=False),
        *_base('spend_commitment_summary'),
        *_finish('spend_commitment_summary', sa.CheckConstraint('committed_minor >= 0 AND received_not_invoiced_minor >= 0',
                                                                name=op.f('ck_spend_commitment_summary_not_negative'))),
        schema='pic')
    op.create_index(op.f('ix_spend_commitment_summary_tenant_id'), 'spend_commitment_summary', ['tenant_id'], unique=False, schema='pic')
    op.create_index('uq_spend_commitment_summary_grain', 'spend_commitment_summary',
                    ['tenant_id', 'period', 'category', 'supplier_id', 'plant', 'company_code', 'cost_object', 'cost_object_type', 'currency'], unique=True, schema='pic')
    op.create_index('ix_spend_commitment_summary_supplier', 'spend_commitment_summary', ['tenant_id', 'supplier_id', 'period'], unique=False, schema='pic')

    op.create_table(
        'spend_view_state',
        sa.Column('view_name', sa.String(length=40), nullable=False),
        sa.Column('refreshed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('mode', sa.String(length=10), nullable=False),
        sa.Column('periods_refreshed', sa.Integer(), nullable=False),
        sa.Column('source_rows', sa.BigInteger(), nullable=False),
        sa.Column('summary_rows', sa.BigInteger(), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=False),
        *_base('spend_view_state'),
        *_finish('spend_view_state',
                 sa.UniqueConstraint('tenant_id', 'view_name', name=op.f('uq_spend_view_state_tenant_id_view_name')),
                 sa.CheckConstraint("view_name IN ('spend_cube_summary','spend_commitment_summary')", name=op.f('ck_spend_view_state_view_name')),
                 sa.CheckConstraint("mode IN ('FULL','PERIODS')", name=op.f('ck_spend_view_state_mode'))),
        schema='pic')
    op.create_index(op.f('ix_spend_view_state_tenant_id'), 'spend_view_state', ['tenant_id'], unique=False, schema='pic')

    op.create_table(
        'spend_view_dirty',
        sa.Column('period', sa.String(length=7), nullable=False),
        sa.Column('marked_at', sa.DateTime(timezone=True), nullable=False),
        *_base('spend_view_dirty'),
        *_finish('spend_view_dirty', sa.UniqueConstraint('tenant_id', 'period', name=op.f('uq_spend_view_dirty_tenant_id_period'))),
        schema='pic')
    op.create_index(op.f('ix_spend_view_dirty_tenant_id'), 'spend_view_dirty', ['tenant_id'], unique=False, schema='pic')

    op.create_table(
        'kpi_snapshot',
        sa.Column('kpi_code', sa.String(length=40), nullable=False),
        sa.Column('period', sa.String(length=7), nullable=False),
        sa.Column('scope_key', sa.String(length=60), nullable=False),
        sa.Column('value', sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column('numerator', sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column('denominator', sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column('unit', sa.String(length=15), nullable=False),
        sa.Column('status', sa.String(length=5), nullable=False),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_base('kpi_snapshot'),
        *_finish('kpi_snapshot',
                 sa.UniqueConstraint('tenant_id', 'kpi_code', 'period', 'scope_key', name=op.f('uq_kpi_snapshot_tenant_id_kpi_code_period_scope_key')),
                 sa.CheckConstraint("status IN ('GOOD','WARN','BAD','NA')", name=op.f('ck_kpi_snapshot_status'))),
        schema='pic')
    op.create_index(op.f('ix_kpi_snapshot_tenant_id'), 'kpi_snapshot', ['tenant_id'], unique=False, schema='pic')
    op.create_index('ix_kpi_snapshot_code_period', 'kpi_snapshot', ['tenant_id', 'kpi_code', 'period'], unique=False, schema='pic')

    op.create_table(
        'saved_view',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('screen', sa.String(length=60), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('filters', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('shared', sa.Boolean(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        *_base('saved_view'),
        *_finish('saved_view',
                 sa.ForeignKeyConstraint(['user_id'], ['pic.app_user.id'], name=op.f('fk_saved_view_user_id_app_user'), ondelete='CASCADE'),
                 sa.UniqueConstraint('tenant_id', 'user_id', 'screen', 'name', name=op.f('uq_saved_view_tenant_id_user_id_screen_name')),
                 sa.CheckConstraint('char_length(name) BETWEEN 1 AND 80', name=op.f('ck_saved_view_name_length'))),
        schema='pic')
    op.create_index(op.f('ix_saved_view_tenant_id'), 'saved_view', ['tenant_id'], unique=False, schema='pic')
    op.create_index('ix_saved_view_screen', 'saved_view', ['tenant_id', 'screen'], unique=False, schema='pic')

    # ------------------------------------------------------------ row-level security and grants
    for table in NEW_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pic.{table} TO {ROLE}")
        op.execute(f"ALTER TABLE pic.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE pic.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON pic.{table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)""")

    # Existing spend: every (tenant, period) is dirty until the first refresh builds the summaries.
    op.execute("INSERT INTO pic.spend_view_dirty (id, tenant_id, created_at, row_version, period, marked_at) "
               "SELECT gen_random_uuid(), tenant_id, now(), 1, period, now() FROM (SELECT DISTINCT tenant_id, period FROM pic.spend_line) x")


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON pic.{table}")
    op.drop_table('saved_view', schema='pic')
    op.drop_table('kpi_snapshot', schema='pic')
    op.drop_table('spend_view_dirty', schema='pic')
    op.drop_table('spend_view_state', schema='pic')
    op.drop_table('spend_commitment_summary', schema='pic')
    op.drop_table('spend_cube_summary', schema='pic')
    op.drop_index('ix_spend_line_offcontract', table_name='spend_line', schema='pic')
    op.drop_index('ix_spend_line_tenant_category_period', table_name='spend_line', schema='pic')
    op.drop_index('ix_spend_line_tenant_supplier_period', table_name='spend_line', schema='pic')
    op.drop_index('ix_spend_line_tenant_period', table_name='spend_line', schema='pic')
    for column in ('price_variance_last_minor', 'amount_group_minor', 'fx_date', 'fx_rate', 'cost_object_type', 'source_system'):
        op.drop_column('spend_line', column, schema='pic')
    op.drop_constraint(op.f('fk_supplier_parent_supplier_id_supplier'), 'supplier', schema='pic', type_='foreignkey')
    op.drop_column('supplier', 'parent_supplier_id', schema='pic')
