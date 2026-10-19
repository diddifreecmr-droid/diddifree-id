"""Health and Prometheus endpoint checks for the observability baseline."""

from tests.conftest import API


async def test_liveness_does_not_require_dependencies(client):
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_metrics_endpoint_exposes_http_metrics(client):
    await client.get("/health/live")
    await client.get("/health/ready")

    response = await client.get("/metrics")

    assert response.status_code == 200
    assert "diddifree_http_requests_total" in response.text
    assert "diddifree_http_request_duration_seconds" in response.text
    assert "diddifree_dependency_health" in response.text


async def test_metrics_endpoint_exposes_otp_and_event_metrics(client):
    from identity_app.core.metrics import observe_event_publish, observe_otp_delivery

    observe_otp_delivery(channel="logging", provider="logging", result="success")
    observe_event_publish(event="user.registered", result="success")
    response = await client.get("/metrics")

    assert response.status_code == 200
    assert "diddifree_otp_deliveries_total" in response.text
    assert "diddifree_event_publish_total" in response.text


async def test_readiness_reports_missing_database_or_redis(client, monkeypatch):
    from identity_app.core import health

    async def unavailable_database():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(health, "_check_database", unavailable_database)
    monkeypatch.setattr(health.settings, "otp_provider", "logging")

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["database"]["status"] == "error"


async def test_prefixed_health_routes_remain_available(client):
    response = await client.get(f"{API}/health/live")

    assert response.status_code == 404
