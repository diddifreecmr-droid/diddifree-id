"""Manage the Google Play review-account marker owned by DiddiFreeID."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from identity_app.core.errors import ApiError
from identity_app.modules.identity.domain.entities import UserReviewAccountChange
from identity_app.modules.identity.domain.events import UserReviewAccountChanged
from identity_app.modules.identity.domain.interfaces import (
    EventPublisher,
    ProfileCache,
    RefreshTokenRepository,
    UserWriteRepository,
)


@dataclass
class ChangeReviewAccount:
    users: UserWriteRepository
    refresh_tokens: RefreshTokenRepository
    events: EventPublisher
    cache: ProfileCache

    async def __call__(
        self,
        *,
        user_id: UUID,
        is_review_account: bool,
        reason: str,
        changed_by: UUID | None,
        changed_by_client_id: str | None,
    ) -> dict:
        user = await self.users.find_by_id(user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "Aucun utilisateur trouvé avec cet identifiant.")

        if user.is_review_account == is_review_account:
            return {"id": str(user.id), "is_review_account": user.is_review_account}

        previous = user.is_review_account
        user.is_review_account = is_review_account
        now = datetime.now(UTC)
        await self.users.save(user)
        await self.users.record_review_account_change(
            UserReviewAccountChange(
                id=UserReviewAccountChange.new_id(),
                user_id=user.id,
                from_is_review_account=previous,
                to_is_review_account=is_review_account,
                reason=reason,
                changed_by=changed_by,
                changed_by_client_id=changed_by_client_id,
                changed_at=now,
            ),
        )
        # Existing access tokens have at most a 15-minute lifetime. Revoking
        # refresh tokens prevents a stale review marker from being renewed.
        await self.refresh_tokens.revoke_all_for_user(user.id)
        await self.users.commit()
        await self.cache.invalidate_user(user.id)

        await self.events.publish(
            UserReviewAccountChanged(
                user_id=user.id,
                phone=user.phone,
                role=user.role.value,
                old_is_review_account=previous,
                new_is_review_account=is_review_account,
            ),
        )
        return {"id": str(user.id), "is_review_account": user.is_review_account}
