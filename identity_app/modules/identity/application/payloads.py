"""The published shape of a user, in one place.

Commands and queries both answer with a profile, and both must answer with the
*same* profile — `GET /users/me` and `PATCH /users/me` returning subtly
different objects is the kind of inconsistency a client discovers in production.

It lives here, beside the two halves rather than inside either, because a
command importing from `queries/` (or the reverse) is precisely the coupling the
CQRS split exists to prevent — and which `tests/test_cqrs_boundaries.py`
enforces.
"""

from __future__ import annotations

from datetime import UTC, datetime

from identity_app.modules.identity.domain.entities import User


def _utc_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def profile_payload(user: User) -> dict:
    """The user object as published by contract §2.

    `requested_role` is an addition to the documented shape: it is what tells an
    admin console which role a file in the KYC queue is asking for. Additive, so
    a consumer parsing the documented fields is unaffected.

    `created_at` (ticket 029) is also additive: the account creation date, ISO
    8601 in UTC with a `Z` suffix. DiddiRewards reads it server-side to decide
    sign-up-date campaigns, so no calling service can send its own date.
    """
    return {
        "id": str(user.id),
        "phone": user.phone,
        "email": user.email,
        "full_name": user.full_name,
        "language": user.language.value,
        "photo_url": user.photo_url,
        "role": user.role.value,
        "status": user.status.value,
        "requested_role": user.requested_role.value if user.requested_role else None,
        "created_at": _utc_timestamp(user.created_at),
    }
