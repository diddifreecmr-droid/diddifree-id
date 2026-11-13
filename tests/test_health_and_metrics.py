"""Health and Prometheus endpoint checks for the observability baseline."""

from identity_app.core.settings import settings
from tests.conftest import API


async def test_liveness_does_not_require_dependencies(client):
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_metrics_endpoint_exposes_http_metrics(client):
    await client.get("/health/live")
    await client.get("/health/ready")

    response = await client.get("/metrics", headers={"Authorization": f"Bearer {settings.metrics_auth_token}"})

    assert response.status_code == 200
    assert "diddi_http_server_requests_total" in response.text
    assert "diddi_http_server_request_duration_seconds" in response.text
    assert "diddi_dependency_requests_total" in response.text
    assert "diddifree_dependency_health" in response.text
    assert "diddi_service_info" in response.text


async def test_metrics_endpoint_exposes_otp_and_event_metrics(client):
    from identity_app.core.metrics import observe_event_publish, observe_otp_delivery

    observe_otp_delivery(channel="logging", provider="logging", result="success")
    observe_event_publish(event="user.registered", result="success")
    response = await client.get("/metrics", headers={"Authorization": f"Bearer {settings.metrics_auth_token}"})

    assert response.status_code == 200
    assert "diddifree_otp_deliveries_total" in response.text
    assert "diddifree_event_publish_total" in response.text


async def test_metrics_requires_configured_bearer_token(client):
    denied = await client.get("/metrics")
    allowed = await client.get("/metrics", headers={"Authorization": f"Bearer {settings.metrics_auth_token}"})

    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "METRICS_UNAUTHORIZED"
    assert allowed.status_code == 200


async def test_metrics_is_unavailable_without_a_configured_token(client, monkeypatch):
    monkeypatch.setattr(settings, "metrics_auth_token", "")

    response = await client.get("/metrics")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "METRICS_NOT_CONFIGURED"


async def test_readiness_reports_missing_database_or_redis(client, monkeypatch):
    from identity_app.core import health

    async def unavailable_database():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(health, "_check_database", unavailable_database)
    monkeypatch.setattr(health.settings, "otp_provider", "logging")

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["checks"]["database"]["status"] == "error"


async def test_prefixed_health_routes_remain_available(client):
    response = await client.get(f"{API}/health/live")

    assert response.status_code == 404


async def test_worker_health_reports_account_purger_heartbeat(client):
    from identity_app.core.worker_health import record_worker_heartbeat
    from identity_app.main import app

    await record_worker_heartbeat(
        app.state.redis,
        worker="account-purger",
        status="ok",
        details={"anonymized_accounts": 0},
    )

    response = await client.get("/health/workers")

    assert response.status_code == 200
    assert response.json()["workers"]["account-purger"]["status"] == "ok"
