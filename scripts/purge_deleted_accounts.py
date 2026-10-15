"""Anonymise accounts whose 30-day restoration window has elapsed.

The command is safe to run repeatedly and concurrently. It keeps the stable
user UUID and status history as tombstones, removes direct identifiers and
publishes ``user.deleted`` so each business module can erase its own data.

The Portainer stack runs this once per hour. It can also be run manually:

    python scripts/purge_deleted_accounts.py
"""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, or_, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from identity_app.core.database import async_session_factory, engine
from identity_app.core.redis import create_redis_pool
from identity_app.core.settings import settings
from identity_app.modules.identity.domain.events import UserDeleted
from identity_app.modules.identity.infra import models as orm
from identity_app.modules.identity.infra.cache import RedisProfileCache
from identity_app.shared_kernel.events.bus import RedisEventPublisher

logger = logging.getLogger("account_purger")


async def purge_due_accounts() -> int:
    now = datetime.now(UTC)
    deleted: list[UserDeleted] = []
    async with async_session_factory() as session, session.begin():
        result = await session.execute(
            select(orm.UserModel)
            .where(
                orm.UserModel.status == "deletion_pending",
                orm.UserModel.deletion_scheduled_for <= now,
            )
            .with_for_update(skip_locked=True),
        )
        rows = list(result.scalars())
        for row in rows:
            old_phone, old_email = row.phone, row.email
            identifier_filters = []
            if old_phone is not None:
                identifier_filters.append(orm.OtpCodeModel.phone == old_phone)
            if old_email is not None:
                identifier_filters.append(orm.OtpCodeModel.email == old_email)
            if identifier_filters:
                await session.execute(delete(orm.OtpCodeModel).where(or_(*identifier_filters)))
            await session.execute(
                delete(orm.ContactLinkChallengeModel).where(
                    orm.ContactLinkChallengeModel.user_id == row.id,
                ),
            )
            await session.execute(
                delete(orm.RefreshTokenModel).where(orm.RefreshTokenModel.user_id == row.id),
            )
            await session.execute(
                delete(orm.UserActivityDailyModel).where(orm.UserActivityDailyModel.user_id == row.id),
            )
            await session.execute(
                delete(orm.UserCapabilityModel).where(orm.UserCapabilityModel.user_id == row.id),
            )

            row.phone = None
            row.email = None
            row.telegram_user_id = None
            row.telegram_chat_id = None
            row.full_name = None
            row.photo_url = None
            row.password_hash = None
            row.role = "user"
            row.status = "deleted"
            row.requested_role = None
            row.deletion_scheduled_for = None
            row.deletion_previous_status = None
            row.deleted_at = now
            row.updated_at = now
            session.add(
                orm.UserStatusHistoryModel(
                    user_id=row.id,
                    from_status="deletion_pending",
                    to_status="deleted",
                    reason="Fin de la période de restauration de 30 jours",
                    changed_by=None,
                    changed_at=now,
                ),
            )
            deleted.append(
                UserDeleted(
                    user_id=row.id,
                    phone=None,
                    role="user",
                    deleted_at=now,
                ),
            )

    if not deleted:
        return 0

    redis = create_redis_pool(settings.redis_url)
    try:
        cache = RedisProfileCache(redis)
        for event in deleted:
            await cache.invalidate_user(event.user_id)
        publisher = RedisEventPublisher(redis)
        for event in deleted:
            await publisher.publish(event)
    finally:
        await redis.aclose()
    return len(deleted)


async def main() -> None:
    count = await purge_due_accounts()
    logger.info("account_purger terminé : %s compte(s) anonymisé(s)", count)
    await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
