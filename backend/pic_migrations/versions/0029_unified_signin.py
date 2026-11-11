"""One platform, one sign-in: organisation type and status, and the sign-in directory.

- tenant: ``kind`` (BUYER | SUPPLIER; every existing organisation is a BUYER) and ``status`` (PENDING_VERIFICATION | PENDING_APPROVAL | ACTIVE |
  REJECTED | SUSPENDED; every existing organisation is ACTIVE). Sign-in is refused for an organisation that is not ACTIVE.
- login_directory: e-mail -> (organisation, user) for sign-in by e-mail without an organisation code. It is a global table (column ``org_id``,
  not ``tenant_id``, so it is not under row-level security) and the application role ``pic_app`` has no privilege on it: only the sign-in code,
  which runs as the owner (system_tx), reads it. A SECURITY DEFINER trigger on app_user keeps it in step with every way a user is created,
  changed, deactivated or erased, so no service has to remember it. Passwords, MFA factors, roles and attributes stay on app_user, inside the
  organisation.

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-10 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "pic_app"
KINDS = ("BUYER", "SUPPLIER")
STATUSES = ("PENDING_VERIFICATION", "PENDING_APPROVAL", "ACTIVE", "REJECTED", "SUSPENDED")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.add_column("tenant", sa.Column("kind", sa.String(length=10), server_default="BUYER", nullable=False), schema="pic")
    op.add_column("tenant", sa.Column("status", sa.String(length=24), server_default="ACTIVE", nullable=False), schema="pic")
    op.create_check_constraint("ck_tenant_kind", "tenant", _in("kind", KINDS), schema="pic")
    op.create_check_constraint("ck_tenant_status", "tenant", _in("status", STATUSES), schema="pic")

    op.create_table(
        "login_directory",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pic.tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("app_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "app_user_id", name="pk_login_directory"),
        schema="pic",
    )
    op.create_index("ix_login_directory_email", "login_directory", ["email"], schema="pic")
    op.execute(f"REVOKE ALL ON pic.login_directory FROM {ROLE}")

    # Runs as the owner (SECURITY DEFINER) so that a request running as pic_app keeps the directory current without any privilege on it.
    op.execute("""
        CREATE OR REPLACE FUNCTION pic.sync_login_directory() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pic, pg_temp AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                DELETE FROM pic.login_directory WHERE org_id = OLD.tenant_id AND app_user_id = OLD.id;
                RETURN OLD;
            END IF;
            INSERT INTO pic.login_directory (org_id, app_user_id, email, active, updated_at)
            VALUES (NEW.tenant_id, NEW.id, lower(NEW.email), NEW.active, now())
            ON CONFLICT (org_id, app_user_id) DO UPDATE SET email = EXCLUDED.email, active = EXCLUDED.active, updated_at = now();
            RETURN NEW;
        END $$""")
    op.execute(f"REVOKE ALL ON FUNCTION pic.sync_login_directory() FROM PUBLIC")
    op.execute("""
        CREATE TRIGGER app_user_login_directory AFTER INSERT OR DELETE OR UPDATE OF email, active ON pic.app_user
        FOR EACH ROW EXECUTE FUNCTION pic.sync_login_directory()""")

    # Backfill organisation by organisation: app_user is under forced row-level security, so each organisation is read in its own context.
    op.execute("""
        DO $$
        DECLARE t record;
        BEGIN
            FOR t IN SELECT id FROM pic.tenant LOOP
                PERFORM set_config('app.tenant_id', t.id::text, true);
                INSERT INTO pic.login_directory (org_id, app_user_id, email, active)
                SELECT tenant_id, id, lower(email), active FROM pic.app_user WHERE tenant_id = t.id
                ON CONFLICT (org_id, app_user_id) DO UPDATE SET email = EXCLUDED.email, active = EXCLUDED.active, updated_at = now();
            END LOOP;
            PERFORM set_config('app.tenant_id', '', true);
        END $$""")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS app_user_login_directory ON pic.app_user")
    op.execute("DROP FUNCTION IF EXISTS pic.sync_login_directory()")
    op.drop_index("ix_login_directory_email", table_name="login_directory", schema="pic")
    op.drop_table("login_directory", schema="pic")
    op.drop_constraint("ck_tenant_status", "tenant", schema="pic")
    op.drop_constraint("ck_tenant_kind", "tenant", schema="pic")
    op.drop_column("tenant", "status", schema="pic")
    op.drop_column("tenant", "kind", schema="pic")
