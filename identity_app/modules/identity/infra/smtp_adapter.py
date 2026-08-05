"""SMTP delivery for OTP codes.

The SMTP credentials are configuration-only. The sender mailbox is never
hard-coded in application code and the OTP remains logged according to
``OTP_LOG_PLAINTEXT`` before delivery.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy import select

from identity_app.core.database import async_session_factory
from identity_app.core.settings import settings
from identity_app.modules.identity.infra.models import UserModel

logger = logging.getLogger(__name__)


class SmtpOtpSender:
    async def send(self, phone: str, code: str, channel: str | None = None) -> None:
        if settings.otp_log_plaintext:
            logger.warning("OTP Email - le code pour phone=%s est %s.", phone, code)
        else:
            logger.info("OTP Email emis pour phone=%s (code non journalise)", phone)

        async with async_session_factory() as session:
            result = await session.execute(
                select(UserModel.email).where(UserModel.phone == phone),
            )
            recipient = result.scalar_one_or_none()

        if not recipient:
            logger.warning("Aucune adresse e-mail OTP configurée pour phone suffix=%s", phone[-4:])
            return

        if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password:
            raise RuntimeError(
                "OTP_PROVIDER=email requires SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD",
            )

        await asyncio.to_thread(self._send_message, recipient, code)

    @staticmethod
    def _send_message(recipient: str, code: str) -> None:
        message = EmailMessage()
        message["Subject"] = "Votre code DiddiFreeID"
        message["From"] = formataddr((settings.smtp_from_name, settings.smtp_from_email))
        message["To"] = recipient
        message.set_content(
            "Bonjour,\n\n"
            f"Votre code DiddiFreeID est : {code}\n\n"
            f"Ce code expire dans {settings.otp_code_lifetime_seconds // 60} minutes.\n"
            "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.\n",
        )

        context = ssl.create_default_context()
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as client:
            if settings.smtp_use_tls:
                client.starttls(context=context)
            client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)
