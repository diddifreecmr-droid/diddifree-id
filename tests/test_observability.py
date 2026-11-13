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
        if record.name == "identity_app.main" and record.msg == "http_request_completed"
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
        "outbound Authorization: Bearer private-token password=not-for-logs",
        (),
        None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["timestamp"].endswith("Z")
    assert payload["service"] == "diddifree-id"
    assert payload["component"] == "api"
    assert "private-token" not in payload["message"]
    assert "not-for-logs" not in payload["message"]


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
