"""OTP rate limiting, in Redis (architecture §8).

Two independent counters guard `POST /auth/otp/request`:

  * per phone — stops one number being spammed with SMS, which costs real money
    and lands on a real person's handset;
  * per IP — stops one caller enumerating many numbers from a single source.

Redis rather than the database because these keys expire on their own and are
written on every attempt, including the ones that are rejected. Putting that
write volume in PostgreSQL would mean a transaction per rejected request.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Per-IP allowance over the same window as the per-phone one. Higher than the
# phone limit on purpose: a shared connection (an office, a mobile carrier NAT)
# legitimately produces several signups in a row.
IP_REQUESTS_PER_WINDOW = 10
IP_WINDOW_SECONDS = 600


class RedisOtpRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def seconds_until_phone_allowed(self, phone: str, cooldown_seconds: int) -> int:
        """Return the remaining cooldown for this phone, 0 if a request is
        allowed now. Does not consume the allowance — call `mark_phone_sent`
        once the OTP has actually been issued, so a request that fails
        validation later does not lock the user out."""
        if cooldown_seconds <= 0:
            return 0
        try:
            ttl = await self._redis.ttl(f"identity:otp:cooldown:{phone}")
        except Exception:
            # Fail open. A Redis outage must not make signup impossible; the
            # per-OTP `attempts` counter in PostgreSQL still bounds abuse.
            logger.warning("rate-limit OTP indisponible (phone), passage en fail-open", exc_info=True)
            return 0
        return max(ttl, 0)

    async def mark_phone_sent(self, phone: str, cooldown_seconds: int) -> None:
        if cooldown_seconds <= 0:
            return
        try:
            await self._redis.set(f"identity:otp:cooldown:{phone}", "1", ex=cooldown_seconds)
        except Exception:
            logger.warning("impossible d'armer le cooldown OTP pour %s", phone, exc_info=True)

    async def hit_ip(self, ip: str) -> bool:
        """Count one request from `ip`. Returns False when over the allowance."""
        if not ip:
            return True
        key = f"identity:otp:ip:{ip}"
        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, IP_WINDOW_SECONDS)
            return count <= IP_REQUESTS_PER_WINDOW
        except Exception:
            logger.warning("rate-limit OTP indisponible (ip), passage en fail-open", exc_info=True)
            return True
