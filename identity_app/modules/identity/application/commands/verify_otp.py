"""`POST /auth/otp/verify` — the only place an account becomes `active`.

This is the busiest command in the service and the one with the most ways to go
subtly wrong, so the ordering below is deliberate:

  1. reject on expiry *before* comparing the code, so an expired code answers
     `410 OTP_EXPIRED` rather than the misleading `400 OTP_INVALID`;
  2. count a failed attempt in SQL and burn the code once the ceiling is hit —
     otherwise six digits fall to a script inside the five-minute window;
  3. consume the code before issuing anything, so a replay of the same request
     cannot mint a second session;
  4. commit before returning the token.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from identity_app.core.errors import ApiError
from identity_app.core.security import verify_otp_code
from identity_app.core.settings import settings
from identity_app.modules.identity.application.payloads import profile_payload
from identity_app.modules.identity.application.validation import validate_phone
from identity_app.modules.identity.domain.entities import (
    RefreshToken,
    UserStatus,
    UserStatusChange,
)
from identity_app.modules.identity.domain.events import UserRegistered
from identity_app.modules.identity.domain.interfaces import (
    EventPublisher,
    OtpRepository,
    ProfileCache,
    RefreshTokenRepository,
    UserWriteRepository,
)
from identity_app.modules.identity.infra.token_service import TokenService


@dataclass
class VerifyOtp:
    otps: OtpRepository
    users: UserWriteRepository
    refresh_tokens: RefreshTokenRepository
    tokens: TokenService
    events: EventPublisher
    cache: ProfileCache

    async def __call__(self, *, phone: str, code: str, device_info: str | None = None) -> dict:
        phone = validate_phone(phone)
        now = datetime.now(UTC)

        otp = await self.otps.find_latest_active(phone)
        if otp is None:
            raise ApiError(400, "OTP_INVALID", "Le code OTP est invalide.")
        if otp.is_expired(now):
            raise ApiError(410, "OTP_EXPIRED", "Le code OTP a expiré.")

        if not verify_otp_code(code, otp.code_hash):
            attempts = await self.otps.register_attempt(otp.id)
            if attempts >= settings.otp_max_attempts:
                # Burn it. Leaving a code alive after N failures would make the
                # counter decorative — the attacker just keeps going.
                await self.otps.mark_consumed(otp.id)
                await self.otps.commit()
                raise ApiError(
                    429,
                    "OTP_TOO_MANY_ATTEMPTS",
                    "Trop de tentatives. Demandez un nouveau code.",
                    {"attempts": attempts},
                )
            await self.otps.commit()
            raise ApiError(
                400,
                "OTP_INVALID",
                "Le code OTP est invalide.",
                {"attempts_remaining": settings.otp_max_attempts - attempts},
            )

        await self.otps.mark_consumed(otp.id)

        user = await self.users.find_by_phone(phone)
        if user is None:
            # Only reachable if the account was deleted between the request and
            # the verification. Account creation belongs to `/auth/register`
            # (contract §1); silently creating one here would produce users with
            # no `full_name` and bypass the 409-on-duplicate rule.
            raise ApiError(404, "USER_NOT_FOUND", "Aucun compte n'est associé à ce numéro.")

        if user.status == UserStatus.SUSPENDED:
            raise ApiError(403, "USER_SUSPENDED", "Ce compte est suspendu.")

        first_verification = user.status == UserStatus.PENDING_VERIFICATION
        if first_verification:
            # An account whose first role request is still pending review goes to
            # `pending_kyc` rather than `active` — the "pending_kyc avant active"
            # of architecture §7.5. It only applies to accounts that were never
            # active: a working account is never demoted by a pending request.
            user.status = UserStatus.PENDING_KYC if user.requested_role else UserStatus.ACTIVE
            await self.users.save(user)
            await self.users.record_status_change(
                UserStatusChange(
                    id=UserStatusChange.new_id(),
                    user_id=user.id,
                    from_status=UserStatus.PENDING_VERIFICATION,
                    to_status=user.status,
                    reason="Vérification OTP",
                    changed_by=None,  # the system, not an admin
                    changed_at=now,
                ),
            )

        raw_refresh, refresh_hash = self.tokens.new_refresh_token()
        await self.refresh_tokens.save(
            RefreshToken(
                id=RefreshToken.new_id(),
                user_id=user.id,
                token_hash=refresh_hash,
                device_info=device_info,
                expires_at=self.tokens.refresh_expiry(now),
                created_at=now,
            ),
        )

        # Commit before handing back a token. The client uses it on its very
        # next request, which can arrive before FastAPI tears this session down;
        # the activation must already be visible or the user is rejected as
        # `pending_verification` by their own fresh token.
        await self.users.commit()

        await self.cache.invalidate_user(user.id)

        if first_verification:
            # Emitted once per account, not on every login — Wallet creating a
            # second wallet for a returning user would be a real bug.
            await self.events.publish(
                UserRegistered(user_id=user.id, phone=user.phone, role=user.role.value),
            )

        access_token = self.tokens.issue_access_token(
            user_id=user.id, role=user.role.value, status=user.status.value,
        )
        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "user": profile_payload(user),
        }
