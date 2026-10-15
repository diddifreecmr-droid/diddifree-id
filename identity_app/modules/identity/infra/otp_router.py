"""Select the OTP transport without coupling the application command to it."""

from __future__ import annotations

from identity_app.core.settings import settings
from identity_app.modules.identity.domain.otp_delivery import OtpDeliveryRequest
from identity_app.modules.identity.infra.senndo import SenndoSmsOtpSender
from identity_app.modules.identity.infra.sms_adapter import LoggingOtpSender
from identity_app.modules.identity.infra.smtp_adapter import SmtpOtpSender
from identity_app.modules.identity.infra.telegram import TelegramOtpSender
from identity_app.modules.identity.infra.whatsapp import EvolutionWhatsAppOtpSender
from identity_app.modules.identity.infra.yellika import YellikaSmsOtpSender


class OtpSenderRouter:
    def __init__(self, telegram_client=None) -> None:  # noqa: ANN001
        self._telegram = TelegramOtpSender(telegram_client) if telegram_client is not None else None
        self._email = SmtpOtpSender()
        self._logging = LoggingOtpSender()
        self._whatsapp = EvolutionWhatsAppOtpSender()
        self._yellika = YellikaSmsOtpSender()
        self._senndo = SenndoSmsOtpSender()

    async def send(
        self,
        phone: str | None,
        code: str,
        channel: str | None = None,
        email: str | None = None,
    ) -> None:
        selected = channel or settings.otp_provider
        channel_name, provider = self._resolve(selected)
        if channel_name == "telegram" and self._telegram is None:
            raise RuntimeError("OTP Telegram demandé mais TELEGRAM_BOT_TOKEN n'est pas configuré")
        adapter = self._adapters(provider)
        if adapter is None:
            raise RuntimeError(f"OTP provider inconnu : {provider}")
        await adapter.deliver(
            OtpDeliveryRequest(
                phone=phone,
                email=email,
                code=code,
                channel=channel_name,
                expires_in_seconds=settings.otp_code_lifetime_seconds,
            ),
        )

    @staticmethod
    def _resolve(selected: str) -> tuple[str, str]:
        if selected in {"email", "smtp"}:
            return "email", "smtp"
        if selected == "sms":
            return "sms", settings.otp_sms_provider
        if selected in {"telegram", "whatsapp", "logging"}:
            return selected, selected
        raise RuntimeError(f"OTP channel inconnu : {selected}")

    def _adapters(self, provider: str):  # noqa: ANN202
        return {
            "email": self._email,
            "smtp": self._email,
            "telegram": self._telegram,
            "whatsapp": self._whatsapp,
            "logging": self._logging,
            "yellika": self._yellika,
            "senndo": self._senndo,
        }.get(provider)
