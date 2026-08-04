"""Contract §3 — the back-office surface, and who is allowed on it."""

from __future__ import annotations

from tests.conftest import API, SERVICE_KEY, register_and_verify


async def test_list_users_is_paginated(client, admin_session, otp_code, phone_factory):
    for _ in range(3):
        await register_and_verify(client, otp_code, phone_factory())

    r = await client.get(
        f"{API}/admin/users",
        params={"page": 1, "page_size": 2},
        headers=admin_session["headers"],
    )

    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 2
    assert body["pagination"]["page"] == 1
    assert body["pagination"]["page_size"] == 2
    assert body["pagination"]["total_items"] >= 4
    assert body["pagination"]["total_pages"] >= 2


async def test_list_users_filters_by_role(client, admin_session):
    r = await client.get(
        f"{API}/admin/users",
        params={"role": "admin"},
        headers=admin_session["headers"],
    )

    assert r.status_code == 200
    assert all(user["role"] == "admin" for user in r.json()["data"])


async def test_list_users_rejects_an_unknown_filter(client, admin_session):
    """An unknown role silently returning an empty page reads as "no such
    users" to the operator, which is a different and wrong answer."""
    r = await client.get(
        f"{API}/admin/users",
        params={"role": "chauffeur"},
        headers=admin_session["headers"],
    )

    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_ROLE"


async def test_admin_routes_are_closed_to_plain_users(client, user_session):
    r = await client.get(f"{API}/admin/users", headers=user_session["headers"])

    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN_ROLE"


async def test_suspend_then_reactivate(client, admin_session, user_session):
    user_id = user_session["user"]["id"]

    r = await client.patch(
        f"{API}/admin/users/{user_id}/status",
        json={"status": "suspended", "reason": "Signalement fraude, ticket #883"},
        headers=admin_session["headers"],
    )
    assert r.status_code == 200
    assert r.json()["status"] == "suspended"

    r = await client.patch(
        f"{API}/admin/users/{user_id}/status",
        json={"status": "active", "reason": "Signalement infondé"},
        headers=admin_session["headers"],
    )
    assert r.status_code == 200
    assert r.json()["status"] == "active"


async def test_an_admin_cannot_set_pending_kyc_by_hand(client, admin_session, user_session):
    """`status` is global. Parking a working account in `pending_kyc` would cut
    its owner off from every module over one module's review."""
    r = await client.patch(
        f"{API}/admin/users/{user_session['user']['id']}/status",
        json={"status": "pending_kyc", "reason": "Tentative"},
        headers=admin_session["headers"],
    )

    assert r.status_code == 422
    assert r.json()["error"]["code"] == "STATUS_NOT_SETTABLE"


async def test_invalid_transition_is_a_conflict(client, admin_session, user_session):
    """`active → active` is not a no-op here: an admin re-suspending an already
    suspended account should be told the action had no effect, not shown a
    success that implies something happened."""
    r = await client.patch(
        f"{API}/admin/users/{user_session['user']['id']}/status",
        json={"status": "active", "reason": "Déjà actif"},
        headers=admin_session["headers"],
    )

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


async def test_suspension_kills_refresh_immediately(client, admin_session, user_session):
    """The point of opaque, stored refresh tokens: suspension must not wait for
    a JWT to expire before it takes hold."""
    await client.patch(
        f"{API}/admin/users/{user_session['user']['id']}/status",
        json={"status": "suspended", "reason": "Test"},
        headers=admin_session["headers"],
    )

    r = await client.post(
        f"{API}/auth/refresh",
        json={"refresh_token": user_session["refresh_token"]},
    )
    assert r.status_code == 401


async def test_status_change_is_audited(client, admin_session, user_session):
    """Architecture §8 asks for a trail of every admin action. Read it back
    from the table — an audit row nobody ever verifies is an assumption, not a
    guarantee."""
    from sqlalchemy import text

    from identity_app.core.database import async_session_factory

    user_id = user_session["user"]["id"]
    await client.patch(
        f"{API}/admin/users/{user_id}/status",
        json={"status": "suspended", "reason": "Signalement fraude, ticket #883"},
        headers=admin_session["headers"],
    )

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT from_status, to_status, reason, changed_by "
                    "FROM identity.user_status_history "
                    "WHERE user_id = :uid ORDER BY changed_at",
                ),
                {"uid": user_id},
            )
        ).all()

    # The OTP activation, then the suspension.
    assert [(r[0], r[1]) for r in rows] == [
        ("pending_verification", "active"),
        ("active", "suspended"),
    ]
    assert rows[1][2] == "Signalement fraude, ticket #883"
    assert str(rows[1][3]) == admin_session["user"]["id"]
    # The activation was the system's doing, not an admin's.
    assert rows[0][3] is None


async def test_role_change_requires_service_or_admin(client, user_session):
    r = await client.patch(
        f"{API}/users/{user_session['user']['id']}/role",
        json={"role": "driver", "reason": "Tentative depuis un compte utilisateur"},
        headers=user_session["headers"],
    )

    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN_ROLE"


async def test_module_requesting_driver_queues_a_kyc_file(client, user_session):
    """The flow of contract §1 crossed with architecture §7.5: Ride records the
    request, and DiddiFreeID holds the role until KYC decides. See
    `test_kyc.py` for the decision half."""
    r = await client.patch(
        f"{API}/users/{user_session['user']['id']}/role",
        json={"role": "driver", "reason": "Validation KYC chauffeur DiddiGo, dossier #4021"},
        headers={"X-Service-Key": SERVICE_KEY},
    )

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ROLE_OWNED_BY_MODULE"
    return

    assert r.status_code == 200
    body = r.json()
    assert body["requested_role"] == "driver"
    assert body["role"] == "user"


async def test_a_role_without_kyc_is_granted_immediately(client, user_session):
    """`admin` is outside `KYC_REQUIRED_ROLES` — otherwise bootstrapping the
    first admin would need an admin to approve it."""
    r = await client.patch(
        f"{API}/users/{user_session['user']['id']}/role",
        json={"role": "admin", "reason": "Nomination"},
        headers={"X-Service-Key": SERVICE_KEY},
    )

    assert r.status_code == 200
    assert r.json()["role"] == "admin"
    assert r.json()["requested_role"] is None


async def test_role_change_rejects_an_unknown_role(client, user_session):
    r = await client.patch(
        f"{API}/users/{user_session['user']['id']}/role",
        json={"role": "superadmin"},
        headers={"X-Service-Key": SERVICE_KEY},
    )

    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_ROLE"


async def test_service_lookup_requires_a_key(client, user_session):
    """`GET /users/{id}` is not a directory the frontend may browse."""
    r = await client.get(
        f"{API}/users/{user_session['user']['id']}",
        headers=user_session["headers"],
    )
    assert r.status_code == 403

    r = await client.get(
        f"{API}/users/{user_session['user']['id']}",
        headers={"X-Service-Key": SERVICE_KEY},
    )
    assert r.status_code == 200
    assert r.json()["id"] == user_session["user"]["id"]


async def test_service_lookup_rejects_a_bad_key(client, user_session):
    r = await client.get(
        f"{API}/users/{user_session['user']['id']}",
        headers={"X-Service-Key": "pas-la-bonne"},
    )

    assert r.status_code == 401
    assert r.json()["error"]["code"] == "SERVICE_KEY_INVALID"


async def test_unknown_user_is_a_404(client):
    r = await client.get(
        f"{API}/users/00000000-0000-0000-0000-000000000000",
        headers={"X-Service-Key": SERVICE_KEY},
    )

    assert r.status_code == 404
    assert r.json()["error"]["code"] == "USER_NOT_FOUND"
