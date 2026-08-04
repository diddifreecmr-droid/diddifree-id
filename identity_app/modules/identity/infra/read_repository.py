"""Read side — the same tables, queried for reading only.

This file is the seam the architecture doc points at (§1): the day a read
replica becomes necessary, this class takes a session bound to the replica and
nothing above it changes. That is only true as long as it stays free of writes,
so it never flushes, never commits, and holds no transaction open.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from identity_app.modules.identity.domain.entities import User, UserLanguage, UserRole, UserStatus
from identity_app.modules.identity.infra import models as orm

# Ceiling on `page_size` so a single admin request cannot ask for the whole
# table and pin a connection for the duration.
MAX_PAGE_SIZE = 100


def _to_domain(row: orm.UserModel) -> User:
    return User(
        id=row.id,
        phone=row.phone,
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
