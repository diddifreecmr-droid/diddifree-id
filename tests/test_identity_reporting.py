from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from tests.conftest import API, register_and_verify


async def test_pilotage_identity_summary_reports_distinct_dau_and_mau(
    client, otp_code, phone_factory
):
    from identity_app.core.database import async_session_factory
    from identity_app.core.settings import settings
    from identity_app.modules.identity.infra.models import (
        ServiceClientModel,
        UserActivityDailyModel,
    )

    first = await register_and_verify(client, otp_code, phone_factory())
    second = await register_and_verify(client, otp_code, phone_factory())
    report_date = date(2026, 1, 15)
    previous_day = report_date - timedelta(days=1)
    seen_at = datetime.now(UTC)
    client_id = f"pilotage-staging-diddifreeid-{uuid4().hex[:8]}"

    async with async_session_factory() as session:
        session.add(
            ServiceClientModel(
                client_id=client_id,
                service_name="pilotage",
                environment="staging",
                secret_hash=hashlib.sha256(b"pilotage-secret").hexdigest(),
                allowed_audiences=[settings.jwt_issuer],
                allowed_scopes=["identity:reporting:read"],
            )
        )
        session.add_all(
            [
                UserActivityDailyModel(
                    user_id=UUID(first["user"]["id"]),
                    activity_date=report_date,
                    first_seen_at=seen_at,
                    last_seen_at=seen_at,
                ),
                UserActivityDailyModel(
                    user_id=UUID(first["user"]["id"]),
                    activity_date=previous_day,
                    first_seen_at=seen_at - timedelta(days=1),
                    last_seen_at=seen_at - timedelta(days=1),
                ),
                UserActivityDailyModel(
                    user_id=UUID(second["user"]["id"]),
                    activity_date=report_date,
                    first_seen_at=seen_at,
                    last_seen_at=seen_at,
                ),
            ]
        )
        await session.commit()

    token = await client.post(
        f"{API}/auth/service/token",
        headers={"X-Client-ID": client_id},
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": "pilotage-secret",
            "audience": settings.jwt_issuer,
            "scope": "identity:reporting:read",
        },
    )
    assert token.status_code == 200, token.text

    response = await client.get(
        f"{API}/internal/pilotage/identity-summary",
        params={"date": report_date.isoformat()},
        headers={
            "Authorization": f"Bearer {token.json()['access_token']}",
            "X-Client-ID": client_id,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    metrics = {item["name"]: item["value"] for item in body["metrics"]}
    assert body["contract_version"] == "pilotage.v1"
    assert body["module"] == "diddifree-id"
    assert metrics["daily_active_users"] == 2
    assert metrics["monthly_active_users"] == 2


async def test_pilotage_identity_summary_requires_reporting_scope(client):
    from identity_app.core.settings import settings
    from identity_app.main import app

    token = app.state.tokens.issue_service_token(
        service_name="pilotage",
        client_id="pilotage-test",
        audience=settings.jwt_issuer,
        scopes=("capabilities:read",),
        lifetime_seconds=600,
    )
    response = await client.get(
        f"{API}/internal/pilotage/identity-summary",
        params={"date": "2026-09-23"},
        headers={
            "Authorization": f"Bearer {token}",
            "X-Client-ID": "pilotage-test",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SERVICE_SCOPE_INVALID"
