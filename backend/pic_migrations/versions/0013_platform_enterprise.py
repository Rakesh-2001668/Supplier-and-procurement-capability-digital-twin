"""Platform enterprise wave 1: versioned workflow definitions (tenant-owned versions with RLS, status, revision), SoD mitigation
grants, tenant ERP field mappings with the outbound payload/mapping version on integration messages, and the tenant MFA default.

- process_definition: status DRAFT/ACTIVE/RETIRED (backfilled from ``active``), tenant_id (NULL = the shared baseline), revision
  (ETag of a draft), note, base_version, created_by/at, published_at. pic_app may now write the table, but row-level security
  limits it to the tenant's own rows (the shared baseline stays read-only for it). Version 1 of the nine flows is reloaded from
  platform/process_defs.py with the sequence flows, lanes and task kinds the designer and validator need.
- sod_mitigation, integration_field_mapping: new tenant tables (grants, forced RLS, tenant_isolation policy, CHECKs).
- integration_message.outbound_payload / mapping_version.
- tenant.mfa_enforce: set for tenants created after this release (existing tenants keep their current MFA rule).

Revision ID: 0013
Revises: 0007
Create Date: 2026-10-30 12:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0013'
down_revision: Union[str, Sequence[str], None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "pic_app"
NEW_TABLES = ("sod_mitigation", "integration_field_mapping")
CTX = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _base():
    return [
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
    ]


def upgrade() -> None:
    # ---------------------------------------------------------------- process_definition
    op.add_column('process_definition', sa.Column('status', sa.String(length=10), server_default='ACTIVE', nullable=False), schema='pic')
    op.add_column('process_definition', sa.Column('tenant_id', sa.UUID(), nullable=True), schema='pic')
    op.add_column('process_definition', sa.Column('revision', sa.Integer(), server_default='1', nullable=False), schema='pic')
    op.add_column('process_definition', sa.Column('note', sa.Text(), nullable=True), schema='pic')
    op.add_column('process_definition', sa.Column('base_version', sa.Integer(), nullable=True), schema='pic')
    op.add_column('process_definition', sa.Column('created_by', sa.UUID(), nullable=True), schema='pic')
    op.add_column('process_definition', sa.Column('created_at', sa.DateTime(timezone=True), nullable=True), schema='pic')
    op.add_column('process_definition', sa.Column('published_at', sa.DateTime(timezone=True), nullable=True), schema='pic')
    op.execute("UPDATE pic.process_definition SET status = CASE WHEN active THEN 'ACTIVE' ELSE 'RETIRED' END, "
               "created_at = now(), published_at = now()")
    op.create_foreign_key('fk_process_definition_tenant_id_tenant', 'process_definition', 'tenant', ['tenant_id'], ['id'],
                          source_schema='pic', referent_schema='pic')
    op.create_index('ix_process_definition_tenant_id', 'process_definition', ['tenant_id'], unique=False, schema='pic')
    op.create_check_constraint('ck_process_definition_status', 'process_definition', "status IN ('DRAFT','ACTIVE','RETIRED')", schema='pic')
    # Tenants may write their own rows; the shared baseline (tenant_id NULL) stays readable only.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pic.process_definition TO {ROLE}")
    op.execute("ALTER TABLE pic.process_definition ENABLE ROW LEVEL SECURITY")  # not FORCE: the owner (seed, migrations) is exempt
    op.execute(f"CREATE POLICY process_definition_read ON pic.process_definition FOR SELECT USING (tenant_id IS NULL OR tenant_id = {CTX})")
    op.execute(f"CREATE POLICY process_definition_write ON pic.process_definition FOR ALL USING (tenant_id = {CTX}) WITH CHECK (tenant_id = {CTX})")
    _load_baseline()

    # ---------------------------------------------------------------- integration_message, tenant
    op.add_column('integration_message', sa.Column('outbound_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema='pic')
    op.add_column('integration_message', sa.Column('mapping_version', sa.Integer(), nullable=True), schema='pic')
    op.add_column('tenant', sa.Column('mfa_enforce', sa.Boolean(), server_default='false', nullable=False), schema='pic')

    # ---------------------------------------------------------------- new tenant tables
    op.create_table('sod_mitigation',
        sa.Column('rule_code', sa.String(length=10), nullable=False),
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('requester_id', sa.UUID(), nullable=False),
        sa.Column('refs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('scope_value', sa.String(length=80), nullable=False),
        sa.Column('justification', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('requested_validity_hours', sa.Integer(), nullable=False),
        sa.Column('compensating_control', sa.Text(), nullable=False),
        sa.Column('approver_roles', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('max_uses', sa.Integer(), nullable=False),
        sa.Column('use_count', sa.Integer(), nullable=False),
        sa.Column('decided_by', sa.UUID(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision_comment', sa.Text(), nullable=True),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=True),
        sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        *_base(),
        sa.CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','REVOKED')", name='ck_sod_mitigation_status'),
        sa.CheckConstraint('requested_validity_hours > 0', name='ck_sod_mitigation_validity_positive'),
        sa.CheckConstraint('valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from', name='ck_sod_mitigation_window'),
        sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_sod_mitigation_tenant_id_tenant')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_sod_mitigation')),
        schema='pic',
    )
    op.create_index(op.f('ix_sod_mitigation_tenant_id'), 'sod_mitigation', ['tenant_id'], unique=False, schema='pic')
    op.create_index('ix_sod_mitigation_lookup', 'sod_mitigation', ['tenant_id', 'requester_id', 'action', 'status'], unique=False, schema='pic')

    op.create_table('integration_field_mapping',
        sa.Column('target_system', sa.String(length=30), nullable=False),
        sa.Column('message_type', sa.String(length=40), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('rules', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_by', sa.UUID(), nullable=True),
        *_base(),
        sa.CheckConstraint("status IN ('DRAFT','ACTIVE','RETIRED')", name='ck_integration_field_mapping_status'),
        sa.CheckConstraint('version > 0', name='ck_integration_field_mapping_version'),
        sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_integration_field_mapping_tenant_id_tenant')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_integration_field_mapping')),
        sa.UniqueConstraint('tenant_id', 'target_system', 'message_type', 'version', name='uq_integration_field_mapping_version'),
        schema='pic',
    )
    op.create_index(op.f('ix_integration_field_mapping_tenant_id'), 'integration_field_mapping', ['tenant_id'], unique=False, schema='pic')
    op.create_index('uq_integration_field_mapping_active', 'integration_field_mapping', ['tenant_id', 'target_system', 'message_type'],
                    unique=True, schema='pic', postgresql_where=sa.text("status = 'ACTIVE'"))

    for table in NEW_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pic.{table} TO {ROLE}")
        op.execute(f"ALTER TABLE pic.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE pic.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON pic.{table} USING (tenant_id = {CTX}) WITH CHECK (tenant_id = {CTX})")


def _load_baseline() -> None:
    """Version 1 of F1-F9 with sequence flows, lanes and task kinds (platform/process_defs.py is the source)."""
    from app.pic.platform import process_defs
    conn = op.get_bind()
    for d in process_defs.baseline():
        body = json.dumps(d["definition"])
        updated = conn.execute(sa.text(
            "UPDATE pic.process_definition SET definition = CAST(:body AS jsonb), name = :name, status = 'ACTIVE', active = true "
            "WHERE key = :key AND version = :version AND tenant_id IS NULL"),
            {"body": body, "name": d["name"], "key": d["key"], "version": d["version"]}).rowcount
        if not updated:
            conn.execute(sa.text(
                "INSERT INTO pic.process_definition (key, version, flow_id, name, definition, active, status, created_at, published_at) "
                "VALUES (:key, :version, :flow, :name, CAST(:body AS jsonb), true, 'ACTIVE', now(), now()) ON CONFLICT DO NOTHING"),
                {"body": body, "name": d["name"], "key": d["key"], "version": d["version"], "flow": d["flow_id"]})


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON pic.{table}")
    op.drop_index('uq_integration_field_mapping_active', table_name='integration_field_mapping', schema='pic')
    op.drop_index(op.f('ix_integration_field_mapping_tenant_id'), table_name='integration_field_mapping', schema='pic')
    op.drop_table('integration_field_mapping', schema='pic')
    op.drop_index('ix_sod_mitigation_lookup', table_name='sod_mitigation', schema='pic')
    op.drop_index(op.f('ix_sod_mitigation_tenant_id'), table_name='sod_mitigation', schema='pic')
    op.drop_table('sod_mitigation', schema='pic')
    op.drop_column('tenant', 'mfa_enforce', schema='pic')
    op.drop_column('integration_message', 'mapping_version', schema='pic')
    op.drop_column('integration_message', 'outbound_payload', schema='pic')
    op.execute("DROP POLICY IF EXISTS process_definition_write ON pic.process_definition")
    op.execute("DROP POLICY IF EXISTS process_definition_read ON pic.process_definition")
    op.execute("ALTER TABLE pic.process_definition DISABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON pic.process_definition FROM {ROLE}")
    op.execute("DELETE FROM pic.process_definition WHERE tenant_id IS NOT NULL")
    op.drop_constraint('ck_process_definition_status', 'process_definition', type_='check', schema='pic')
    op.drop_index('ix_process_definition_tenant_id', table_name='process_definition', schema='pic')
    op.drop_constraint('fk_process_definition_tenant_id_tenant', 'process_definition', type_='foreignkey', schema='pic')
    for column in ('published_at', 'created_at', 'created_by', 'base_version', 'note', 'revision', 'tenant_id', 'status'):
        op.drop_column('process_definition', column, schema='pic')
