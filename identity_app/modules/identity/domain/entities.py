"""Identity domain entities — plain dataclasses, no SQLAlchemy, no FastAPI.

Clean-architecture rule from the architecture doc §2: `domain/` depends on
nothing. The ORM models in `infra/models.py` are a projection of these types
and are never imported from here.

Instances are mutable: a command loads a `User`, assigns `status`, and hands it
back to the write repository. Rebuilding a frozen instance on every transition
would buy immutability at the cost of noise in every command.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4


class UserRole(str, Enum):
    """Global role, as carried in the JWT.

    Deliberately coarse. DiddiFreeID answers *who this is*, never *what they may
    do inside a given module* — architecture §4 explains why mixing the two
    would couple this service to every module's business rules.

    `service` is intentionally absent: service-to-service callers are not users
    and have no row in `identity.users` (see `core.auth_deps`).
    """

    USER = "user"
    DRIVER = "driver"
    MERCHANT = "merchant"
    ADMIN = "admin"


# These values remain readable for a rolling migration of old rows, but Auth
# must not assign them. The owning modules keep their own business roles.
MODULE_OWNED_ROLE_NAMES: frozenset[str] = frozenset({"driver", "merchant"})


#: Roles DiddiFreeID will not hand out without a KYC decision (architecture §7.5:
#: driver validation moves here, out of DiddiGo's auto-approval).
#:
#: `admin` is absent on purpose — the first admin is bootstrapped by ops, and a
#: KYC queue that nobody can approve until an admin exists would deadlock.
# KYC for a business role belongs to the owning module. This set is kept empty
# so new Auth flows can never create a module-owned KYC request.
KYC_REQUIRED_ROLES: frozenset[UserRole] = frozenset()


class UserStatus(str, Enum):
    PENDING_VERIFICATION = "pending_verification"
    PENDING_KYC = "pending_kyc"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class UserLanguage(str, Enum):
    """Languages currently supported by the ecosystem profile."""

    FR = "fr"
    EN = "en"


# Transitions the OTP flow, the KYC flow or an admin may perform. Anything
# absent is answered with `409 INVALID_STATUS_TRANSITION`, per contract §3.
#
# Two absences are deliberate:
#   * `active → pending_verification` — sending a live account back to
#     unverified would strip its ability to authenticate with no audit story;
#   * `active → pending_kyc` — `status` is global, read by all twelve modules.
#     Demoting a working account because its owner applied to drive would cut
#     their DiddiPay and DiddiShop access for the duration of the review. A
#     pending request lives in `User.requested_role` instead, and the account
#     stays exactly as usable as it was.
ALLOWED_STATUS_TRANSITIONS: dict[UserStatus, frozenset[UserStatus]] = {
    UserStatus.PENDING_VERIFICATION: frozenset(
        {UserStatus.ACTIVE, UserStatus.PENDING_KYC, UserStatus.SUSPENDED},
    ),
    UserStatus.PENDING_KYC: frozenset({UserStatus.ACTIVE, UserStatus.SUSPENDED}),
    UserStatus.ACTIVE: frozenset({UserStatus.SUSPENDED}),
    UserStatus.SUSPENDED: frozenset({UserStatus.ACTIVE}),
}

#: Statuses in which a person may still hold a session on DiddiFreeID itself.
#: `pending_kyc` is here on purpose: someone waiting on a driver review must be
#: able to open the app and see where their request stands. It is *not* a
#: licence to act — consuming modules read `status` from the token and refuse
#: anything but `active` (contract §2).
SESSION_ALLOWED_STATUSES: frozenset[UserStatus] = frozenset(
    {UserStatus.ACTIVE, UserStatus.PENDING_KYC},
)

#: Statuses an admin may set directly through `PATCH /admin/users/{id}/status`.
#: `pending_kyc` is driven by the KYC flow, not by hand: setting it on an active
#: account is precisely the ecosystem-wide lockout described above.
ADMIN_SETTABLE_STATUSES: frozenset[UserStatus] = frozenset(
    {UserStatus.ACTIVE, UserStatus.SUSPENDED},
)


def can_transition(current: UserStatus, target: UserStatus) -> bool:
    return target in ALLOWED_STATUS_TRANSITIONS.get(current, frozenset())


@dataclass
class User:
    id: UUID
    phone: str
    email: str | None = None
    role: UserRole = UserRole.USER
    status: UserStatus = UserStatus.PENDING_VERIFICATION
    full_name: str | None = None
    language: UserLanguage = UserLanguage.FR
    photo_url: str | None = None
    password_hash: str | None = None  # NULL when the account is OTP-only
    #: Role awaiting a KYC decision. Set when a module requests a promotion to a
    #: role in `KYC_REQUIRED_ROLES`, cleared when the decision lands. The user
    #: keeps `role` — and therefore every permission they already had — until
    #: approval.
    requested_role: UserRole | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @staticmethod
    def new_id() -> UUID:
        return uuid4()

    def needs_kyc_for(self, target_role: UserRole) -> bool:
        return target_role in KYC_REQUIRED_ROLES and self.role != target_role


@dataclass
class OtpCode:
    """One-time password record.

    `attempts` is what stops a 6-digit code from being brute-forced inside its
    5-minute window (architecture §8): the row is burned after
    `OTP_MAX_ATTEMPTS` wrong guesses, not just after expiry.
    """

    id: UUID
    phone: str
    code_hash: str
    expires_at: datetime
    created_at: datetime
    consumed_at: datetime | None = None
    attempts: int = 0

    @staticmethod
    def new_id() -> UUID:
        return uuid4()

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at <= now


@dataclass
class RefreshToken:
    """Opaque refresh token, stored only as a hash.

    Being opaque rather than a JWT is what makes immediate revocation possible
    (architecture §5): logging out a device, or suspending an account, takes
    effect on the next refresh instead of waiting for a signature to expire.
    """

    id: UUID
    user_id: UUID
    token_hash: str
    expires_at: datetime
    created_at: datetime
    device_info: str | None = None
    revoked_at: datetime | None = None

    @staticmethod
    def new_id() -> UUID:
        return uuid4()

    def is_usable(self, now: datetime) -> bool:
        return self.revoked_at is None and self.expires_at > now


@dataclass
class UserStatusChange:
    """Audit row — every status transition, who caused it and why.

    Mirrors DiddiGo's `ride_status_history` so the two services present the
    same audit shape to whoever reads them (architecture §4).
    """

    id: UUID
    user_id: UUID
    to_status: UserStatus
    changed_at: datetime
    from_status: UserStatus | None = None
    reason: str | None = None
    changed_by: UUID | None = None  # NULL when the system did it, else the admin

    @staticmethod
    def new_id() -> UUID:
        return uuid4()


@dataclass
class UserRoleChange:
    """Audit row for role decisions.

    Exists because `reason` is a documented field of `PATCH /users/{id}/role`
    (contract §3) — "Validation KYC chauffeur DiddiGo, dossier #4021" is written
    to be read back months later, and a reason that goes nowhere is a field the
    caller fills in for nothing.

    `to_role` is NULL for a refusal: no role was granted, which is exactly what
    a rejected KYC means, and it keeps refusals in the same trail as approvals.
    """

    id: UUID
    user_id: UUID
    changed_at: datetime
    from_role: UserRole | None = None
    to_role: UserRole | None = None
    requested_role: UserRole | None = None
    reason: str | None = None
    changed_by: UUID | None = None

    @staticmethod
    def new_id() -> UUID:
        return uuid4()
