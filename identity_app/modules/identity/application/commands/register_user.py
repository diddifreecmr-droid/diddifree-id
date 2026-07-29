"""`POST /auth/register` — create the account, unverified."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from identity_app.core.errors import ApiError
from identity_app.modules.identity.application.validation import validate_phone
from identity_app.modules.identity.domain.entities import User, UserRole, UserStatus
from identity_app.modules.identity.domain.interfaces import UserWriteRepository


@dataclass
class RegisterUser:
    users: UserWriteRepository

    async def __call__(self, *, phone: str, full_name: str | None) -> dict:
        phone = validate_phone(phone)

        if await self.users.find_by_phone(phone) is not None:
            raise ApiError(409, "PHONE_ALREADY_REGISTERED", "Ce numéro est déjà enregistré.")

        user = User(
            id=User.new_id(),
            phone=phone,
            full_name=full_name or None,
            # No `role` parameter, unlike DiddiGo's register: contract §1 makes
            # every account a plain `user`, and a module promotes it through
            # `PATCH /users/{id}/role` once its own qualification passes. That
            # is what stops DiddiFreeID from owning any module's business rules.
            role=UserRole.USER,
            status=UserStatus.PENDING_VERIFICATION,
            created_at=datetime.now(UTC),
        )
        await self.users.save(user)
        # Committed here so an immediate `POST /auth/otp/request` — which the
        # client will fire the moment this response lands — finds the account.
        await self.users.commit()

        return {
            "user_id": str(user.id),
            "phone": user.phone,
            "status": user.status.value,
        }
