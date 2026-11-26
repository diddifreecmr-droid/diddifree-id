from identity_app.core.settings import settings
from tests.conftest import API


def service_headers(
    app,
    *,
    service: str = "diddisend",
    scopes: tuple[str, ...] = ("capabilities:write",),
) -> dict[str, str]:
    token = app.state.tokens.issue_service_token(
        service_name=service,
        client_id=f"{service}-staging",
        audience=settings.jwt_issuer,
        scopes=scopes,
        lifetime_seconds=600,
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Client-ID": f"{service}-staging",
    }


def backoffice_headers(app, *, scopes: tuple[str, ...] = ("capabilities:read",)) -> dict[str, str]:
    token = app.state.tokens.issue_service_token(
        service_name="backoffice",
        client_id="backoffice-staging-diddifreeid",
        audience=settings.jwt_issuer,
        scopes=scopes,
        lifetime_seconds=600,
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Client-ID": "backoffice-staging-diddifreeid",
    }


def rewards_capability_headers(app, *, scopes: tuple[str, ...] = ("capabilities:read",)) -> dict[str, str]:
    client_id = "diddirewards-staging-diddifreeid"
    token = app.state.tokens.issue_service_token(
        service_name="diddirewards",
        client_id=client_id,
        audience=settings.jwt_issuer,
        scopes=scopes,
        lifetime_seconds=600,
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Client-ID": client_id,
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
            "first_enabled_at": "2026-11-20T12:00:00Z",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["operational_status"] == "pending_verification"
    assert updated.json()["first_enabled_at"] == "2026-11-20T12:00:00Z"

    duplicate = await client.patch(
        f"{API}/pro/internal/users/{user_id}/capabilities/diddisend/courier/status",
        headers=service_headers(app),
        json={
            "operational_status": "pending_verification",
            "actions": ["complete_kyc"],
            "projection_version": 2,
            "event_id": "diddisend-event-2",
            "first_enabled_at": "2026-11-20T12:00:00Z",
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
            "first_enabled_at": "2026-11-20T12:00:00Z",
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


async def test_diddigo_validation_projection_uses_canonical_status(client, user_session):
    from identity_app.main import app

    user_id = user_session["user"]["id"]
    requested = await client.post(
        f"{API}/pro/capabilities/diddigo/driver/request",
        headers=user_session["headers"],
    )
    assert requested.status_code == 201, requested.text

    response = await client.patch(
        f"{API}/pro/internal/users/{user_id}/capabilities/diddigo/driver/status",
        headers=service_headers(app, service="diddigo"),
        json={
            "operational_status": "validated",
            "actions": [],
            "projection_version": 2,
            "event_id": "diddigo-driver-approval-1",
            "first_enabled_at": "2026-11-25T10:00:00Z",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["access_status"] == "enabled"
    assert response.json()["operational_status"] == "validated"
    assert response.json()["status_source"] == "diddigo"
    assert response.json()["first_enabled_at"] == "2026-11-25T10:00:00Z"


async def test_validated_cannot_reactivate_suspended_capability(client, user_session):
    from identity_app.main import app

    user_id = user_session["user"]["id"]
    headers = service_headers(app, service="diddigo", scopes=("capabilities:access:write",))
    requested = await client.post(
        f"{API}/pro/capabilities/diddigo/driver/request",
        headers=user_session["headers"],
    )
    assert requested.status_code == 201

    suspended = await client.patch(
        f"{API}/pro/internal/users/{user_id}/capabilities/diddigo/driver/access",
        headers=headers,
        json={"access_status": "suspended", "reason": "kyc_review", "event_id": "access-suspend-1"},
    )
    assert suspended.status_code == 200

    conflict = await client.patch(
        f"{API}/pro/internal/users/{user_id}/capabilities/diddigo/driver/status",
        headers=service_headers(app, service="diddigo"),
        json={
            "operational_status": "validated",
            "actions": [],
            "projection_version": 2,
            "event_id": "approval-after-suspension",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "CAPABILITY_ACCESS_CONFLICT"

    revalidated = await client.patch(
        f"{API}/pro/internal/users/{user_id}/capabilities/diddigo/driver/status",
        headers=service_headers(app, service="diddigo"),
        json={
            "operational_status": "revalidated",
            "actions": [],
            "projection_version": 2,
            "event_id": "revalidation-1",
        },
    )
    assert revalidated.status_code == 200, revalidated.text
    assert revalidated.json()["access_status"] == "enabled"


async def test_service_access_decision_is_idempotent_and_preserves_first_date(client, user_session):
    from identity_app.main import app

    user_id = user_session["user"]["id"]
    headers = service_headers(app, service="diddigo", scopes=("capabilities:access:write",))
    payload = {
        "access_status": "enabled",
        "reason": "kyc_approved",
        "event_id": "diddigo:driver-access:1",
        "enabled_at": "2026-11-25T10:00:00Z",
    }

    first = await client.patch(
        f"{API}/pro/internal/users/{user_id}/capabilities/diddigo/driver/access",
        headers=headers,
        json=payload,
    )
    assert first.status_code == 200, first.text
    assert first.json()["access_status"] == "enabled"
    assert first.json()["first_enabled_at"] == "2026-11-25T10:00:00Z"

    replay = await client.patch(
        f"{API}/pro/internal/users/{user_id}/capabilities/diddigo/driver/access",
        headers=headers,
        json=payload | {"access_status": "suspended", "reason": "different"},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["access_status"] == "enabled"
    assert replay.json()["access_reason"] == "kyc_approved"

    suspended = await client.patch(
        f"{API}/pro/internal/users/{user_id}/capabilities/diddigo/driver/access",
        headers=headers,
        json={
            "access_status": "suspended",
            "reason": "kyc_review",
            "event_id": "diddigo:driver-access:2",
        },
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["access_status"] == "suspended"
    assert suspended.json()["first_enabled_at"] == "2026-11-25T10:00:00Z"

    late_retry = await client.patch(
        f"{API}/pro/internal/users/{user_id}/capabilities/diddigo/driver/access",
        headers=headers,
        json=payload,
    )
    assert late_retry.status_code == 200, late_retry.text
    assert late_retry.json()["access_status"] == "suspended"


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


async def test_backoffice_reads_and_enables_user_capability(client, user_session):
    from identity_app.main import app

    user_id = user_session["user"]["id"]
    read_response = await client.get(
        f"{API}/admin/users/{user_id}/capabilities",
        headers=backoffice_headers(app),
    )
    assert read_response.status_code == 200
    assert read_response.json()["capabilities"] == []

    write_response = await client.patch(
        f"{API}/admin/users/{user_id}/capabilities/diddisend/courier",
        headers=backoffice_headers(app, scopes=("capabilities:access:write",)),
        json={"access_status": "enabled"},
    )
    assert write_response.status_code == 200, write_response.text
    assert write_response.json()["access_status"] == "enabled"

    read_response = await client.get(
        f"{API}/admin/users/{user_id}/capabilities",
        headers=backoffice_headers(app),
    )
    assert read_response.json()["capabilities"][0]["service"] == "diddisend"


async def test_non_backoffice_service_cannot_change_capability_access(client, user_session):
    from identity_app.main import app

    response = await client.patch(
        f"{API}/admin/users/{user_session['user']['id']}/capabilities/diddigo/driver",
        headers=service_headers(app),
        json={"access_status": "enabled"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SERVICE_CAPABILITY_ACCESS_FORBIDDEN"


async def test_rewards_reads_first_enabled_at_and_it_survives_reactivation(
    client, admin_session, user_session
):
    from identity_app.main import app

    user_id = user_session["user"]["id"]
    requested = await client.post(
        f"{API}/pro/capabilities/diddigo/driver/request",
        headers=user_session["headers"],
    )
    assert requested.status_code == 201

    enabled = await client.patch(
        f"{API}/admin/users/{user_id}/capabilities/diddigo/driver",
        headers=admin_session["headers"],
        json={"access_status": "enabled"},
    )
    assert enabled.status_code == 200, enabled.text
    first_enabled_at = enabled.json()["first_enabled_at"]
    assert first_enabled_at is not None

    rewards_read = await client.get(
        f"{API}/users/{user_id}/capabilities",
        headers=rewards_capability_headers(app),
    )
    assert rewards_read.status_code == 200, rewards_read.text
    capability = rewards_read.json()["capabilities"][0]
    assert capability["first_enabled_at"] == first_enabled_at

    suspended = await client.patch(
        f"{API}/admin/users/{user_id}/capabilities/diddigo/driver",
        headers=admin_session["headers"],
        json={"access_status": "suspended"},
    )
    assert suspended.status_code == 200
    reenabled = await client.patch(
        f"{API}/admin/users/{user_id}/capabilities/diddigo/driver",
        headers=admin_session["headers"],
        json={"access_status": "enabled"},
    )
    assert reenabled.status_code == 200
    assert reenabled.json()["first_enabled_at"] == first_enabled_at


async def test_rewards_capability_route_rejects_missing_scope_and_wrong_service(client, user_session):
    from identity_app.main import app

    user_id = user_session["user"]["id"]
    missing_scope = await client.get(
        f"{API}/users/{user_id}/capabilities",
        headers=rewards_capability_headers(app, scopes=("profile:read",)),
    )
    assert missing_scope.status_code == 403

    token = app.state.tokens.issue_service_token(
        service_name="diddisend",
        client_id="diddisend-staging-diddifreeid",
        audience=settings.jwt_issuer,
        scopes=("capabilities:read",),
        lifetime_seconds=600,
    )
    wrong_service = await client.get(
        f"{API}/users/{user_id}/capabilities",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Client-ID": "diddisend-staging-diddifreeid",
        },
    )
    assert wrong_service.status_code == 403
