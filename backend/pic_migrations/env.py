from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

from app.pic.config import get_settings
from app.pic.db import SCHEMA, Base
import app.pic.models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table":
        return obj.schema == SCHEMA
    return True


def run_migrations_offline() -> None:
    context.configure(url=get_settings().sqlalchemy_url, target_metadata=target_metadata, literal_binds=True,
                      include_schemas=True, include_object=include_object, version_table_schema=SCHEMA)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_settings().sqlalchemy_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, include_schemas=True,
                          include_object=include_object, version_table_schema=SCHEMA, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
