"""Profile edit — the `full_name` half of the account.

Not in the published contract yet, but the architecture names `UpdateProfile`
among the commands (§2) and `user.updated` among the events (§6), and the cache
invalidation story is meaningless without a write path to exercise it.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from identity_app.core.errors import ApiError
from identity_app.modules.identity.application.payloads import profile_payload
from identity_app.modules.identity.domain.events import UserUpdated
from identity_app.modules.identity.domain.entities import UserLanguage
from identity_app.modules.identity.domain.interfaces import (
    EventPublisher,
    ProfileCache,
    UserWriteRepository,
)


@dataclass
class UpdateProfile:
    users: UserWriteRepository
    events: EventPublisher
    cache: ProfileCache

    async def __call__(
        self,
        *,
        user_id: UUID,
        full_name: str | None,
        email: str | None,
        email_provided: bool,
        language: str | None,
        photo_url: str | None,
        photo_url_provided: bool,
    ) -> dict:
        user = await self.users.find_by_id(user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "Aucun utilisateur trouvé avec cet identifiant.")

        changed: list[str] = []
        if full_name is not None and full_name != user.full_name:
            user.full_name = full_name
            changed.append("full_name")

        if email_provided:
            normalized_email = email.strip().lower() if email else None
            if normalized_email != user.email:
                if normalized_email is not None:
                    other = await self.users.find_by_email(normalized_email)
                    if other is not None and other.id != user.id:
                        raise ApiError(
                            409,
                            "EMAIL_ALREADY_REGISTERED",
                            "Cette adresse e-mail est déjà enregistrée.",
                        )
                user.email = normalized_email
                changed.append("email")

        if language is not None and language != user.language.value:
            user.language = UserLanguage(language)
            changed.append("language")

        if photo_url_provided and photo_url != user.photo_url:
            user.photo_url = photo_url
            changed.append("photo_url")

        if not changed:
            # Nothing moved. Skipping the write also skips the event, which
            # matters: subscribers drop their cached copy on `user.updated`, and
            # a no-op PATCH loop would keep flushing every module's cache.
            return profile_payload(user)

        await self.users.save(user)
        await self.users.commit()
        await self.cache.invalidate_user(user.id)
        await self.events.publish(
            UserUpdated(
                user_id=user.id,
                phone=user.phone,
                role=user.role.value,
                changed_fields=changed,
            ),
        )
        return profile_payload(user)
