"""SAP live mapping for outline agreements, payment reversal and supply-chain financing (engineer A fills in).

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-09 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
