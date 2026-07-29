"""`PATCH /users/{user_id}/role` — promotion driven by a module, never by us.

Ride decides a driver's licence checks out; Shop decides a merchant is real.
DiddiFreeID only records the outcome (contract §1) — and, for the roles listed
in `KYC_REQUIRED_ROLES`, holds it for review first.

That review is the point of architecture §7.5: DiddiGo auto-approves driver KYC
today, and the gate belongs here instead. So a promotion to `driver` or
`merchant` does not grant the role — it *requests* it. `ChangeRole` records the
request, `DecideKyc` resolves it.

Crucially, requesting a role never takes anything away. An active user who
applies to drive keeps `role=user` and `status=active` throughout, and goes on
using DiddiPay and DiddiShop while their file is reviewed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from identity_app.core.errors import ApiError
from identity_app.modules.identity.application.payloads import profile_payload
from identity_app.modules.identity.domain.entities import UserRole, UserRoleChange
from identity_app.modules.identity.domain.events import UserRoleChanged, UserUpdated
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
        try:
            target_role = UserRole(role)
        except ValueError as exc:
            raise ApiError(
                422,
                "INVALID_ROLE",
                f"Rôle inconnu : {role!r}. Valeurs acceptées : {', '.join(r.value for r in UserRole)}.",
                {"field": "role"},
            ) from exc

        user = await self.users.find_by_id(user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "Aucun utilisateur trouvé avec cet identifiant.")

        now = datetime.now(UTC)

        if user.needs_kyc_for(target_role):
            if user.requested_role == target_role:
                # Idempotent: a module retrying after a timeout must not queue
                # the same file twice for the review team.
                return profile_payload(user)

            previous_role = user.role
            user.requested_role = target_role
            await self.users.save(user)
            await self.users.record_role_change(
                UserRoleChange(
                    id=UserRoleChange.new_id(),
                    user_id=user.id,
                    from_role=previous_role,
                    # Nothing granted yet — the decision writes its own row.
                    to_role=None,
                    requested_role=target_role,
                    reason=reason,
                    changed_by=changed_by,
                    changed_at=now,
                ),
            )
            await self.users.commit()
            await self.cache.invalidate_user(user.id)

            # `user.updated`, not a bespoke `user.kyc_requested`: subscribers only
            # act on the four events of contract §4, so a new name would be a
            # notification nobody listens for. What matters here is that caches
            # drop their copy — which is exactly what `user.updated` means.
            await self.events.publish(
                UserUpdated(
                    user_id=user.id,
                    phone=user.phone,
                    role=user.role.value,
                    changed_fields=["requested_role"],
                ),
            )
            return profile_payload(user)

        if user.role == target_role:
            return profile_payload(user)

        old_role = user.role
        user.role = target_role
        # A direct change settles any pending request — an admin granting the
        # role outright, or a demotion, both make the queued file moot.
        user.requested_role = None
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
