"""Ports the identity module needs from the outside world.

Protocols live in `domain/` because they describe WHAT is needed, never HOW.
Any implementation satisfying them is interchangeable — which is the concrete
mechanism behind the architecture's promise that swapping the read side for a
PostgreSQL read replica later is "a change of implementation, not a rewrite".

The read/write split is the CQRS decision made visible in the type system: a
command receives `UserWriteRepository`, a query receives `UserReadRepository`,
and neither can reach the other's methods by accident.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from identity_app.modules.identity.domain.entities import (
    OtpCode,
    RefreshToken,
    User,
    UserRoleChange,
    UserStatusChange,
)
from identity_app.modules.identity.domain.events import DomainEvent


class UserWriteRepository(Protocol):
    """Write side — transactional, always reads fresh, never from cache."""

    async def save(self, user: User) -> User:
        """INSERT or UPDATE the user row."""
        ...

    async def find_by_id(self, user_id: UUID) -> User | None:
        ...

    async def find_by_phone(self, phone: str) -> User | None:
        ...

    async def record_status_change(self, change: UserStatusChange) -> None:
        """Append to `identity.user_status_history`. Part of the same
        transaction as the status write it documents — an audit trail that can
        disagree with the row it audits is worse than none."""
        ...

    async def record_role_change(self, change: UserRoleChange) -> None:
        """Append to `identity.user_role_history` — role grants and KYC
        refusals alike, with the caller's `reason`."""
        ...

    async def commit(self) -> None:
        """Make pending writes visible to other connections now, rather than at
        request teardown. See `core.database.get_session` for why that matters."""
        ...


class UserReadRepository(Protocol):
    """Read side — no writes, no transactions to hold open."""

    async def get_by_id(self, user_id: UUID) -> User | None:
        ...

    async def get_by_phone(self, phone: str) -> User | None:
        ...

    async def list_users(
        self,
        *,
        role: str | None,
        status: str | None,
        pending_kyc: bool,
        created_since: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[User], int]:
        """Returns one page of users and the total count matching the filters."""
        ...


class OtpRepository(Protocol):
    async def save(self, otp: OtpCode) -> OtpCode:
        ...

    async def find_latest_active(self, phone: str) -> OtpCode | None:
        """Newest OTP for `phone` that has not been consumed. Expiry is checked
        by the caller so it can answer `410 OTP_EXPIRED` rather than the
        indistinguishable `400 OTP_INVALID`."""
        ...

    async def register_attempt(self, otp_id: UUID) -> int:
        """Increment and return the attempt counter for a failed verification."""
        ...

    async def mark_consumed(self, otp_id: UUID) -> None:
        """Idempotent — a second call on a consumed OTP is a no-op."""
        ...

    async def commit(self) -> None:
        ...


class RefreshTokenRepository(Protocol):
    async def save(self, token: RefreshToken) -> RefreshToken:
        ...

    async def find_by_hash(self, token_hash: str) -> RefreshToken | None:
        ...

    async def revoke(self, token_id: UUID) -> None:
        ...

    async def revoke_all_for_user(self, user_id: UUID) -> int:
        """Revoke every live token of a user. Returns how many were revoked."""
        ...

    async def commit(self) -> None:
        ...


class ProfileCache(Protocol):
    """Read-through cache for user profiles. Queries only — a command that read
    a cached profile before writing could persist a stale row."""

    async def get_user(self, user_id: UUID) -> User | None:
        ...

    async def set_user(self, user: User) -> None:
        ...

    async def invalidate_user(self, user_id: UUID) -> None:
        ...


class EventPublisher(Protocol):
    async def publish(self, event: DomainEvent) -> None:
        ...


class OtpSender(Protocol):
    async def send(self, phone: str, code: str) -> None:
        """Deliver the plaintext code. The code is never stored in clear, so
        this is the only moment it exists outside the user's phone."""
        ...
