"""Contract §1 — registration, OTP, refresh rotation, logout."""

from __future__ import annotations

import pytest

from tests.conftest import API, register_and_verify


async def test_register_creates_pending_account(client, phone_factory):
    phone = phone_factory()
    r = await client.post(f"{API}/auth/register", json={"phone": phone, "full_name": "Awa Koné"})

    assert r.status_code == 201
    body = r.json()
    assert body["phone"] == phone
    assert body["status"] == "pending_verification"
    assert body["user_id"]


async def test_register_rejects_malformed_phone(client):
    r = await client.post(f"{API}/auth/register", json={"phone": "0700000000"})

    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_PHONE_FORMAT"


async def test_register_rejects_duplicate_phone(client, phone_factory):
    phone = phone_factory()
    await client.post(f"{API}/auth/register", json={"phone": phone})

    r = await client.post(f"{API}/auth/register", json={"phone": phone})

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "PHONE_ALREADY_REGISTERED"


async def test_verify_activates_account_and_returns_tokens(client, otp_code, phone_factory):
    body = await register_and_verify(client, otp_code, phone_factory())

    assert body["user"]["status"] == "active"
    assert body["user"]["full_name"] == "Awa Koné"
    assert body["user"]["role"] == "user"
    assert body["access_token"]
    # Opaque, not a JWT — that is what makes immediate revocation possible.
    assert body["refresh_token"].startswith("opaque_")
    assert body["refresh_token"].count(".") == 0


async def test_verify_rejects_wrong_code(client, otp_code, phone_factory):
    phone = phone_factory()
    await client.post(f"{API}/auth/register", json={"phone": phone})
    await client.post(f"{API}/auth/otp/request", json={"phone": phone})

    wrong = "000000" if otp_code.latest() != "000000" else "111111"
    r = await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": wrong})

    assert r.status_code == 400
    assert r.json()["error"]["code"] == "OTP_INVALID"


async def test_verify_burns_code_after_max_attempts(client, otp_code, phone_factory, monkeypatch):
    from identity_app.core.settings import settings

    monkeypatch.setattr(settings, "otp_max_attempts", 3)

    phone = phone_factory()
    await client.post(f"{API}/auth/register", json={"phone": phone})
    await client.post(f"{API}/auth/otp/request", json={"phone": phone})
    real_code = otp_code.latest()
    wrong = "000000" if real_code != "000000" else "111111"

    for _ in range(2):
        r = await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": wrong})
        assert r.status_code == 400

    r = await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": wrong})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "OTP_TOO_MANY_ATTEMPTS"

    # The code is now burned: even the correct one no longer works, which is
    # the whole point — otherwise the attempt ceiling would only slow an
    # attacker down rather than stop them.
    r = await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": real_code})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "OTP_INVALID"


async def test_expired_code_answers_410_not_400(client, otp_code, phone_factory, monkeypatch):
    """An expired code and a wrong code are different problems for the user:
    one means "ask for a new one", the other "check what you typed"."""
    from identity_app.core.settings import settings

    monkeypatch.setattr(settings, "otp_code_lifetime_seconds", -1)

    phone = phone_factory()
    await client.post(f"{API}/auth/register", json={"phone": phone})
    await client.post(f"{API}/auth/otp/request", json={"phone": phone})

    r = await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": otp_code.latest()})

    assert r.status_code == 410
    assert r.json()["error"]["code"] == "OTP_EXPIRED"


async def test_otp_request_does_not_reveal_unknown_numbers(client, phone_factory):
    """Same answer for a registered and an unregistered number — otherwise the
    endpoint tells anyone who asks whether a person uses DiddiFree."""
    unknown = phone_factory()
    r = await client.post(f"{API}/auth/otp/request", json={"phone": unknown})

    assert r.status_code == 200
    assert set(r.json()) == {"expires_in_seconds", "retry_after_seconds", "channel"}


async def test_email_channel_requires_profile_email(client, phone_factory):
    phone = phone_factory()
    await client.post(f"{API}/auth/register", json={"phone": phone})

    r = await client.post(
        f"{API}/auth/otp/request",
        json={"phone": phone, "channel": "email"},
    )

    assert r.status_code == 409
    assert r.json()["error"]["code"] == "EMAIL_NOT_CONFIGURED"


async def test_refresh_rotates_the_token(client, user_session):
    r = await client.post(
        f"{API}/auth/refresh",
        json={"refresh_token": user_session["refresh_token"]},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"] != user_session["refresh_token"]


async def test_reusing_a_rotated_refresh_token_kills_every_session(client, user_session):
    first = user_session["refresh_token"]
    r = await client.post(f"{API}/auth/refresh", json={"refresh_token": first})
    second = r.json()["refresh_token"]

    # Replay the token that was already rotated away.
    r = await client.post(f"{API}/auth/refresh", json={"refresh_token": first})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "REFRESH_TOKEN_REVOKED"

    # The whole family is now revoked, including the one the legitimate client
    # holds — a thief cannot keep the session alive by racing the real user.
    r = await client.post(f"{API}/auth/refresh", json={"refresh_token": second})
    assert r.status_code == 401


async def test_refresh_rejects_unknown_token(client):
    r = await client.post(f"{API}/auth/refresh", json={"refresh_token": "opaque_nope"})

    assert r.status_code == 401
    assert r.json()["error"]["code"] == "REFRESH_TOKEN_INVALID"


async def test_logout_revokes_the_device(client, user_session):
    r = await client.post(
        f"{API}/auth/logout",
        json={"refresh_token": user_session["refresh_token"], "all_devices": False},
    )
    assert r.status_code == 204
    assert r.content == b""

    r = await client.post(
        f"{API}/auth/refresh",
        json={"refresh_token": user_session["refresh_token"]},
    )
    assert r.status_code == 401


async def test_logout_all_devices(client, otp_code, phone_factory):
    phone = phone_factory()
    first = await register_and_verify(client, otp_code, phone)

    # Second device: request a new code and verify again.
    await client.post(f"{API}/auth/otp/request", json={"phone": phone})
    r = await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": otp_code.latest()})
    second = r.json()

    r = await client.post(
        f"{API}/auth/logout",
        json={"refresh_token": second["refresh_token"], "all_devices": True},
    )
    assert r.status_code == 204

    for token in (first["refresh_token"], second["refresh_token"]):
        r = await client.post(f"{API}/auth/refresh", json={"refresh_token": token})
        assert r.status_code == 401


async def test_logout_is_idempotent_on_unknown_token(client):
    r = await client.post(
        f"{API}/auth/logout",
        json={"refresh_token": "opaque_never_existed", "all_devices": False},
    )
    assert r.status_code == 204


async def test_me_returns_the_profile(client, user_session):
    r = await client.get(f"{API}/users/me", headers=user_session["headers"])

    assert r.status_code == 200
    assert r.json() == user_session["user"]


async def test_me_requires_a_token(client):
    r = await client.get(f"{API}/users/me")

    assert r.status_code == 401
    assert r.json()["error"]["code"] == "TOKEN_MISSING"


@pytest.mark.parametrize(
    ("token", "expected_code"),
    [("not-a-jwt", "TOKEN_INVALID"), ("", "TOKEN_MISSING")],
)
async def test_me_rejects_bad_tokens(client, token, expected_code):
    r = await client.get(f"{API}/users/me", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 401
    assert r.json()["error"]["code"] == expected_code


async def test_profile_update_is_reflected_immediately(client, user_session):
    """Covers the cache invalidation path: `/users/me` is a cached query, so a
    write that forgot to invalidate would keep serving the old name."""
    await client.get(f"{API}/users/me", headers=user_session["headers"])  # populate the cache

    r = await client.patch(
        f"{API}/users/me",
        json={"full_name": "Awa Koné-Traoré"},
        headers=user_session["headers"],
    )
    assert r.status_code == 200

    r = await client.get(f"{API}/users/me", headers=user_session["headers"])
    assert r.json()["full_name"] == "Awa Koné-Traoré"
