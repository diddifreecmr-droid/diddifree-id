"""`/admin/*` — contract §3, reserved to `role=admin`.

Both routes go through `require_admin`, which re-reads the account rather than
trusting the token's `role` claim. See `core.auth_deps` for why that trade is
worth one database read on a low-traffic path.
"""

import logging
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from identity_app.core.auth_deps import (
    require_admin,
    require_backoffice_capability_read,
    require_backoffice_capability_write,
)
from identity_app.core.deps import (
    change_status_command,
    decide_kyc_command,
    get_my_capabilities_query,
    list_users_query,
    service_client_repo,
    update_capability_access_command,
)
from identity_app.core.errors import ApiError
from identity_app.modules.identity.application.commands import ChangeStatus, DecideKyc, UpdateCapabilityAccess
from identity_app.modules.identity.application.queries import GetMyCapabilities, ListUsers
from identity_app.modules.identity.domain.entities import User
from identity_app.modules.identity.infra.read_repository import MAX_PAGE_SIZE
from identity_app.modules.identity.infra.service_client_repository import SqlAlchemyServiceClientRepository
from identity_app.modules.identity.presentation.schemas import (
    CapabilityAccessRequest,
    CapabilityResponse,
    ChangeStatusRequest,
    KycDecisionRequest,
    ProMeResponse,
    ServiceClientListResponse,
    ServiceClientResponse,
    ServiceClientSecretRotationResponse,
    ServiceClientUpdateRequest,
    UserListResponse,
    UserProfile,
)

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)


def _service_client_response(client) -> dict:
    return {
        "client_id": client.client_id,
        "service_name": client.service_name,
        "environment": client.environment,
        "allowed_audiences": list(client.allowed_audiences),
        "allowed_scopes": list(client.allowed_scopes),
        "active": client.active,
        "expires_at": client.expires_at.isoformat() if client.expires_at else None,
        "revoked_at": client.revoked_at.isoformat() if client.revoked_at else None,
    }


@router.get("/service-clients", response_model=ServiceClientListResponse)
async def list_service_clients(
    _admin: User = Depends(require_admin),
    clients: SqlAlchemyServiceClientRepository = Depends(service_client_repo),
) -> dict:
    """List S2S policies without exposing hashes or plaintext secrets."""
    return {"data": [_service_client_response(client) for client in await clients.list_clients()]}


@router.patch("/service-clients/{client_id}", response_model=ServiceClientResponse)
async def update_service_client(
    client_id: str,
    payload: ServiceClientUpdateRequest,
    admin: User = Depends(require_admin),
    clients: SqlAlchemyServiceClientRepository = Depends(service_client_repo),
) -> dict:
    client = await clients.update_client(
        client_id.strip(),
        allowed_audiences=payload.allowed_audiences,
        allowed_scopes=payload.allowed_scopes,
        active=payload.active,
    )
    if client is None:
        raise ApiError(404, "SERVICE_CLIENT_NOT_FOUND", "Client service introuvable.")
    logger.info(
        "service_client_policy_updated",
        extra={
            "client_id": client.client_id,
            "admin_id": str(admin.id),
            "active": client.active,
            "scope_count": len(client.allowed_scopes),
            "audience_count": len(client.allowed_audiences),
        },
    )
    return _service_client_response(client)


@router.post("/service-clients/{client_id}/secret/rotate", response_model=ServiceClientSecretRotationResponse)
async def rotate_service_client_secret(
    client_id: str,
    admin: User = Depends(require_admin),
    clients: SqlAlchemyServiceClientRepository = Depends(service_client_repo),
) -> dict:
    """Rotate a machine-client secret and return the plaintext once."""
    secret = token_urlsafe(32)
    client = await clients.rotate_secret(client_id.strip(), secret_hash=sha256(secret.encode()).hexdigest())
    if client is None:
        raise ApiError(404, "SERVICE_CLIENT_NOT_FOUND", "Client service introuvable.")
    logger.info(
        "service_client_secret_rotated",
        extra={
            "client_id": client.client_id,
            "admin_id": str(admin.id),
            "active": client.active,
        },
    )
    return {**_service_client_response(client), "client_secret": secret}


@router.get("/users", response_model=UserListResponse)
async def list_users(
    role: str | None = Query(default=None, examples=["user"]),
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


@router.patch(
    "/users/{user_id}/capabilities/{service}/{capability_type}",
    response_model=CapabilityResponse,
)
async def update_capability_access(
    user_id: UUID,
    service: str,
    capability_type: str,
    payload: CapabilityAccessRequest,
    _caller: User | None = Depends(require_backoffice_capability_write),
    command: UpdateCapabilityAccess = Depends(update_capability_access_command),
) -> dict:
    return await command(
        user_id=user_id,
        service=service,
        capability_type=capability_type,
        access_status=payload.access_status,
    )


@router.get("/users/{user_id}/capabilities", response_model=ProMeResponse)
async def get_user_capabilities(
    user_id: UUID,
    _caller: User | None = Depends(require_backoffice_capability_read),
    query: GetMyCapabilities = Depends(get_my_capabilities_query),
) -> dict:
    """Backoffice view for one user; unlike `/pro/me`, it is not user-session scoped."""
    return await query(user_id)
