"""Strategic sourcing completion (M05, second pass): normalised multi-currency bids with a per-component TCO trace, the sourcing policy and TCO
rule sets, evaluator conflict declarations, two-person bid opening, bid withdrawal and disqualification, should-cost models, price benchmarks and
event templates.

All changes are additive; nothing is dropped and existing rows keep their meaning (an existing event scores by the lowest-price ratio as before,
an existing bid line has no quoted currency and no trace, an existing award decision has no recorded exceptions).

- sourcing_event: scheduled opening (``open_at``), scoring method, purpose code (P01, backfilled from the requirements), need date (backfilled), budget check and justification,
  clarification deadline, pricing reference date, minimum bidders, competitive flag, opening state, template / clone origin, rule versions.
- event_line: need date (backfilled from the requisition line).
- criterion: ``min_score`` (technical gate).
- bid: offer validity, withdrawal, disqualification, number of edits.
- bid_line: quoted price and currency, FX rate and date, incoterm, origin, MOQ, unit of the quoted price and its factor, tax inclusion and rate, HS
  code, ``tco_incomplete`` and the per-component ``tco_trace``.
- award_scenario: ``risk_score``. award_decision: ``authority``, ``exceptions``, ``regret_sent_at``.
- evaluator_declaration, bid_opening, should_cost_model, price_benchmark, sourcing_template: new tenant tables with the pic_app grants and forced
  row-level security.
- rule sets SOURCING-POLICY and SOURCING-TCO for every tenant that has no version yet.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-04 12:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0022'
down_revision: Union[str, Sequence[str], None] = '0021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "pic_app"
CTX = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
NEW_TABLES = ["evaluator_declaration", "bid_opening", "should_cost_model", "price_benchmark", "sourcing_template"]
RULE_KEYS = ("SOURCING-POLICY", "SOURCING-TCO")


def _base(table: str) -> list:
    return [sa.Column('id', sa.UUID(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('created_by', sa.UUID(), nullable=True), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('row_version', sa.Integer(), nullable=False), sa.Column('tenant_id', sa.UUID(), nullable=False)]


def _finish(table: str, *constraints) -> None:
    op.create_index(op.f(f'ix_{table}_tenant_id'), table, ['tenant_id'], unique=False, schema='pic')
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pic.{table} TO {ROLE}")
    op.execute(f"ALTER TABLE pic.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE pic.{table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON pic.{table} USING (tenant_id = {CTX}) WITH CHECK (tenant_id = {CTX})")


def _columns() -> None:
    def add(table: str, column: sa.Column) -> None:
        op.add_column(table, column, schema='pic')

    add('sourcing_event', sa.Column('scoring_method', sa.String(length=12), nullable=False, server_default='LOWEST_RATIO'))
    add('sourcing_event', sa.Column('purpose_code', sa.String(length=40), nullable=True))
    add('sourcing_event', sa.Column('need_date', sa.Date(), nullable=True))
    add('sourcing_event', sa.Column('budget_check', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    add('sourcing_event', sa.Column('budget_justification', sa.Text(), nullable=True))
    add('sourcing_event', sa.Column('clarification_close_at', sa.DateTime(timezone=True), nullable=True))
    add('sourcing_event', sa.Column('reference_date', sa.Date(), nullable=True))
    add('sourcing_event', sa.Column('min_bidders', sa.Integer(), nullable=True))
    add('sourcing_event', sa.Column('competitive', sa.Boolean(), nullable=True))
    add('sourcing_event', sa.Column('opening', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'))
    add('sourcing_event', sa.Column('template_code', sa.String(length=40), nullable=True))
    add('sourcing_event', sa.Column('cloned_from', sa.String(length=30), nullable=True))
    add('sourcing_event', sa.Column('rule_versions', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'))
    add('sourcing_event', sa.Column('open_at', sa.DateTime(timezone=True), nullable=True))
    add('event_line', sa.Column('need_date', sa.Date(), nullable=True))
    add('criterion', sa.Column('min_score', sa.Numeric(precision=5, scale=2), nullable=True))
    add('bid', sa.Column('valid_until', sa.Date(), nullable=True))
    add('bid', sa.Column('withdrawn_at', sa.DateTime(timezone=True), nullable=True))
    add('bid', sa.Column('withdrawn_reason', sa.Text(), nullable=True))
    add('bid', sa.Column('disqualified_at', sa.DateTime(timezone=True), nullable=True))
    add('bid', sa.Column('disqualified_by', sa.UUID(), nullable=True))
    add('bid', sa.Column('disqualified_reason', sa.Text(), nullable=True))
    add('bid', sa.Column('edits', sa.Integer(), nullable=False, server_default='0'))
    add('bid_line', sa.Column('price_quoted_minor', sa.BigInteger(), nullable=True))
    add('bid_line', sa.Column('currency', sa.String(length=3), nullable=True))
    add('bid_line', sa.Column('fx_rate', sa.Numeric(precision=18, scale=8), nullable=True))
    add('bid_line', sa.Column('fx_date', sa.Date(), nullable=True))
    add('bid_line', sa.Column('incoterm', sa.String(length=10), nullable=True))
    add('bid_line', sa.Column('origin', sa.String(length=10), nullable=True))
    add('bid_line', sa.Column('moq', sa.Numeric(precision=18, scale=3), nullable=True))
    add('bid_line', sa.Column('price_uom', sa.String(length=5), nullable=True))
    add('bid_line', sa.Column('uom_factor', sa.Numeric(precision=18, scale=6), nullable=True))
    add('bid_line', sa.Column('tax_included', sa.Boolean(), nullable=False, server_default='false'))
    add('bid_line', sa.Column('tax_rate_pct', sa.Numeric(precision=5, scale=2), nullable=True))
    add('bid_line', sa.Column('hs_code', sa.String(length=10), nullable=True))
    add('bid_line', sa.Column('tco_incomplete', sa.Boolean(), nullable=False, server_default='false'))
    add('bid_line', sa.Column('tco_trace', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'))
    add('award_scenario', sa.Column('risk_score', sa.Integer(), nullable=True))
    add('award_decision', sa.Column('authority', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    add('award_decision', sa.Column('exceptions', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'))
    add('award_decision', sa.Column('regret_sent_at', sa.DateTime(timezone=True), nullable=True))
    # backfill: the purpose code and need date an existing event sourced
    op.execute("""
        UPDATE pic.event_line l SET need_date = x.need_date
        FROM (SELECT l2.id, min(p.need_date) AS need_date FROM pic.event_line l2
              JOIN pic.pr_line p ON p.requisition_id = l2.requisition_id AND p.line_no = l2.pr_line_no GROUP BY l2.id) x
        WHERE x.id = l.id AND l.need_date IS NULL""")
    op.execute("""
        UPDATE pic.sourcing_event e SET need_date = x.need_date, purpose_code = x.purpose_code
        FROM (SELECT l.event_id, min(l.need_date) AS need_date, min(r.purpose_code) AS purpose_code FROM pic.event_line l
              LEFT JOIN pic.requisition r ON r.id = l.requisition_id GROUP BY l.event_id) x
        WHERE x.event_id = e.id AND e.need_date IS NULL AND e.purpose_code IS NULL""")


def _tables() -> None:
    op.create_table('evaluator_declaration', *_base('evaluator_declaration'),
        sa.Column('event_id', sa.UUID(), nullable=False), sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('has_conflict', sa.Boolean(), nullable=False), sa.Column('declaration', sa.Text(), nullable=False),
        sa.Column('declared_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_evaluator_declaration_tenant_id_tenant')),
        sa.ForeignKeyConstraint(['event_id'], ['pic.sourcing_event.id'], name=op.f('fk_evaluator_declaration_event_id_sourcing_event')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_evaluator_declaration')),
        sa.UniqueConstraint('tenant_id', 'event_id', 'user_id', name=op.f('uq_evaluator_declaration_tenant_id_event_id_user_id')), schema='pic')
    _finish('evaluator_declaration')
    op.create_table('bid_opening', *_base('bid_opening'),
        sa.Column('event_id', sa.UUID(), nullable=False), sa.Column('round', sa.Integer(), nullable=False), sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_bid_opening_tenant_id_tenant')),
        sa.ForeignKeyConstraint(['event_id'], ['pic.sourcing_event.id'], name=op.f('fk_bid_opening_event_id_sourcing_event')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_bid_opening')),
        sa.UniqueConstraint('tenant_id', 'event_id', 'round', 'user_id', name=op.f('uq_bid_opening_tenant_id_event_id_round_user_id')), schema='pic')
    _finish('bid_opening')
    op.create_table('should_cost_model', *_base('should_cost_model'),
        sa.Column('code', sa.String(length=40), nullable=False), sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('commodity', sa.String(length=40), nullable=False), sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('spec', postgresql.JSONB(astext_type=sa.Text()), nullable=False), sa.Column('index_code', sa.String(length=30), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true'), sa.Column('note', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_should_cost_model_tenant_id_tenant')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_should_cost_model')),
        sa.UniqueConstraint('tenant_id', 'code', 'version', name=op.f('uq_should_cost_model_tenant_id_code_version')), schema='pic')
    _finish('should_cost_model')
    op.create_table('price_benchmark', *_base('price_benchmark'),
        sa.Column('category', sa.String(length=40), nullable=False), sa.Column('material_id', sa.UUID(), nullable=True),
        sa.Column('kind', sa.String(length=15), nullable=False), sa.Column('as_of', sa.Date(), nullable=False),
        sa.Column('price_minor', sa.BigInteger(), nullable=False), sa.Column('uom', sa.String(length=5), nullable=False),
        sa.Column('source', sa.String(length=80), nullable=False), sa.Column('note', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_price_benchmark_tenant_id_tenant')),
        sa.ForeignKeyConstraint(['material_id'], ['pic.material.id'], name=op.f('fk_price_benchmark_material_id_material')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_price_benchmark')), schema='pic')
    op.create_index('ix_price_benchmark_category', 'price_benchmark', ['tenant_id', 'category', 'as_of'], unique=False, schema='pic')
    _finish('price_benchmark')
    op.create_table('sourcing_template', *_base('sourcing_template'),
        sa.Column('code', sa.String(length=40), nullable=False), sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('event_type', sa.String(length=20), nullable=False), sa.Column('category', sa.String(length=40), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
        sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_sourcing_template_tenant_id_tenant')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_sourcing_template')),
        sa.UniqueConstraint('tenant_id', 'code', name=op.f('uq_sourcing_template_tenant_id_code')), schema='pic')
    _finish('sourcing_template')


def _rule_sets() -> None:
    from app.pic.platform import sourcing_defaults
    for key, (body, description) in sourcing_defaults.BODIES.items():
        op.execute(sa.text(
            "INSERT INTO pic.rule_set (id, created_at, row_version, tenant_id, key, version, effective_from, body, description) "
            "SELECT gen_random_uuid(), now(), 1, t.id, :key, '2026.1', DATE '2026-04-01', CAST(:body AS jsonb), :description FROM pic.tenant t "
            "WHERE NOT EXISTS (SELECT 1 FROM pic.rule_set r WHERE r.tenant_id = t.id AND r.key = :key)"
        ).bindparams(key=key, body=json.dumps(body), description=description))


def upgrade() -> None:
    _columns()
    _tables()
    _rule_sets()


def downgrade() -> None:
    op.execute("DELETE FROM pic.rule_set WHERE key IN ('SOURCING-POLICY','SOURCING-TCO')")
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON pic.{table}")
        op.drop_table(table, schema='pic')
    for table, columns in (
            ('award_decision', ['regret_sent_at', 'exceptions', 'authority']), ('award_scenario', ['risk_score']),
            ('bid_line', ['tco_trace', 'tco_incomplete', 'hs_code', 'tax_rate_pct', 'tax_included', 'uom_factor', 'price_uom', 'moq', 'origin',
                          'incoterm', 'fx_date', 'fx_rate', 'currency', 'price_quoted_minor']),
            ('bid', ['edits', 'disqualified_reason', 'disqualified_by', 'disqualified_at', 'withdrawn_reason', 'withdrawn_at', 'valid_until']),
            ('criterion', ['min_score']), ('event_line', ['need_date']),
            ('sourcing_event', ['open_at', 'rule_versions', 'cloned_from', 'template_code', 'opening', 'competitive', 'min_bidders', 'reference_date',
                                'clarification_close_at', 'budget_justification', 'budget_check', 'need_date', 'purpose_code', 'scoring_method'])):
        for column in columns:
            op.drop_column(table, column, schema='pic')
