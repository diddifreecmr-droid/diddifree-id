"""Google Play review-account isolation at the DiddiFreeID boundary."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from identity_app.core.settings import settings
from identity_app.modules.identity.infra.token_service import ALGORITHM, TokenService
from identity_app.shared_kernel.events.bus import STREAM_KEY
from tests.conftest import API, register_and_verify


def _claims(access_token: str) -> dict:
    return jwt.decode(access_token, options={"verify_signature": False})


class _EventReader:
    def __init__(self, redis, last_id: str) -> None:
        self._redis = redis
        self._last_id = last_id

    async def read_named(self, name: str) -> list[dict]:
        entries = await self._redis.xrange(STREAM_KEY, f"({self._last_id}", "+")
        return [
            event
            for _entry_id, fields in entries
            if (event := json.loads(fields["payload"]))["event"] == name
        ]


@pytest.fixture
async def events():
    from identity_app.core.redis import create_redis_pool
    from identity_app.core.settings import settings as app_settings

    redis = create_redis_pool(app_settings.redis_url)
    tail = await redis.xrevrange(STREAM_KEY, "+", "-", count=1)
    try:
        yield _EventReader(redis, tail[0][0] if tail else "0-0")
    finally:
        await redis.aclose()


async def test_new_accounts_receive_a_false_review_claim(client, otp_code, phone_factory):
    body = await register_and_verify(client, otp_code, phone_factory())

    assert _claims(body["access_token"])["is_review_account"] is False
    # The marker is infrastructure metadata, not a feature for the end user.
    assert "is_review_account" not in body["user"]


async def test_admin_can_enable_review_account_with_audit_and_event(
    client, admin_session, user_session, otp_code, events,
):
    user_id = user_session["user"]["id"]
    changed = await client.patch(
        f"{API}/admin/users/{user_id}/review-account",
        json={"is_review_account": True, "reason": "Google Play review account"},
        headers=admin_session["headers"],
    )

    assert changed.status_code == 200
    assert changed.json() == {"id": user_id, "is_review_account": True}

    # The old session cannot mint a fresh token with the former marker.
    refreshed = await client.post(
        f"{API}/auth/refresh",
        json={"refresh_token": user_session["refresh_token"]},
    )
    assert refreshed.status_code == 401

    # A new authentication issues the updated backend-only claim.
    phone = user_session["user"]["phone"]
    requested = await client.post(f"{API}/auth/otp/request", json={"phone": phone})
    assert requested.status_code == 200
    logged_in = await client.post(
        f"{API}/auth/otp/verify",
        json={"phone": phone, "code": otp_code.latest()},
    )
    assert logged_in.status_code == 200
    assert _claims(logged_in.json()["access_token"])["is_review_account"] is True

    published = await events.read_named("user.review_account_changed")
    assert len(published) == 1
    assert published[0]["old_is_review_account"] is False
    assert published[0]["new_is_review_account"] is True

    from sqlalchemy import text

    from identity_app.core.database import async_session_factory

    async with async_session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT from_is_review_account, to_is_review_account, reason, changed_by "
                    "FROM identity.user_review_account_history WHERE user_id = :user_id",
                ),
                {"user_id": user_id},
            )
        ).one()

    assert tuple(row[:3]) == (False, True, "Google Play review account")
    assert str(row[3]) == admin_session["user"]["id"]


async def test_plain_user_cannot_manage_review_accounts(client, user_session):
    response = await client.patch(
        f"{API}/admin/users/{user_session['user']['id']}/review-account",
        json={"is_review_account": True, "reason": "Tentative non autorisée"},
        headers=user_session["headers"],
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN_ROLE"


async def test_malformed_review_claim_is_rejected(client, user_session):
    """A signed but non-boolean claim must not be silently coerced to true."""
    tokens = TokenService()
    now = datetime.now(UTC)
    malformed = jwt.encode(
        {
            "sub": user_session["user"]["id"],
            "role": "user",
            "status": "active",
            "is_review_account": "true",
            "iss": settings.jwt_issuer,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        tokens._key_ring.private_pem,
        algorithm=ALGORITHM,
        headers={"kid": tokens._key_ring.active_kid},
    )

    response = await client.get(
        f"{API}/users/me",
        headers={"Authorization": f"Bearer {malformed}"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"
