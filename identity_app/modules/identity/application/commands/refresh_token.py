"""`POST /auth/refresh` — rotate the refresh token, mint a new access token."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from identity_app.core.errors import ApiError
from identity_app.modules.identity.domain.entities import (
    SESSION_ALLOWED_STATUSES,
    RefreshToken,
)
from identity_app.modules.identity.domain.interfaces import (
    RefreshTokenRepository,
    UserWriteRepository,
)
from identity_app.modules.identity.infra.token_service import TokenService, hash_refresh_token

logger = logging.getLogger(__name__)


@dataclass
class RefreshAccessToken:
    refresh_tokens: RefreshTokenRepository
    users: UserWriteRepository
    tokens: TokenService

    async def __call__(self, *, refresh_token: str, device_info: str | None = None) -> dict:
        now = datetime.now(UTC)
        stored = await self.refresh_tokens.find_by_hash(hash_refresh_token(refresh_token))

        if stored is None:
            raise ApiError(401, "REFRESH_TOKEN_INVALID", "Le refresh token est invalide.")

        if stored.revoked_at is not None:
            # A token that was already rotated away is being presented again.
            # Either it leaked, or a client is retrying — and the two are
            # indistinguishable from here. Revoking the user's whole set is the
            # standard response: the legitimate user logs in again, while a
            # thief loses the session they stole. Silently issuing a new pair
            # would hand a stolen token indefinite life.
            revoked = await self.refresh_tokens.revoke_all_for_user(stored.user_id)
            await self.refresh_tokens.commit()
            logger.warning(
                "réutilisation d'un refresh token révoqué (user_id=%s) — %s session(s) invalidée(s)",
                stored.user_id,
                revoked,
            )
            raise ApiError(
                401,
                "REFRESH_TOKEN_REVOKED",
                "Ce refresh token a déjà été utilisé. Toutes les sessions ont été fermées par sécurité.",
            )

        if stored.expires_at <= now:
            raise ApiError(401, "REFRESH_TOKEN_INVALID", "Le refresh token a expiré.")

        user = await self.users.find_by_id(stored.user_id)
        if user is None:
            raise ApiError(401, "REFRESH_TOKEN_INVALID", "Le refresh token est invalide.")
        if user.status not in SESSION_ALLOWED_STATUSES:
            # This is the point where suspension actually bites: the access
            # token stays valid for at most 15 minutes, but no new one is ever
            # issued (contract §2). A `pending_kyc` account is not suspended and
            # keeps refreshing — its token simply says `pending_kyc`, which every
            # module refuses to act on.
            raise ApiError(403, "USER_SUSPENDED", "Ce compte n'est plus actif.")

        await self.refresh_tokens.revoke(stored.id)

        raw_refresh, refresh_hash = self.tokens.new_refresh_token()
        await self.refresh_tokens.save(
            RefreshToken(
                id=RefreshToken.new_id(),
                user_id=user.id,
                token_hash=refresh_hash,
                device_info=device_info or stored.device_info,
                expires_at=self.tokens.refresh_expiry(now),
                created_at=now,
            ),
        )
        await self.refresh_tokens.commit()

        return {
            "access_token": self.tokens.issue_access_token(
                user_id=user.id, role=user.role.value, status=user.status.value,
            ),
            "refresh_token": raw_refresh,
        }
