"""Invoice approval bands, CFO role and the expired-bid award block: no schema change.

Everything lives in existing tables and in code: the CFO role is a built-in role (platform/auth.py ROLE_SCOPES), the default bands are a rule
body (rule_set INVOICE-APPROVAL; p2p_defaults.INVOICE_APPROVAL_BANDS for new tenants, dataset pack approval_bands for the demo tenants), the
expired-offer override policy is a SOURCING-POLICY key with a code default, and the override itself is kept in award_decision.exceptions (JSON).
Existing tenants keep their rules unchanged ("bands": [] = accounts-payable approval only). The revision stays in the chain (0026 -> 0027 -> 0028).

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-09 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
