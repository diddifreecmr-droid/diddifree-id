from __future__ import annotations

from identity_app.core.settings import settings
from identity_app.modules.identity.domain.otp_delivery import OtpDeliveryRequest
from identity_app.modules.identity.infra import senndo


class FakeResponse:
    status_code = 202
    text = '{"id":"msg_test_123","status":"sent"}'

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return {"id": "msg_test_123", "status": "sent"}


class FakeAsyncClient:
    calls: list[dict] = []

    def __init__(self, *, timeout: int) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, *, json: dict, headers: dict) -> FakeResponse:
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": self.timeout})
        return FakeResponse()


async def test_senndo_sender_posts_idempotent_sms(monkeypatch):
    FakeAsyncClient.calls = []
    monkeypatch.setattr(senndo.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(settings, "senndo_sms_base_url", "https://api.senndo.test/")
    monkeypatch.setattr(settings, "senndo_sms_api_key", "sk_test_provider_key")
    monkeypatch.setattr(settings, "senndo_sms_timeout_seconds", 11)
    monkeypatch.setattr(settings, "otp_log_plaintext", False)

    result = await senndo.SenndoSmsOtpSender().deliver(
        OtpDeliveryRequest(
            phone="+2250700000000",
            email=None,
            code="482913",
            channel="sms",
            expires_in_seconds=300,
        ),
    )

    assert result.provider == "senndo"
    assert result.provider_message_id == "msg_test_123"
    assert FakeAsyncClient.calls[0]["url"] == "https://api.senndo.test/v1/messages"
    assert FakeAsyncClient.calls[0]["json"]["channel"] == "sms"
    assert FakeAsyncClient.calls[0]["json"]["to"] == "+2250700000000"
    assert FakeAsyncClient.calls[0]["json"]["idempotencyKey"].startswith("diddifreeid-otp-")
    assert FakeAsyncClient.calls[0]["headers"]["Authorization"] == "Bearer sk_test_provider_key"


async def test_senndo_sender_requires_portainer_credentials(monkeypatch):
    monkeypatch.setattr(settings, "senndo_sms_api_key", None)

    try:
        await senndo.SenndoSmsOtpSender().send("+2250700000000", "482913", "sms")
    except RuntimeError as exc:
        assert str(exc) == "OTP_SMS_PROVIDER=senndo requires SENNDO_SMS_API_KEY"
    else:
        raise AssertionError("Senndo aurait dû refuser un appel sans clé")
