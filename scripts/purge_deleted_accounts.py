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
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, or_, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from identity_app.core.database import async_session_factory, engine
from identity_app.core.logging import configure_logging, reset_request_id, set_request_id, shutdown_otel_logging
from identity_app.core.metrics import configure_metrics, observe_job
from identity_app.core.redis import create_redis_pool
from identity_app.core.settings import settings
from identity_app.core.tracing import configure_tracing, scheduled_job_trace, shutdown_tracing
from identity_app.core.worker_health import record_worker_heartbeat
from identity_app.modules.identity.domain.events import UserDeleted
from identity_app.modules.identity.infra import models as orm
from identity_app.modules.identity.infra.cache import RedisProfileCache
from identity_app.shared_kernel.events.bus import RedisEventPublisher

logger = logging.getLogger("account_purger")


async def purge_due_accounts(*, redis=None) -> int:  # noqa: ANN001
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

    owns_redis = redis is None
    redis = redis or create_redis_pool(settings.redis_url)
    try:
        cache = RedisProfileCache(redis)
        for event in deleted:
            await cache.invalidate_user(event.user_id)
        publisher = RedisEventPublisher(redis)
        for event in deleted:
            await publisher.publish(event)
    finally:
        if owns_redis:
            await redis.aclose()
    return len(deleted)


async def main() -> None:
    configure_logging(settings.log_level, component="account-purger")
    configure_metrics(component="account-purger")
    configure_tracing()
    redis = create_redis_pool(settings.redis_url)
    started_at = time.perf_counter()
    execution_id: str | None = None
    request_token = None
    try:
        with scheduled_job_trace("account-purger") as execution_id:
            request_token = set_request_id(f"job_{execution_id}")
            count = await purge_due_accounts(redis=redis)
        duration_seconds = time.perf_counter() - started_at
        observe_job(job_type="account-purger", outcome="success", duration_seconds=duration_seconds)
        await record_worker_heartbeat(
            redis,
            worker="account-purger",
            status="ok",
            details={
                "anonymized_accounts": count,
                "duration_seconds": round(duration_seconds, 3),
                "execution_id": execution_id,
            },
        )
        logger.info(
            "account_purger terminé : %s compte(s) anonymisé(s)",
            count,
            extra={"event": "worker.account_purger.completed"},
        )
    except Exception:
        observe_job(
            job_type="account-purger",
            outcome="error",
            duration_seconds=time.perf_counter() - started_at,
        )
        try:
            await record_worker_heartbeat(redis, worker="account-purger", status="error")
        except Exception:
            logger.warning(
                "account_purger heartbeat impossible",
                exc_info=True,
                extra={"event": "worker.account_purger.heartbeat_failed"},
            )
        logger.exception("account_purger failed", extra={"event": "worker.account_purger.failed"})
        raise
    finally:
        if request_token is not None:
            reset_request_id(request_token)
        await redis.aclose()
        await engine.dispose()
        shutdown_tracing()
        shutdown_otel_logging()


if __name__ == "__main__":
    asyncio.run(main())
