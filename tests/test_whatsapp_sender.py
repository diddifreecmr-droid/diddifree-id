from __future__ import annotations

from identity_app.core.settings import settings
from identity_app.modules.identity.infra import whatsapp


class FakeResponse:
    def raise_for_status(self) -> None:
        return None


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


async def test_evolution_sender_posts_otp_to_instance(monkeypatch, caplog):
    FakeAsyncClient.calls = []
    monkeypatch.setattr(whatsapp.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(settings, "evolution_api_url", "https://evolution.test/")
    monkeypatch.setattr(settings, "evolution_api_key", "test-evolution-key")
    monkeypatch.setattr(settings, "evolution_instance", "diddi-staging")
    monkeypatch.setattr(settings, "evolution_api_timeout_seconds", 7)
    monkeypatch.setattr(settings, "otp_log_plaintext", True)

    await whatsapp.EvolutionWhatsAppOtpSender().send("+2250700000000", "482913", "whatsapp")

    assert FakeAsyncClient.calls == [
        {
            "url": "https://evolution.test/message/sendText/diddi-staging",
            "json": {
                "number": "2250700000000",
                "textMessage": {
                    "text": "Votre code DiddiFreeID est : 482913\n\nCe code expire dans 5 minutes.",
                },
            },
            "headers": {"apikey": "test-evolution-key"},
            "timeout": 7,
        },
    ]
    assert "482913" in caplog.text
