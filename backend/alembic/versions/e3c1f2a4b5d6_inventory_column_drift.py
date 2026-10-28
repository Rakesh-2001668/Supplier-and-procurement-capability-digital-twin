"""Inventory column drift

The inventory models gained category, unit, thresholds, location, status and the
stock-transaction audit fields without a migration; databases built with create_all
(the Docker supplier_twin database) have them, databases built from this chain do not.
ADD COLUMN IF NOT EXISTS makes this safe on both.

Revision ID: e3c1f2a4b5d6
Revises: d504090e6c08
Create Date: 2026-10-27 12:00:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e3c1f2a4b5d6'
down_revision: Union[str, Sequence[str], None] = 'd504090e6c08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = [
    ("inventory_items", "category", "VARCHAR(100)"),
    ("inventory_items", "unit", "VARCHAR(30)"),
    ("inventory_items", "min_threshold", "INTEGER"),
    ("inventory_items", "max_capacity", "INTEGER"),
    ("inventory_items", "location", "VARCHAR(100)"),
    ("inventory_items", "status", "VARCHAR(50)"),
    ("stock_transactions", "notes", "TEXT"),
    ("stock_transactions", "performed_by", "VARCHAR(100)"),
    ("stock_transactions", "balance_after", "INTEGER"),
]


def upgrade() -> None:
    """Upgrade schema."""
    for table, column, type_ in COLUMNS:
        op.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {type_}')


def downgrade() -> None:
    """Downgrade schema."""
    for table, column, _ in reversed(COLUMNS):
        op.execute(f'ALTER TABLE {table} DROP COLUMN IF EXISTS {column}')
