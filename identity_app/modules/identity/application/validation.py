"""Input rules shared by several commands.

Lives in `application/` rather than `domain/` because these raise `ApiError`,
i.e. they already know about HTTP status codes. Keeping that knowledge out of
`domain/` is what lets the domain stay importable by anything.
"""

from __future__ import annotations

import re

from identity_app.core.errors import ApiError

# E.164: leading '+', a non-zero country digit, then 7–14 more digits.
# Same expression DiddiGo uses — a number accepted by one service and rejected
# by the other would be an ugly surprise during the migration in §7.
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def validate_phone(phone: str) -> str:
    """Normalise and validate, or raise `422 INVALID_PHONE_FORMAT` per contract §1."""
    normalised = "".join(phone.split())  # tolerate "+225 07 00 00 00 00"
    if not _E164.match(normalised):
        raise ApiError(
            422,
            "INVALID_PHONE_FORMAT",
            "Le numéro doit être au format international, ex. +2250700000000.",
            {"field": "phone"},
        )
    return normalised
