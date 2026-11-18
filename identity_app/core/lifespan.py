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
from identity_app.core.logging import configure_logging, shutdown_otel_logging
from identity_app.core.redis import create_redis_pool
from identity_app.core.settings import settings
from identity_app.core.tracing import configure_tracing, shutdown_tracing
from identity_app.modules.identity.infra.token_service import TokenService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await ping_db()
    app.state.redis = create_redis_pool(settings.redis_url)

    try:
        # Reapply this after Uvicorn has loaded its logging configuration so
        # uvicorn.error propagates once to the root OTLP handler.
        configure_logging(settings.log_level, component="api")
        # Telemetry is best-effort. Its configuration must never gate startup.
        configure_tracing(app)
        # Validate before serving traffic. Review accounts must never silently
        # fall back to a normal OTP delivery because a Portainer secret is bad.
        if settings.review_static_otp_enabled:
            _review_static_otp_codes = settings.review_static_otp_codes

        if settings.otp_provider in {"email", "smtp"} and (
            not settings.smtp_host
            or not settings.smtp_username
            or not settings.smtp_password
        ):
            raise RuntimeError(
                "OTP_PROVIDER=email requires SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD",
            )

        if settings.otp_provider == "whatsapp" and (
            not settings.evolution_api_url
            or not settings.evolution_api_key
            or not settings.evolution_instance
        ):
            raise RuntimeError(
                "OTP_PROVIDER=whatsapp requires EVOLUTION_API_URL, EVOLUTION_API_KEY and EVOLUTION_INSTANCE",
            )

        if settings.otp_provider == "sms" and settings.otp_sms_provider == "yellika" and (
            not settings.yellika_sms_token or not settings.yellika_sms_sender_id
        ):
            raise RuntimeError(
                "OTP_PROVIDER=sms with OTP_SMS_PROVIDER=yellika requires "
                "YELLIKA_SMS_TOKEN and YELLIKA_SMS_SENDER_ID",
            )

        if settings.otp_provider == "sms" and settings.otp_sms_provider == "senndo" and (
            not settings.senndo_sms_api_key
        ):
            raise RuntimeError("OTP_PROVIDER=sms with OTP_SMS_PROVIDER=senndo requires SENNDO_SMS_API_KEY")

        # The Telegram bot is commented out (2026-11-18). Its token was written
        # to the logs by httpx's request line and must be rotated before this
        # transport is reinstated. A deployment that still selects Telegram as
        # the default channel must stop here instead of answering every OTP
        # request with 502.
        if settings.otp_provider == "telegram":
            raise RuntimeError(
                "OTP_PROVIDER=telegram is disabled: the Telegram bot is commented out in core/lifespan.py",
            )
        # if settings.otp_provider == "telegram" or settings.telegram_bot_token:
        #     if not settings.telegram_bot_token:
        #         raise RuntimeError("OTP_PROVIDER=telegram requires TELEGRAM_BOT_TOKEN")
        #     telegram_client = TelegramClient(
        #         settings.telegram_bot_token,
        #         poll_timeout_seconds=settings.telegram_poll_timeout_seconds,
        #     )
        #     await telegram_client.get_me()
        #     # Polling and a configured webhook cannot run at the same time.
        #     await telegram_client.delete_webhook()
        #     app.state.telegram_client = telegram_client
        #     telegram_task = asyncio.create_task(TelegramBotWorker(telegram_client).run())
    except Exception:
        await app.state.redis.aclose()
        raise

    tokens = TokenService()
    app.state.tokens = tokens
    logger.info(
        "lifespan startup complete (redis_configured=%s, kid actif=%s, kids publiés=[%s])",
        bool(settings.redis_url),
        settings.jwt_active_kid,
        ", ".join(tokens.published_kids),
        extra={"event": "app.startup.completed"},
    )
    try:
        yield
    finally:
        await app.state.redis.aclose()
        logger.info("lifespan shutdown complete", extra={"event": "app.shutdown.completed"})
        shutdown_tracing()
        shutdown_otel_logging()
