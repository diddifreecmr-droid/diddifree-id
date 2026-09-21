from identity_app.core.settings import settings
from tests.conftest import API


def service_headers(app, *, service: str = "diddisend") -> dict[str, str]:
    token = app.state.tokens.issue_service_token(
        service_name=service,
        client_id=f"{service}-staging",
        audience=settings.jwt_issuer,
        scopes=("capabilities:write",),
        lifetime_seconds=600,
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Client-ID": f"{service}-staging",
    }


async def test_pro_capability_projection_flow(client, user_session):
    from identity_app.main import app

    user_id = user_session["user"]["id"]
    user_headers = user_session["headers"]

    requested = await client.post(
        f"{API}/pro/capabilities/diddisend/courier/request",
        headers=user_headers,
    )
    assert requested.status_code == 201, requested.text
    assert requested.json()["access_status"] == "requested"
    assert requested.json()["operational_status"] == "unknown"

    initial = await client.get(f"{API}/pro/me", headers=user_headers)
    assert initial.status_code == 200
    assert initial.json()["capabilities"][0]["freshness"] == "fresh"

    updated = await client.patch(
        f"{API}/pro/internal/users/{user_id}/capabilities/diddisend/courier/status",
        headers=service_headers(app),
        json={
            "operational_status": "pending_verification",
            "actions": ["complete_kyc"],
            "projection_version": 2,
            "event_id": "diddisend-event-2",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["operational_status"] == "pending_verification"

    duplicate = await client.patch(
        f"{API}/pro/internal/users/{user_id}/capabilities/diddisend/courier/status",
        headers=service_headers(app),
        json={
            "operational_status": "pending_verification",
            "actions": ["complete_kyc"],
            "projection_version": 2,
            "event_id": "diddisend-event-2",
        },
    )
    assert duplicate.status_code == 200

    conflict = await client.patch(
        f"{API}/pro/internal/users/{user_id}/capabilities/diddisend/courier/status",
        headers=service_headers(app),
        json={
            "operational_status": "ready",
            "actions": [],
            "projection_version": 2,
            "event_id": "diddisend-event-other",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "CAPABILITY_VERSION_CONFLICT"


async def test_capability_projection_rejects_wrong_service_owner(client, user_session):
    from identity_app.main import app

    user_id = user_session["user"]["id"]
    response = await client.patch(
        f"{API}/pro/internal/users/{user_id}/capabilities/diddigo/driver/status",
        headers=service_headers(app, service="diddisend"),
        json={
            "operational_status": "ready",
            "actions": [],
            "projection_version": 1,
            "event_id": "wrong-owner",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SERVICE_CAPABILITY_OWNER_INVALID"


async def test_admin_controls_access_without_overwriting_operational_status(
    client, admin_session, user_session
):
    user_id = user_session["user"]["id"]
    request = await client.post(
        f"{API}/pro/capabilities/diddigo/driver/request",
        headers=user_session["headers"],
    )
    assert request.status_code == 201

    response = await client.patch(
        f"{API}/admin/users/{user_id}/capabilities/diddigo/driver",
        headers=admin_session["headers"],
        json={"access_status": "enabled"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["access_status"] == "enabled"
    assert response.json()["operational_status"] == "unknown"
