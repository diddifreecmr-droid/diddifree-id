"""Basic request correlation guarantees for the observability baseline."""

import logging

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
