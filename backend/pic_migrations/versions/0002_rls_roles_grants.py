"""Tenant isolation, application role, append-only audit and P02 origin protection.

- Creates role pic_app (NOLOGIN, NOBYPASSRLS). Requests run as this role through SET LOCAL ROLE.
- Enables and forces row-level security on every pic table that has tenant_id:
  tenant_id = current_setting('app.tenant_id')::uuid   (Technical Document §4, AD-02)
- pic_app may only INSERT/SELECT audit_event (append-only, §14).
- Requisition origin can never be changed after creation (P02).

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels = None
depends_on = None

ROLE = "pic_app"
APPEND_ONLY = ("audit_event",)
READ_ONLY = ("tenant", "process_definition", "alembic_version")


def _tenant_tables(conn) -> list[str]:
    return [r[0] for r in conn.execute(sa.text(
        "SELECT table_name FROM information_schema.columns WHERE table_schema = 'pic' AND column_name = 'tenant_id' ORDER BY table_name"))]


def upgrade() -> None:
    conn = op.get_bind()
    op.execute(f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} NOLOGIN NOBYPASSRLS;
            END IF;
        END $$;""")
    op.execute(f"GRANT {ROLE} TO CURRENT_USER")
    op.execute(f"GRANT USAGE ON SCHEMA pic TO {ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA pic TO {ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA pic TO {ROLE}")
    for table in READ_ONLY:
        op.execute(f"REVOKE INSERT, UPDATE, DELETE ON pic.{table} FROM {ROLE}")
    for table in APPEND_ONLY:
        op.execute(f"REVOKE UPDATE, DELETE ON pic.{table} FROM {ROLE}")

    for table in _tenant_tables(conn):
        op.execute(f"ALTER TABLE pic.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE pic.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON pic.{table}")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON pic.{table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)""")

    op.execute("""
        CREATE OR REPLACE FUNCTION pic.protect_requisition_origin() RETURNS trigger AS $$
        BEGIN
            IF NEW.origin IS DISTINCT FROM OLD.origin OR NEW.origin_ref IS DISTINCT FROM OLD.origin_ref THEN
                RAISE EXCEPTION 'P02: requisition origin is stored once and never overwritten' USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END $$ LANGUAGE plpgsql""")
    op.execute("""
        CREATE TRIGGER requisition_origin_immutable BEFORE UPDATE OF origin, origin_ref ON pic.requisition
        FOR EACH ROW EXECUTE FUNCTION pic.protect_requisition_origin()""")


def downgrade() -> None:
    conn = op.get_bind()
    op.execute("DROP TRIGGER IF EXISTS requisition_origin_immutable ON pic.requisition")
    op.execute("DROP FUNCTION IF EXISTS pic.protect_requisition_origin()")
    for table in _tenant_tables(conn):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON pic.{table}")
        op.execute(f"ALTER TABLE pic.{table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE pic.{table} DISABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA pic FROM {ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA pic FROM {ROLE}")
