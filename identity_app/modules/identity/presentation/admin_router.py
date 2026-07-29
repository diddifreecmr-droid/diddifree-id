"""`/admin/*` — contract §3, reserved to `role=admin`.

Both routes go through `require_admin`, which re-reads the account rather than
trusting the token's `role` claim. See `core.auth_deps` for why that trade is
worth one database read on a low-traffic path.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from identity_app.core.auth_deps import require_admin
from identity_app.core.deps import (
    change_status_command,
    decide_kyc_command,
    list_users_query,
)
from identity_app.modules.identity.application.commands import ChangeStatus, DecideKyc
from identity_app.modules.identity.application.queries import ListUsers
from identity_app.modules.identity.domain.entities import User
from identity_app.modules.identity.infra.read_repository import MAX_PAGE_SIZE
from identity_app.modules.identity.presentation.schemas import (
    ChangeStatusRequest,
    KycDecisionRequest,
    UserListResponse,
    UserProfile,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=UserListResponse)
async def list_users(
    role: str | None = Query(default=None, examples=["driver"]),
    status: str | None = Query(default=None, examples=["active"]),
    pending_kyc: bool = Query(
        default=False,
        description="Ne renvoyer que les comptes ayant une demande de rôle en attente de décision KYC.",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
    _admin: User = Depends(require_admin),
    query: ListUsers = Depends(list_users_query),
) -> dict:
    return await query(
        role=role, status=status, pending_kyc=pending_kyc, page=page, page_size=page_size,
    )


@router.patch("/users/{user_id}/status", response_model=UserProfile)
async def change_status(
    user_id: UUID,
    payload: ChangeStatusRequest,
    admin: User = Depends(require_admin),
    command: ChangeStatus = Depends(change_status_command),
) -> dict:
    return await command(
        user_id=user_id,
        status=payload.status,
        reason=payload.reason,
        # Recorded in `user_status_history.changed_by` — the audit trail names
        # the admin, which is the whole point of the transverse traceability
        # requirement in the cahier des charges.
        changed_by=admin.id,
    )


@router.patch("/users/{user_id}/kyc", response_model=UserProfile)
async def decide_kyc(
    user_id: UUID,
    payload: KycDecisionRequest,
    admin: User = Depends(require_admin),
    command: DecideKyc = Depends(decide_kyc_command),
) -> dict:
    """Grant or refuse a pending role request.

    The review queue is `GET /admin/users?pending_kyc=true`. This is the gate
    architecture §7.5 moves out of DiddiGo, where driver validation is currently
    auto-approved.
    """
    return await command(
        user_id=user_id,
        approved=payload.approved,
        reason=payload.reason,
        decided_by=admin.id,
    )
