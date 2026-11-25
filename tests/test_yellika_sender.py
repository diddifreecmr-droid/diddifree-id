from __future__ import annotations

import pytest

from identity_app.core.settings import settings
from identity_app.modules.identity.infra import yellika


class FakeResponse:
    status_code = 200
    text = '{"status":"success","message_id":"yellika-123"}'

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return {"status": "success", "message_id": "yellika-123"}


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


@pytest.mark.asyncio
async def test_yellika_sender_posts_normalized_sms(monkeypatch):
    FakeAsyncClient.calls = []
    monkeypatch.setattr(yellika.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(settings, "yellika_sms_base_url", "https://panel.yellika.test/")
    monkeypatch.setattr(settings, "yellika_sms_token", "test-token")
    monkeypatch.setattr(settings, "yellika_sms_sender_id", "DIDDI")
    monkeypatch.setattr(settings, "yellika_sms_timeout_seconds", 9)
    monkeypatch.setattr(settings, "otp_log_plaintext", False)

    result = await yellika.YellikaSmsOtpSender().send("+2250700000000", "482913", "sms")

    assert result is None
    assert FakeAsyncClient.calls == [
        {
            "url": "https://panel.yellika.test/api/v3/sms/send",
            "json": {
                "recipient": "2250700000000",
                "sender_id": "DIDDI",
                "type": "plain",
                "message": "Votre code DiddiFreeID est : 482913\n\nCe code expire dans 5 minutes.",
            },
            "headers": {
                "Accept": "application/json",
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
            },
            "timeout": 9,
        },
    ]


@pytest.mark.asyncio
async def test_yellika_sender_requires_portainer_credentials(monkeypatch):
    monkeypatch.setattr(settings, "yellika_sms_token", None)
    monkeypatch.setattr(settings, "yellika_sms_sender_id", None)

    with pytest.raises(RuntimeError, match="YELLIKA_SMS_TOKEN"):
        await yellika.YellikaSmsOtpSender().send("+2250700000000", "482913", "sms")
