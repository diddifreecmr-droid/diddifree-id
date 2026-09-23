"""WhatsApp OTP delivery through an Evolution API instance."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from identity_app.core.settings import settings
from identity_app.modules.identity.domain.interfaces import WhatsAppNumberNotFound

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

        try:
            async with httpx.AsyncClient(timeout=settings.evolution_api_timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code == 400 and "textMessage" in response.text:
                    # Newer Evolution releases wrap the text in textMessage.
                    response = await client.post(
                        url,
                        json={"number": phone.lstrip("+"), "textMessage": {"text": payload["text"]}},
                        headers=headers,
                    )
                if _is_whatsapp_number_not_found(response):
                    logger.info("Evolution API WhatsApp number not found phone=%s body=%s", phone, response.text[:500])
                    raise WhatsAppNumberNotFound("Le numéro n'existe pas sur WhatsApp.")
                response.raise_for_status()
        except WhatsAppNumberNotFound:
            raise
        except httpx.HTTPError as exc:
            provider_response = getattr(exc, "response", None)
            status = provider_response.status_code if provider_response is not None else "network"
            body = provider_response.text[:500] if provider_response is not None else str(exc)
            logger.error("Evolution API WhatsApp failed status=%s body=%s", status, body)
            raise RuntimeError("Evolution API a refusé l'envoi WhatsApp") from exc


def _is_whatsapp_number_not_found(response: httpx.Response) -> bool:
    if response.status_code != 400:
        return False
    try:
        body: Any = response.json()
    except ValueError:
        return False
    messages = body.get("response", {}).get("message", []) if isinstance(body, dict) else []
    if not isinstance(messages, list):
        return False
    return any(isinstance(item, dict) and item.get("exists") is False for item in messages)
