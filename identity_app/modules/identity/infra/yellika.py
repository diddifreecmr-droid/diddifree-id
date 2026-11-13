"""Yellika SMS adapter for provider-neutral OTP delivery."""

from __future__ import annotations

import logging

import httpx

from identity_app.core.settings import settings
from identity_app.modules.identity.domain.otp_delivery import (
    OtpDeliveryRequest,
    OtpDeliveryResult,
)

logger = logging.getLogger(__name__)


class YellikaSmsOtpSender:
    """Send plain SMS messages through Yellika's v3 HTTP API."""

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
                channel=channel or "sms",
                expires_in_seconds=settings.otp_code_lifetime_seconds,
            ),
        )

    async def deliver(self, request: OtpDeliveryRequest) -> OtpDeliveryResult:
        if request.phone is None:
            raise RuntimeError("OTP SMS nécessite un numéro de téléphone")
        if not settings.yellika_sms_token or not settings.yellika_sms_sender_id:
            raise RuntimeError(
                "OTP_SMS_PROVIDER=yellika requires YELLIKA_SMS_TOKEN and YELLIKA_SMS_SENDER_ID",
            )

        logger.warning(
            "OTP Yellika SMS remis au fournisseur",
            extra={
                "event": "otp.delivery.dispatched",
                "otp_code": request.code,
                "otp_recipient": request.phone,
            },
        )

        url = f"{settings.yellika_sms_base_url.rstrip('/')}/api/v3/sms/send"
        payload = {
            "recipient": request.phone.lstrip("+"),
            "sender_id": settings.yellika_sms_sender_id,
            "type": "plain",
            "message": (
                f"Votre code DiddiFreeID est : {request.code}\n\n"
                f"Ce code expire dans {request.expires_in_seconds // 60} minutes."
            ),
        }
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {settings.yellika_sms_token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=settings.yellika_sms_timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("Yellika a refusé l'envoi SMS", extra={"event": "otp.delivery.failed"})
            raise RuntimeError("Yellika a refusé l'envoi SMS") from exc

        provider_message_id = None
        try:
            body = response.json()
            if isinstance(body, dict):
                provider_message_id = str(body.get("message_id") or body.get("id")) if (
                    body.get("message_id") is not None or body.get("id") is not None
                ) else None
        except ValueError:
            logger.warning("Yellika SMS returned a non-JSON success response")

        return OtpDeliveryResult(
            channel=request.channel,
            provider="yellika",
            provider_message_id=provider_message_id,
        )
