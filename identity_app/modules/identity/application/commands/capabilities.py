"""Commands for the global capability projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
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
        event_id: str,
        first_enabled_at: datetime | None = None,
    ) -> dict:
        _validate_names(service, capability_type)
        if await self.users.get_by_id(user_id) is None:
            observe_capability_event(operation="projection", result="user_not_found", service=service)
            raise ApiError(404, "USER_NOT_FOUND", "Aucun utilisateur trouvé avec cet identifiant.")
        current = await self.capabilities.get(user_id, service, capability_type)
        if current is not None and event_id == current.last_event_id:
            observe_capability_event(operation="projection", result="duplicate", service=service)
            return current.as_payload()
        if current is not None and projection_version < current.projection_version:
            observe_capability_event(operation="projection", result="stale_version", service=service)
            return current.as_payload()
        if current is not None and projection_version == current.projection_version:
            observe_capability_event(operation="projection", result="version_conflict", service=service)
            raise ApiError(409, "CAPABILITY_VERSION_CONFLICT", "La projection reçue a déjà cette version.")
        if first_enabled_at is not None:
            first_enabled_at = first_enabled_at.astimezone(UTC)
            if first_enabled_at > datetime.now(UTC):
                raise ApiError(422, "INVALID_FIRST_ENABLED_AT", "La date de validation ne peut pas être future.")
        capability = await self.capabilities.upsert(
            user_id=user_id,
            service=service,
            capability_type=capability_type,
            access_status="enabled" if operational_status == "validated" else None,
            operational_status=operational_status,
            status_source=service,
            actions=actions,
            projection_version=projection_version,
            last_event_id=event_id,
            first_enabled_at=first_enabled_at,
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


@dataclass
class UpdateCapabilityAccessByService:
    """Apply an access decision from the owning business module."""

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
        reason: str,
        event_id: str,
        enabled_at: datetime | None,
    ) -> dict:
        _validate_names(service, capability_type)
        if access_status not in {"enabled", "suspended", "rejected", "revoked"}:
            raise ApiError(422, "INVALID_CAPABILITY_ACCESS_STATUS", "Statut d'accès invalide.")
        if await self.users.get_by_id(user_id) is None:
            observe_capability_event(operation="access", result="user_not_found", service=service)
            raise ApiError(404, "USER_NOT_FOUND", "Aucun utilisateur trouvé avec cet identifiant.")

        current = await self.capabilities.get(user_id, service, capability_type)
        if current is not None and current.last_access_event_id == event_id:
            observe_capability_event(operation="access", result="duplicate", service=service)
            return current.as_payload()
        if enabled_at is not None:
            enabled_at = enabled_at.astimezone(UTC)
            if enabled_at > datetime.now(UTC):
                raise ApiError(422, "INVALID_ENABLED_AT", "La date de validation ne peut pas être future.")
            if access_status != "enabled":
                raise ApiError(422, "INVALID_ENABLED_AT", "enabled_at est réservé à une activation.")

        capability = await self.capabilities.upsert(
            user_id=user_id,
            service=service,
            capability_type=capability_type,
            access_status=access_status,
            status_source=service,
            first_enabled_at=enabled_at,
            last_access_event_id=event_id,
            access_reason=reason,
        )
        if current is None or current.last_access_event_id != event_id:
            await self.capabilities.record_access_change(
                user_id=user_id,
                service=service,
                capability_type=capability_type,
                from_status=current.access_status if current else None,
                to_status=access_status,
                reason=reason,
                event_id=event_id,
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
