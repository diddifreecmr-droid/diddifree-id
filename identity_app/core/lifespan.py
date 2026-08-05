"""Startup/shutdown wiring for shared resources.

The key ring is loaded here, at startup, on purpose: a missing or malformed
private key must stop the process immediately rather than surface as a 500 on
the first login attempt. An identity service that boots without the ability to
sign is worse than one that refuses to boot.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from identity_app.core.database import ping_db
from identity_app.core.redis import create_redis_pool
from identity_app.core.settings import settings
from identity_app.modules.identity.infra.token_service import TokenService
from identity_app.modules.identity.infra.telegram import TelegramBotWorker, TelegramClient

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await ping_db()
    app.state.redis = create_redis_pool(settings.redis_url)

    telegram_client: TelegramClient | None = None
    telegram_task: asyncio.Task | None = None
    try:
        if settings.otp_provider in {"email", "smtp"} and (
            not settings.smtp_username or not settings.smtp_password
        ):
            raise RuntimeError("OTP_PROVIDER=email requires SMTP_USERNAME and SMTP_PASSWORD")

        if settings.otp_provider == "telegram" or settings.telegram_bot_token:
            if not settings.telegram_bot_token:
                raise RuntimeError("OTP_PROVIDER=telegram requires TELEGRAM_BOT_TOKEN")
            telegram_client = TelegramClient(
                settings.telegram_bot_token,
                poll_timeout_seconds=settings.telegram_poll_timeout_seconds,
            )
            await telegram_client.get_me()
            # Polling and a configured webhook cannot run at the same time.
            await telegram_client.delete_webhook()
            app.state.telegram_client = telegram_client
            telegram_task = asyncio.create_task(TelegramBotWorker(telegram_client).run())
    except Exception:
        if telegram_client is not None:
            await telegram_client.close()
        await app.state.redis.aclose()
        raise

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
        if telegram_task is not None:
            telegram_task.cancel()
            await asyncio.gather(telegram_task, return_exceptions=True)
        if telegram_client is not None:
            await telegram_client.close()
        await app.state.redis.aclose()
        logger.info("lifespan shutdown complete")
