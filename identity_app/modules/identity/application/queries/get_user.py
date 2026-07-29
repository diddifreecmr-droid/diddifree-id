"""Single-user reads — `GET /users/me` and `GET /users/{user_id}`.

These are the endpoints a module calls when the JWT is not enough: the token
carries `sub`, `role` and `status`, so anything needing `full_name` (a DiddiPay
receipt, a DiddiFund campaign owner) comes through here. Everything else should
be answered from the token, without a network call at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from identity_app.core.errors import ApiError
from identity_app.modules.identity.application.payloads import profile_payload
from identity_app.modules.identity.application.validation import validate_phone
from identity_app.modules.identity.domain.interfaces import ProfileCache, UserReadRepository


@dataclass
class GetUserById:
    users: UserReadRepository
    cache: ProfileCache

    async def __call__(self, user_id: UUID) -> dict:
        cached = await self.cache.get_user(user_id)
        if cached is not None:
            return profile_payload(cached)

        user = await self.users.get_by_id(user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "Aucun utilisateur trouvé avec cet identifiant.")

        await self.cache.set_user(user)
        return profile_payload(user)


@dataclass
class GetCurrentUserProfile:
    """`GET /users/me`.

    Separate from `GetUserById` even though the body is identical, because the
    two answer different questions and will diverge: `me` is the natural place
    for self-only fields (verified devices, notification settings) that must
    never appear in a service-to-service lookup of someone else.
    """

    users: UserReadRepository
    cache: ProfileCache

    async def __call__(self, user_id: UUID) -> dict:
        return await GetUserById(users=self.users, cache=self.cache)(user_id)


@dataclass
class GetUserByPhone:
    """Lookup by phone number.

    Not exposed over HTTP, and that is intentional: an endpoint answering "does
    this number belong to a DiddiFree user" is a subscriber-enumeration tool.
    It exists for internal use — the DiddiGo migration script (architecture §7)
    reconciles accounts by phone.
    """

    users: UserReadRepository

    async def __call__(self, phone: str) -> dict | None:
        user = await self.users.get_by_phone(validate_phone(phone))
        return None if user is None else profile_payload(user)
