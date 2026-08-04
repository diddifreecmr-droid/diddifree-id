"""Business-role ownership boundaries."""

from __future__ import annotations

from tests.conftest import API, SERVICE_KEY


async def test_driver_role_is_owned_by_diddigo(client, user_session):
    response = await client.patch(
        f"{API}/users/{user_session['user']['id']}/role",
        json={"role": "driver", "reason": "Qualification DiddiGo"},
        headers={"X-Service-Key": SERVICE_KEY},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ROLE_OWNED_BY_MODULE"


async def test_merchant_role_is_owned_by_its_module(client, user_session):
    response = await client.patch(
        f"{API}/users/{user_session['user']['id']}/role",
        json={"role": "merchant", "reason": "Qualification métier"},
        headers={"X-Service-Key": SERVICE_KEY},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ROLE_OWNED_BY_MODULE"


async def test_legacy_kyc_route_does_not_grant_a_business_role(client, user_session, admin_session):
    response = await client.patch(
        f"{API}/admin/users/{user_session['user']['id']}/kyc",
        json={"approved": True, "reason": "Ancien parcours"},
        headers=admin_session["headers"],
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_KYC_PENDING"
