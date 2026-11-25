"""DiddiFree Pro capabilities facade.

This router exposes the global access projection. It never decides whether a
user can perform a business operation; each owning module remains authoritative
for that decision.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Path

from identity_app.core.auth_deps import get_current_user_id, require_capability_service
from identity_app.core.deps import (
    get_my_capabilities_query,
    request_capability_command,
    update_capability_projection_command,
)
from identity_app.modules.identity.application.commands import RequestCapability, UpdateCapabilityProjection
from identity_app.modules.identity.application.queries import GetMyCapabilities
from identity_app.modules.identity.presentation.schemas import (
    CapabilityProjectionRequest,
    CapabilityResponse,
    ProMeResponse,
)

router = APIRouter(prefix="/pro", tags=["pro"])


@router.get("/me", response_model=ProMeResponse)
async def pro_me(
    user_id: UUID = Depends(get_current_user_id),
    query: GetMyCapabilities = Depends(get_my_capabilities_query),
) -> dict:
    return await query(user_id)


@router.post(
    "/capabilities/{service}/{capability_type}/request",
    response_model=CapabilityResponse,
    status_code=201,
)
async def request_capability(
    service: str = Path(min_length=1, max_length=80),
    capability_type: str = Path(min_length=1, max_length=80),
    user_id: UUID = Depends(get_current_user_id),
    command: RequestCapability = Depends(request_capability_command),
) -> dict:
    return await command(user_id=user_id, service=service, capability_type=capability_type)


@router.patch(
    "/internal/users/{user_id}/capabilities/{service}/{capability_type}/status",
    response_model=CapabilityResponse,
)
async def update_capability_projection(
    payload: CapabilityProjectionRequest,
    user_id: UUID,
    service: str = Path(min_length=1, max_length=80),
    capability_type: str = Path(min_length=1, max_length=80),
    _service: None = Depends(require_capability_service),
    command: UpdateCapabilityProjection = Depends(update_capability_projection_command),
) -> dict:
    return await command(
        user_id=user_id,
        service=service,
        capability_type=capability_type,
        operational_status=payload.operational_status,
        actions=payload.actions,
        projection_version=payload.projection_version,
        event_id=payload.event_id,
    )
