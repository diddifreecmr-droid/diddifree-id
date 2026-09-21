"""Read the DiddiFree Pro capability projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from identity_app.core.metrics import observe_capability_stale_read
from identity_app.core.settings import settings
from identity_app.modules.identity.domain.interfaces import CapabilityReadRepository


@dataclass
class GetMyCapabilities:
    capabilities: CapabilityReadRepository

    async def __call__(self, user_id: UUID) -> dict:
        now = datetime.now(UTC)
        rows = await self.capabilities.list_for_user(user_id)
        payload = []
        for capability in rows:
            item = capability.as_payload()
            age_seconds = max(0, int((now - capability.updated_at).total_seconds()))
            item["freshness"] = "stale" if age_seconds > settings.capability_projection_stale_seconds else "fresh"
            if item["freshness"] == "stale":
                observe_capability_stale_read(service=capability.service)
            payload.append(item)
        return {
            "user_id": str(user_id),
            "calculated_at": now.isoformat().replace("+00:00", "Z"),
            "capabilities": payload,
        }
