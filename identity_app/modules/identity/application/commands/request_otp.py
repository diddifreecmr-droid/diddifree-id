"""`POST /auth/otp/request` — mint a code and send it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import randbelow

from identity_app.core.errors import ApiError
from identity_app.core.security import hash_otp_code
from identity_app.core.settings import settings
from identity_app.modules.identity.application.validation import validate_phone
from identity_app.modules.identity.domain.entities import OtpCode
from identity_app.modules.identity.domain.interfaces import (
    OtpRepository,
    OtpSender,
    UserWriteRepository,
)
from identity_app.modules.identity.infra.rate_limiter import RedisOtpRateLimiter


@dataclass
class RequestOtp:
    otps: OtpRepository
    users: UserWriteRepository
    sender: OtpSender
    rate_limiter: RedisOtpRateLimiter

    async def __call__(self, *, phone: str, client_ip: str | None = None) -> dict:
        phone = validate_phone(phone)

        if client_ip and not await self.rate_limiter.hit_ip(client_ip):
            raise ApiError(
                429,
                "OTP_RATE_LIMITED",
                "Trop de demandes depuis cette adresse. Réessayez plus tard.",
                {"retry_after_seconds": settings.otp_rate_limit_seconds},
            )

        remaining = await self.rate_limiter.seconds_until_phone_allowed(
            phone, settings.otp_rate_limit_seconds,
        )
        if remaining > 0:
            raise ApiError(
                429,
                "OTP_RATE_LIMITED",
                "Veuillez attendre avant de redemander un code.",
                {"retry_after_seconds": remaining},
            )

        user = await self.users.find_by_phone(phone)

        # The response is identical whether or not the number is known. Any
        # difference here — a 404, a different delay, another error code —
        # turns this endpoint into an oracle for "is this person a DiddiFree
        # user", which is exactly the kind of question an attacker asks first.
        # A caller who requests a code for an unknown number simply never
        # receives one, and `verify` answers the usual `400 OTP_INVALID`.
        if user is not None:
            now = datetime.now(UTC)
            code = f"{randbelow(1_000_000):06d}"
            await self.otps.save(
                OtpCode(
                    id=OtpCode.new_id(),
                    phone=phone,
                    code_hash=hash_otp_code(code),
                    expires_at=now + timedelta(seconds=settings.otp_code_lifetime_seconds),
                    created_at=now,
                ),
            )
            # Commit before the code leaves the process: the user can submit it
            # the instant the SMS lands, and `verify_otp` runs on another
            # session that must already see this row.
            await self.otps.commit()
            await self.sender.send(phone, code)

        await self.rate_limiter.mark_phone_sent(phone, settings.otp_rate_limit_seconds)

        return {
            "expires_in_seconds": settings.otp_code_lifetime_seconds,
            "retry_after_seconds": settings.otp_rate_limit_seconds,
        }
