"""Wave 1, engineer C1: material change requests and versions, event-line sources (requirement bundling) and lots, bid lot terms,
data-driven criteria, call-off contracts of a master agreement with a governing-law variant, supplier rebates (agreement, accrual,
settlement), clause extraction, supplier segment history, development plans, ESG / cyber assessments and the scorecard responsiveness and
ESG measures. Every new table gets grants and forced row-level security like the other tenant tables.

Revision ID: 0010
Revises: 0007
Create Date: 2026-10-31 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "pic_app"
NEW_TABLES = ("material_change_request", "material_version", "event_line_source", "bid_lot", "rebate_agreement", "rebate_accrual",
              "rebate_settlement", "clause_extraction", "supplier_segment", "development_plan", "development_action", "supplier_assessment")


def upgrade() -> None:
    op.create_table('clause_extraction',
    sa.Column('number', sa.String(length=30), nullable=False),
    sa.Column('source_name', sa.String(length=200), nullable=False),
    sa.Column('source_hash', sa.String(length=64), nullable=False),
    sa.Column('contract_ref', sa.String(length=40), nullable=False),
    sa.Column('contract_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('items', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('attributes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('unmatched', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('extractor_version', sa.String(length=30), nullable=False),
    sa.Column('reviewed_by', sa.UUID(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("status IN ('EXTRACTED','REVIEWED','APPLIED','REJECTED')", name=op.f('ck_clause_extraction_status')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_clause_extraction_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_clause_extraction')),
    sa.UniqueConstraint('tenant_id', 'number', name=op.f('uq_clause_extraction_tenant_id_number')),
    sa.UniqueConstraint('tenant_id', 'source_hash', 'contract_ref', name=op.f('uq_clause_extraction_tenant_id_source_hash_contract_ref')),
    schema='pic'
    )
    op.create_index(op.f('ix_clause_extraction_tenant_id'), 'clause_extraction', ['tenant_id'], unique=False, schema='pic')
    op.create_table('material_change_request',
    sa.Column('number', sa.String(length=30), nullable=False),
    sa.Column('material_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=15), nullable=False),
    sa.Column('material_type', sa.String(length=20), nullable=False),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('domains', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('impact', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('requested_by', sa.UUID(), nullable=False),
    sa.Column('from_version', sa.Integer(), nullable=False),
    sa.Column('to_version', sa.Integer(), nullable=True),
    sa.Column('approvals', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('rule_set_version', sa.String(length=80), nullable=True),
    sa.Column('erp_key', sa.String(length=80), nullable=True),
    sa.Column('erp_document', sa.String(length=40), nullable=True),
    sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rejection_reason', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("status IN ('IN_APPROVAL','APPLIED','REJECTED','CANCELLED')", name=op.f('ck_material_change_request_status')),
    sa.ForeignKeyConstraint(['material_id'], ['pic.material.id'], name=op.f('fk_material_change_request_material_id_material')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_material_change_request_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_material_change_request')),
    sa.UniqueConstraint('tenant_id', 'number', name=op.f('uq_material_change_request_tenant_id_number')),
    schema='pic'
    )
    op.create_index('ix_material_change_request_material', 'material_change_request', ['tenant_id', 'material_id'], unique=False, schema='pic')
    op.create_index(op.f('ix_material_change_request_tenant_id'), 'material_change_request', ['tenant_id'], unique=False, schema='pic')
    op.create_table('material_version',
    sa.Column('material_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('changed_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('change_request_id', sa.UUID(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint('version >= 1', name=op.f('ck_material_version_version_positive')),
    sa.ForeignKeyConstraint(['material_id'], ['pic.material.id'], name=op.f('fk_material_version_material_id_material')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_material_version_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_material_version')),
    sa.UniqueConstraint('tenant_id', 'material_id', 'version', name=op.f('uq_material_version_tenant_id_material_id_version')),
    schema='pic'
    )
    op.create_index(op.f('ix_material_version_tenant_id'), 'material_version', ['tenant_id'], unique=False, schema='pic')
    op.create_table('supplier_assessment',
    sa.Column('supplier_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=6), nullable=False),
    sa.Column('as_of', sa.Date(), nullable=False),
    sa.Column('expires_on', sa.Date(), nullable=True),
    sa.Column('answers', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('score', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('submitted_by', sa.UUID(), nullable=False),
    sa.Column('reviewed_by', sa.UUID(), nullable=True),
    sa.Column('review_note', sa.Text(), nullable=True),
    sa.Column('rule_set_version', sa.String(length=80), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("kind IN ('ESG','CYBER')", name=op.f('ck_supplier_assessment_kind')),
    sa.CheckConstraint("status IN ('SUBMITTED','ACCEPTED','REJECTED')", name=op.f('ck_supplier_assessment_status')),
    sa.CheckConstraint('score >= 0 AND score <= 100', name=op.f('ck_supplier_assessment_score_range')),
    sa.ForeignKeyConstraint(['supplier_id'], ['pic.supplier.id'], name=op.f('fk_supplier_assessment_supplier_id_supplier')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_supplier_assessment_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_supplier_assessment')),
    sa.UniqueConstraint('tenant_id', 'supplier_id', 'kind', 'as_of', name=op.f('uq_supplier_assessment_tenant_id_supplier_id_kind_as_of')),
    schema='pic'
    )
    op.create_index('ix_supplier_assessment_supplier', 'supplier_assessment', ['tenant_id', 'supplier_id', 'kind'], unique=False, schema='pic')
    op.create_index(op.f('ix_supplier_assessment_tenant_id'), 'supplier_assessment', ['tenant_id'], unique=False, schema='pic')
    op.create_table('supplier_segment',
    sa.Column('supplier_id', sa.UUID(), nullable=False),
    sa.Column('segment', sa.String(length=12), nullable=False),
    sa.Column('method', sa.String(length=6), nullable=False),
    sa.Column('spend_share', sa.Numeric(precision=7, scale=4), nullable=False),
    sa.Column('risk_score', sa.Integer(), nullable=False),
    sa.Column('criticality', sa.String(length=10), nullable=False),
    sa.Column('inputs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('rule_set_version', sa.String(length=80), nullable=True),
    sa.Column('effective_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('effective_to', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("method IN ('AUTO','MANUAL')", name=op.f('ck_supplier_segment_method')),
    sa.CheckConstraint("segment IN ('STRATEGIC','LEVERAGE','BOTTLENECK','ROUTINE')", name=op.f('ck_supplier_segment_segment')),
    sa.ForeignKeyConstraint(['supplier_id'], ['pic.supplier.id'], name=op.f('fk_supplier_segment_supplier_id_supplier')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_supplier_segment_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_supplier_segment')),
    schema='pic'
    )
    op.create_index('ix_supplier_segment_supplier', 'supplier_segment', ['tenant_id', 'supplier_id', 'effective_to'], unique=False, schema='pic')
    op.create_index(op.f('ix_supplier_segment_tenant_id'), 'supplier_segment', ['tenant_id'], unique=False, schema='pic')
    op.create_table('bid_lot',
    sa.Column('bid_id', sa.UUID(), nullable=False),
    sa.Column('lot_code', sa.String(length=20), nullable=False),
    sa.Column('discount_pct', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('all_or_nothing', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint('discount_pct >= 0 AND discount_pct < 100', name=op.f('ck_bid_lot_discount_range')),
    sa.ForeignKeyConstraint(['bid_id'], ['pic.bid.id'], name=op.f('fk_bid_lot_bid_id_bid')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_bid_lot_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bid_lot')),
    sa.UniqueConstraint('tenant_id', 'bid_id', 'lot_code', name=op.f('uq_bid_lot_tenant_id_bid_id_lot_code')),
    schema='pic'
    )
    op.create_index(op.f('ix_bid_lot_tenant_id'), 'bid_lot', ['tenant_id'], unique=False, schema='pic')
    op.create_table('development_plan',
    sa.Column('number', sa.String(length=30), nullable=False),
    sa.Column('supplier_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('objective', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('target_date', sa.Date(), nullable=False),
    sa.Column('capa_id', sa.UUID(), nullable=True),
    sa.Column('metric', sa.String(length=25), nullable=True),
    sa.Column('baseline_value', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('target_value', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('result_value', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('outcome', sa.Text(), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("status IN ('DRAFT','ACTIVE','COMPLETED','CANCELLED')", name=op.f('ck_development_plan_status')),
    sa.ForeignKeyConstraint(['capa_id'], ['pic.capa.id'], name=op.f('fk_development_plan_capa_id_capa')),
    sa.ForeignKeyConstraint(['supplier_id'], ['pic.supplier.id'], name=op.f('fk_development_plan_supplier_id_supplier')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_development_plan_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_development_plan')),
    sa.UniqueConstraint('tenant_id', 'number', name=op.f('uq_development_plan_tenant_id_number')),
    schema='pic'
    )
    op.create_index('ix_development_plan_supplier', 'development_plan', ['tenant_id', 'supplier_id'], unique=False, schema='pic')
    op.create_index(op.f('ix_development_plan_tenant_id'), 'development_plan', ['tenant_id'], unique=False, schema='pic')
    op.create_table('event_line_source',
    sa.Column('event_line_id', sa.UUID(), nullable=False),
    sa.Column('requisition_id', sa.UUID(), nullable=False),
    sa.Column('pr_line_no', sa.Integer(), nullable=False),
    sa.Column('qty', sa.Numeric(precision=18, scale=3), nullable=False),
    sa.Column('origin', sa.String(length=20), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint('qty > 0', name=op.f('ck_event_line_source_qty_positive')),
    sa.ForeignKeyConstraint(['event_line_id'], ['pic.event_line.id'], name=op.f('fk_event_line_source_event_line_id_event_line')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_event_line_source_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_event_line_source')),
    sa.UniqueConstraint('tenant_id', 'event_line_id', 'requisition_id', 'pr_line_no', name=op.f('uq_event_line_source_tenant_id_event_line_id_requisition_id_pr_line_no')),
    schema='pic'
    )
    op.create_index(op.f('ix_event_line_source_tenant_id'), 'event_line_source', ['tenant_id'], unique=False, schema='pic')
    op.create_table('rebate_agreement',
    sa.Column('number', sa.String(length=30), nullable=False),
    sa.Column('contract_id', sa.UUID(), nullable=False),
    sa.Column('supplier_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('basis', sa.String(length=10), nullable=False),
    sa.Column('period', sa.String(length=10), nullable=False),
    sa.Column('tier_mode', sa.String(length=12), nullable=False),
    sa.Column('scope', sa.String(length=10), nullable=False),
    sa.Column('tiers', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('valid_from', sa.Date(), nullable=False),
    sa.Column('valid_to', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('company_code', sa.String(length=10), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("basis IN ('VOLUME','VALUE')", name=op.f('ck_rebate_agreement_basis')),
    sa.CheckConstraint("period IN ('MONTHLY','QUARTERLY','ANNUAL')", name=op.f('ck_rebate_agreement_period')),
    sa.CheckConstraint("scope IN ('CONTRACT','SUPPLIER')", name=op.f('ck_rebate_agreement_scope')),
    sa.CheckConstraint("status IN ('ACTIVE','CLOSED','CANCELLED')", name=op.f('ck_rebate_agreement_status')),
    sa.CheckConstraint("tier_mode IN ('SLAB','RETROACTIVE')", name=op.f('ck_rebate_agreement_tier_mode')),
    sa.CheckConstraint('valid_to >= valid_from', name=op.f('ck_rebate_agreement_validity')),
    sa.ForeignKeyConstraint(['contract_id'], ['pic.contract.id'], name=op.f('fk_rebate_agreement_contract_id_contract')),
    sa.ForeignKeyConstraint(['supplier_id'], ['pic.supplier.id'], name=op.f('fk_rebate_agreement_supplier_id_supplier')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_rebate_agreement_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rebate_agreement')),
    sa.UniqueConstraint('tenant_id', 'number', name=op.f('uq_rebate_agreement_tenant_id_number')),
    schema='pic'
    )
    op.create_index('ix_rebate_agreement_contract', 'rebate_agreement', ['tenant_id', 'contract_id'], unique=False, schema='pic')
    op.create_index(op.f('ix_rebate_agreement_tenant_id'), 'rebate_agreement', ['tenant_id'], unique=False, schema='pic')
    op.create_table('development_action',
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reminders', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("status IN ('OPEN','DONE','CANCELLED')", name=op.f('ck_development_action_status')),
    sa.ForeignKeyConstraint(['plan_id'], ['pic.development_plan.id'], name=op.f('fk_development_action_plan_id_development_plan')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_development_action_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_development_action')),
    sa.UniqueConstraint('tenant_id', 'plan_id', 'seq', name=op.f('uq_development_action_tenant_id_plan_id_seq')),
    schema='pic'
    )
    op.create_index('ix_development_action_due', 'development_action', ['tenant_id', 'status', 'due_date'], unique=False, schema='pic')
    op.create_index(op.f('ix_development_action_tenant_id'), 'development_action', ['tenant_id'], unique=False, schema='pic')
    op.create_table('rebate_accrual',
    sa.Column('agreement_id', sa.UUID(), nullable=False),
    sa.Column('period_label', sa.String(length=12), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('basis_value_minor', sa.BigInteger(), nullable=False),
    sa.Column('basis_qty', sa.Numeric(precision=18, scale=3), nullable=False),
    sa.Column('rate_pct', sa.Numeric(precision=6, scale=3), nullable=False),
    sa.Column('accrued_minor', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("status IN ('OPEN','SETTLED')", name=op.f('ck_rebate_accrual_status')),
    sa.CheckConstraint('accrued_minor >= 0', name=op.f('ck_rebate_accrual_accrued_not_negative')),
    sa.ForeignKeyConstraint(['agreement_id'], ['pic.rebate_agreement.id'], name=op.f('fk_rebate_accrual_agreement_id_rebate_agreement')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_rebate_accrual_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rebate_accrual')),
    sa.UniqueConstraint('tenant_id', 'agreement_id', 'period_label', name=op.f('uq_rebate_accrual_tenant_id_agreement_id_period_label')),
    schema='pic'
    )
    op.create_index(op.f('ix_rebate_accrual_tenant_id'), 'rebate_accrual', ['tenant_id'], unique=False, schema='pic')
    op.create_table('rebate_settlement',
    sa.Column('number', sa.String(length=30), nullable=False),
    sa.Column('agreement_id', sa.UUID(), nullable=False),
    sa.Column('accrual_id', sa.UUID(), nullable=False),
    sa.Column('supplier_id', sa.UUID(), nullable=False),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('settled_by', sa.UUID(), nullable=True),
    sa.Column('erp_key', sa.String(length=120), nullable=False),
    sa.Column('erp_document', sa.String(length=40), nullable=True),
    sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("status IN ('PENDING_ERP','POSTED')", name=op.f('ck_rebate_settlement_status')),
    sa.CheckConstraint('amount_minor > 0', name=op.f('ck_rebate_settlement_amount_positive')),
    sa.ForeignKeyConstraint(['accrual_id'], ['pic.rebate_accrual.id'], name=op.f('fk_rebate_settlement_accrual_id_rebate_accrual')),
    sa.ForeignKeyConstraint(['agreement_id'], ['pic.rebate_agreement.id'], name=op.f('fk_rebate_settlement_agreement_id_rebate_agreement')),
    sa.ForeignKeyConstraint(['supplier_id'], ['pic.supplier.id'], name=op.f('fk_rebate_settlement_supplier_id_supplier')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_rebate_settlement_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rebate_settlement')),
    sa.UniqueConstraint('tenant_id', 'accrual_id', name=op.f('uq_rebate_settlement_tenant_id_accrual_id')),
    sa.UniqueConstraint('tenant_id', 'number', name=op.f('uq_rebate_settlement_tenant_id_number')),
    schema='pic'
    )
    op.create_index(op.f('ix_rebate_settlement_tenant_id'), 'rebate_settlement', ['tenant_id'], unique=False, schema='pic')

    op.add_column('material', sa.Column('version', sa.Integer(), server_default='1', nullable=False), schema='pic')
    op.add_column('scorecard', sa.Column('rfq_invited', sa.Integer(), server_default='0', nullable=False), schema='pic')
    op.add_column('scorecard', sa.Column('rfq_responded', sa.Integer(), server_default='0', nullable=False), schema='pic')
    op.add_column('scorecard', sa.Column('rfq_response_hours', sa.Numeric(precision=8, scale=2), nullable=True), schema='pic')
    op.add_column('scorecard', sa.Column('capa_response_hours', sa.Numeric(precision=8, scale=2), nullable=True), schema='pic')
    op.add_column('scorecard', sa.Column('esg_score', sa.Numeric(precision=5, scale=2), nullable=True), schema='pic')
    op.add_column('sourcing_event', sa.Column('bundle', postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema='pic')
    op.add_column('event_line', sa.Column('lot_code', sa.String(length=20), nullable=True), schema='pic')
    op.add_column('event_line', sa.Column('baseline_price_minor', sa.BigInteger(), nullable=True), schema='pic')
    op.add_column('criterion', sa.Column('data_source', sa.String(length=12), server_default='MANUAL', nullable=False), schema='pic')
    op.add_column('bid', sa.Column('auto_scores', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False), schema='pic')
    op.add_column('contract', sa.Column('framework_contract_id', sa.UUID(), nullable=True), schema='pic')
    op.add_column('contract', sa.Column('jurisdiction', sa.String(length=10), nullable=True), schema='pic')
    op.create_foreign_key(op.f('fk_contract_framework_contract_id_contract'), 'contract', 'contract', ['framework_contract_id'], ['id'],
                          source_schema='pic', referent_schema='pic')
    op.create_index('ix_contract_framework', 'contract', ['tenant_id', 'framework_contract_id'], unique=False, schema='pic')

    for table in NEW_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pic.{table} TO {ROLE}")
        op.execute(f"ALTER TABLE pic.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE pic.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON pic.{table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)""")
    # the supplier-segment history keeps one current row per supplier
    op.create_index('uq_supplier_segment_current', 'supplier_segment', ['tenant_id', 'supplier_id'], unique=True, schema='pic',
                    postgresql_where=sa.text('effective_to IS NULL'))
    op.create_check_constraint('ck_event_line_lot_code', 'event_line', "lot_code IS NULL OR lot_code ~ '^[A-Z0-9][A-Z0-9_-]{0,19}$'", schema='pic')
    op.create_check_constraint('ck_criterion_data_source', 'criterion', "data_source IN ('MANUAL','SCORECARD','ESG','RISK')", schema='pic')
    op.create_check_constraint('ck_contract_framework_not_self', 'contract', 'framework_contract_id IS NULL OR framework_contract_id <> id', schema='pic')
    op.create_check_constraint('ck_material_version_positive', 'material', 'version >= 1', schema='pic')


def downgrade() -> None:
    op.drop_index('ix_contract_framework', table_name='contract', schema='pic')
    op.drop_constraint(op.f('fk_contract_framework_contract_id_contract'), 'contract', type_='foreignkey', schema='pic')
    op.drop_constraint('ck_material_version_positive', 'material', type_='check', schema='pic')
    op.drop_constraint('ck_contract_framework_not_self', 'contract', type_='check', schema='pic')
    op.drop_constraint('ck_criterion_data_source', 'criterion', type_='check', schema='pic')
    op.drop_constraint('ck_event_line_lot_code', 'event_line', type_='check', schema='pic')
    op.drop_index('uq_supplier_segment_current', table_name='supplier_segment', schema='pic')
    for table, column in (("contract", "jurisdiction"), ("contract", "framework_contract_id"), ("bid", "auto_scores"), ("criterion", "data_source"),
                          ("event_line", "baseline_price_minor"), ("event_line", "lot_code"), ("sourcing_event", "bundle"), ("scorecard", "esg_score"),
                          ("scorecard", "capa_response_hours"), ("scorecard", "rfq_response_hours"), ("scorecard", "rfq_responded"),
                          ("scorecard", "rfq_invited"), ("material", "version")):
        op.drop_column(table, column, schema='pic')
    op.drop_index(op.f('ix_rebate_settlement_tenant_id'), table_name='rebate_settlement', schema='pic')
    op.drop_table('rebate_settlement', schema='pic')
    op.drop_index(op.f('ix_rebate_accrual_tenant_id'), table_name='rebate_accrual', schema='pic')
    op.drop_table('rebate_accrual', schema='pic')
    op.drop_index(op.f('ix_development_action_tenant_id'), table_name='development_action', schema='pic')
    op.drop_index('ix_development_action_due', table_name='development_action', schema='pic')
    op.drop_table('development_action', schema='pic')
    op.drop_index(op.f('ix_rebate_agreement_tenant_id'), table_name='rebate_agreement', schema='pic')
    op.drop_index('ix_rebate_agreement_contract', table_name='rebate_agreement', schema='pic')
    op.drop_table('rebate_agreement', schema='pic')
    op.drop_index(op.f('ix_event_line_source_tenant_id'), table_name='event_line_source', schema='pic')
    op.drop_table('event_line_source', schema='pic')
    op.drop_index(op.f('ix_development_plan_tenant_id'), table_name='development_plan', schema='pic')
    op.drop_index('ix_development_plan_supplier', table_name='development_plan', schema='pic')
    op.drop_table('development_plan', schema='pic')
    op.drop_index(op.f('ix_bid_lot_tenant_id'), table_name='bid_lot', schema='pic')
    op.drop_table('bid_lot', schema='pic')
    op.drop_index(op.f('ix_supplier_segment_tenant_id'), table_name='supplier_segment', schema='pic')
    op.drop_index('ix_supplier_segment_supplier', table_name='supplier_segment', schema='pic')
    op.drop_table('supplier_segment', schema='pic')
    op.drop_index(op.f('ix_supplier_assessment_tenant_id'), table_name='supplier_assessment', schema='pic')
    op.drop_index('ix_supplier_assessment_supplier', table_name='supplier_assessment', schema='pic')
    op.drop_table('supplier_assessment', schema='pic')
    op.drop_index(op.f('ix_material_version_tenant_id'), table_name='material_version', schema='pic')
    op.drop_table('material_version', schema='pic')
    op.drop_index(op.f('ix_material_change_request_tenant_id'), table_name='material_change_request', schema='pic')
    op.drop_index('ix_material_change_request_material', table_name='material_change_request', schema='pic')
    op.drop_table('material_change_request', schema='pic')
    op.drop_index(op.f('ix_clause_extraction_tenant_id'), table_name='clause_extraction', schema='pic')
    op.drop_table('clause_extraction', schema='pic')
