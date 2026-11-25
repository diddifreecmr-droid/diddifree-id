from __future__ import annotations

from identity_app.core.settings import settings
from identity_app.modules.identity.infra.otp_router import OtpSenderRouter


class FakeAdapter:
    def __init__(self) -> None:
        self.requests = []

    async def deliver(self, request):  # noqa: ANN001
        self.requests.append(request)


async def test_sms_channel_selects_configured_provider(monkeypatch):
    monkeypatch.setattr(settings, "otp_sms_provider", "yellika")
    router = OtpSenderRouter()
    adapter = FakeAdapter()
    router._yellika = adapter

    await router.send("+2250700000000", "482913", "sms")

    request = adapter.requests[0]
    assert request.phone == "+2250700000000"
    assert request.code == "482913"
    assert request.channel == "sms"
    assert request.expires_in_seconds == settings.otp_code_lifetime_seconds


async def test_telegram_without_client_keeps_specific_configuration_error():
    router = OtpSenderRouter()

    try:
        await router.send("+2250700000000", "482913", "telegram")
    except RuntimeError as exc:
        assert str(exc) == "OTP Telegram demandé mais TELEGRAM_BOT_TOKEN n'est pas configuré"
    else:
        raise AssertionError("Le routeur aurait dû refuser Telegram sans client")
