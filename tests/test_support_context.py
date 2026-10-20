from identity_app.core.settings import settings
from tests.conftest import API


def support_headers(app, *, scopes: tuple[str, ...] = ("identity:support-context:read",)) -> dict[str, str]:
    client_id = "diddisupport-staging-diddifreeid"
    token = app.state.tokens.issue_service_token(
        service_name="diddisupport",
        client_id=client_id,
        audience=settings.jwt_issuer,
        scopes=scopes,
        lifetime_seconds=600,
    )
    return {"Authorization": f"Bearer {token}", "X-Client-ID": client_id}


async def test_diddisupport_reads_masked_user_context(client, user_session):
    from identity_app.main import app

    user_id = user_session["user"]["id"]
    capability = await client.post(
        f"{API}/pro/capabilities/diddisend/courier/request",
        headers=user_session["headers"],
    )
    assert capability.status_code == 201, capability.text

    response = await client.get(
        f"/internal/v1/support/users/{user_id}/context",
        headers={**support_headers(app), "X-Request-ID": "support-case-123"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["X-Request-ID"] == "support-case-123"
    body = response.json()
    assert body["protocol"] == "diddi.context.v1"
    assert body["resource_type"] == "user"
    assert body["resource_id"] == user_id
    assert body["context"]["display_name"] == "Awa Koné"
    assert body["context"]["phone_masked"].startswith("+225")
    assert body["context"]["phone_masked"] != user_session["user"]["phone"]
    assert "phone" not in body["context"]
    assert "email" not in body["context"]
    assert body["context"]["capabilities"] == [
        {
            "service": "diddisend",
            "type": "courier",
            "access_status": "requested",
            "operational_status": "unknown",
            "status_source": "diddifreeid",
            "updated_at": body["context"]["capabilities"][0]["updated_at"],
        }
    ]


async def test_support_context_rejects_another_service(client, user_session):
    from identity_app.main import app

    token = app.state.tokens.issue_service_token(
        service_name="diddisend",
        client_id="diddisend-staging-diddifreeid",
        audience=settings.jwt_issuer,
        scopes=("identity:support-context:read",),
        lifetime_seconds=600,
    )
    response = await client.get(
        f"/internal/v1/support/users/{user_session['user']['id']}/context",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Client-ID": "diddisend-staging-diddifreeid",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SERVICE_SUPPORT_CONTEXT_FORBIDDEN"


async def test_support_context_requires_its_dedicated_scope(client, user_session):
    from identity_app.main import app

    response = await client.get(
        f"/internal/v1/support/users/{user_session['user']['id']}/context",
        headers=support_headers(app, scopes=("identity:reporting:read",)),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SERVICE_SCOPE_INVALID"
