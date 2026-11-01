"""Wave 1 (engineer A): scheduled job registry and run history (scheduled_job, job_run), delegation of authority (delegation), the
tenant flag table (AI switch), agent suspension columns, and the verifiable audit archive (audit_archive_batch, audit_event_archive).

Every new table gets forced row-level security. The audit trail stays append-only for the application role: events leave
audit_event only through pic.audit_archive_range(), a SECURITY DEFINER function that moves a verified range to the archive in one
transaction and records the checkpoint (anchor and head hash) the chain verification continues from; archived rows can be
dropped after the statutory retention only through pic.audit_archive_expire(), which keeps the batch checkpoint.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-30 21:19:44.727967

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "pic_app"
CRUD_TABLES = ("scheduled_job", "job_run", "delegation", "tenant_flag")
ARCHIVE_TABLES = ("audit_archive_batch", "audit_event_archive")  # read-only for pic_app: written by the definer functions

ARCHIVE_RANGE = """
CREATE OR REPLACE FUNCTION pic.audit_archive_range(p_tenant uuid, p_seq_to bigint, p_batch uuid, p_expected integer,
                                                   p_content text, p_by text, p_reason text)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pic, pg_temp AS $$
DECLARE
    v_ctx text; v_from bigint; v_max bigint; v_count integer; v_anchor text; v_head text; v_first timestamptz; v_last timestamptz;
    v_prev_head text;
BEGIN
    v_ctx := NULLIF(current_setting('app.tenant_id', true), '');
    IF v_ctx IS NULL OR v_ctx::uuid <> p_tenant THEN
        RAISE EXCEPTION 'audit archive: tenant context mismatch' USING ERRCODE = 'insufficient_privilege';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtext('audit:' || p_tenant::text));  -- the key audit.record() takes
    SELECT min(seq), max(seq) INTO v_from, v_max FROM pic.audit_event WHERE tenant_id = p_tenant;
    IF v_from IS NULL OR p_seq_to < v_from OR p_seq_to >= v_max THEN
        RAISE EXCEPTION 'audit archive: the range must end before the newest event' USING ERRCODE = 'check_violation';
    END IF;
    SELECT count(*) INTO v_count FROM pic.audit_event WHERE tenant_id = p_tenant AND seq <= p_seq_to;
    IF v_count <> p_expected THEN
        RAISE EXCEPTION 'audit archive: % events in range, caller verified %', v_count, p_expected USING ERRCODE = 'check_violation';
    END IF;
    SELECT prev_hash, ts INTO v_anchor, v_first FROM pic.audit_event WHERE tenant_id = p_tenant AND seq = v_from;
    SELECT hash, ts INTO v_head, v_last FROM pic.audit_event
        WHERE tenant_id = p_tenant AND seq = (SELECT max(seq) FROM pic.audit_event WHERE tenant_id = p_tenant AND seq <= p_seq_to);
    SELECT head_hash INTO v_prev_head FROM pic.audit_archive_batch WHERE tenant_id = p_tenant ORDER BY seq_to DESC LIMIT 1;
    IF v_anchor IS DISTINCT FROM v_prev_head THEN
        RAISE EXCEPTION 'audit archive: the range does not continue the archived chain' USING ERRCODE = 'check_violation';
    END IF;
    INSERT INTO pic.audit_archive_batch (id, tenant_id, seq_from, seq_to, event_count, anchor_hash, head_hash, content_sha256, first_ts,
                                         last_ts, archived_at, archived_by, reason, status)
    VALUES (p_batch, p_tenant, v_from, p_seq_to, v_count, v_anchor, v_head, p_content, v_first, v_last, now(), p_by, p_reason, 'ARCHIVED');
    INSERT INTO pic.audit_event_archive (seq, batch_id, event_id, tenant_id, object_type, object_id, object_ref, action, actor, on_behalf_of,
                                         before, after, reason, rule_set_version, ai_ref, ts, prev_hash, hash)
        SELECT seq, p_batch, event_id, tenant_id, object_type, object_id, object_ref, action, actor, on_behalf_of, before, after, reason,
               rule_set_version, ai_ref, ts, prev_hash, hash
        FROM pic.audit_event WHERE tenant_id = p_tenant AND seq <= p_seq_to;
    DELETE FROM pic.audit_event WHERE tenant_id = p_tenant AND seq <= p_seq_to;
    RETURN v_count;
END $$"""

ARCHIVE_EXPIRE = """
CREATE OR REPLACE FUNCTION pic.audit_archive_expire(p_tenant uuid, p_batch uuid, p_before timestamptz)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pic, pg_temp AS $$
DECLARE v_ctx text; v_count integer;
BEGIN
    v_ctx := NULLIF(current_setting('app.tenant_id', true), '');
    IF v_ctx IS NULL OR v_ctx::uuid <> p_tenant THEN
        RAISE EXCEPTION 'audit archive: tenant context mismatch' USING ERRCODE = 'insufficient_privilege';
    END IF;
    PERFORM 1 FROM pic.audit_archive_batch WHERE id = p_batch AND tenant_id = p_tenant AND status = 'ARCHIVED' AND last_ts < p_before;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'audit archive: batch not found, already expired or still inside its retention' USING ERRCODE = 'check_violation';
    END IF;
    DELETE FROM pic.audit_event_archive WHERE tenant_id = p_tenant AND batch_id = p_batch;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    UPDATE pic.audit_archive_batch SET status = 'EXPIRED', expired_at = now() WHERE id = p_batch;
    RETURN v_count;
END $$"""



def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('audit_archive_batch',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('seq_from', sa.BigInteger(), nullable=False),
    sa.Column('seq_to', sa.BigInteger(), nullable=False),
    sa.Column('event_count', sa.Integer(), nullable=False),
    sa.Column('anchor_hash', sa.String(length=64), nullable=True),
    sa.Column('head_hash', sa.String(length=64), nullable=False),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.Column('first_ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('archived_by', sa.String(length=80), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('expired_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('ARCHIVED','EXPIRED')", name=op.f('ck_audit_archive_batch_status')),
    sa.CheckConstraint('seq_to >= seq_from AND event_count > 0', name=op.f('ck_audit_archive_batch_range_valid')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_audit_archive_batch_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_archive_batch')),
    sa.UniqueConstraint('tenant_id', 'seq_from', name=op.f('uq_audit_archive_batch_tenant_id_seq_from')),
    schema='pic'
    )
    op.create_index(op.f('ix_audit_archive_batch_tenant_id'), 'audit_archive_batch', ['tenant_id'], unique=False, schema='pic')
    op.create_table('scheduled_job',
    sa.Column('job_key', sa.String(length=60), nullable=False),
    sa.Column('schedule', sa.String(length=80), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_status', sa.String(length=10), nullable=True),
    sa.Column('last_duration_ms', sa.Integer(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('running_since', sa.DateTime(timezone=True), nullable=True),
    sa.Column('run_count', sa.Integer(), nullable=False),
    sa.Column('consecutive_failures', sa.Integer(), nullable=False),
    sa.Column('changed_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("last_status IS NULL OR last_status IN ('SUCCESS','FAILED','PARTIAL','SKIPPED','RUNNING')", name=op.f('ck_scheduled_job_last_status')),
    sa.CheckConstraint('consecutive_failures >= 0 AND run_count >= 0', name=op.f('ck_scheduled_job_counters_not_negative')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_scheduled_job_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_scheduled_job')),
    sa.UniqueConstraint('tenant_id', 'job_key', name=op.f('uq_scheduled_job_tenant_id_job_key')),
    schema='pic'
    )
    op.create_index('ix_scheduled_job_due', 'scheduled_job', ['tenant_id', 'enabled', 'next_run_at'], unique=False, schema='pic')
    op.create_index(op.f('ix_scheduled_job_tenant_id'), 'scheduled_job', ['tenant_id'], unique=False, schema='pic')
    op.create_table('tenant_flag',
    sa.Column('key', sa.String(length=40), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('changed_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_tenant_flag_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tenant_flag')),
    sa.UniqueConstraint('tenant_id', 'key', name=op.f('uq_tenant_flag_tenant_id_key')),
    schema='pic'
    )
    op.create_index(op.f('ix_tenant_flag_tenant_id'), 'tenant_flag', ['tenant_id'], unique=False, schema='pic')
    op.create_table('audit_event_archive',
    sa.Column('seq', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('batch_id', sa.UUID(), nullable=False),
    sa.Column('event_id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('object_type', sa.String(length=40), nullable=False),
    sa.Column('object_id', sa.UUID(), nullable=False),
    sa.Column('object_ref', sa.String(length=60), nullable=True),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('actor', sa.String(length=80), nullable=False),
    sa.Column('on_behalf_of', sa.String(length=80), nullable=True),
    sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('rule_set_version', sa.String(length=80), nullable=True),
    sa.Column('ai_ref', sa.String(length=80), nullable=True),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('prev_hash', sa.String(length=64), nullable=True),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['batch_id'], ['pic.audit_archive_batch.id'], name=op.f('fk_audit_event_archive_batch_id_audit_archive_batch')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_audit_event_archive_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('seq', name=op.f('pk_audit_event_archive')),
    sa.UniqueConstraint('event_id', name=op.f('uq_audit_event_archive_event_id')),
    schema='pic'
    )
    op.create_index('ix_audit_event_archive_batch', 'audit_event_archive', ['tenant_id', 'batch_id', 'seq'], unique=False, schema='pic')
    op.create_index('ix_audit_event_archive_object', 'audit_event_archive', ['tenant_id', 'object_type', 'object_id'], unique=False, schema='pic')
    op.create_index(op.f('ix_audit_event_archive_tenant_id'), 'audit_event_archive', ['tenant_id'], unique=False, schema='pic')
    op.create_table('delegation',
    sa.Column('delegator_id', sa.UUID(), nullable=False),
    sa.Column('delegate_id', sa.UUID(), nullable=False),
    sa.Column('valid_from', sa.Date(), nullable=False),
    sa.Column('valid_to', sa.Date(), nullable=False),
    sa.Column('roles', postgresql.ARRAY(sa.String(length=40)), nullable=False),
    sa.Column('value_limit_minor', sa.BigInteger(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_by', sa.UUID(), nullable=True),
    sa.Column('revoke_reason', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("status IN ('ACTIVE','REVOKED')", name=op.f('ck_delegation_status')),
    sa.CheckConstraint('delegator_id <> delegate_id', name=op.f('ck_delegation_not_self')),
    sa.CheckConstraint('valid_to >= valid_from', name=op.f('ck_delegation_dates_ordered')),
    sa.CheckConstraint('value_limit_minor IS NULL OR value_limit_minor > 0', name=op.f('ck_delegation_limit_positive')),
    sa.ForeignKeyConstraint(['delegate_id'], ['pic.app_user.id'], name=op.f('fk_delegation_delegate_id_app_user')),
    sa.ForeignKeyConstraint(['delegator_id'], ['pic.app_user.id'], name=op.f('fk_delegation_delegator_id_app_user')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_delegation_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_delegation')),
    schema='pic'
    )
    op.create_index('ix_delegation_delegate', 'delegation', ['tenant_id', 'delegate_id', 'status'], unique=False, schema='pic')
    op.create_index('ix_delegation_delegator', 'delegation', ['tenant_id', 'delegator_id', 'status'], unique=False, schema='pic')
    op.create_index(op.f('ix_delegation_tenant_id'), 'delegation', ['tenant_id'], unique=False, schema='pic')
    op.create_table('job_run',
    sa.Column('job_key', sa.String(length=60), nullable=False),
    sa.Column('scheduled_job_id', sa.UUID(), nullable=False),
    sa.Column('trigger', sa.String(length=10), nullable=False),
    sa.Column('dry_run', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('triggered_by', sa.String(length=80), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_version', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("status IN ('RUNNING','SUCCESS','FAILED','PARTIAL','SKIPPED')", name=op.f('ck_job_run_status')),
    sa.CheckConstraint("trigger IN ('SCHEDULE','MANUAL')", name=op.f('ck_job_run_trigger')),
    sa.ForeignKeyConstraint(['scheduled_job_id'], ['pic.scheduled_job.id'], name=op.f('fk_job_run_scheduled_job_id_scheduled_job')),
    sa.ForeignKeyConstraint(['tenant_id'], ['pic.tenant.id'], name=op.f('fk_job_run_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_run')),
    schema='pic'
    )
    op.create_index('ix_job_run_history', 'job_run', ['tenant_id', 'job_key', 'started_at'], unique=False, schema='pic')
    op.create_index(op.f('ix_job_run_tenant_id'), 'job_run', ['tenant_id'], unique=False, schema='pic')
    op.add_column('agent', sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=True), schema='pic')
    op.add_column('agent', sa.Column('suspension_reason', sa.Text(), nullable=True), schema='pic')
    op.add_column('agent', sa.Column('suspended_by', sa.String(length=80), nullable=True), schema='pic')
    op.add_column('agent', sa.Column('acceptance_reset_at', sa.DateTime(timezone=True), nullable=True), schema='pic')

    for table in CRUD_TABLES + ARCHIVE_TABLES:
        op.execute(f"ALTER TABLE pic.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE pic.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON pic.{table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)""")
    for table in CRUD_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pic.{table} TO {ROLE}")
    for table in ARCHIVE_TABLES:
        op.execute(f"GRANT SELECT ON pic.{table} TO {ROLE}")
    op.execute(ARCHIVE_RANGE)
    op.execute(ARCHIVE_EXPIRE)
    for signature in ("audit_archive_range(uuid, bigint, uuid, integer, text, text, text)", "audit_archive_expire(uuid, uuid, timestamptz)"):
        op.execute(f"REVOKE ALL ON FUNCTION pic.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION pic.{signature} TO {ROLE}")
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.execute("DROP FUNCTION IF EXISTS pic.audit_archive_expire(uuid, uuid, timestamptz)")
    op.execute("DROP FUNCTION IF EXISTS pic.audit_archive_range(uuid, bigint, uuid, integer, text, text, text)")
    op.drop_column('agent', 'acceptance_reset_at', schema='pic')
    op.drop_column('agent', 'suspended_by', schema='pic')
    op.drop_column('agent', 'suspension_reason', schema='pic')
    op.drop_column('agent', 'suspended_at', schema='pic')
    op.drop_index(op.f('ix_job_run_tenant_id'), table_name='job_run', schema='pic')
    op.drop_index('ix_job_run_history', table_name='job_run', schema='pic')
    op.drop_table('job_run', schema='pic')
    op.drop_index(op.f('ix_delegation_tenant_id'), table_name='delegation', schema='pic')
    op.drop_index('ix_delegation_delegator', table_name='delegation', schema='pic')
    op.drop_index('ix_delegation_delegate', table_name='delegation', schema='pic')
    op.drop_table('delegation', schema='pic')
    op.drop_index(op.f('ix_audit_event_archive_tenant_id'), table_name='audit_event_archive', schema='pic')
    op.drop_index('ix_audit_event_archive_object', table_name='audit_event_archive', schema='pic')
    op.drop_index('ix_audit_event_archive_batch', table_name='audit_event_archive', schema='pic')
    op.drop_table('audit_event_archive', schema='pic')
    op.drop_index(op.f('ix_tenant_flag_tenant_id'), table_name='tenant_flag', schema='pic')
    op.drop_table('tenant_flag', schema='pic')
    op.drop_index(op.f('ix_scheduled_job_tenant_id'), table_name='scheduled_job', schema='pic')
    op.drop_index('ix_scheduled_job_due', table_name='scheduled_job', schema='pic')
    op.drop_table('scheduled_job', schema='pic')
    op.drop_index(op.f('ix_audit_archive_batch_tenant_id'), table_name='audit_archive_batch', schema='pic')
    op.drop_table('audit_archive_batch', schema='pic')
    # ### end Alembic commands ###
