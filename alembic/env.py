"""Alembic env — async-capable, driven by our own settings + model metadata.

Same shape as the DiddiGo one so the two projects stay operable by the same
people, minus the PostGIS pieces: DiddiFreeID has a single `identity` schema
and no geometry columns.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import Base so its metadata exists before the model module is imported below.
from identity_app.core.database import Base  # noqa: F401
from identity_app.core.settings import settings

# Importing the models registers them on `Base.metadata`, which is what
# autogenerate diffs against.
from identity_app.modules.identity.infra import models as _identity_models  # noqa: F401

config = context.config

# `.env` has already been read by pydantic-settings at import time; in tests
# the caller exports DATABASE_URL before any `identity_app.*` import.
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# The only schema this project owns. Anything else in the database — including
# a `ride`/`auth` schema left over from a DiddiGo migration run against the
# same cluster — is deliberately invisible to autogenerate.
INCLUDE_SCHEMAS = {"identity"}


def include_object(obj, name, type_, reflected, compare_to):
    """Restrict the diff to project schemas. Indexes and constraints live under
    their parent table, which `include_schemas` already covers, so only tables
    and schemas need filtering."""
    if type_ == "table":
        return obj.schema in INCLUDE_SCHEMAS
    if type_ == "schema":
        return name in INCLUDE_SCHEMAS
    return True


def run_migrations_offline() -> None:
    """Run in 'offline' mode — emit SQL to stdout, for reviewing a migration
    before it touches a live database."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=include_object,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=include_object,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run in 'online' mode — connect to the database and apply migrations."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
