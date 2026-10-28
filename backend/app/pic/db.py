"""Database foundation: one metadata, tenant-scoped mixin and RLS transactions.

Every request runs inside ``tenant_tx``. That transaction switches to the
non-owner ``pic_app`` role and sets ``app.tenant_id`` so PostgreSQL row-level
security policies (see the initial migration) filter every query to the
caller's tenant. Code never filters by tenant by hand.
"""
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, MetaData, create_engine, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, declared_attr, mapped_column, sessionmaker

from app.pic.config import get_settings

SCHEMA = "pic"

naming = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA, naming_convention=naming)


def new_id() -> uuid.UUID:
    return uuid.uuid7()


def utcnow() -> datetime:
    """Business clock (wall clock in production; pinned by seeds and tests)."""
    from app.pic.platform import clock
    return clock.now()


class TenantScoped:
    """Columns every tenant-owned table carries (Technical Document §1.1, §4)."""

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.tenant.id"), index=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=utcnow)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    @declared_attr.directive
    def __mapper_args__(cls):
        return {"version_id_col": cls.row_version}


def money_col(nullable: bool = False):
    """Amount in integer minor units (paise for INR)."""
    return mapped_column(BigInteger, nullable=nullable, default=0 if not nullable else None)


_engine = None
_SessionLocal: Optional[sessionmaker] = None


def engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.sqlalchemy_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            pool_recycle=300,
            future=True,
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=True, expire_on_commit=False)
    return _engine


def session_factory() -> sessionmaker:
    engine()
    return _SessionLocal


@contextmanager
def tenant_tx(tenant_id: uuid.UUID, user_id: Optional[uuid.UUID] = None, principal=None) -> Iterator[Session]:
    """Open one transaction scoped to a tenant. Commits on success, rolls back on error."""
    settings = get_settings()
    session = session_factory()()
    try:
        with session.begin():
            session.execute(text(f'SET LOCAL ROLE "{settings.app_role}"'))
            session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
            session.info["tenant_id"] = tenant_id
            session.info["user_id"] = user_id
            session.info["principal"] = principal
            yield session
    finally:
        session.close()


@contextmanager
def system_tx() -> Iterator[Session]:
    """Owner-level transaction for tables without RLS (tenant directory) and migrations."""
    session = session_factory()()
    try:
        with session.begin():
            yield session
    finally:
        session.close()


def current_tenant(session: Session) -> uuid.UUID:
    return session.info["tenant_id"]


def current_user(session: Session) -> Optional[uuid.UUID]:
    return session.info.get("user_id")
