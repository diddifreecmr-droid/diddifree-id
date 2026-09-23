"""Read side — the same tables, queried for reading only.

This file is the seam the architecture doc points at (§1): the day a read
replica becomes necessary, this class takes a session bound to the replica and
nothing above it changes. That is only true as long as it stays free of writes,
so it never flushes, never commits, and holds no transaction open.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from identity_app.modules.identity.domain.capabilities import Capability
from identity_app.modules.identity.domain.entities import User, UserLanguage, UserRole, UserStatus
from identity_app.modules.identity.infra import models as orm

# Ceiling on `page_size` so a single admin request cannot ask for the whole
# table and pin a connection for the duration.
MAX_PAGE_SIZE = 100


def _to_domain(row: orm.UserModel) -> User:
    return User(
        id=row.id,
        phone=row.phone,
        email=row.email,
        full_name=row.full_name,
        language=UserLanguage(row.language),
        photo_url=row.photo_url,
        password_hash=row.password_hash,
        role=UserRole(row.role),
        status=UserStatus(row.status),
        requested_role=UserRole(row.requested_role) if row.requested_role else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyUserReadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self._session.execute(
            select(orm.UserModel).where(orm.UserModel.id == user_id),
        )
        row = result.scalar_one_or_none()
        return None if row is None else _to_domain(row)

    async def get_by_phone(self, phone: str) -> User | None:
        result = await self._session.execute(
            select(orm.UserModel).where(orm.UserModel.phone == phone),
        )
        row = result.scalar_one_or_none()
        return None if row is None else _to_domain(row)

    async def list_users(
        self,
        *,
        role: str | None = None,
        status: str | None = None,
        pending_kyc: bool = False,
        created_since: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[User], int]:
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)

        filters = []
        if role is not None:
            filters.append(orm.UserModel.role == role)
        if status is not None:
            filters.append(orm.UserModel.status == status)
        if pending_kyc:
            filters.append(orm.UserModel.requested_role.is_not(None))
        if created_since is not None:
            filters.append(orm.UserModel.created_at >= created_since)

        total = await self._session.scalar(
            select(func.count()).select_from(orm.UserModel).where(*filters),
        )

        # `created_at` alone is not a total order — several users created in the
        # same transaction share a timestamp and could then appear on two pages,
        # or on none. `id` breaks the tie deterministically.
        #
        # Backfill reads ascending: a module replaying history wants the oldest
        # account first, so that interrupting the walk and resuming from the last
        # `created_at` it saw does not skip anyone.
        order = (
            (orm.UserModel.created_at.asc(), orm.UserModel.id.asc())
            if created_since is not None
            else (orm.UserModel.created_at.desc(), orm.UserModel.id.desc())
        )

        result = await self._session.execute(
            select(orm.UserModel)
            .where(*filters)
            .order_by(*order)
            .offset((page - 1) * page_size)
            .limit(page_size),
        )
        return [_to_domain(row) for row in result.scalars()], int(total or 0)

    async def identity_summary(
        self,
        *,
        day_start: datetime,
        day_end: datetime,
        activity_day: date,
        activity_month_start: date,
        activity_month_end: date,
    ) -> dict[str, int]:
        """Return aggregate identity metrics without exposing user records."""

        total = await self._session.scalar(
            select(func.count()).select_from(orm.UserModel),
        )
        registered = await self._session.scalar(
            select(func.count()).select_from(orm.UserModel).where(
                orm.UserModel.created_at >= day_start,
                orm.UserModel.created_at < day_end,
            ),
        )
        verified = await self._session.scalar(
            select(func.count()).select_from(orm.UserModel).where(
                orm.UserModel.status != UserStatus.PENDING_VERIFICATION.value,
            ),
        )
        active = await self._session.scalar(
            select(func.count()).select_from(orm.UserModel).where(
                orm.UserModel.status == UserStatus.ACTIVE.value,
            ),
        )
        daily_active = await self._session.scalar(
            select(func.count()).select_from(orm.UserActivityDailyModel).where(
                orm.UserActivityDailyModel.activity_date == activity_day,
            ),
        )
        monthly_active = await self._session.scalar(
            select(func.count(func.distinct(orm.UserActivityDailyModel.user_id))).where(
                orm.UserActivityDailyModel.activity_date >= activity_month_start,
                orm.UserActivityDailyModel.activity_date <= activity_month_end,
            ),
        )
        return {
            "users_total": int(total or 0),
            "users_registered": int(registered or 0),
            "users_verified": int(verified or 0),
            "users_active": int(active or 0),
            "daily_active_users": int(daily_active or 0),
            "monthly_active_users": int(monthly_active or 0),
        }


def _capability_to_domain(row: orm.UserCapabilityModel) -> Capability:
    return Capability(
        user_id=row.user_id,
        service=row.service,
        capability_type=row.capability_type,
        access_status=row.access_status,
        operational_status=row.operational_status,
        status_source=row.status_source,
        actions=tuple(row.actions or ()),
        projection_version=row.projection_version,
        last_event_id=row.last_event_id,
        updated_at=row.updated_at,
        created_at=row.created_at,
    )


class SqlAlchemyCapabilityReadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: UUID) -> list[Capability]:
        result = await self._session.execute(
            select(orm.UserCapabilityModel)
            .where(orm.UserCapabilityModel.user_id == user_id)
            .order_by(orm.UserCapabilityModel.service, orm.UserCapabilityModel.capability_type)
            .execution_options(populate_existing=True),
        )
        return [_capability_to_domain(row) for row in result.scalars()]
