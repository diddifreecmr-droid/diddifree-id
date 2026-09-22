"""Read access to registered machine clients."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from identity_app.modules.identity.domain.service_client import ServiceClient
from identity_app.modules.identity.infra import models as orm


class SqlAlchemyServiceClientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_client_id(self, client_id: str) -> ServiceClient | None:
        result = await self._session.execute(
            select(orm.ServiceClientModel)
            .where(orm.ServiceClientModel.client_id == client_id)
            .execution_options(populate_existing=True),
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return _to_domain(row)

    async def list_clients(self) -> list[ServiceClient]:
        result = await self._session.execute(
            select(orm.ServiceClientModel).order_by(
                orm.ServiceClientModel.service_name,
                orm.ServiceClientModel.environment,
                orm.ServiceClientModel.client_id,
            ),
        )
        return [_to_domain(row) for row in result.scalars().all()]

    async def update_client(
        self,
        client_id: str,
        *,
        allowed_audiences: list[str] | None = None,
        allowed_scopes: list[str] | None = None,
        active: bool | None = None,
    ) -> ServiceClient | None:
        result = await self._session.execute(
            select(orm.ServiceClientModel)
            .where(orm.ServiceClientModel.client_id == client_id)
            .execution_options(populate_existing=True),
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None

        if allowed_audiences is not None:
            row.allowed_audiences = allowed_audiences
        if allowed_scopes is not None:
            row.allowed_scopes = allowed_scopes
        if active is not None:
            row.active = active
            row.revoked_at = None if active else datetime.now(UTC)
        await self._session.flush()
        return _to_domain(row)


def _to_domain(row: orm.ServiceClientModel) -> ServiceClient:
    return ServiceClient(
        id=row.id,
        client_id=row.client_id,
        service_name=row.service_name,
        environment=row.environment,
        secret_hash=row.secret_hash,
        allowed_audiences=tuple(row.allowed_audiences or ()),
        allowed_scopes=tuple(row.allowed_scopes or ()),
        active=row.active,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )
