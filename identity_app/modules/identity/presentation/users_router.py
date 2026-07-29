"""`/users/*` — contract §2 and the role-change route of §3.

Worth restating at the top of this file, because it is the rule most likely to
be broken by a well-meaning module: none of these routes exist to check whether
a token is valid. That is done locally, from the JWKS. These are for the cases
where the token genuinely does not carry enough — `full_name` on a receipt, the
name of a campaign owner — for a module recording a qualification it has just
granted, and for backfilling history a module could not receive as events.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from identity_app.core.auth_deps import get_current_user_id, require_service_or_admin
from identity_app.core.deps import (
    change_role_command,
    get_current_profile_query,
    get_user_by_id_query,
    list_users_query,
    update_profile_command,
)
from identity_app.modules.identity.application.commands import ChangeRole, UpdateProfile
from identity_app.modules.identity.application.queries import (
    GetCurrentUserProfile,
    GetUserById,
    ListUsers,
)
from identity_app.modules.identity.infra.read_repository import MAX_PAGE_SIZE
from identity_app.modules.identity.presentation.schemas import (
    ChangeRoleRequest,
    UpdateProfileRequest,
    UserListResponse,
    UserProfile,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserProfile)
async def me(
    user_id: UUID = Depends(get_current_user_id),
    query: GetCurrentUserProfile = Depends(get_current_profile_query),
) -> dict:
    return await query(user_id)


@router.patch("/me", response_model=UserProfile)
async def update_me(
    payload: UpdateProfileRequest,
    user_id: UUID = Depends(get_current_user_id),
    command: UpdateProfile = Depends(update_profile_command),
) -> dict:
    return await command(user_id=user_id, full_name=payload.full_name)


# Declared before `/{user_id}`: FastAPI matches in declaration order, and the
# other way round "backfill" would be parsed as a UUID and 422.
@router.get("/backfill", response_model=UserListResponse)
async def backfill(
    since: datetime = Query(
        description=(
            "Horodatage ISO 8601. Renvoie les comptes créés à partir de cet instant, "
            "du plus ancien au plus récent."
        ),
        examples=["2026-07-01T00:00:00Z"],
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=MAX_PAGE_SIZE),
    _caller: UUID | None = Depends(require_service_or_admin),
    query: ListUsers = Depends(list_users_query),
) -> dict:
    """Catch-up for a module that could not receive the events.

    The event stream has a bounded retention: a module offline longer than that,
    or one joining the ecosystem after the fact, has no way to learn about the
    users it missed. This walks them in creation order so an interrupted pass
    can resume from the last `created_at` it saw.

    Consuming it must be idempotent — a module will inevitably reprocess
    accounts it already knows about.
    """
    return await query(created_since=since, page=page, page_size=page_size)


@router.get("/{user_id}", response_model=UserProfile)
async def get_user(
    user_id: UUID,
    _caller: UUID | None = Depends(require_service_or_admin),
    query: GetUserById = Depends(get_user_by_id_query),
) -> dict:
    """Service-to-service profile lookup. Not for the frontend — a browser-side
    caller has `/users/me`, and letting it read arbitrary ids would turn this
    into a directory of the entire user base."""
    return await query(user_id)


@router.patch("/{user_id}/role", response_model=UserProfile)
async def change_role(
    user_id: UUID,
    payload: ChangeRoleRequest,
    caller: UUID | None = Depends(require_service_or_admin),
    command: ChangeRole = Depends(change_role_command),
) -> dict:
    """Called by a module once its own qualification passed — Ride after a
    licence check, Shop after merchant onboarding (contract §3).

    For `driver` and `merchant` this *requests* the role rather than granting
    it: the account enters the KYC queue, and an admin resolves it through
    `PATCH /admin/users/{id}/kyc`. The response carries `requested_role` so the
    caller can tell a grant from a queued request.
    """
    return await command(
        user_id=user_id,
        role=payload.role,
        reason=payload.reason,
        # `None` when the caller is a service — the audit row then shows the
        # decision came from a module, not from a person.
        changed_by=caller,
    )
