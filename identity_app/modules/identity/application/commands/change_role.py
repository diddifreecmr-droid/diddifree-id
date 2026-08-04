"""Change a platform-owned Auth role.

Business roles such as ``driver`` and ``merchant`` belong to their owning
module. This command remains for the small set of ecosystem-wide roles and
returns an explicit error for legacy module-role requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from identity_app.core.errors import ApiError
from identity_app.modules.identity.application.payloads import profile_payload
from identity_app.modules.identity.domain.entities import (
    MODULE_OWNED_ROLE_NAMES,
    UserRole,
    UserRoleChange,
)
from identity_app.modules.identity.domain.events import UserRoleChanged
from identity_app.modules.identity.domain.interfaces import (
    EventPublisher,
    ProfileCache,
    UserWriteRepository,
)


@dataclass
class ChangeRole:
    users: UserWriteRepository
    events: EventPublisher
    cache: ProfileCache

    async def __call__(
        self,
        *,
        user_id: UUID,
        role: str,
        reason: str | None = None,
        changed_by: UUID | None = None,
    ) -> dict:
        if role in MODULE_OWNED_ROLE_NAMES:
            raise ApiError(
                409,
                "ROLE_OWNED_BY_MODULE",
                f"Le rôle {role!r} appartient à son module métier et ne peut pas être attribué par Auth.",
                {"role": role, "owner": "diddi-go" if role == "driver" else "module métier"},
            )

        try:
            target_role = UserRole(role)
        except ValueError as exc:
            accepted = [UserRole.USER.value, UserRole.ADMIN.value]
            raise ApiError(
                422,
                "INVALID_ROLE",
                f"Rôle inconnu : {role!r}. Valeurs acceptées : {', '.join(accepted)}.",
                {"field": "role", "accepted": accepted},
            ) from exc

        user = await self.users.find_by_id(user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "Aucun utilisateur trouvé avec cet identifiant.")

        if user.role == target_role:
            return profile_payload(user)

        old_role = user.role
        user.role = target_role
        # Clear an old pending request while migrating accounts created by the
        # previous Auth-owned KYC flow. New requests cannot be created anymore.
        user.requested_role = None
        now = datetime.now(UTC)
        await self.users.save(user)
        await self.users.record_role_change(
            UserRoleChange(
                id=UserRoleChange.new_id(),
                user_id=user.id,
                from_role=old_role,
                to_role=target_role,
                reason=reason,
                changed_by=changed_by,
                changed_at=now,
            ),
        )
        await self.users.commit()
        await self.cache.invalidate_user(user.id)
        await self.events.publish(
            UserRoleChanged(
                user_id=user.id,
                phone=user.phone,
                role=target_role.value,
                old_role=old_role.value,
                new_role=target_role.value,
            ),
        )
        return profile_payload(user)
