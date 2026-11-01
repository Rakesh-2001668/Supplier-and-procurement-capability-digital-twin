"""Enterprise administration (M13, ADM-01..ADM-04): organisation management, user lifecycle, custom roles, template applications.

- company_code, plant, storage_location, cost_object: ``active`` (deactivated instead of deleted once referenced).
- app_user: ``session_version`` (revoke sessions) and ``activation_pending`` (invited, link not yet used).
- purchasing_org, purchasing_group: new master tables.
- user_token: single-use activation / password-reset tokens (SHA-256 only).
- tenant: pic_app may update industry_template only (applying a template pack).
- role_def: tenant-defined roles. template_application: who applied which industry template and what it changed.

New tenant tables get the pic_app grants and forced row-level security like migrations 0005, 0007, 0012 and 0013.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-01 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0015'
down_revision: Union[str, Sequence[str], None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "pic_app"
NEW_TABLES = ("purchasing_org", "purchasing_group", "user_token", "role_def", "template_application")
CTX = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
ACTIVE_TABLES = ("company_code", "plant", "storage_location", "cost_object")


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


def upgrade() -> None:
    for table in ACTIVE_TABLES:
        op.add_column(table, sa.Column('active', sa.Boolean(), server_default='true', nullable=False), schema='pic')
    op.add_column('app_user', sa.Column('session_version', sa.Integer(), server_default='1', nullable=False), schema='pic')
    op.add_column('app_user', sa.Column('activation_pending', sa.Boolean(), server_default='false', nullable=False), schema='pic')

    op.create_table('purchasing_org',
        sa.Column('code', sa.String(length=10), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('company_code', sa.String(length=10), nullable=False),
        sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
        *_base(), *_tail('purchasing_org'),
        sa.UniqueConstraint('tenant_id', 'code', name=op.f('uq_purchasing_org_tenant_id_code')),
        schema='pic')
    op.create_index(op.f('ix_purchasing_org_tenant_id'), 'purchasing_org', ['tenant_id'], unique=False, schema='pic')

    op.create_table('purchasing_group',
        sa.Column('code', sa.String(length=10), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('purchasing_org', sa.String(length=10), nullable=True),
        sa.Column('plant', sa.String(length=10), nullable=True),
        sa.Column('buyer_user_ids', postgresql.ARRAY(sa.UUID()), server_default='{}', nullable=False),
        sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
        *_base(), *_tail('purchasing_group'),
        sa.UniqueConstraint('tenant_id', 'code', name=op.f('uq_purchasing_group_tenant_id_code')),
        schema='pic')
    op.create_index(op.f('ix_purchasing_group_tenant_id'), 'purchasing_group', ['tenant_id'], unique=False, schema='pic')

    op.create_table('user_token',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('purpose', sa.String(length=20), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        *_base(), *_tail('user_token'),
        sa.CheckConstraint("purpose IN ('ACTIVATION','PASSWORD_RESET')", name='ck_user_token_purpose'),
        sa.UniqueConstraint('token_hash', name='uq_user_token_hash'),
        schema='pic')
    op.create_index(op.f('ix_user_token_tenant_id'), 'user_token', ['tenant_id'], unique=False, schema='pic')
    op.create_index('ix_user_token_user', 'user_token', ['tenant_id', 'user_id', 'purpose'], unique=False, schema='pic')

    op.create_table('role_def',
        sa.Column('code', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('scopes', postgresql.ARRAY(sa.String(length=40)), nullable=False),
        sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
        *_base(), *_tail('role_def'),
        sa.UniqueConstraint('tenant_id', 'code', name=op.f('uq_role_def_tenant_id_code')),
        schema='pic')
    op.create_index(op.f('ix_role_def_tenant_id'), 'role_def', ['tenant_id'], unique=False, schema='pic')

    op.create_table('template_application',
        sa.Column('template', sa.String(length=40), nullable=False),
        sa.Column('previous_template', sa.String(length=40), nullable=True),
        sa.Column('applied_by', sa.UUID(), nullable=True),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_base(), *_tail('template_application'),
        schema='pic')
    op.create_index(op.f('ix_template_application_tenant_id'), 'template_application', ['tenant_id'], unique=False, schema='pic')

    for table in NEW_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pic.{table} TO {ROLE}")
        op.execute(f"ALTER TABLE pic.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE pic.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON pic.{table} USING (tenant_id = {CTX}) WITH CHECK (tenant_id = {CTX})")


    # Applying an industry template switches the tenant's own template: column-level, so nothing else of the tenant directory is writable.
    op.execute(f"GRANT UPDATE (industry_template) ON pic.tenant TO {ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE (industry_template) ON pic.tenant FROM {ROLE}")
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON pic.{table}")
        op.drop_index(op.f(f'ix_{table}_tenant_id'), table_name=table, schema='pic')
        if table == 'user_token':
            op.drop_index('ix_user_token_user', table_name=table, schema='pic')
        op.drop_table(table, schema='pic')
    op.drop_column('app_user', 'activation_pending', schema='pic')
    op.drop_column('app_user', 'session_version', schema='pic')
    for table in ACTIVE_TABLES:
        op.drop_column(table, 'active', schema='pic')
