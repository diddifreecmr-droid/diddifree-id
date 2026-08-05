"""Select the OTP transport without coupling the application command to it."""

from __future__ import annotations

from identity_app.core.settings import settings
from identity_app.modules.identity.infra.sms_adapter import LoggingOtpSender
from identity_app.modules.identity.infra.smtp_adapter import SmtpOtpSender
from identity_app.modules.identity.infra.telegram import TelegramOtpSender


class OtpSenderRouter:
    def __init__(self, telegram_client=None) -> None:  # noqa: ANN001
        self._telegram = TelegramOtpSender(telegram_client) if telegram_client is not None else None
        self._email = SmtpOtpSender()
        self._logging = LoggingOtpSender()

    async def send(self, phone: str, code: str, channel: str | None = None) -> None:
        selected = channel or settings.otp_provider
        if selected in {"email", "smtp"}:
            await self._email.send(phone, code, selected)
            return
        if selected == "telegram":
            if self._telegram is None:
                raise RuntimeError("OTP Telegram demandé mais TELEGRAM_BOT_TOKEN n'est pas configuré")
            await self._telegram.send(phone, code, selected)
            return
        if selected == "logging":
            await self._logging.send(phone, code, selected)
            return
        raise RuntimeError(f"OTP_PROVIDER inconnu : {selected}")
