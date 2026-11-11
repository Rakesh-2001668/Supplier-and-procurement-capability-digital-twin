"""Organisation registration (unified platform, phase 3): self-service requests approved by a platform operator.

- tenant.kind may also be PLATFORM: the platform's own organisation, whose users are the platform operators (role PLATFORM_OPERATOR). They
  sign in like everyone else (sign-in by e-mail, mandatory MFA) and their decisions are audited in that organisation's hash chain.
- org_registration: one row per registration request. Global (no tenant_id, so not under row-level security) and not granted to the
  application role ``pic_app``: the public registration endpoints and the operator console read and write it as the owner (system_tx), after
  their own checks. Holds the organisation's shared mailbox and domain, the named first administrator, the optional "authorised by" person,
  the e-mail verification (only the SHA-256 of the link token), the screening result and the operator's decision.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "pic_app"
STATUSES = ("PENDING_VERIFICATION", "PENDING_APPROVAL", "APPROVED", "REJECTED", "EXPIRED")


def _tenant_kind_check(values: str) -> None:
    # Migration 0029 named the constraint through the metadata naming convention ("ck_%(table_name)s_%(constraint_name)s"), so it is
    # ck_tenant_ck_tenant_kind; plain SQL keeps the name exact here and drops either spelling.
    op.execute("ALTER TABLE pic.tenant DROP CONSTRAINT IF EXISTS ck_tenant_ck_tenant_kind")
    op.execute("ALTER TABLE pic.tenant DROP CONSTRAINT IF EXISTS ck_tenant_kind")
    op.execute(f"ALTER TABLE pic.tenant ADD CONSTRAINT ck_tenant_ck_tenant_kind CHECK (kind IN ({values}))")


def upgrade() -> None:
    _tenant_kind_check("'BUYER', 'SUPPLIER', 'PLATFORM'")

    op.create_table(
        "org_registration",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("number", sa.String(length=20), nullable=False, unique=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("state_code", sa.String(length=2)),
        sa.Column("industry_template", sa.String(length=40), nullable=False),
        sa.Column("gstin", sa.String(length=15)),
        sa.Column("org_email", sa.String(length=200), nullable=False),
        sa.Column("org_domain", sa.String(length=200), nullable=False),
        sa.Column("admin_name", sa.String(length=200), nullable=False),
        sa.Column("admin_email", sa.String(length=200), nullable=False),
        sa.Column("admin_phone", sa.String(length=20)),
        sa.Column("authorised_by_name", sa.String(length=200)),
        sa.Column("authorised_by_designation", sa.String(length=120)),
        sa.Column("expected_users", sa.Integer()),
        sa.Column("verify_token_hash", sa.String(length=64), unique=True),
        sa.Column("verify_expires_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("screening", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("organisation_code", sa.String(length=20)),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pic.tenant.id")),
        sa.Column("decided_by", sa.String(length=200)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_reason", sa.Text()),
        sa.Column("request_ip", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('BUYER', 'SUPPLIER')", name="ck_org_registration_kind"),
        sa.CheckConstraint("status IN (" + ", ".join(repr(s) for s in STATUSES) + ")", name="ck_org_registration_status"),
        schema="pic",
    )
    op.create_index("ix_org_registration_status", "org_registration", ["status", "created_at"], schema="pic")
    op.create_index("ix_org_registration_domain", "org_registration", ["org_domain"], schema="pic")
    op.execute(f"REVOKE ALL ON pic.org_registration FROM {ROLE}")


def downgrade() -> None:
    op.drop_index("ix_org_registration_domain", table_name="org_registration", schema="pic")
    op.drop_index("ix_org_registration_status", table_name="org_registration", schema="pic")
    op.drop_table("org_registration", schema="pic")
    _tenant_kind_check("'BUYER', 'SUPPLIER'")
