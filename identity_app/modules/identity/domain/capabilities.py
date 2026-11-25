"""Domain values for the DiddiFree Pro capability projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

CAPABILITY_ACCESS_STATUSES = frozenset({"requested", "enabled", "suspended", "revoked"})


@dataclass(frozen=True)
class Capability:
    user_id: UUID
    service: str
    capability_type: str
    access_status: str
    operational_status: str
    status_source: str
    actions: tuple[str, ...]
    projection_version: int
    last_event_id: str | None
    updated_at: datetime
    created_at: datetime

    def as_payload(self) -> dict:
        updated_at = self.updated_at.astimezone(UTC)
        created_at = self.created_at.astimezone(UTC)
        return {
            "service": self.service,
            "type": self.capability_type,
            "access_status": self.access_status,
            "operational_status": self.operational_status,
            "status_source": self.status_source,
            "actions": list(self.actions),
            "projection_version": self.projection_version,
            "last_event_id": self.last_event_id,
            "updated_at": updated_at.isoformat().replace("+00:00", "Z"),
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
        }
