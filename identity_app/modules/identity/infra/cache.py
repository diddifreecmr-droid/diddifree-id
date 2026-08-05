"""Redis profile cache — the read side's shock absorber.

Only queries read it (architecture §2). Commands invalidate it after writing
rather than refreshing it: the next reader re-populates from PostgreSQL, and a
missing entry is always safe whereas a wrongly-refreshed one is not.

The TTL is a backstop, not the invalidation mechanism. Correctness comes from
explicit invalidation on every write path; the TTL only bounds how long a
mistake could survive.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis

from identity_app.modules.identity.domain.entities import User, UserLanguage, UserRole, UserStatus

logger = logging.getLogger(__name__)

PROFILE_TTL_SECONDS = 300


def _key(user_id: UUID) -> str:
    return f"identity:profile:{user_id}"


class RedisProfileCache:
    def __init__(self, redis: Redis, ttl_seconds: int = PROFILE_TTL_SECONDS) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def get_user(self, user_id: UUID) -> User | None:
        try:
            raw = await self._redis.get(_key(user_id))
        except Exception:
            # A cache outage must not take authentication down with it: log and
            # let the caller fall through to PostgreSQL.
            logger.warning("lecture du cache profil impossible pour %s", user_id, exc_info=True)
            return None
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return User(
                id=UUID(data["id"]),
                phone=data["phone"],
                email=data.get("email"),
                full_name=data["full_name"],
                language=UserLanguage(data.get("language", "fr")),
                photo_url=data.get("photo_url"),
                role=UserRole(data["role"]),
                status=UserStatus(data["status"]),
                created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
                updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
            )
        except (ValueError, KeyError):
            # Entry written by an older shape of this code. Drop it rather than
            # failing the request.
            logger.warning("entrée de cache illisible pour %s, purge", user_id, exc_info=True)
            await self.invalidate_user(user_id)
            return None

    async def set_user(self, user: User) -> None:
        payload = json.dumps(
            {
                "id": str(user.id),
                "phone": user.phone,
                "email": user.email,
                "full_name": user.full_name,
                "language": user.language.value,
                "photo_url": user.photo_url,
                "role": user.role.value,
                "status": user.status.value,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "updated_at": user.updated_at.isoformat() if user.updated_at else None,
            },
        )
        try:
            await self._redis.set(_key(user.id), payload, ex=self._ttl)
        except Exception:
            logger.warning("écriture du cache profil impossible pour %s", user.id, exc_info=True)

    async def invalidate_user(self, user_id: UUID) -> None:
        try:
            await self._redis.delete(_key(user_id))
        except Exception:
            # Worth an error rather than a warning: a failed invalidation means
            # a stale profile can be served for up to the TTL.
            logger.error("invalidation du cache profil impossible pour %s", user_id, exc_info=True)
