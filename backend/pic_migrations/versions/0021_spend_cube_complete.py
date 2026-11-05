"""Spend cube completion (M01): credit / debit notes as signed document lines, document date and buyer on the spend line, invoiced / debit /
credit measures and the buyer dimension in the cube summary, steward queue with four-eyes and SLA, maverick lifecycle (SLA, escalation, recovery),
versioned category plans with a dated wave plan, forecast snapshots, data-quality runs and supplier duplicate clusters.

All changes are additive except two unique constraints that have to widen so that one invoice line can carry its credit and debit notes
(``spend_line``: invoice line + document type + document reference) and so that a category plan can have versions (``category_plan``: + version);
nothing is dropped and existing rows keep their meaning (every existing spend line is an INVOICE line, every existing plan is version 1).

- spend_line: ``document_type`` (INVOICE | CREDIT_NOTE | DEBIT_NOTE), ``document_ref``, ``document_date`` (backfilled from the invoice), ``buyer_id``
  (backfilled from the purchase order).
- spend_cube_summary: ``buyer_id`` (nil UUID = none), ``invoiced_group_minor`` / ``debit_group_minor`` / ``credit_group_minor``. The summary is derived data:
  it is emptied here and rebuilt by the first read (or the scheduled job), because the grain gained the buyer.
- classification_review, maverick_rule, maverick_hit, taxonomy_node, category_plan: the columns of the models (steward SLA and four-eyes, rule SLA and
  escalation role, hit lifecycle, retired taxonomy nodes, plan versions, wave plan, savings by lever).
- spend_forecast_snapshot, spend_quality_run, spend_duplicate_cluster: new tenant tables with the pic_app grants and forced row-level security.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-04 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0021'
down_revision: Union[str, Sequence[str], None] = '0020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "pic_app"
NEW_TABLES = ("spend_forecast_snapshot", "spend_quality_run", "spend_duplicate_cluster")
CTX = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
NIL = "00000000-0000-0000-0000-000000000000"
S = 'pic'


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


def _add(table: str, *columns: sa.Column) -> None:
    for column in columns:
        op.add_column(table, column, schema=S)


def upgrade() -> None:
    # ---- spend_line
    _add('spend_line',
         sa.Column('document_type', sa.String(length=12), server_default='INVOICE', nullable=False),
         sa.Column('document_ref', sa.String(length=60), server_default='', nullable=False),
         sa.Column('document_date', sa.Date(), nullable=True),
         sa.Column('buyer_id', sa.UUID(), nullable=True))
    op.drop_constraint('uq_spend_line_tenant_id_invoice_line_id', 'spend_line', schema=S, type_='unique')
    op.create_unique_constraint(op.f('uq_spend_line_invoice_line_document'), 'spend_line',
                                ['tenant_id', 'invoice_line_id', 'document_type', 'document_ref'], schema=S)
    op.create_check_constraint(op.f('ck_spend_line_document_type'), 'spend_line', "document_type IN ('INVOICE','CREDIT_NOTE','DEBIT_NOTE')", schema=S)
    op.create_check_constraint(op.f('ck_spend_line_amount_range'), 'spend_line', "abs(amount_minor) <= 1000000000000000", schema=S)
    op.create_index('ix_spend_line_invoice_ref', 'spend_line', ['tenant_id', 'invoice_ref'], schema=S)
    op.execute("UPDATE pic.spend_line sl SET document_date = i.invoice_date FROM pic.invoice_line il JOIN pic.invoice i ON i.id = il.invoice_id "
               "WHERE il.id = sl.invoice_line_id AND sl.document_date IS NULL")
    op.execute("UPDATE pic.spend_line sl SET buyer_id = po.created_by FROM pic.po_line pl JOIN pic.purchase_order po ON po.id = pl.po_id "
               "WHERE pl.id = sl.po_line_id AND sl.buyer_id IS NULL")

    # ---- spend_cube_summary (derived: emptied, rebuilt on the first read because the grain gained the buyer)
    _add('spend_cube_summary',
         sa.Column('buyer_id', sa.UUID(), server_default=NIL, nullable=False),
         sa.Column('invoiced_group_minor', sa.BigInteger(), server_default='0', nullable=False),
         sa.Column('debit_group_minor', sa.BigInteger(), server_default='0', nullable=False),
         sa.Column('credit_group_minor', sa.BigInteger(), server_default='0', nullable=False))
    op.drop_index('uq_spend_cube_summary_grain', table_name='spend_cube_summary', schema=S)
    op.create_index('uq_spend_cube_summary_grain', 'spend_cube_summary',
                    ['tenant_id', 'period', 'category', 'supplier_id', 'buyer_id', 'plant', 'company_code', 'cost_object', 'cost_object_type',
                     'material_group', 'currency', 'source', 'source_system', 'contracted', 'addressable', 'maverick'], unique=True, schema=S)
    op.create_index('ix_spend_cube_summary_period', 'spend_cube_summary', ['tenant_id', 'period'], schema=S)
    op.execute("DELETE FROM pic.spend_cube_summary")
    op.execute("DELETE FROM pic.spend_view_state WHERE view_name = 'spend_cube_summary'")
    op.execute("DELETE FROM pic.spend_view_dirty")

    # ---- steward queue, maverick lifecycle, taxonomy, category plans
    _add('classification_review',
         sa.Column('value_group_minor', sa.BigInteger(), nullable=True),
         sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
         sa.Column('first_category', sa.String(length=40), nullable=True),
         sa.Column('first_decided_by', sa.UUID(), nullable=True),
         sa.Column('first_decided_at', sa.DateTime(timezone=True), nullable=True),
         sa.Column('decision_reason', sa.Text(), nullable=True),
         sa.Column('learned_keyword', sa.String(length=60), nullable=True),
         sa.Column('channel', sa.String(length=10), server_default='AGENT', nullable=False))
    op.create_index('ix_classification_review_status', 'classification_review', ['tenant_id', 'status'], schema=S)
    _add('taxonomy_node', sa.Column('active', sa.Boolean(), server_default='true', nullable=False))
    _add('maverick_rule',
         sa.Column('sla_days', sa.Integer(), server_default='10', nullable=False),
         sa.Column('escalate_role', sa.String(length=40), nullable=True))
    _add('maverick_hit',
         sa.Column('amount_group_minor', sa.BigInteger(), nullable=True),
         sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
         sa.Column('escalation_level', sa.Integer(), server_default='0', nullable=False),
         sa.Column('escalated_at', sa.DateTime(timezone=True), nullable=True),
         sa.Column('escalated_to_role', sa.String(length=40), nullable=True),
         sa.Column('reason_code', sa.String(length=30), nullable=True),
         sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
         sa.Column('resolved_by', sa.UUID(), nullable=True),
         sa.Column('recovered_minor', sa.BigInteger(), nullable=True),
         sa.Column('resolution_note', sa.Text(), nullable=True),
         sa.Column('savings_at_risk_minor', sa.BigInteger(), server_default='0', nullable=False))
    # existing rows get the values the new services expect: SLA and escalation role of each rule by severity / owner, and for every review and hit
    # the value in the group currency and its due date (created + SLA), so the queue ageing and the escalation work on history too
    op.execute("UPDATE pic.maverick_rule SET sla_days = CASE severity WHEN 'Critical' THEN 3 WHEN 'High' THEN 5 WHEN 'Medium' THEN 10 ELSE 15 END, "
               "escalate_role = CASE owner_role WHEN 'CATEGORY_MANAGER' THEN 'PROCUREMENT_HEAD' ELSE 'CPO' END")
    op.execute("UPDATE pic.classification_review r SET value_group_minor = abs(coalesce(sl.amount_group_minor, sl.amount_minor)), "
               "due_at = r.created_at + interval '5 days' FROM pic.spend_line sl WHERE sl.id = r.spend_line_id")
    op.execute("UPDATE pic.maverick_hit h SET amount_group_minor = abs(coalesce(sl.amount_group_minor, h.amount_minor)), "
               "due_at = h.created_at + make_interval(days => mr.sla_days), "
               "savings_at_risk_minor = CASE WHEN h.rule_code IN ('OFF_CONTRACT', 'OFF_CONTRACT_PRICE') THEN greatest(coalesce(sl.price_variance_minor, 0), 0) ELSE 0 END "
               "FROM pic.spend_line sl, pic.maverick_rule mr WHERE sl.id = h.spend_line_id AND mr.tenant_id = h.tenant_id AND mr.code = h.rule_code")
    op.create_index('ix_maverick_hit_status', 'maverick_hit', ['tenant_id', 'status'], schema=S)
    op.create_index('ix_maverick_hit_supplier', 'maverick_hit', ['tenant_id', 'supplier_id'], schema=S)
    _add('category_plan',
         sa.Column('version', sa.Integer(), server_default='1', nullable=False),
         sa.Column('supersedes_id', sa.UUID(), nullable=True),
         sa.Column('submitted_by', sa.UUID(), nullable=True),
         sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
         sa.Column('decision_comment', sa.Text(), nullable=True),
         sa.Column('addressable_minor', sa.BigInteger(), nullable=True),
         sa.Column('wave_plan', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
         sa.Column('savings_by_lever', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))
    op.drop_constraint('uq_category_plan_tenant_id_category_fiscal_year', 'category_plan', schema=S, type_='unique')
    op.create_unique_constraint(op.f('uq_category_plan_tenant_id_category_fiscal_year_version'), 'category_plan',
                                ['tenant_id', 'category', 'fiscal_year', 'version'], schema=S)

    # ---- new tables
    op.create_table('spend_forecast_snapshot',
        sa.Column('as_of_period', sa.String(length=7), nullable=False),
        sa.Column('category', sa.String(length=40), nullable=False),
        sa.Column('plant', sa.String(length=10), server_default='', nullable=False),
        sa.Column('period', sa.String(length=7), nullable=False),
        sa.Column('horizon', sa.Integer(), nullable=False),
        sa.Column('method', sa.String(length=40), nullable=False),
        sa.Column('forecast_minor', sa.BigInteger(), nullable=False),
        sa.Column('low_minor', sa.BigInteger(), nullable=False),
        sa.Column('high_minor', sa.BigInteger(), nullable=False),
        *_base(), *_tail('spend_forecast_snapshot'),
        sa.UniqueConstraint('tenant_id', 'as_of_period', 'category', 'plant', 'period',
                            name=op.f('uq_spend_forecast_snapshot_tenant_id_as_of_period_category_plant_period')),
        schema=S)
    op.create_table('spend_quality_run',
        sa.Column('score', sa.Numeric(5, 2), nullable=False),
        sa.Column('lines', sa.BigInteger(), nullable=False),
        sa.Column('spend_group_minor', sa.BigInteger(), nullable=False),
        sa.Column('checks', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('run_by', sa.UUID(), nullable=True),
        sa.Column('run_at', sa.DateTime(timezone=True), nullable=False),
        *_base(), *_tail('spend_quality_run'),
        schema=S)
    op.create_table('spend_duplicate_cluster',
        sa.Column('cluster_key', sa.String(length=40), nullable=False),
        sa.Column('supplier_codes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('score', sa.Numeric(4, 3), nullable=False),
        sa.Column('spend_group_minor', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=15), nullable=False),
        sa.Column('survivor_code', sa.String(length=30), nullable=True),
        sa.Column('proposal_number', sa.String(length=30), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('decided_by', sa.UUID(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        *_base(), *_tail('spend_duplicate_cluster'),
        sa.UniqueConstraint('tenant_id', 'cluster_key', name=op.f('uq_spend_duplicate_cluster_tenant_id_cluster_key')),
        schema=S)
    for table in NEW_TABLES:
        op.create_index(op.f(f'ix_{table}_tenant_id'), table, ['tenant_id'], unique=False, schema=S)
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pic.{table} TO {ROLE}")
        op.execute(f"ALTER TABLE pic.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE pic.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON pic.{table} USING (tenant_id = {CTX}) WITH CHECK (tenant_id = {CTX})")


def downgrade() -> None:
    for table in NEW_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON pic.{table}")
        op.drop_table(table, schema=S)
    # versions of a category plan cannot be kept under the narrower constraint: only the latest version of each plan survives
    op.execute("DELETE FROM pic.category_plan a USING pic.category_plan b WHERE a.tenant_id = b.tenant_id AND a.category = b.category "
               "AND a.fiscal_year = b.fiscal_year AND a.version < b.version")
    op.drop_constraint('uq_category_plan_tenant_id_category_fiscal_year_version', 'category_plan', schema=S, type_='unique')
    op.create_unique_constraint(op.f('uq_category_plan_tenant_id_category_fiscal_year'), 'category_plan', ['tenant_id', 'category', 'fiscal_year'], schema=S)
    for column in ('savings_by_lever', 'wave_plan', 'addressable_minor', 'decision_comment', 'submitted_at', 'submitted_by', 'supersedes_id', 'version'):
        op.drop_column('category_plan', column, schema=S)
    op.drop_index('ix_maverick_hit_supplier', table_name='maverick_hit', schema=S)
    op.drop_index('ix_maverick_hit_status', table_name='maverick_hit', schema=S)
    for column in ('savings_at_risk_minor', 'resolution_note', 'recovered_minor', 'resolved_by', 'resolved_at', 'reason_code', 'escalated_to_role',
                   'escalated_at', 'escalation_level', 'due_at', 'amount_group_minor'):
        op.drop_column('maverick_hit', column, schema=S)
    op.drop_column('maverick_rule', 'escalate_role', schema=S)
    op.drop_column('maverick_rule', 'sla_days', schema=S)
    op.drop_column('taxonomy_node', 'active', schema=S)
    op.drop_index('ix_classification_review_status', table_name='classification_review', schema=S)
    for column in ('channel', 'learned_keyword', 'decision_reason', 'first_decided_at', 'first_decided_by', 'first_category', 'due_at', 'value_group_minor'):
        op.drop_column('classification_review', column, schema=S)
    # the summary is derived data: emptied so that the next read rebuilds it under the older grain
    op.execute("DELETE FROM pic.spend_cube_summary")
    op.execute("DELETE FROM pic.spend_view_state WHERE view_name = 'spend_cube_summary'")
    op.drop_index('ix_spend_cube_summary_period', table_name='spend_cube_summary', schema=S)
    op.drop_index('uq_spend_cube_summary_grain', table_name='spend_cube_summary', schema=S)
    for column in ('credit_group_minor', 'debit_group_minor', 'invoiced_group_minor', 'buyer_id'):
        op.drop_column('spend_cube_summary', column, schema=S)
    op.create_index('uq_spend_cube_summary_grain', 'spend_cube_summary',
                    ['tenant_id', 'period', 'category', 'supplier_id', 'plant', 'company_code', 'cost_object', 'cost_object_type', 'material_group',
                     'currency', 'source', 'source_system', 'contracted', 'addressable', 'maverick'], unique=True, schema=S)
    # credit / debit note lines have no place in the older model: they are removed (the notes themselves stay in credit_note / debit_note)
    op.execute("DELETE FROM pic.spend_line WHERE document_type <> 'INVOICE'")
    op.drop_index('ix_spend_line_invoice_ref', table_name='spend_line', schema=S)
    op.drop_constraint(op.f('ck_spend_line_amount_range'), 'spend_line', schema=S, type_='check')
    op.drop_constraint(op.f('ck_spend_line_document_type'), 'spend_line', schema=S, type_='check')
    op.drop_constraint('uq_spend_line_invoice_line_document', 'spend_line', schema=S, type_='unique')
    op.create_unique_constraint(op.f('uq_spend_line_tenant_id_invoice_line_id'), 'spend_line', ['tenant_id', 'invoice_line_id'], schema=S)
    for column in ('buyer_id', 'document_date', 'document_ref', 'document_type'):
        op.drop_column('spend_line', column, schema=S)
