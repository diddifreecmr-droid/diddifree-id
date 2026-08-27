"""WhatsApp OTP delivery through an Evolution API instance."""

from __future__ import annotations

import logging

import httpx

from identity_app.core.settings import settings

logger = logging.getLogger(__name__)


class EvolutionWhatsAppOtpSender:
    """Send OTP text messages through Evolution API's sendText endpoint."""

    async def send(
        self,
        phone: str | None,
        code: str,
        channel: str | None = None,
        email: str | None = None,
    ) -> None:
        if phone is None:
            raise RuntimeError("OTP WhatsApp nécessite un numéro de téléphone")

        if settings.otp_log_plaintext:
            logger.warning("OTP WhatsApp - le code pour phone=%s est %s.", phone, code)
        else:
            logger.info("OTP WhatsApp emis pour phone=%s (code non journalise)", phone)

        if not settings.evolution_api_url or not settings.evolution_api_key or not settings.evolution_instance:
            raise RuntimeError(
                "OTP_PROVIDER=whatsapp requires EVOLUTION_API_URL, EVOLUTION_API_KEY and EVOLUTION_INSTANCE",
            )

        url = (
            f"{settings.evolution_api_url.rstrip('/')}/message/sendText/"
            f"{settings.evolution_instance}"
        )
        payload = {
            # Evolution API expects the international number without '+'.
            "number": phone.lstrip("+"),
            # This instance runs the API version where the text is a top-level
            # field. The official newer payload uses `textMessage.text`.
            "text": (
                f"Votre code DiddiFreeID est : {code}\n\n"
                f"Ce code expire dans {settings.otp_code_lifetime_seconds // 60} minutes."
            ),
        }
        headers = {"apikey": settings.evolution_api_key}

        async with httpx.AsyncClient(timeout=settings.evolution_api_timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
