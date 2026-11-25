"""Internal aggregate reporting surface consumed by Pilotage."""

from datetime import date

from fastapi import APIRouter, Depends, Query

from identity_app.core.auth_deps import require_pilotage_reporting
from identity_app.core.deps import get_identity_summary_query
from identity_app.modules.identity.application.queries import GetIdentitySummary
from identity_app.modules.identity.presentation.schemas import IdentitySummaryResponse

router = APIRouter(prefix="/internal/pilotage", tags=["internal-reporting"])


@router.get("/identity-summary", response_model=IdentitySummaryResponse)
async def identity_summary(
    date: date = Query(description="Jour métier dans le fuseau Africa/Abidjan."),
    _pilotage: None = Depends(require_pilotage_reporting),
    query: GetIdentitySummary = Depends(get_identity_summary_query),
) -> dict:
    return await query(day=date)
