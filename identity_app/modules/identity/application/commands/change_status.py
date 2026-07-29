"""`PATCH /admin/users/{user_id}/status` — suspend or reinstate an account."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from identity_app.core.errors import ApiError
from identity_app.modules.identity.application.payloads import profile_payload
from identity_app.modules.identity.domain.entities import (
    ADMIN_SETTABLE_STATUSES,
    UserStatus,
    UserStatusChange,
    can_transition,
)
from identity_app.modules.identity.domain.events import UserStatusChanged
from identity_app.modules.identity.domain.interfaces import (
    EventPublisher,
    ProfileCache,
    RefreshTokenRepository,
    UserWriteRepository,
)


@dataclass
class ChangeStatus:
    users: UserWriteRepository
    refresh_tokens: RefreshTokenRepository
    events: EventPublisher
    cache: ProfileCache

    async def __call__(
        self,
        *,
        user_id: UUID,
        status: str,
        reason: str | None,
        changed_by: UUID | None,
    ) -> dict:
        try:
            target = UserStatus(status)
        except ValueError as exc:
            raise ApiError(
                422,
                "INVALID_STATUS",
                f"Statut inconnu : {status!r}. Valeurs acceptées : "
                f"{', '.join(s.value for s in UserStatus)}.",
                {"field": "status"},
            ) from exc

        if target not in ADMIN_SETTABLE_STATUSES:
            # `pending_kyc` in particular: it is reached through the KYC flow, and
            # setting it by hand on a live account would cut that person off from
            # every module in the ecosystem over a single module's review.
            raise ApiError(
                422,
                "STATUS_NOT_SETTABLE",
                f"Le statut {target.value!r} n'est pas modifiable par cette route. "
                f"Valeurs acceptées : {', '.join(sorted(s.value for s in ADMIN_SETTABLE_STATUSES))}.",
                {"field": "status"},
            )

        user = await self.users.find_by_id(user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "Aucun utilisateur trouvé avec cet identifiant.")

        current = user.status
        if not can_transition(current, target):
            raise ApiError(
                409,
                "INVALID_STATUS_TRANSITION",
                f"Transition impossible : {current.value} → {target.value}.",
                {"from_status": current.value, "to_status": target.value},
            )

        now = datetime.now(UTC)
        user.status = target
        await self.users.save(user)
        await self.users.record_status_change(
            UserStatusChange(
                id=UserStatusChange.new_id(),
                user_id=user.id,
                from_status=current,
                to_status=target,
                reason=reason,
                changed_by=changed_by,
                changed_at=now,
            ),
        )

        if target == UserStatus.SUSPENDED:
            # Kill the sessions too. Without this, a suspended user keeps
            # refreshing indefinitely — `RefreshAccessToken` would block them,
            # but only once their current access token expires, and any device
            # already holding a refresh token would otherwise stay in a loop of
            # its own. Revoking here makes the suspension bite at once.
            await self.refresh_tokens.revoke_all_for_user(user.id)

        await self.users.commit()
        await self.cache.invalidate_user(user.id)

        await self.events.publish(
            UserStatusChanged(
                user_id=user.id,
                phone=user.phone,
                role=user.role.value,
                old_status=current.value,
                new_status=target.value,
                reason=reason,
            ),
        )

        return profile_payload(user)
