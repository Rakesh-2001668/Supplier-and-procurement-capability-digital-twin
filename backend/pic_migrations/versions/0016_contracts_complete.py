"""Contracts (M07 CLM) completion: obligation completion evidence, contract category, per-line consumption alerts.

- obligation: ``kind`` (OBLIGATION | MILESTONE), ``completed_at`` / ``completed_by`` / ``completion_note`` so the on-time KPI compares the
  completion date with the due date instead of counting any completed obligation as met.
- clause: ``standard_text`` (library wording at draft time, so the AI review detects a changed wording even when the position is STANDARD).
- contract: ``category`` (the category whose clause overlay the draft was built from; blueprint 13.1 templates by category).
- contract_line: ``thresholds_hit`` (80 / 90 / 100 % alerts already raised for that line; each line alerts on its own).

Existing tables only: row-level security and grants already cover them.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-01 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('obligation', sa.Column('kind', sa.String(length=12), server_default='OBLIGATION', nullable=False), schema='pic')
    op.add_column('obligation', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True), schema='pic')
    op.add_column('obligation', sa.Column('completed_by', sa.UUID(), nullable=True), schema='pic')
    op.add_column('obligation', sa.Column('completion_note', sa.Text(), nullable=True), schema='pic')
    op.add_column('clause', sa.Column('standard_text', sa.Text(), nullable=True), schema='pic')
    op.add_column('contract', sa.Column('category', sa.String(length=40), nullable=True), schema='pic')
    op.add_column('contract_line', sa.Column('thresholds_hit', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
                  schema='pic')
    # Backfill: lines of contracts that already raised an alert keep it, so the new per-line check does not alert twice.
    op.execute("UPDATE pic.contract_line l SET thresholds_hit = c.thresholds_hit FROM pic.contract c "
               "WHERE c.id = l.contract_id AND jsonb_array_length(coalesce(c.thresholds_hit, '[]'::jsonb)) > 0")
    # Backfill: an obligation completed before this migration has no timestamp; its last update is the best evidence.
    # Backfill: a clause still on a STANDARD position carries the library wording as it was drafted.
    op.execute("UPDATE pic.clause SET standard_text = text WHERE position = 'STANDARD'")
    op.execute("UPDATE pic.obligation SET completed_at = coalesce(updated_at, created_at) WHERE status IN ('DONE', 'COMPLETED')")


def downgrade() -> None:
    op.drop_column('contract_line', 'thresholds_hit', schema='pic')
    op.drop_column('contract', 'category', schema='pic')
    op.drop_column('clause', 'standard_text', schema='pic')
    for column in ('completion_note', 'completed_by', 'completed_at', 'kind'):
        op.drop_column('obligation', column, schema='pic')
