"""Request reversible self-service account deletion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from identity_app.core.errors import ApiError
from identity_app.core.settings import settings
from identity_app.modules.identity.domain.entities import UserStatus, UserStatusChange
from identity_app.modules.identity.domain.events import UserDeletionRequested
from identity_app.modules.identity.domain.interfaces import (
    EventPublisher,
    ProfileCache,
    RefreshTokenRepository,
    UserWriteRepository,
)


@dataclass
class RequestAccountDeletion:
    users: UserWriteRepository
    refresh_tokens: RefreshTokenRepository
    events: EventPublisher
    cache: ProfileCache

    async def __call__(self, *, user_id: UUID) -> dict:
        user = await self.users.find_by_id(user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "Aucun utilisateur trouvé avec cet identifiant.")
        if user.status == UserStatus.DELETED:
            raise ApiError(410, "ACCOUNT_DELETED", "Ce compte a été définitivement supprimé.")
        if user.status == UserStatus.DELETION_PENDING:
            scheduled_for = user.deletion_scheduled_for
            if scheduled_for is None:
                raise ApiError(409, "DELETION_STATE_INVALID", "La demande de suppression est incomplète.")
            return self._response(scheduled_for)
        if user.status not in {UserStatus.ACTIVE, UserStatus.PENDING_KYC}:
            raise ApiError(
                403,
                "ACCOUNT_NOT_DELETABLE",
                "Ce compte ne peut pas être supprimé dans son état actuel.",
            )

        now = datetime.now(UTC)
        scheduled_for = now + timedelta(days=settings.account_deletion_grace_days)
        previous_status = user.status
        user.status = UserStatus.DELETION_PENDING
        user.deletion_requested_at = now
        user.deletion_scheduled_for = scheduled_for
        user.deletion_previous_status = previous_status
        await self.users.save(user)
        await self.users.record_status_change(
            UserStatusChange(
                id=UserStatusChange.new_id(),
                user_id=user.id,
                from_status=previous_status,
                to_status=UserStatus.DELETION_PENDING,
                reason="Suppression demandée par l'utilisateur",
                changed_by=None,
                changed_at=now,
            ),
        )
        await self.refresh_tokens.revoke_all_for_user(user.id)
        await self.users.commit()
        await self.cache.invalidate_user(user.id)
        await self.events.publish(
            UserDeletionRequested(
                user_id=user.id,
                phone=user.phone,
                role=user.role.value,
                scheduled_for=scheduled_for,
            ),
        )
        return self._response(scheduled_for)

    @staticmethod
    def _response(scheduled_for: datetime) -> dict:
        value = scheduled_for.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return {
            "status": UserStatus.DELETION_PENDING.value,
            "scheduled_for": value,
            "restore_until": value,
        }
