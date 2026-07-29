"""Async SQLAlchemy engine + session factory.

The engine is instantiated once at module import from `settings.database_url`.
Routes obtain a session through the `get_session` dependency re-exported by
`identity_app.core.deps`.

Migration ownership: Alembic. Nothing here calls `create_all` — the schema
comes from `alembic upgrade head`. The lifespan calls `ping_db()` only to
surface connection problems at startup rather than on the first request.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from identity_app.core.settings import settings

logger = logging.getLogger(__name__)


engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=(settings.environment == "debug"),
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def ping_db() -> None:
    """Best-effort connectivity check at startup.

    Raises if the database is unreachable; the lifespan lets that propagate and
    the app refuses to start, which is the correct fail-loud behaviour for an
    identity service — a half-started DiddiFreeID would take every module's
    login flow down with it in a much more confusing way.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("database reachable at %s", settings.database_url.split("@", 1)[-1])
    except Exception:
        logger.exception("database NOT reachable at %s", settings.database_url.split("@", 1)[-1])
        raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Yields one AsyncSession per request; commits if the
    handler returns normally, rolls back otherwise.

    IMPORTANT — this commit is a safety net, not the primary one. FastAPI closes
    dependencies *after* the response reaches the client, so a caller acting on
    the response can issue its next request before this commit lands. That is a
    real race on write endpoints: `POST /auth/otp/verify` hands back an access
    token, and a client using it immediately would otherwise be authenticated
    against a user still stored as `pending_verification`.

    Commands therefore commit explicitly before returning (see
    `identity_app.modules.identity.application.commands`). This teardown then
    commits nothing and simply ends the transaction, which also keeps pooled
    connections clean.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
