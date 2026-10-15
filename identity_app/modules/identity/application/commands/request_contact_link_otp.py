"""Request an OTP before attaching a new email or phone to an account."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import randbelow
from uuid import UUID

from identity_app.core.errors import ApiError
from identity_app.core.security import hash_otp_code
from identity_app.core.settings import settings
from identity_app.modules.identity.application.validation import validate_phone
from identity_app.modules.identity.domain.contact_link import ContactLinkChallenge
from identity_app.modules.identity.domain.interfaces import (
    ContactLinkChallengeRepository,
    OtpSender,
    UserWriteRepository,
    WhatsAppNumberNotFound,
)
from identity_app.modules.identity.infra.rate_limiter import RedisOtpRateLimiter


@dataclass
class RequestContactLinkOtp:
    challenges: ContactLinkChallengeRepository
    users: UserWriteRepository
    sender: OtpSender
    rate_limiter: RedisOtpRateLimiter

    async def __call__(
        self,
        *,
        user_id: UUID,
        phone: str | None,
        email: str | None,
        channel: str | None,
        client_ip: str | None = None,
    ) -> dict:
        phone = validate_phone(phone) if phone else None
        email = email.strip().lower() if email else None
        if bool(phone) == bool(email):
            raise ApiError(422, "IDENTIFIER_REQUIRED", "Exactement un téléphone ou un e-mail est requis.")

        user = await self.users.find_by_id(user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "Aucun utilisateur trouvé avec cet identifiant.")

        contact_type = "phone" if phone else "email"
        target = phone or email
        assert target is not None
        if target == (user.phone if contact_type == "phone" else user.email):
            raise ApiError(409, "CONTACT_ALREADY_LINKED", "Ce contact est déjà lié à ce compte.")

        other = await self.users.find_by_phone(target) if phone else await self.users.find_by_email(target)
        if other is not None and other.id != user.id:
            code = "PHONE_ALREADY_REGISTERED" if phone else "EMAIL_ALREADY_REGISTERED"
            message = "Ce numéro est déjà enregistré." if phone else "Cette adresse e-mail est déjà enregistrée."
            raise ApiError(409, code, message)

        selected_channel = self._select_channel(contact_type, channel)
        identifier = f"contact-link:{user_id}:{contact_type}:{target}"
        if client_ip and not await self.rate_limiter.hit_ip(client_ip):
            raise ApiError(
                429,
                "OTP_RATE_LIMITED",
                "Trop de demandes depuis cette adresse. Réessayez plus tard.",
                {"retry_after_seconds": settings.otp_rate_limit_seconds},
            )
        remaining = await self.rate_limiter.seconds_until_identifier_allowed(
            identifier,
            settings.otp_rate_limit_seconds,
        )
        if remaining > 0:
            raise ApiError(
                429,
                "OTP_RATE_LIMITED",
                "Veuillez attendre avant de redemander un code.",
                {"retry_after_seconds": remaining},
            )

        now = datetime.now(UTC)
        code = f"{randbelow(1_000_000):06d}"
        await self.challenges.save(
            ContactLinkChallenge(
                id=ContactLinkChallenge.new_id(),
                user_id=user.id,
                contact_type=contact_type,
                target=target,
                code_hash=hash_otp_code(code),
                expires_at=now + timedelta(seconds=settings.otp_code_lifetime_seconds),
                created_at=now,
            ),
        )
        await self.challenges.commit()
        try:
            await self.sender.send(phone, code, selected_channel, email)
        except WhatsAppNumberNotFound as exc:
            raise ApiError(422, "WHATSAPP_NUMBER_NOT_FOUND", "Ce numéro n'existe pas sur WhatsApp.") from exc
        except RuntimeError as exc:
            raise ApiError(
                502,
                "OTP_PROVIDER_UNAVAILABLE",
                "Le service d'envoi OTP est momentanément indisponible. Réessayez plus tard.",
            ) from exc

        await self.rate_limiter.mark_identifier_sent(identifier, settings.otp_rate_limit_seconds)
        return {
            "contact_type": contact_type,
            "channel": selected_channel,
            "expires_in_seconds": settings.otp_code_lifetime_seconds,
            "retry_after_seconds": settings.otp_rate_limit_seconds,
        }

    @staticmethod
    def _select_channel(contact_type: str, channel: str | None) -> str:
        selected = channel or settings.otp_provider
        if selected == "smtp":
            selected = "email"
        if channel is None and contact_type == "email" and selected not in {"email", "logging"}:
            selected = "email"
        if contact_type == "email" and selected not in {"email", "logging"}:
            raise ApiError(422, "EMAIL_CONTACT_REQUIRES_EMAIL_CHANNEL", "Un email doit être vérifié par email.")
        if contact_type == "phone" and selected not in {"sms", "telegram", "whatsapp", "logging"}:
            raise ApiError(
                422,
                "PHONE_CONTACT_REQUIRES_PHONE_CHANNEL",
                "Un téléphone doit être vérifié par SMS ou messagerie.",
            )
        return selected
