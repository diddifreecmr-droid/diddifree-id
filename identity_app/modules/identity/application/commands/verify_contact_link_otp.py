"""Verify a contact-link OTP and attach the proven contact to the account."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from identity_app.core.errors import ApiError
from identity_app.core.security import verify_otp_code
from identity_app.core.settings import settings
from identity_app.modules.identity.application.payloads import profile_payload
from identity_app.modules.identity.application.validation import validate_phone
from identity_app.modules.identity.domain.events import UserUpdated
from identity_app.modules.identity.domain.interfaces import (
    ContactLinkChallengeRepository,
    EventPublisher,
    ProfileCache,
    UserWriteRepository,
)


@dataclass
class VerifyContactLinkOtp:
    challenges: ContactLinkChallengeRepository
    users: UserWriteRepository
    events: EventPublisher
    cache: ProfileCache

    async def __call__(
        self,
        *,
        user_id: UUID,
        phone: str | None,
        email: str | None,
        code: str,
    ) -> dict:
        phone = validate_phone(phone) if phone else None
        email = email.strip().lower() if email else None
        if bool(phone) == bool(email):
            raise ApiError(422, "IDENTIFIER_REQUIRED", "Exactement un téléphone ou un e-mail est requis.")

        contact_type = "phone" if phone else "email"
        target = phone or email
        assert target is not None
        challenge = await self.challenges.find_latest_active(user_id, contact_type, target)
        if challenge is None:
            raise ApiError(400, "CONTACT_OTP_INVALID", "Le code de liaison est invalide.")
        now = datetime.now(UTC)
        if challenge.is_expired(now):
            raise ApiError(410, "CONTACT_OTP_EXPIRED", "Le code de liaison a expiré.")

        if not verify_otp_code(code, challenge.code_hash):
            attempts = await self.challenges.register_attempt(challenge.id)
            if attempts >= settings.otp_max_attempts:
                await self.challenges.mark_consumed(challenge.id)
                await self.challenges.commit()
                raise ApiError(429, "CONTACT_OTP_TOO_MANY_ATTEMPTS", "Trop de tentatives. Demandez un nouveau code.")
            await self.challenges.commit()
            raise ApiError(
                400,
                "CONTACT_OTP_INVALID",
                "Le code de liaison est invalide.",
                {"attempts_remaining": settings.otp_max_attempts - attempts},
            )

        user = await self.users.find_by_id(user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "Aucun utilisateur trouvé avec cet identifiant.")
        other = await self.users.find_by_phone(target) if phone else await self.users.find_by_email(target)
        if other is not None and other.id != user.id:
            code = "PHONE_ALREADY_REGISTERED" if phone else "EMAIL_ALREADY_REGISTERED"
            message = "Ce numéro est déjà enregistré." if phone else "Cette adresse e-mail est déjà enregistrée."
            raise ApiError(409, code, message)

        await self.challenges.mark_consumed(challenge.id)
        changed_fields = [contact_type]
        if phone:
            user.phone = phone
        else:
            user.email = email
        await self.users.save(user)
        await self.users.commit()
        await self.cache.invalidate_user(user.id)
        await self.events.publish(
            UserUpdated(
                user_id=user.id,
                phone=user.phone,
                role=user.role.value,
                changed_fields=changed_fields,
            ),
        )
        return profile_payload(user)
