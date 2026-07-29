"""Contract §4 — the events other modules build on.

Wallet creates an account on `user.registered`, Ride reacts to
`user.role_changed`, everyone drops cached profiles on `user.updated`. If the
payload shape drifts, those subscribers break silently, so the shape is asserted
here rather than trusted.

These tests read the stream by id rather than by subscription, which is only
possible because the bus persists now — with Pub/Sub the assertion had to race
the publication.
"""

from __future__ import annotations

import json

import pytest

from identity_app.shared_kernel.events.bus import STREAM_KEY
from tests.conftest import API, SERVICE_KEY, register_and_verify


class EventReader:
    """Reads everything published to the stream after construction."""

    def __init__(self, redis, last_id: str) -> None:
        self._redis = redis
        self._last_id = last_id

    async def read(self) -> list[dict]:
        entries = await self._redis.xrange(STREAM_KEY, f"({self._last_id}", "+")
        return [json.loads(fields["payload"]) for _entry_id, fields in entries]

    async def read_named(self, name: str) -> list[dict]:
        return [event for event in await self.read() if event["event"] == name]


@pytest.fixture
async def events():
    """An `EventReader` positioned at the current end of the stream."""
    from identity_app.core.redis import create_redis_pool
    from identity_app.core.settings import settings

    redis = create_redis_pool(settings.redis_url)
    tail = await redis.xrevrange(STREAM_KEY, "+", "-", count=1)
    last_id = tail[0][0] if tail else "0-0"
    try:
        yield EventReader(redis, last_id)
    finally:
        await redis.aclose()


async def test_first_verification_publishes_user_registered(
    client, otp_code, phone_factory, events,
):
    phone = phone_factory()
    body = await register_and_verify(client, otp_code, phone)

    published = await events.read_named("user.registered")

    assert len(published) == 1
    event = published[0]
    assert event["user_id"] == body["user"]["id"]
    assert event["phone"] == phone
    assert event["role"] == "user"
    # ISO 8601 UTC with a `Z`, as the contract's §0 spells out.
    assert event["at"].endswith("Z")


async def test_second_login_does_not_republish_user_registered(
    client, otp_code, phone_factory, events,
):
    """Wallet creates an account on this event. Emitting it on every login
    would give a returning user a second wallet."""
    phone = phone_factory()
    await register_and_verify(client, otp_code, phone)

    assert len(await events.read_named("user.registered")) == 1

    await client.post(f"{API}/auth/otp/request", json={"phone": phone})
    r = await client.post(f"{API}/auth/otp/verify", json={"phone": phone, "code": otp_code.latest()})
    assert r.status_code == 200

    assert len(await events.read_named("user.registered")) == 1


async def test_events_survive_a_consumer_that_was_not_listening(
    client, otp_code, phone_factory,
):
    """The reason for moving off Pub/Sub. A module down at publication time must
    still find the event when it comes back — otherwise a user ends up with no
    wallet and nothing reports it."""
    from identity_app.core.redis import create_redis_pool
    from identity_app.core.settings import settings
    from identity_app.shared_kernel.events.bus import RedisEventConsumer

    # Nobody is subscribed at this point.
    body = await register_and_verify(client, otp_code, phone_factory())

    redis = create_redis_pool(settings.redis_url)
    try:
        consumer = RedisEventConsumer(redis, group="wallet-test", name="worker-1")
        await consumer.ensure_group(from_beginning=True)

        received = await consumer.read(block_ms=100)
        registered = [e for _id, e in received if e["event"] == "user.registered"]

        assert [e["user_id"] for e in registered] == [body["user"]["id"]]
    finally:
        await redis.aclose()


async def test_an_unacknowledged_event_is_redelivered(client, otp_code, phone_factory):
    """A consumer that crashes mid-handling must see the event again. This is
    what `ack`-after-handling buys, and why handlers must be idempotent."""
    from identity_app.core.redis import create_redis_pool
    from identity_app.core.settings import settings
    from identity_app.shared_kernel.events.bus import RedisEventConsumer

    await register_and_verify(client, otp_code, phone_factory())

    redis = create_redis_pool(settings.redis_url)
    try:
        consumer = RedisEventConsumer(redis, group="crash-test", name="worker-1")
        await consumer.ensure_group(from_beginning=True)

        first = await consumer.read(block_ms=100)
        assert first
        # Simulate the crash: handled nothing, acknowledged nothing.

        pending = await consumer.read_pending()
        assert [entry_id for entry_id, _ in pending] == [entry_id for entry_id, _ in first]

        for entry_id, _event in pending:
            await consumer.ack(entry_id)

        assert await consumer.read_pending() == []
    finally:
        await redis.aclose()


async def test_role_change_publishes_both_roles(client, user_session, admin_session, events):
    """`admin` needs no KYC, so this grants immediately — the direct path."""
    await client.patch(
        f"{API}/users/{user_session['user']['id']}/role",
        json={"role": "admin", "reason": "Nomination"},
        headers={"X-Service-Key": SERVICE_KEY},
    )

    published = await events.read_named("user.role_changed")

    assert len(published) == 1
    assert published[0]["old_role"] == "user"
    assert published[0]["new_role"] == "admin"


async def test_a_kyc_request_publishes_user_updated_not_role_changed(
    client, user_session, events,
):
    """Nothing was granted yet. Publishing `user.role_changed` here would have
    Ride switch on driver features for someone whose file is still open."""
    await client.patch(
        f"{API}/users/{user_session['user']['id']}/role",
        json={"role": "driver", "reason": "Dossier #4021"},
        headers={"X-Service-Key": SERVICE_KEY},
    )

    assert await events.read_named("user.role_changed") == []
    updated = await events.read_named("user.updated")
    assert len(updated) == 1
    assert updated[0]["changed_fields"] == ["requested_role"]


async def test_kyc_approval_publishes_role_changed(client, user_session, admin_session, events):
    user_id = user_session["user"]["id"]
    await client.patch(
        f"{API}/users/{user_id}/role",
        json={"role": "driver", "reason": "Dossier #4021"},
        headers={"X-Service-Key": SERVICE_KEY},
    )
    await client.patch(
        f"{API}/admin/users/{user_id}/kyc",
        json={"approved": True, "reason": "Permis vérifié"},
        headers=admin_session["headers"],
    )

    published = await events.read_named("user.role_changed")

    assert len(published) == 1
    assert published[0]["old_role"] == "user"
    assert published[0]["new_role"] == "driver"


async def test_suspension_publishes_user_suspended_with_reason(
    client, user_session, admin_session, events,
):
    await client.patch(
        f"{API}/admin/users/{user_session['user']['id']}/status",
        json={"status": "suspended", "reason": "Signalement fraude, ticket #883"},
        headers=admin_session["headers"],
    )

    published = await events.read_named("user.suspended")

    assert len(published) == 1
    assert published[0]["new_status"] == "suspended"
    assert published[0]["reason"] == "Signalement fraude, ticket #883"


async def test_reactivation_goes_out_as_user_updated(
    client, user_session, admin_session, events,
):
    """There is no `user.reactivated` in the contract. Publishing one would be
    an event nobody subscribes to, i.e. a silently dropped notification."""
    user_id = user_session["user"]["id"]
    await client.patch(
        f"{API}/admin/users/{user_id}/status",
        json={"status": "suspended", "reason": "Test"},
        headers=admin_session["headers"],
    )
    await client.patch(
        f"{API}/admin/users/{user_id}/status",
        json={"status": "active", "reason": "Levée de la suspension"},
        headers=admin_session["headers"],
    )

    updated = await events.read_named("user.updated")

    assert [e["new_status"] for e in updated] == ["active"]


async def test_profile_edit_publishes_changed_fields(client, user_session, events):
    await client.patch(
        f"{API}/users/me",
        json={"full_name": "Awa Koné-Traoré"},
        headers=user_session["headers"],
    )

    published = await events.read_named("user.updated")

    assert len(published) == 1
    assert published[0]["changed_fields"] == ["full_name"]


async def test_a_no_op_edit_publishes_nothing(client, user_session, events):
    """Subscribers flush their profile cache on `user.updated`. A PATCH that
    changes nothing must not make the whole ecosystem drop its caches."""
    r = await client.patch(
        f"{API}/users/me",
        json={"full_name": user_session["user"]["full_name"]},
        headers=user_session["headers"],
    )
    assert r.status_code == 200

    assert await events.read_named("user.updated") == []


async def test_the_stream_is_capped(client, otp_code, phone_factory):
    """Retention is bounded, which is exactly why `GET /users/backfill` exists.
    Asserting the cap is configured keeps an unbounded stream from silently
    becoming the memory story nobody planned for."""
    from identity_app.core.redis import create_redis_pool
    from identity_app.core.settings import settings
    from identity_app.shared_kernel.events.bus import STREAM_MAX_LEN

    await register_and_verify(client, otp_code, phone_factory())

    redis = create_redis_pool(settings.redis_url)
    try:
        length = await redis.xlen(STREAM_KEY)
        assert 0 < length <= STREAM_MAX_LEN
    finally:
        await redis.aclose()
