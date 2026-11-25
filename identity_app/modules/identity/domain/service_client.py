"""Domain value object for a machine client registered in DiddiFreeID."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class ServiceClient:
    id: UUID
    client_id: str
    service_name: str
    environment: str
    secret_hash: str
    allowed_audiences: tuple[str, ...]
    allowed_scopes: tuple[str, ...]
    active: bool
    expires_at: datetime | None
    revoked_at: datetime | None
