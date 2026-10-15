"""Senndo SMS adapter for provider-neutral OTP delivery."""

from __future__ import annotations

import hashlib
import logging

import httpx

from identity_app.core.settings import settings
from identity_app.modules.identity.domain.otp_delivery import (
    OtpDeliveryRequest,
    OtpDeliveryResult,
)

logger = logging.getLogger(__name__)


class SenndoSmsOtpSender:
    """Send OTP messages through Senndo's idempotent messaging endpoint."""

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
        if not settings.senndo_sms_api_key:
            raise RuntimeError("OTP_SMS_PROVIDER=senndo requires SENNDO_SMS_API_KEY")

        if settings.otp_log_plaintext:
            logger.warning("OTP Senndo SMS - le code pour phone=%s est %s.", request.phone, request.code)
        else:
            logger.info("OTP Senndo SMS emis pour phone=%s (code non journalise)", request.phone)

        idempotency_key = request.idempotency_key or _idempotency_key(request.phone, request.code)
        payload = {
            "channel": "sms",
            "to": request.phone,
            "text": (
                f"Votre code DiddiFreeID est : {request.code}\n\n"
                f"Ce code expire dans {request.expires_in_seconds // 60} minutes."
            ),
            "idempotencyKey": idempotency_key,
        }
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {settings.senndo_sms_api_key}",
            "Content-Type": "application/json",
        }

        url = f"{settings.senndo_sms_base_url.rstrip('/')}/v1/messages"
        try:
            async with httpx.AsyncClient(timeout=settings.senndo_sms_timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            provider_response = getattr(exc, "response", None)
            status = provider_response.status_code if provider_response is not None else "network"
            body = provider_response.text[:500] if provider_response is not None else str(exc)
            logger.error("Senndo SMS failed status=%s body=%s", status, body)
            raise RuntimeError("Senndo a refusé l'envoi SMS") from exc

        provider_message_id = None
        status = "accepted"
        try:
            body = response.json()
            if isinstance(body, dict):
                provider_message_id = str(body["id"]) if body.get("id") is not None else None
                status = str(body.get("status") or status)
        except ValueError:
            logger.warning("Senndo SMS returned a non-JSON success response")

        return OtpDeliveryResult(
            channel=request.channel,
            provider="senndo",
            status=status,
            provider_message_id=provider_message_id,
        )


def _idempotency_key(identifier: str, code: str) -> str:
    digest = hashlib.sha256(f"{identifier}:{code}".encode()).hexdigest()
    return f"diddifreeid-otp-{digest}"
