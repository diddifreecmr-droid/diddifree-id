"""Event definitions. Pure data — serialisation lives in the infra publisher."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class DomainEvent:
    """Base envelope: the four fields every subscriber can rely on."""

    user_id: UUID
    phone: str
    role: str
    at: datetime = field(default_factory=_now)

    #: Wire name, e.g. `user.registered`. Set by each subclass.
    name: str = field(init=False, default="")

    def to_payload(self) -> dict:
        """The published JSON body (contract §4)."""
        return {
            "event": self.name,
            "user_id": str(self.user_id),
            "phone": self.phone,
            "role": self.role,
            # `Z` rather than `+00:00`: the contract's §0 example uses the
            # military-zone form and some consumers parse it strictly.
            "at": self.at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }


@dataclass
class UserRegistered(DomainEvent):
    """First successful OTP verification of an account.

    Emitted once per user, not on every login — Wallet creating a second wallet
    on a returning user's second login would be a real bug, so `VerifyOtp` only
    publishes this when it is the transition out of `pending_verification`.
    """

    name: str = field(init=False, default="user.registered")


@dataclass
class UserUpdated(DomainEvent):
    """Profile fields changed. Subscribers use it to drop cached copies."""

    changed_fields: list[str] = field(default_factory=list)
    name: str = field(init=False, default="user.updated")

    def to_payload(self) -> dict:
        return super().to_payload() | {"changed_fields": self.changed_fields}


@dataclass
class UserRoleChanged(DomainEvent):
    old_role: str = ""
    new_role: str = ""
    name: str = field(init=False, default="user.role_changed")

    def to_payload(self) -> dict:
        return super().to_payload() | {"old_role": self.old_role, "new_role": self.new_role}


@dataclass
class UserStatusChanged(DomainEvent):
    """Status transition.

    Published under the wire name `user.suspended` when the target status is
    `suspended`, because that is the name the contract gives subscribers. A
    reactivation goes out as `user.updated` instead: nothing in the contract
    defines a `user.reactivated`, and inventing one would leave subscribers
    silently ignoring it.
    """

    old_status: str = ""
    new_status: str = ""
    reason: str | None = None
    name: str = field(init=False, default="user.suspended")

    def __post_init__(self) -> None:
        if self.new_status != "suspended":
            self.name = "user.updated"

    def to_payload(self) -> dict:
        return super().to_payload() | {
            "old_status": self.old_status,
            "new_status": self.new_status,
            "reason": self.reason,
        }
