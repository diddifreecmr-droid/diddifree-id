"""Redis client factory + FastAPI dependency.

A single `redis.asyncio.Redis` instance is shared across the app via
`app.state.redis`. The lifespan creates it on startup and closes it on
shutdown. Routes consume it through `get_redis`.

Redis serves three distinct jobs here (architecture §3): the read-side profile
cache, the OTP rate-limit counters, and the domain event bus.
"""

import logging

from redis.asyncio import Redis
from starlette.requests import Request

from identity_app.core.settings import settings

# NOTE: no `from __future__ import annotations` in this module. FastAPI resolves
# the `Request` parameter of `get_redis` from its runtime annotation; under PEP
# 563 it sees the string "Request", fails to recognise the ASGI request, and
# treats it as a required query parameter — every dependent route then 422s
# with `missing query.request`.

logger = logging.getLogger(__name__)


def create_redis_pool(url: str) -> Redis:
    """Construct the shared Redis async client.

    `decode_responses=True` makes redis-py return `str` rather than `bytes`,
    which removes encode/decode boilerplate from the cache and event-bus code
    at a negligible cost.
    """
    return Redis.from_url(url, decode_responses=True)


async def get_redis(request: Request) -> Redis:
    """FastAPI dependency — returns the shared pool from app state."""
    pool = getattr(request.app.state, "redis", None)
    if pool is None:
        # Defensive: if a test or a one-off code path calls this without the
        # lifespan having run, build a throwaway client.
        pool = create_redis_pool(settings.redis_url)
    return pool
