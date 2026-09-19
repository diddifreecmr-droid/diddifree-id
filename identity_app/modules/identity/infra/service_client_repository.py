"""Read access to registered machine clients."""

from __future__ import annotations

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
