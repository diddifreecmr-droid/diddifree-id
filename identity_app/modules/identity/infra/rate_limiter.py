"""OTP rate limiting, in Redis (architecture §8).

Two independent counters guard `POST /auth/otp/request`:

  * per identifier — stops one phone number or e-mail address being spammed;
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

    async def seconds_until_identifier_allowed(self, identifier: str, cooldown_seconds: int) -> int:
        """Return the remaining cooldown for this identifier, 0 if a request is
        allowed now. Does not consume the allowance — call `mark_identifier_sent`
        once the OTP has actually been issued, so a request that fails
        validation later does not lock the user out."""
        if cooldown_seconds <= 0:
            return 0
        try:
            ttl = await self._redis.ttl(f"identity:otp:cooldown:{identifier}")
        except Exception:
            # Fail open. A Redis outage must not make signup impossible; the
            # per-OTP `attempts` counter in PostgreSQL still bounds abuse.
            logger.warning("rate-limit OTP indisponible (identifier), passage en fail-open", exc_info=True)
            return 0
        return max(ttl, 0)

    async def mark_identifier_sent(self, identifier: str, cooldown_seconds: int) -> None:
        if cooldown_seconds <= 0:
            return
        try:
            await self._redis.set(f"identity:otp:cooldown:{identifier}", "1", ex=cooldown_seconds)
        except Exception:
            logger.warning("impossible d'armer le cooldown OTP pour %s", identifier, exc_info=True)

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


class RedisReviewStaticOtpRateLimiter:
    """Protect the deliberately long-lived Review code from online guessing.

    Unlike a regular OTP, a Review code does not expire after five minutes.
    The limiter therefore fails closed: if Redis is unavailable, a static code
    cannot be verified rather than becoming a one-million-value password with
    no online defence.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def _failures_key(user_id: str) -> str:
        return f"identity:review-static-otp:failures:{user_id}"

    @staticmethod
    def _lock_key(user_id: str) -> str:
        return f"identity:review-static-otp:lock:{user_id}"

    async def lock_seconds_remaining(self, user_id: str) -> int:
        try:
            return max(await self._redis.ttl(self._lock_key(user_id)), 0)
        except Exception as exc:
            logger.error("limiteur Review OTP indisponible", exc_info=True)
            raise RuntimeError("REVIEW_OTP_RATE_LIMIT_UNAVAILABLE") from exc

    async def register_failure(
        self,
        user_id: str,
        *,
        max_attempts: int,
        lock_seconds: int,
    ) -> tuple[int, int]:
        """Return `(attempts, lock_seconds_remaining)` after one failure."""
        try:
            failures_key = self._failures_key(user_id)
            attempts = await self._redis.incr(failures_key)
            if attempts == 1:
                await self._redis.expire(failures_key, lock_seconds)
            if attempts >= max_attempts:
                await self._redis.set(self._lock_key(user_id), "1", ex=lock_seconds)
                await self._redis.delete(failures_key)
                return attempts, lock_seconds
            return attempts, 0
        except Exception as exc:
            logger.error("limiteur Review OTP indisponible", exc_info=True)
            raise RuntimeError("REVIEW_OTP_RATE_LIMIT_UNAVAILABLE") from exc

    async def reset_failures(self, user_id: str) -> None:
        try:
            await self._redis.delete(self._failures_key(user_id))
        except Exception as exc:
            logger.error("limiteur Review OTP indisponible", exc_info=True)
            raise RuntimeError("REVIEW_OTP_RATE_LIMIT_UNAVAILABLE") from exc
