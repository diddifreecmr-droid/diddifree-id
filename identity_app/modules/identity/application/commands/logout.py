"""`POST /auth/logout` — revoke one device, or every one of them."""

from __future__ import annotations

from dataclasses import dataclass

from identity_app.modules.identity.domain.interfaces import RefreshTokenRepository
from identity_app.modules.identity.infra.token_service import hash_refresh_token


@dataclass
class Logout:
    refresh_tokens: RefreshTokenRepository

    async def __call__(self, *, refresh_token: str, all_devices: bool = False) -> None:
        stored = await self.refresh_tokens.find_by_hash(hash_refresh_token(refresh_token))

        # Deliberately silent when the token is unknown or already revoked. The
        # contract promises `204` with no body, and logging out is idempotent by
        # nature — a client retrying after a dropped connection should not get
        # an error for succeeding twice. It also keeps this endpoint from
        # confirming whether a given token string ever existed.
        if stored is None:
            return

        if all_devices:
            await self.refresh_tokens.revoke_all_for_user(stored.user_id)
        else:
            await self.refresh_tokens.revoke(stored.id)

        await self.refresh_tokens.commit()
