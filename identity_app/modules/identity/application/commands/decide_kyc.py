"""`PATCH /admin/users/{user_id}/kyc` — resolve a pending role request.

The other half of the gate moved here from DiddiGo (architecture §7.5). A
decision either grants the requested role, or refuses it; both are written to
`identity.user_role_history`, because "why is this person a driver" and "why was
this person refused" are equally likely to be asked six months later.

A refusal is not a punishment: the account goes back to being an ordinary,
fully usable `user`. Only the requested role is denied.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from identity_app.core.errors import ApiError
from identity_app.modules.identity.application.payloads import profile_payload
from identity_app.modules.identity.domain.entities import (
    MODULE_OWNED_ROLE_NAMES,
    UserRoleChange,
    UserStatus,
    UserStatusChange,
)
from identity_app.modules.identity.domain.events import UserRoleChanged, UserUpdated
from identity_app.modules.identity.domain.interfaces import (
    EventPublisher,
    ProfileCache,
    UserWriteRepository,
)


@dataclass
class DecideKyc:
    users: UserWriteRepository
    events: EventPublisher
    cache: ProfileCache

    async def __call__(
        self,
        *,
        user_id: UUID,
        approved: bool,
        reason: str | None,
        decided_by: UUID | None,
    ) -> dict:
        user = await self.users.find_by_id(user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "Aucun utilisateur trouvé avec cet identifiant.")

        requested = user.requested_role
        if requested is None:
            raise ApiError(
                409,
                "NO_KYC_PENDING",
                "Aucune demande de rôle en attente pour cet utilisateur.",
            )

        if requested.value in MODULE_OWNED_ROLE_NAMES:
            raise ApiError(
                410,
                "KYC_MOVED_TO_MODULE",
                "La qualification KYC et les rôles métier sont gérés par leur module propriétaire.",
                {"role": requested.value},
            )

        now = datetime.now(UTC)
        previous_role = user.role
        previous_status = user.status

        user.requested_role = None
        if approved:
            user.role = requested

        # An account parked in `pending_kyc` has never been usable — it was
        # routed there instead of `active` at OTP verification. Whatever the
        # decision, it now becomes a normal account: approved as the new role,
        # refused as the plain user it already was.
        if previous_status == UserStatus.PENDING_KYC:
            user.status = UserStatus.ACTIVE

        await self.users.save(user)

        if user.status != previous_status:
            await self.users.record_status_change(
                UserStatusChange(
                    id=UserStatusChange.new_id(),
                    user_id=user.id,
                    from_status=previous_status,
                    to_status=user.status,
                    reason=reason or ("Décision KYC : accordé" if approved else "Décision KYC : refusé"),
                    changed_by=decided_by,
                    changed_at=now,
                ),
            )

        await self.users.record_role_change(
            UserRoleChange(
                id=UserRoleChange.new_id(),
                user_id=user.id,
                from_role=previous_role,
                # NULL marks a refusal: no role was granted.
                to_role=requested if approved else None,
                requested_role=requested,
                reason=reason,
                changed_by=decided_by,
                changed_at=now,
            ),
        )
        await self.users.commit()
        await self.cache.invalidate_user(user.id)

        if approved:
            # The event Ride is actually waiting for, to switch on its driver
            # features (contract §4).
            await self.events.publish(
                UserRoleChanged(
                    user_id=user.id,
                    phone=user.phone,
                    role=user.role.value,
                    old_role=previous_role.value,
                    new_role=user.role.value,
                ),
            )
        else:
            await self.events.publish(
                UserUpdated(
                    user_id=user.id,
                    phone=user.phone,
                    role=user.role.value,
                    changed_fields=["requested_role"],
                ),
            )

        return profile_payload(user)
