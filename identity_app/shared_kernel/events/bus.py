"""Event bus — Redis Streams.

The contract (§4) leaves the transport open, to be settled with the Infra team.
It is settled here as **Redis Streams**, not Pub/Sub and not Kafka, for a reason
worth writing down because it will be re-litigated:

  * Pub/Sub was the starting point and does not persist. A subscriber that is
    down when an event fires never learns of it. Tolerable for cache
    invalidation; not tolerable for `user.registered`, which is what makes
    Wallet create an account — a missed one leaves a user with no wallet and
    nothing to notice it by.
  * Streams fix exactly that, on the Redis already deployed. Entries persist,
    consumer groups track per-module progress, and an entry stays pending until
    the module acknowledges it — so a consumer that crashes mid-handling gets
    the event again instead of losing it.
  * Kafka would also fix it, and buys partitioning, long retention and replay
    at arbitrary depth. It also brings a cluster to operate, monitor and keep
    alive. For twelve modules of which most are unwritten, that is a real cost
    against a problem Streams already solves. The day event volume, ordering
    guarantees across partitions, or independent replay of months of history
    matter, this file is what changes — the rest of the service does not know
    which transport is underneath.

**Retention is bounded** (`STREAM_MAX_LEN`). A module offline longer than that
window cannot catch up from the stream and must call `GET /users/backfill`.
That endpoint exists precisely because no broker choice removes the need for it.

Ordering: one stream for every event type, so a user's `role_changed` can never
be delivered after the `suspended` that followed it. Consumers filter by name.
"""

from __future__ import annotations

import json
import logging

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from identity_app.modules.identity.domain.events import DomainEvent

logger = logging.getLogger(__name__)

#: Single stream, single ordering. Consumers read everything and skip what they
#: do not care about — cheaper than reasoning about cross-stream ordering.
STREAM_KEY = "identity.events"

#: Approximate cap on retained entries. At DiddiFree's expected write rate
#: (registrations, role decisions, suspensions — not per-transaction traffic)
#: this is comfortably weeks of history, which is the window a module has to
#: come back before it needs the backfill route instead.
STREAM_MAX_LEN = 100_000


class RedisEventPublisher:
    def __init__(self, redis: Redis, stream: str = STREAM_KEY) -> None:
        self._redis = redis
        self._stream = stream

    async def publish(self, event: DomainEvent) -> None:
        payload = event.to_payload()
        try:
            entry_id = await self._redis.xadd(
                self._stream,
                {"event": event.name, "payload": json.dumps(payload)},
                maxlen=STREAM_MAX_LEN,
                approximate=True,
            )
            logger.info(
                "événement publié : %s user_id=%s (entry=%s)", event.name, event.user_id, entry_id,
            )
        except Exception:
            # Never let a bus failure roll back a completed write. The user IS
            # registered; the account exists. Failing the HTTP call here would
            # tell the client the opposite of what the database now holds.
            #
            # This is the residual gap that no transport closes on its own: the
            # write landed and the event did not. `GET /users/backfill` is how a
            # module recovers from it.
            logger.error("publication de l'événement %s impossible", event.name, exc_info=True)


class NullEventPublisher:
    """No-op publisher, for tests that do not care about the bus."""

    async def publish(self, event: DomainEvent) -> None:  # noqa: ARG002
        return None


class RedisEventConsumer:
    """Consumer-side helper, meant to be copied into a subscribing module.

    Typical loop in, say, Wallet::

        consumer = RedisEventConsumer(redis, group="diddi-wallet", name="worker-1")
        await consumer.ensure_group(from_beginning=True)

        # After a restart, finish what was delivered but never acknowledged.
        for entry_id, event in await consumer.read_pending():
            await handle(event)
            await consumer.ack(entry_id)

        while True:
            for entry_id, event in await consumer.read():
                await handle(event)
                await consumer.ack(entry_id)

    Acknowledge **after** handling, never before: the gap between the two is
    what turns a crash into a redelivery instead of a lost event. Handlers must
    therefore be idempotent — at-least-once is what this gives you, and exactly
    -once is not on offer from any broker without the handler's cooperation.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        group: str,
        name: str,
        stream: str = STREAM_KEY,
    ) -> None:
        self._redis = redis
        self._stream = stream
        self._group = group
        self._name = name

    async def ensure_group(self, *, from_beginning: bool = True) -> None:
        """Create the consumer group if it does not exist.

        `from_beginning` replays everything still retained — what a module wants
        the first time it subscribes. `False` starts at the tail, for a group
        that only cares about what happens next.
        """
        start_id = "0" if from_beginning else "$"
        try:
            await self._redis.xgroup_create(
                self._stream, self._group, id=start_id, mkstream=True,
            )
            logger.info("groupe de consommateurs %r créé sur %s", self._group, self._stream)
        except ResponseError as exc:
            # Already there — the normal case on every restart after the first.
            if "BUSYGROUP" not in str(exc):
                raise

    async def read(self, *, count: int = 10, block_ms: int = 5000) -> list[tuple[str, dict]]:
        """Fetch entries never delivered to this group."""
        response = await self._redis.xreadgroup(
            self._group,
            self._name,
            {self._stream: ">"},
            count=count,
            block=block_ms,
        )
        return _decode(response)

    async def read_pending(self, *, count: int = 100) -> list[tuple[str, dict]]:
        """Fetch entries delivered to *this consumer* but never acknowledged.

        Call it on startup: these are the events that were in flight when the
        process last died.
        """
        response = await self._redis.xreadgroup(
            self._group,
            self._name,
            {self._stream: "0"},
            count=count,
        )
        return _decode(response)

    async def ack(self, entry_id: str) -> None:
        await self._redis.xack(self._stream, self._group, entry_id)


def _decode(response) -> list[tuple[str, dict]]:  # noqa: ANN001 — redis-py's nested shape
    events: list[tuple[str, dict]] = []
    for _stream, entries in response or []:
        for entry_id, fields in entries:
            try:
                events.append((entry_id, json.loads(fields["payload"])))
            except (KeyError, ValueError):
                # A malformed entry must not stall the consumer on every poll.
                # Log it and move on; it stays in the pending list for a human.
                logger.error("entrée d'événement illisible : %s", entry_id, exc_info=True)
    return events
