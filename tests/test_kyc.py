"""Architecture §7.5 — the driver KYC gate, moved out of DiddiGo.

The property these tests exist to protect: **requesting a role never takes
anything away**. `status` is read by all twelve modules, so an active user who
applies to drive must keep using DiddiPay and DiddiShop while their file is
reviewed. Only an account that was never active waits in `pending_kyc`.
"""

from __future__ import annotations

from tests.conftest import API, SERVICE_KEY, register_and_verify


async def _request_driver(client, user_id: str, reason: str = "Dossier #4021"):
    return await client.patch(
        f"{API}/users/{user_id}/role",
        json={"role": "driver", "reason": reason},
        headers={"X-Service-Key": SERVICE_KEY},
    )


async def test_an_active_user_is_not_downgraded_by_a_request(client, user_session):
    user_id = user_session["user"]["id"]

    r = await _request_driver(client, user_id)

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "active", "un compte actif ne doit jamais être dégradé par une demande"
    assert body["role"] == "user"
    assert body["requested_role"] == "driver"


async def test_an_active_applicant_keeps_using_the_ecosystem(client, user_session):
    """The concrete consequence of the assertion above: their token still says
    `active`, so DiddiPay and DiddiShop keep serving them."""
    await _request_driver(client, user_session["user"]["id"])

    r = await client.post(
        f"{API}/auth/refresh",
        json={"refresh_token": user_session["refresh_token"]},
    )
    assert r.status_code == 200

    from identity_app.modules.identity.infra.token_service import TokenService

    claims = TokenService().decode_access_token(r.json()["access_token"])
    assert claims["status"] == "active"


async def test_a_never_active_account_waits_in_pending_kyc(client, otp_code, phone_factory):
    """`pending_kyc avant active`, as the architecture puts it — but only for an
    account that had nothing to lose."""
    phone = phone_factory()
    r = await client.post(f"{API}/auth/register", json={"phone": phone, "full_name": "Koffi N."})
    user_id = r.json()["user_id"]

    await _request_driver(client, user_id)

    await client.post(f"{API}/auth/otp/request", json={"phone": phone})
    r = await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": otp_code.latest()})

    assert r.status_code == 200
    assert r.json()["user"]["status"] == "pending_kyc"


async def test_a_pending_kyc_user_can_still_read_their_own_profile(
    client, otp_code, phone_factory,
):
    """They must be able to open the app and see where their request stands."""
    phone = phone_factory()
    r = await client.post(f"{API}/auth/register", json={"phone": phone})
    await _request_driver(client, r.json()["user_id"])
    await client.post(f"{API}/auth/otp/request", json={"phone": phone})
    body = (
        await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": otp_code.latest()})
    ).json()

    r = await client.get(
        f"{API}/users/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )

    assert r.status_code == 200
    assert r.json()["status"] == "pending_kyc"
    assert r.json()["requested_role"] == "driver"


async def test_a_module_refuses_a_pending_kyc_token(client, otp_code, phone_factory):
    """Reading one's own status is allowed; acting is not. A module sees
    `status != active` and declines."""
    import httpx

    from identity_app.main import app
    from identity_app.shared_kernel.contracts.identity_provider import (
        JwksIdentityVerifier,
        UserNotActive,
    )

    phone = phone_factory()
    r = await client.post(f"{API}/auth/register", json={"phone": phone})
    await _request_driver(client, r.json()["user_id"])
    await client.post(f"{API}/auth/otp/request", json={"phone": phone})
    body = (
        await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": otp_code.latest()})
    ).json()

    verifier = JwksIdentityVerifier(
        "http://testserver",
        client=httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver",
        ),
    )
    try:
        import pytest

        with pytest.raises(UserNotActive):
            await verifier.verify(body["access_token"])
    finally:
        await verifier.aclose()


async def test_approval_grants_the_role(client, user_session, admin_session):
    user_id = user_session["user"]["id"]
    await _request_driver(client, user_id)

    r = await client.patch(
        f"{API}/admin/users/{user_id}/kyc",
        json={"approved": True, "reason": "Permis vérifié, dossier #4021"},
        headers=admin_session["headers"],
    )

    assert r.status_code == 200
    assert r.json()["role"] == "driver"
    assert r.json()["requested_role"] is None


async def test_refusal_leaves_an_ordinary_user(client, user_session, admin_session):
    """A refusal denies the role, not the account."""
    user_id = user_session["user"]["id"]
    await _request_driver(client, user_id)

    r = await client.patch(
        f"{API}/admin/users/{user_id}/kyc",
        json={"approved": False, "reason": "Permis expiré"},
        headers=admin_session["headers"],
    )

    assert r.status_code == 200
    assert r.json()["role"] == "user"
    assert r.json()["status"] == "active"
    assert r.json()["requested_role"] is None


async def test_refusal_releases_an_account_stuck_in_pending_kyc(
    client, otp_code, phone_factory, admin_session,
):
    phone = phone_factory()
    r = await client.post(f"{API}/auth/register", json={"phone": phone})
    user_id = r.json()["user_id"]
    await _request_driver(client, user_id)
    await client.post(f"{API}/auth/otp/request", json={"phone": phone})
    await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": otp_code.latest()})

    r = await client.patch(
        f"{API}/admin/users/{user_id}/kyc",
        json={"approved": False, "reason": "Pièce illisible"},
        headers=admin_session["headers"],
    )

    assert r.status_code == 200
    # They were never a driver, but they are a perfectly valid user.
    assert r.json()["status"] == "active"
    assert r.json()["role"] == "user"


async def test_deciding_without_a_pending_file_is_a_conflict(
    client, user_session, admin_session,
):
    r = await client.patch(
        f"{API}/admin/users/{user_session['user']['id']}/kyc",
        json={"approved": True},
        headers=admin_session["headers"],
    )

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "NO_KYC_PENDING"


async def test_repeating_a_request_does_not_queue_it_twice(client, user_session):
    user_id = user_session["user"]["id"]
    await _request_driver(client, user_id)
    r = await _request_driver(client, user_id)

    assert r.status_code == 200
    assert r.json()["requested_role"] == "driver"

    from sqlalchemy import text

    from identity_app.core.database import async_session_factory

    async with async_session_factory() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM identity.user_role_history WHERE user_id = :uid"),
                {"uid": user_id},
            )
        ).scalar_one()

    assert count == 1, "un retry du module ne doit pas ouvrir un second dossier"


async def test_the_review_queue_lists_pending_files(client, user_session, admin_session):
    await _request_driver(client, user_session["user"]["id"])

    r = await client.get(
        f"{API}/admin/users",
        params={"pending_kyc": "true"},
        headers=admin_session["headers"],
    )

    assert r.status_code == 200
    ids = [u["id"] for u in r.json()["data"]]
    assert user_session["user"]["id"] in ids
    assert all(u["requested_role"] is not None for u in r.json()["data"])


async def test_the_decision_is_audited_with_its_reason(client, user_session, admin_session):
    """The `reason` of `PATCH /users/{id}/role` used to be accepted and dropped.
    "Pourquoi cette personne est chauffeur" has to be answerable later."""
    from sqlalchemy import text

    from identity_app.core.database import async_session_factory

    user_id = user_session["user"]["id"]
    await _request_driver(client, user_id, reason="Validation KYC chauffeur DiddiGo, dossier #4021")
    await client.patch(
        f"{API}/admin/users/{user_id}/kyc",
        json={"approved": True, "reason": "Permis et pièce conformes"},
        headers=admin_session["headers"],
    )

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT from_role, to_role, requested_role, reason, changed_by "
                    "FROM identity.user_role_history WHERE user_id = :uid ORDER BY changed_at",
                ),
                {"uid": user_id},
            )
        ).all()

    assert len(rows) == 2
    request_row, decision_row = rows

    # The request: nothing granted, the module's reason kept, no admin behind it.
    assert request_row[1] is None
    assert request_row[2] == "driver"
    assert request_row[3] == "Validation KYC chauffeur DiddiGo, dossier #4021"
    assert request_row[4] is None

    # The decision: the role granted, by a named admin.
    assert decision_row[0] == "user"
    assert decision_row[1] == "driver"
    assert decision_row[3] == "Permis et pièce conformes"
    assert str(decision_row[4]) == admin_session["user"]["id"]


async def test_a_refusal_is_audited_as_a_null_grant(client, user_session, admin_session):
    from sqlalchemy import text

    from identity_app.core.database import async_session_factory

    user_id = user_session["user"]["id"]
    await _request_driver(client, user_id)
    await client.patch(
        f"{API}/admin/users/{user_id}/kyc",
        json={"approved": False, "reason": "Permis expiré"},
        headers=admin_session["headers"],
    )

    async with async_session_factory() as session:
        decision = (
            await session.execute(
                text(
                    "SELECT to_role, requested_role, reason FROM identity.user_role_history "
                    "WHERE user_id = :uid ORDER BY changed_at DESC LIMIT 1",
                ),
                {"uid": user_id},
            )
        ).one()

    assert decision[0] is None, "un refus ne accorde aucun rôle"
    assert decision[1] == "driver"
    assert decision[2] == "Permis expiré"


async def test_backfill_walks_users_from_a_point_in_time(client, otp_code, phone_factory):
    """A module joining after the fact, or one offline past the stream's
    retention, has no events to replay — it walks the user base instead."""
    from datetime import UTC, datetime, timedelta

    before = datetime.now(UTC) - timedelta(seconds=5)
    created = [
        (await register_and_verify(client, otp_code, phone_factory()))["user"]["id"]
        for _ in range(3)
    ]

    r = await client.get(
        f"{API}/users/backfill",
        params={"since": before.isoformat(), "page_size": 100},
        headers={"X-Service-Key": SERVICE_KEY},
    )

    assert r.status_code == 200
    returned = [u["id"] for u in r.json()["data"]]
    assert set(created) <= set(returned)


async def test_backfill_is_closed_to_ordinary_users(client, user_session):
    r = await client.get(
        f"{API}/users/backfill",
        params={"since": "2026-01-01T00:00:00Z"},
        headers=user_session["headers"],
    )

    assert r.status_code == 403
