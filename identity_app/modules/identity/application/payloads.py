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

from identity_app.modules.identity.domain.entities import User


def profile_payload(user: User) -> dict:
    """The user object as published by contract §2.

    `requested_role` is an addition to the documented shape: it is what tells an
    admin console which role a file in the KYC queue is asking for. Additive, so
    a consumer parsing the documented fields is unaffected.
    """
    return {
        "id": str(user.id),
        "phone": user.phone,
        "full_name": user.full_name,
        "role": user.role.value,
        "status": user.status.value,
        "requested_role": user.requested_role.value if user.requested_role else None,
    }
