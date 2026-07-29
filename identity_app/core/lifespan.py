"""Startup/shutdown wiring for shared resources.

The key ring is loaded here, at startup, on purpose: a missing or malformed
private key must stop the process immediately rather than surface as a 500 on
the first login attempt. An identity service that boots without the ability to
sign is worse than one that refuses to boot.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from identity_app.core.database import ping_db
from identity_app.core.redis import create_redis_pool
from identity_app.core.settings import settings
from identity_app.modules.identity.infra.token_service import TokenService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await ping_db()
    app.state.redis = create_redis_pool(settings.redis_url)

    tokens = TokenService()
    app.state.tokens = tokens
    logger.info(
        "lifespan startup complete (redis=%s, kid actif=%s, kids publiés=[%s])",
        settings.redis_url,
        settings.jwt_active_kid,
        ", ".join(tokens.published_kids),
    )
    try:
        yield
    finally:
        await app.state.redis.aclose()
        logger.info("lifespan shutdown complete")
