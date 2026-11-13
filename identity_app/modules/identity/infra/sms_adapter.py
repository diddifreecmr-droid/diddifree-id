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
    """Development sender with a safe delivery audit event.

    Test code captures the request at the sender boundary; credentials never
    enter application logs, including when this local-only sender is selected.
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
        logger.info("OTP remis au canal de développement", extra={"event": "otp.delivery.dispatched"})
        return OtpDeliveryResult(channel=request.channel, provider="logging")
