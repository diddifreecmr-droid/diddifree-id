"""Architecture §8 — OTP abuse controls.

The suite runs with `OTP_RATE_LIMIT_SECONDS=0` so ordinary tests are not fighting
a cooldown; these turn it back on for the cases that are actually about it.
"""

from __future__ import annotations

import pytest

from tests.conftest import API


@pytest.fixture
def cooldown(monkeypatch):
    from identity_app.core.settings import settings

    monkeypatch.setattr(settings, "otp_rate_limit_seconds", 60)
    return 60


async def test_second_request_within_the_cooldown_is_rejected(client, phone_factory, cooldown):
    phone = phone_factory()
    await client.post(f"{API}/auth/register", json={"phone": phone})

    r = await client.post(f"{API}/auth/otp/request", json={"phone": phone})
    assert r.status_code == 200

    r = await client.post(f"{API}/auth/otp/request", json={"phone": phone})
    assert r.status_code == 429
    body = r.json()
    assert body["error"]["code"] == "OTP_RATE_LIMITED"
    # The contract promises the client is told how long to wait.
    assert body["error"]["details"]["retry_after_seconds"] > 0


async def test_the_cooldown_is_per_phone(client, phone_factory, cooldown):
    first, second = phone_factory(), phone_factory()
    for phone in (first, second):
        await client.post(f"{API}/auth/register", json={"phone": phone})

    assert (await client.post(f"{API}/auth/otp/request", json={"phone": first})).status_code == 200
    # A different number is a different person; one user's cooldown must not
    # block anyone else's signup.
    assert (await client.post(f"{API}/auth/otp/request", json={"phone": second})).status_code == 200


async def test_an_unknown_number_still_arms_the_cooldown(client, phone_factory, cooldown):
    """Otherwise the endpoint answers instantly for unknown numbers and slowly
    for known ones — an enumeration oracle built out of timing and 429s."""
    phone = phone_factory()

    assert (await client.post(f"{API}/auth/otp/request", json={"phone": phone})).status_code == 200
    r = await client.post(f"{API}/auth/otp/request", json={"phone": phone})
    assert r.status_code == 429


async def test_per_ip_ceiling_stops_number_enumeration(client, phone_factory):
    """Distinct numbers dodge the per-phone cooldown, so the per-IP counter is
    what stops a script walking a range of numbers from one machine."""
    from identity_app.modules.identity.infra import rate_limiter

    statuses = []
    for _ in range(rate_limiter.IP_REQUESTS_PER_WINDOW + 2):
        r = await client.post(
            f"{API}/auth/otp/request",
            json={"phone": phone_factory()},
            headers={"X-Forwarded-For": "203.0.113.42"},
        )
        statuses.append(r.status_code)

    assert statuses[0] == 200
    assert statuses[-1] == 429
    assert statuses.count(200) == rate_limiter.IP_REQUESTS_PER_WINDOW


async def test_otp_codes_are_never_stored_in_clear(client, otp_code, phone_factory):
    """Architecture §8. A database dump must not hand over live codes — and
    with a keyed hash, the digest is useless without the pepper."""
    from sqlalchemy import text

    from identity_app.core.database import async_session_factory

    phone = phone_factory()
    await client.post(f"{API}/auth/register", json={"phone": phone})
    await client.post(f"{API}/auth/otp/request", json={"phone": phone})
    code = otp_code.latest()

    async with async_session_factory() as session:
        stored = (
            await session.execute(
                text("SELECT code_hash FROM identity.otp_codes WHERE phone = :p"),
                {"p": phone},
            )
        ).scalar_one()

    assert stored != code
    # Not a bare SHA-256 either: that would be reversible for a six-digit code
    # by trying all one million of them.
    from hashlib import sha256

    assert stored != sha256(code.encode()).hexdigest()


async def test_refresh_tokens_are_never_stored_in_clear(client, user_session):
    from sqlalchemy import text

    from identity_app.core.database import async_session_factory

    async with async_session_factory() as session:
        hashes = (
            await session.execute(
                text("SELECT token_hash FROM identity.refresh_tokens WHERE user_id = :uid"),
                {"uid": user_session["user"]["id"]},
            )
        ).scalars().all()

    assert hashes
    assert user_session["refresh_token"] not in hashes
