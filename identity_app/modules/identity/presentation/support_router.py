"""Internal DiddiSupport context endpoint for DiddiFreeID-owned user data."""

from uuid import UUID

from fastapi import APIRouter, Depends

from identity_app.core.auth_deps import require_support_context_reader
from identity_app.core.deps import get_support_user_context_query
from identity_app.modules.identity.application.queries import GetSupportUserContext
from identity_app.modules.identity.presentation.schemas import SupportContextResponse

router = APIRouter(prefix="/internal/v1/support", tags=["internal-support"])


@router.get("/users/{user_id}/context", response_model=SupportContextResponse)
async def get_user_support_context(
    user_id: UUID,
    _caller: None = Depends(require_support_context_reader),
    query: GetSupportUserContext = Depends(get_support_user_context_query),
) -> dict:
    """Return only the DiddiFreeID projection necessary to support an account."""
    return await query(user_id)
