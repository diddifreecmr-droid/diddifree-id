"""`GET /admin/users` — the paginated, filterable back-office list.

Also backs `GET /users/backfill`, which is the same query with `created_since`
set: a module joining the ecosystem, or one that was down longer than the event
stream's retention, walks the user base from a point in time instead of relying
on events it can no longer receive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import ceil

from identity_app.core.errors import ApiError
from identity_app.modules.identity.application.payloads import profile_payload
from identity_app.modules.identity.domain.entities import UserRole, UserStatus
from identity_app.modules.identity.domain.interfaces import UserReadRepository


@dataclass
class ListUsers:
    users: UserReadRepository

    async def __call__(
        self,
        *,
        role: str | None = None,
        status: str | None = None,
        pending_kyc: bool = False,
        created_since: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        # Validate the filters rather than passing them straight through: an
        # unknown value would silently return an empty page, which reads to the
        # operator as "no drivers" instead of "you typed the filter wrong".
        if role is not None and role not in {r.value for r in UserRole}:
            raise ApiError(
                422,
                "INVALID_ROLE",
                f"Rôle inconnu : {role!r}.",
                {"field": "role", "accepted": [r.value for r in UserRole]},
            )
        if status is not None and status not in {s.value for s in UserStatus}:
            raise ApiError(
                422,
                "INVALID_STATUS",
                f"Statut inconnu : {status!r}.",
                {"field": "status", "accepted": [s.value for s in UserStatus]},
            )

        rows, total = await self.users.list_users(
            role=role,
            status=status,
            pending_kyc=pending_kyc,
            created_since=created_since,
            page=page,
            page_size=page_size,
        )

        return {
            "data": [profile_payload(user) for user in rows],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total,
                "total_pages": ceil(total / page_size) if page_size else 0,
            },
        }
