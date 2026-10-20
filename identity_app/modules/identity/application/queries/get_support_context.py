"""The small, masked identity projection consumed by DiddiSupport."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from identity_app.core.errors import ApiError
from identity_app.modules.identity.domain.interfaces import CapabilityReadRepository, UserReadRepository


def _masked_phone(phone: str | None) -> str | None:
    if phone is None:
        return None
    if len(phone) <= 4:
        return "*" * len(phone)
    return f"{phone[:4]}{'*' * max(1, len(phone) - 6)}{phone[-2:]}"


def _masked_email(email: str | None) -> str | None:
    if email is None:
        return None
    local, separator, domain = email.partition("@")
    if not separator:
        return "***"
    visible = local[:1] if local else ""
    return f"{visible}{'*' * max(2, len(local) - len(visible))}@{domain}"


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class GetSupportUserContext:
    """Read a purpose-limited projection, never the reusable user profile."""

    users: UserReadRepository
    capabilities: CapabilityReadRepository

    async def __call__(self, user_id: UUID) -> dict:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "Aucun utilisateur trouvé avec cet identifiant.")

        capability_rows = await self.capabilities.list_for_user(user_id)
        return {
            "protocol": "diddi.context.v1",
            "resource_type": "user",
            "resource_id": str(user.id),
            "context": {
                "display_name": user.full_name,
                "phone_masked": _masked_phone(user.phone),
                "email_masked": _masked_email(user.email),
                "language": user.language.value,
                "account_status": user.status.value,
                "created_at": _timestamp(user.created_at),
                "capabilities": [
                    {
                        "service": capability.service,
                        "type": capability.capability_type,
                        "access_status": capability.access_status,
                        "operational_status": capability.operational_status,
                        "status_source": capability.status_source,
                        "updated_at": _timestamp(capability.updated_at),
                    }
                    for capability in capability_rows
                ],
            },
        }
