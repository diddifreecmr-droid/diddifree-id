"""OTP logging adapter used for local development and safe fallback."""

from __future__ import annotations

import logging

from identity_app.core.settings import settings
from identity_app.modules.identity.domain.otp_delivery import (
    OtpDeliveryRequest,
    OtpDeliveryResult,
)

logger = logging.getLogger(__name__)


class LoggingOtpSender:
    """Development sender — writes the code to the log.

    Guarded by `OTP_LOG_PLAINTEXT`. With the flag off, the code is not logged at
    all: an OTP in a production log file is a credential in a production log
    file, readable by anyone with access to log aggregation.
    """

    async def send(
        self,
        phone: str | None,
        code: str,
        channel: str | None = None,
        email: str | None = None,
    ) -> None:
        await self.deliver(
            OtpDeliveryRequest(
                phone=phone,
                email=email,
                code=code,
                channel=channel or "logging",
                expires_in_seconds=settings.otp_code_lifetime_seconds,
            ),
        )

    async def deliver(self, request: OtpDeliveryRequest) -> OtpDeliveryResult:
        phone = request.phone
        email = request.email
        code = request.code
        identifier = phone or email
        if settings.otp_log_plaintext:
            logger.warning(
                "OTP stub — en développement, le code pour identifier=%s est %s. "
                "Aucun fournisseur de transport n'est configuré.",
                identifier,
                code,
            )
        else:
            logger.info("OTP émis pour identifier=%s (code non journalisé)", identifier)
        return OtpDeliveryResult(channel=request.channel, provider="logging")
