"""Basic request correlation guarantees for the observability baseline."""

import json
import logging
from uuid import uuid4

from identity_app.core.logging import JsonFormatter
from tests.conftest import API


async def test_health_returns_request_id(client):
    response = await client.get("/health")

    assert response.status_code == 200
    request_id = response.headers.get("X-Request-ID")
    assert request_id
    assert len(request_id) == 32


async def test_valid_incoming_request_id_is_preserved(client):
    request_id = "frontend-login-2026.09.05"

    response = await client.get(f"{API}/.well-known/jwks.json", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] == request_id


async def test_completed_request_log_is_correlated(client, caplog):
    request_id = "frontend-profile-2026.09.05"
    caplog.set_level(logging.INFO, logger="identity_app.main")

    response = await client.get("/health", headers={"X-Request-ID": request_id})

    records = [
        record
        for record in caplog.records
        if record.name == "identity_app.main" and record.msg == "Requête HTTP terminée"
    ]
    assert response.status_code == 200
    assert records
    assert records[-1].request_id == request_id


async def test_invalid_incoming_request_id_is_replaced(client):
    invalid_request_id = "bad value with spaces"
    response = await client.get("/health", headers={"X-Request-ID": invalid_request_id})

    generated_id = response.headers.get("X-Request-ID")
    assert generated_id
    assert generated_id != invalid_request_id
    assert len(generated_id) == 32


def test_json_logs_include_resource_identity_and_redact_secrets():
    record = logging.LogRecord(
        "identity_app.test",
        logging.INFO,
        __file__,
        1,
        "outbound Authorization: Bearer private-token password=not-for-logs OTP code 482913 "+
        "email=someone@example.com phone=+2250700000000",
        (),
        None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["timestamp"].endswith("Z")
    assert payload["schema_version"] == "1.0.0"
    assert payload["level"] == "info"
    assert payload["resource"]["service.name"] == "diddifree-id"
    assert payload["resource"]["diddi.component"] == "api"
    assert len(payload["resource"]) == 8
    assert "private-token" not in payload["message"]
    assert "not-for-logs" not in payload["message"]
    assert "482913" not in payload["message"]
    assert "someone@example.com" not in payload["message"]
    assert "+2250700000000" not in payload["message"]


def test_plaintext_otp_log_switch_is_explicit_and_opt_in(monkeypatch):
    from identity_app.core.settings import settings

    record = logging.LogRecord("identity_app.test", logging.WARNING, __file__, 1, "OTP envoyé", (), None)
    record.otp_code = "482913"
    record.otp_recipient = "+2250700000000"

    monkeypatch.setattr(settings, "otp_log_plaintext", False)
    hidden = json.loads(JsonFormatter().format(record))
    assert "otp.code" not in hidden["attributes"]

    monkeypatch.setattr(settings, "otp_log_plaintext", True)
    shown = json.loads(JsonFormatter().format(record))
    assert shown["attributes"]["otp.code"] == "482913"
    assert shown["attributes"]["otp.recipient"] == "+2250700000000"


async def test_correlation_id_alias_is_accepted_but_request_id_wins(client):
    aliased = await client.get("/health", headers={"X-Correlation-ID": "legacy-correlation"})
    preferred = await client.get(
        "/health",
        headers={"X-Correlation-ID": "legacy-correlation", "X-Request-ID": "new-request"},
    )

    assert aliased.headers["X-Request-ID"] == "legacy-correlation"
    assert preferred.headers["X-Request-ID"] == "new-request"


async def test_domain_events_carry_w3c_trace_metadata_without_changing_payload(monkeypatch):
    from identity_app.modules.identity.domain.events import UserRegistered
    from identity_app.shared_kernel.events import bus

    class FakeRedis:
        def __init__(self):
            self.fields = None

        async def xadd(self, _stream, fields, **_kwargs):
            self.fields = fields
            return "1-0"

    fake_redis = FakeRedis()
    monkeypatch.setattr(
        bus,
        "inject_trace_context",
        lambda: {"traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"},
    )

    event = UserRegistered(user_id=uuid4(), phone=None, role="user")
    await bus.RedisEventPublisher(fake_redis).publish(event)

    assert fake_redis.fields["traceparent"].startswith("00-")
    payload = json.loads(fake_redis.fields["payload"])
    assert "traceparent" not in payload
    assert payload["event"] == "user.registered"
