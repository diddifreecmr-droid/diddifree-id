"""Commands for the global capability projection."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from identity_app.core.errors import ApiError
from identity_app.core.metrics import observe_capability_event
from identity_app.modules.identity.domain.capabilities import CAPABILITY_ACCESS_STATUSES
from identity_app.modules.identity.domain.events import CapabilityRequested, CapabilityStatusUpdated
from identity_app.modules.identity.domain.interfaces import (
    CapabilityWriteRepository,
    EventPublisher,
    UserReadRepository,
)


def _validate_names(service: str, capability_type: str) -> None:
    if not service.strip() or not capability_type.strip():
        raise ApiError(422, "INVALID_CAPABILITY", "Le service et le type de capacité sont requis.")


@dataclass
class RequestCapability:
    capabilities: CapabilityWriteRepository
    events: EventPublisher
    users: UserReadRepository

    async def __call__(self, *, user_id: UUID, service: str, capability_type: str) -> dict:
        _validate_names(service, capability_type)
        if await self.users.get_by_id(user_id) is None:
            observe_capability_event(operation="request", result="user_not_found", service=service)
            raise ApiError(404, "USER_NOT_FOUND", "Aucun utilisateur trouvé avec cet identifiant.")
        current = await self.capabilities.get(user_id, service, capability_type)
        if current is not None:
            observe_capability_event(operation="request", result="already_exists", service=service)
            return current.as_payload()
        capability = await self.capabilities.upsert(
            user_id=user_id,
            service=service,
            capability_type=capability_type,
            access_status="requested",
            operational_status="unknown" if current is None else None,
            status_source="diddifreeid",
        )
        await self.capabilities.commit()
        await self.events.publish(
            CapabilityRequested(
                user_id=user_id,
                phone=None,
                role="user",
                service=service,
                capability_type=capability_type,
            ),
        )
        observe_capability_event(operation="request", result="created", service=service)
        return capability.as_payload()


@dataclass
class UpdateCapabilityProjection:
    capabilities: CapabilityWriteRepository
    events: EventPublisher
    users: UserReadRepository

    async def __call__(
        self,
        *,
        user_id: UUID,
        service: str,
        capability_type: str,
        operational_status: str,
        actions: list[str],
        projection_version: int,
        event_id: str | None,
    ) -> dict:
        _validate_names(service, capability_type)
        if await self.users.get_by_id(user_id) is None:
            observe_capability_event(operation="projection", result="user_not_found", service=service)
            raise ApiError(404, "USER_NOT_FOUND", "Aucun utilisateur trouvé avec cet identifiant.")
        current = await self.capabilities.get(user_id, service, capability_type)
        if current is not None and projection_version < current.projection_version:
            observe_capability_event(operation="projection", result="stale_version", service=service)
            return current.as_payload()
        if (
            current is not None
            and projection_version == current.projection_version
            and event_id is not None
            and event_id == current.last_event_id
        ):
            observe_capability_event(operation="projection", result="duplicate", service=service)
            return current.as_payload()
        if current is not None and projection_version == current.projection_version:
            observe_capability_event(operation="projection", result="version_conflict", service=service)
            raise ApiError(409, "CAPABILITY_VERSION_CONFLICT", "La projection reçue a déjà cette version.")
        capability = await self.capabilities.upsert(
            user_id=user_id,
            service=service,
            capability_type=capability_type,
            operational_status=operational_status,
            status_source=service,
            actions=actions,
            projection_version=projection_version,
            last_event_id=event_id,
        )
        await self.capabilities.commit()
        await self.events.publish(
            CapabilityStatusUpdated(
                user_id=user_id,
                phone=None,
                role="user",
                service=service,
                capability_type=capability_type,
                access_status=capability.access_status,
                operational_status=capability.operational_status,
                status_source=capability.status_source,
                projection_version=capability.projection_version,
            ),
        )
        observe_capability_event(operation="projection", result="updated", service=service)
        return capability.as_payload()


@dataclass
class UpdateCapabilityAccess:
    capabilities: CapabilityWriteRepository
    events: EventPublisher
    users: UserReadRepository

    async def __call__(
        self,
        *,
        user_id: UUID,
        service: str,
        capability_type: str,
        access_status: str,
    ) -> dict:
        _validate_names(service, capability_type)
        if access_status not in CAPABILITY_ACCESS_STATUSES:
            raise ApiError(
                422,
                "INVALID_CAPABILITY_ACCESS_STATUS",
                "Statut d'accès invalide.",
                {"accepted": sorted(CAPABILITY_ACCESS_STATUSES)},
            )
        if await self.users.get_by_id(user_id) is None:
            observe_capability_event(operation="access", result="user_not_found", service=service)
            raise ApiError(404, "USER_NOT_FOUND", "Aucun utilisateur trouvé avec cet identifiant.")
        current = await self.capabilities.get(user_id, service, capability_type)
        capability = await self.capabilities.upsert(
            user_id=user_id,
            service=service,
            capability_type=capability_type,
            access_status=access_status,
            projection_version=(current.projection_version + 1) if current else 1,
            status_source="diddifreeid",
        )
        await self.capabilities.commit()
        await self.events.publish(
            CapabilityStatusUpdated(
                user_id=user_id,
                phone=None,
                role="user",
                service=service,
                capability_type=capability_type,
                access_status=capability.access_status,
                operational_status=capability.operational_status,
                status_source=capability.status_source,
                projection_version=capability.projection_version,
            ),
        )
        observe_capability_event(operation="access", result="updated", service=service)
        return capability.as_payload()
